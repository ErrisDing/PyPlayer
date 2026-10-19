#!/usr/bin/env python3
"""
Main Window - Primary application window
Assembles all UI components and provides the public View interface

Shell (batch 2, spec §3.3): a 56 px ``ActionRail`` column, a full-width
playlist, the ``LibrarySidebar`` floating over the list as a sibling of the
container rather than a layout item, and a ``BottomPanel`` whose first row is
the ``NowPlayingStrip``. There is no menu bar -- every action it carried lives
on the rail, except Ctrl+Q, which hangs off the window itself (spec §6) -- and
no left column: the cover/title/artist read-out moved to the control bar, the
library picker moved to the floating panel.
"""

from typing import Any, List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QApplication,
    QFileDialog, QMessageBox,
)
from PyQt6.QtCore import QEvent, pyqtSignal, QRect
from PyQt6.QtGui import QAction, QKeySequence, QCloseEvent, QPixmap, QPainter, QColor

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import i18n
from view.widgets import ActionRail, BottomPanel, LibrarySidebar, PlaylistView, Toast
from view.widgets.action_rail import (
    ACTION_ABOUT,
    ACTION_APPEARANCE,
    ACTION_OPEN_FILE,
    ACTION_OPEN_FOLDER,
    ACTION_REFRESH,
    ACTION_REFRESH_ALL,
)
from view.models import PlaylistModel, DisplayEntry


class MainWindow(QMainWindow):
    """
    Main application window implementing the View layer.

    Features:
    - Clean separation of UI from business logic
    - Signals for all user actions
    - Public API for Presenter to update UI

    Styling: the window owns no stylesheet. ``view.theme_manager.ThemeManager``
    pushes one application-wide sheet and palette; this class only reacts to
    ``theme_changed`` for the things QSS cannot restyle by itself -- the
    token-coloured SVG glyphs of the icon rail and the bottom panel
    (``view.icons``), the sidebar row glyphs, the delegate-painted playlist
    rows and the background scrim -- through :meth:`recolor`.

    Layout: ``central`` is a ``QVBoxLayout`` of a content row and the bottom
    panel; the content row is ``[ActionRail | content stack]``. The stack holds
    ``#playlistContainer`` (a layout host only -- no QSS rule, no registration
    in ``REQUIRED_OBJECT_NAMES``) and the two overlays parent to it or into it:
    the floating panel sits over the stack as a sibling of the container, the
    toast sits inside the container and re-places with it. Overlays are not
    layout items: their geometry is theirs, this class only decides *when* a
    re-place happens (see :meth:`eventFilter`).
    """

    # === User Action Signals ===
    # These signals are emitted when the user performs actions
    play_pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    next_track_requested = pyqtSignal()
    prev_track_requested = pyqtSignal()
    seek_requested = pyqtSignal(float)          # position in seconds
    volume_changed = pyqtSignal(float)          # 0.0 - 1.0
    loop_mode_changed = pyqtSignal(str)         # "OFF", "ONE", "ALL"
    track_double_clicked = pyqtSignal(int)      # display index
    refresh_library_requested = pyqtSignal(str) # library path
    refresh_all_requested = pyqtSignal()        # refresh all libraries
    scan_folder_requested = pyqtSignal(str)     # folder path
    library_selected = pyqtSignal(str)          # library path selected
    add_library_requested = pyqtSignal(str)     # new library path from the panel
    manage_libraries_requested = pyqtSignal()   # open library management dialog
    manage_appearance_requested = pyqtSignal()  # open appearance settings dialog
    # Batch 3 (Task 6): the three playlist batch routes. The payloads are ascending,
    # deduplicated *display* rows straight from ``PlaylistView`` -- this layer converts
    # nothing and must not re-sort (the removal loop reverses them itself, spec §4.2)
    # and must not read an empty list as a request (``PlaylistView.request_*`` already
    # refuse to emit one, spec §7). ``clear_playlist_requested`` carries nothing:
    # clearing is not scoped to a target.
    play_tracks_requested = pyqtSignal(list)    # display indices
    remove_tracks_requested = pyqtSignal(list)  # display indices
    clear_playlist_requested = pyqtSignal()

    # === Window-level key bindings (Task 6, shaped by ruling R11) ===
    # Literals, deliberately not ``QKeySequence.StandardKey`` lookups: measured on this
    # host under ``QT_QPA_PLATFORM=offscreen``, ``StandardKey.Quit`` resolves to the
    # string ``"Exit"`` (batch 2), so a StandardKey-based test can inject
    # ``QKeyEvent(Key_Space, ControlModifier)`` all day and never hit the binding. A
    # literal is the same sequence on every platform, which is what makes the
    # key-injection tests in ``tests/test_playlist_shortcuts.py`` deterministic.
    #
    # Three keys, not five. ``Delete`` and ``Enter`` are answered by
    # ``PlaylistView.keyPressEvent`` (view/widgets/playlist_view.py) since ruling R11,
    # because a window-level binding for them cannot be scoped to the list on this
    # binding (``QAction.setShortcutWidget`` does not exist in PyQt6 6.11) and an
    # in-slot focus gate does not un-consume the press -- it only hides the effect. What
    # stays here is exactly the set of keys whose meaning is *not* "these rows":
    # play/pause and prev/next are transport, so they belong to the window.
    SHORTCUT_PLAY_PAUSE = 'Ctrl+Space'
    SHORTCUT_PREV = 'Ctrl+Up'
    SHORTCUT_NEXT = 'Ctrl+Down'

    def __init__(self, theme_manager, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Ensure i18n is initialized
        i18n.detect_init()

        # The theme layer: tokens for the scrim, alphas for the overlay, and
        # the manager handed to the widgets that paint colours themselves.
        self._theme = theme_manager

        # Current library tracking
        self._current_library_path: str = ""
        self._libraries: List[Any] = []

        # Background image for custom painting
        self._background_pixmap: Optional[QPixmap] = None
        # Mirrors ``theme_manager.alphas.overlay``; refreshed by ``recolor`` so
        # the scrim follows the manager's copy on every theme/alpha change.
        self._overlay_alpha: float = theme_manager.alphas.overlay

        self._setup_window()
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_connections()

        theme_manager.theme_changed.connect(self.recolor)
        self.recolor(theme_manager.tokens)

    def _setup_window(self) -> None:
        """Set up window properties: title, size, minimum size."""
        # The title is written exactly once, here. The status channel batch 1 left
        # behind rewrote it on every event; spec §1 criterion 3 retires that, and
        # Task 8 deleted the channel with it. Task 8's source scan of ``view/`` and
        # ``presenter/`` is what keeps it from coming back as a one-line forwarder
        # (ledger R1's transitional shim).
        self._base_title = i18n.get('window.title')
        self.setWindowTitle(self._base_title)

        # Size window relative to available screen space
        app = QApplication.instance()
        if app and app.primaryScreen():
            screen_geom = app.primaryScreen().availableGeometry()
            target_w = min(max(int(screen_geom.width() * 0.8), 800), 1400)
            target_h = min(max(int(screen_geom.height() * 0.75), 500), 900)
            target_x = screen_geom.x() + (screen_geom.width() - target_w) // 2
            target_y = screen_geom.y() + (screen_geom.height() - target_h) // 2
            self.setGeometry(target_x, target_y, target_w, target_h)
        else:
            self.setGeometry(100, 100, 1000, 700)

        self.setMinimumSize(800, 500)

    # === Keyboard (batch 3, spec §5) ===

    def _setup_shortcuts(self) -> None:
        """Install every window-level key binding, and nothing else's.

        ``addAction`` is the load-bearing line, not the ``QKeySequence``: batch 2
        deleted the menu bar, and an action that is constructed but never attached to a
        widget is reachable by nothing -- the shortcut string exists, the key is dead.
        ``Ctrl+Q`` came here from :meth:`_setup_window` for the same reason: spec §5
        asks for the window's key bindings to sit in one place, and it is the only
        action batch 2 left behind.

        Two rules from the measurements this shape depends on:

        * **``Ctrl+Space`` and never bare ``Space``** (spec §4.4 / ruling R4). Task 1
          measured the bare key on this host: it walks the list cursor and replaces the
          selection with the row it landed on, and ``Ctrl+Space`` reaches the *same*
          built-in handler. So the binding has to be one that **consumes** the press
          before ``QListView`` sees it -- which is what an enabled window ``QAction``
          does, and what ``test_shortcut_beats_the_focused_widget_to_the_key`` proves
          by requiring the selection and the current row to come back unchanged
          (ruling R10). ``tests/test_playlist_shortcuts.py``
          :class:`NativeKeyBehaviourProbeTest` re-measures the unconstrained view
          beside it, so the two halves cannot both go quiet on a Qt upgrade.
        * **No ``Ctrl+A``.** ``QListView`` already answers it natively (measured:
          ``[1] -> [0, 1, 2]`` on a three-row list), and a window action on the same
          key would eat the press before the view's ``selectAll()`` ran.

        Ownership: every action here is parented to and added to *this* window, and
        ``BottomPanel`` binds nothing of its own (pinned by
        ``test_the_widgets_bind_no_shortcuts_of_their_own``). The two exemptions are
        ``ActionRail``'s ``Ctrl+O``, which batch 2 deliberately pinned on the rail, and
        ``Delete``/``Enter``, which ruling **R11** moved to
        :meth:`view.widgets.playlist_view.PlaylistView.keyPressEvent`.

        R11 is the fix for Important 1 of the Task 6 review, and it is a change of
        mechanism, not of wording. What was shipped at ``3356222`` bound ``Delete`` and
        ``Return`` as window ``QAction``s and made "do nothing when focus is outside the
        list" true by returning early from the slot. That does not work: matching has
        already consumed the key by then, so the early return leaves the focused widget
        with nothing either. Measured with ``#playButton`` focused -- the button's own
        ``keyPressEvent`` saw ``Enter`` and ``Delete`` **0** times, while an identical
        button in a window with no bindings at all saw each **1** time. So the two keys
        were dead across the whole window subtree: the five ``QPushButton``s of the
        control bar, every ``LibraryRow``, and the ``QLineEdit`` batch 6 will add for
        search. The alternatives were measured too and none is available:
        ``QAction.setShortcutWidget`` (the API that would give a real subtree scope) does
        not exist in PyQt6 6.11; narrowing the context to ``WidgetShortcut`` stops the
        binding answering *inside* the list as well; and re-enabling the focused
        widget around the press (enable/disable bookkeeping) was **not probed** -- it
        is named here as a shape, not as a measurement, and it would still be the
        window hand-managing a key it has already taken. Handling the two keys in the view needs neither, because the press only
        reaches :class:`PlaylistView` when ``QListView`` was not using it -- measured:
        ``Delete``/``Enter``/numpad ``Key_Enter`` arrive, bare ``Space`` and the bare
        arrows do not. See the plan's 裁定 R11 for the numbers.
        """
        # Ctrl+Q has no rail button -- closing the window *is* quitting, and
        # spec §6 keeps Exit off the column -- so it needs a window-level owner
        # here or the shortcut dies with the menu bar. The platform standard
        # stays the first entry (Cmd+Q on macOS, Ctrl+Q on Windows/Linux, which
        # is what the deleted menu used); the literal ``Ctrl+Q`` rides along
        # because it is the promise spec §6 makes and because the offscreen
        # platform resolves ``StandardKey.Quit`` to the unusable string
        # ``"Exit"`` -- measured, and the reason the shortcut regression test
        # could not have been green here before the swap. Identical sequences
        # collapse, so a real Windows desktop gets one shortcut, not two.
        exit_action = QAction(i18n.get('menu.exit'), self)
        exit_action.setShortcuts([
            QKeySequence(QKeySequence.StandardKey.Quit),
            QKeySequence('Ctrl+Q'),
        ])
        exit_action.triggered.connect(self.close)
        self.addAction(exit_action)

        # Transport only. Adding a Delete/Enter action back here would re-open
        # Important 1, and ``test_no_window_binding_steals_delete_or_enter`` is the
        # guard that says so in that case.
        # Nothing is stored on the window for these three: no attribute is read, and
        # the ownership tests enumerate the bindings by *sequence*
        # (``test_shortcuts_are_owned_by_the_main_window``), never by name. The object
        # names these actions used to carry are gone with them -- no QSS rule styles
        # them (this sheet is the only one, ``theme_manager.py``) and no ``findChild``
        # ever looked them up. ``tests/test_dead_code_removed.py`` forbids naming them
        # again, including here.
        self._add_shortcut(self.SHORTCUT_PLAY_PAUSE, self._on_play_pause_shortcut)
        self._add_shortcut(self.SHORTCUT_PREV, self._on_prev_shortcut)
        self._add_shortcut(self.SHORTCUT_NEXT, self._on_next_shortcut)

    def _add_shortcut(self, sequence: str, handler) -> QAction:
        """Build one enabled ``QAction``, attach it to this window, return it.

        Kept as a helper because the three transport bindings differ only in key
        and slot, and the ``addAction`` line is the one every one of them must not lose.
        No text: these actions are reachable only by the keyboard (there is no menu bar
        left to show a label), so giving them copy would mean inventing UI strings nobody
        renders -- and the plan's locale rule is about user-visible text.

        No ``setShortcutContext`` call either: all three are ``WindowShortcut`` by
        default, which is what "the whole shell answers the transport keys" means. A
        binding that should answer only inside the list belongs in
        :meth:`view.widgets.playlist_view.PlaylistView.keyPressEvent` instead (ruling
        R11) -- at this window level there is no context value that means "the playlist
        subtree", and the in-slot focus gate that used to pretend otherwise consumed
        the key either way.
        """
        action = QAction(self)
        action.setShortcut(QKeySequence(sequence))
        action.triggered.connect(handler)
        self.addAction(action)
        return action

    def _on_play_pause_shortcut(self) -> None:
        """``Ctrl+Space``: the same request the strip's play button makes.

        Re-emitting ``play_pause_requested`` and nothing more: the presenter owns the
        play/pause decision, so the keyboard cannot grow a second opinion here.
        """
        self.play_pause_requested.emit()

    def _on_prev_shortcut(self) -> None:
        """``Ctrl+Up``: previous track, exactly like the strip's button."""
        self.prev_track_requested.emit()

    def _on_next_shortcut(self) -> None:
        """``Ctrl+Down``: next track, exactly like the strip's button."""
        self.next_track_requested.emit()

    def _setup_ui(self) -> None:
        """Set up the main UI layout: rail | full-width list, control bar below."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        # The rail owns its width (``RAIL_WIDTH``, fixed inside the widget);
        # the list gets every remaining pixel -- spec §1 criterion 1.
        self._rail = ActionRail(self._theme)

        # ``content_stack`` is the area right of the rail. The sidebar is its
        # child but not a layout item, so it floats over the list without
        # taking width from it; ``_place_panel`` clamps it inside the stack and
        # the app-level filter re-places it on resize.
        self._content_stack = QWidget()
        stack_layout = QVBoxLayout(self._content_stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)

        # Layout host only: named so the tests and the toast wiring can find
        # it, deliberately unstyled and deliberately *not* in
        # ``REQUIRED_OBJECT_NAMES`` (ledger R2 -- a registered name the sheet
        # does not emit would fail the structure contract it exists to guard).
        self._playlist_container = QWidget()
        self._playlist_container.setObjectName('playlistContainer')
        container_layout = QVBoxLayout(self._playlist_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self._playlist_view = PlaylistView(self._theme)
        container_layout.addWidget(self._playlist_view)
        stack_layout.addWidget(self._playlist_container)

        content_row.addWidget(self._rail)
        content_row.addWidget(self._content_stack, stretch=1)
        main_layout.addLayout(content_row, stretch=1)

        self._sidebar = LibrarySidebar(self._theme, self._content_stack)

        # The toast floats in the list container, so "above the control bar"
        # is the container's own bottom edge and needs no bar height here
        # (Task 6's ruling). It re-places with the container via eventFilter.
        self._toast = Toast(self._playlist_container)
        self._playlist_container.installEventFilter(self)

        # Bottom panel - now-playing strip, progress and playback controls
        self._bottom_panel = BottomPanel(self._theme)
        main_layout.addWidget(self._bottom_panel)

    # spec §8 asks whether Qt still synthesises a minimal application menu on
    # macOS once no QMenuBar content exists. That is unverifiable on this
    # Windows host, so no invisible fallback bar is pre-implemented here;
    # Task 10's closing report carries the item as "unverified, macOS users
    # must confirm before merge".
    def _setup_connections(self) -> None:
        """Connect internal widget signals to main window signals."""
        # Bottom panel connections
        self._bottom_panel.play_pause_clicked.connect(self.play_pause_requested.emit)
        self._bottom_panel.stop_clicked.connect(self.stop_requested.emit)
        self._bottom_panel.next_clicked.connect(self.next_track_requested.emit)
        self._bottom_panel.prev_clicked.connect(self.prev_track_requested.emit)
        self._bottom_panel.volume_changed.connect(self.volume_changed.emit)
        self._bottom_panel.loop_mode_changed.connect(self.loop_mode_changed.emit)
        self._bottom_panel.seek_requested.connect(self.seek_requested.emit)

        # Playlist connections
        self._playlist_view.track_double_clicked.connect(self.track_double_clicked.emit)

        # Batch 3 (Task 6): the three batch routes re-exported as the View API. Pure
        # forwards -- the signal types already match (``pyqtSignal(list)`` to
        # ``pyqtSignal(list)``, and ``clear_playlist_requested`` carries nothing), so
        # there is no conversion here and nothing should be added: the indices are
        # already ascending and deduplicated by ``PlaylistView``, and re-sorting a second
        # time would be a second place for the two to disagree (spec §4.2 hands the
        # descending order to the presenter's loop).
        #
        # Both entries reach these lines: the right-click menu emits the view's own
        # signals, and the view's :meth:`~view.widgets.playlist_view.PlaylistView.keyPressEvent`
        # calls the ``request_*`` helpers that emit the same ones (ruling R11). One
        # route, so the keyboard and the menu cannot drift apart -- and the reason the
        # key tests in ``tests/test_playlist_shortcuts.py`` fail when a forward below is
        # dropped.
        self._playlist_view.play_requested.connect(self.play_tracks_requested.emit)
        self._playlist_view.remove_requested.connect(self.remove_tracks_requested.emit)
        # Ruling R9: this one has had a real emitter since Task 3 and, until this task,
        # no landing at all. Its consumer is ``MainPresenter._on_clear_playlist``.
        self._playlist_view.clear_playlist_requested.connect(
            self.clear_playlist_requested.emit)

        # Rail: connect *only* ``action_triggered``. A click on a rail button
        # already routes ``clicked -> action.trigger() -> triggered``, and
        # ``ActionRail._make_button`` listens on the action side only (Task 3's
        # critical fix), so a second connection on the buttons would deliver
        # every click to the presenter twice -- pinned by
        # ``tests/test_view_structure.py::test_rail_dispatch_reaches_the_window_exactly_once``.
        self._rail.action_triggered.connect(self._on_rail_action)
        self._rail.library_panel_requested.connect(self.toggle_library_panel)

        # Same rule on the panel side: its signals already carry their own
        # de-duplication (Task 4), the window just re-exports them. Both footer
        # entries -- add and manage (spec §3.2's Task 8 correction) -- reach the
        # presenter through a window signal, so the panel knows nothing about
        # dialogs or configuration.
        self._sidebar.library_selected.connect(self._on_library_selected)
        self._sidebar.add_library_requested.connect(self.add_library_requested.emit)
        self._sidebar.manage_requested.connect(self.manage_libraries_requested.emit)

    # === Rail handlers ===

    def _on_rail_action(self, action_id: str) -> None:
        """Dispatch one ``action_triggered`` emission to the slot the menu used.

        The ids are the rail module's constants, not local literals: the wire
        format and this table are the same declaration (``ActionRail`` docstring,
        Task 3). ``ACTION_LIBRARY`` never arrives here -- the panel toggle is
        its own signal because the window, not the presenter, owns it. An
        unknown id is ignored on purpose: the rail cannot emit one, and a
        crash in a click handler is worse than a no-op.
        """
        handlers = {
            ACTION_OPEN_FILE: self._on_open_file,
            ACTION_OPEN_FOLDER: self._on_open_folder,
            ACTION_REFRESH: self._on_refresh_library,
            ACTION_REFRESH_ALL: self._on_refresh_all,
            ACTION_APPEARANCE: self.manage_appearance_requested.emit,
            ACTION_ABOUT: self._on_about,
        }
        handler = handlers.get(action_id)
        if handler is not None:
            handler()

    def _on_open_file(self) -> None:
        """Handle open file action.

        Known pre-existing defect, deliberately preserved (spec §6): with
        several files selected only the *first* file's parent directory is
        scanned. Fixing it is out of scope for batch 2.
        """
        files, _ = QFileDialog.getOpenFileNames(
            self,
            i18n.get('dialog.open_file'),
            "",
            i18n.get('dialog.audio_files') + " (*.mp3 *.wav *.flac *.ogg *.m4a *.aac)"
        )
        if files:
            # Emit signal for first file, or add all to playlist
            if len(files) == 1:
                self.scan_folder_requested.emit(str(Path(files[0]).parent))
            else:
                # Add all files - for now just play first
                self.scan_folder_requested.emit(str(Path(files[0]).parent))

    def _on_open_folder(self) -> None:
        """Handle open folder action."""
        folder = QFileDialog.getExistingDirectory(
            self,
            i18n.get('dialog.open_folder')
        )
        if folder:
            self.scan_folder_requested.emit(folder)

    def _on_refresh_library(self) -> None:
        """Handle refresh library action."""
        # Emit signal with current library path if available
        if self._current_library_path:
            self.refresh_library_requested.emit(self._current_library_path)

    def _on_refresh_all(self) -> None:
        """Handle refresh all libraries action."""
        self.refresh_all_requested.emit()

    def _on_library_selected(self, library_path: str) -> None:
        """Handle library selection from the floating panel."""
        self._current_library_path = library_path
        self.library_selected.emit(library_path)

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            i18n.get('dialog.about.title'),
            i18n.get('dialog.about.text')
        )

    # === Overlay plumbing ===

    def eventFilter(self, watched, event) -> bool:
        """Re-place a visible toast when its container gets a new size.

        ``Toast.show_toast`` positions only at show time (Task 6's contract),
        so after a drag-shrink a live toast would sit off-centre or overhang
        the narrower container for the rest of its interval. The widget keeps
        its own placement maths; this window owns the *when*, and watches the
        container directly because the resize that matters is the container's
        own (already clamped by the layout), not the window's.
        """
        if (event.type() == QEvent.Type.Resize
                and watched is self._playlist_container
                and self._toast.isVisible()):
            self._toast.reposition()
        return super().eventFilter(watched, event)

    def toggle_library_panel(self) -> None:
        """Open or close the floating library panel (rail's library button)."""
        self._sidebar.toggle()

    def is_library_panel_open(self) -> bool:
        """Whether the panel is currently showing."""
        return self._sidebar.is_panel_open()

    def show_toast(self, message: str, msec: int = 2500) -> None:
        """Show a timed feedback line above the control bar (spec §5)."""
        self._toast.show_toast(message, msec)

    def set_action_progress(self, action_id: str, running: bool) -> None:
        """Put a rail action into (or out of) its running state.

        The presenter's two library-scan call sites use this instead of a message
        (spec §5's 进度态 row); the three-layer name (``set_action_progress`` here,
        ``set_progress`` on the rail) is the plan's, not a typo. Which ids may be in
        flight is the rail's decision, not the caller's -- it raises for anything
        outside :data:`view.widgets.action_rail.PROGRESSABLE_IDS`, and this forwarder
        deliberately adds no guard of its own: a second whitelist two layers up is a
        second place for the two lists to disagree.
        """
        self._rail.set_progress(action_id, running)

    def _check_background_image(self, config) -> None:
        """
        Check if configured background image exists.
        Show warning and clear config if file not found.

        Args:
            config: SettingsManager instance
        """
        bg_path = config.get_background_image()
        if bg_path and not os.path.exists(bg_path):
            QMessageBox.warning(
                self,
                i18n.get('dialog.title.warning', default='警告'),
                i18n.get('warning.background_not_found', default='背景图片文件不存在，已恢复默认背景')
            )
            config.set_background_image(None)

    def set_background_image(self, path: Optional[str]) -> None:
        """
        Set the background image for the main window.
        Uses aspect ratio preserving scale, fitting the shorter edge.

        Args:
            path: Path to the background image, or None to clear.
        """
        if path and os.path.exists(path):
            self._background_pixmap = QPixmap(path)
            self.update()  # Trigger repaint
        else:
            # Clear background, restore default
            self._background_pixmap = None
            self.update()

    def set_overlay_alpha(self, alpha: float) -> None:
        """Set the background overlay transparency.

        The value lives on the manager (single source for the sheet and the
        scrim); ``theme_changed`` then comes back around to :meth:`recolor`,
        which refreshes the local mirror and repaints.
        """
        self._theme.set_alpha('overlay', alpha)

    def scrim_color(self) -> QColor:
        """The background overlay colour: theme scrim token at the overlay alpha.

        Replaces the hardcoded ``QColor(255, 255, 255, alpha)`` the paint event
        used before the theme layer existed -- that white-on-dark-image scrim
        was half of why dark mode read as light.
        """
        color = QColor(self._theme.tokens.scrim)
        color.setAlphaF(min(1.0, max(0.0, self._overlay_alpha)))
        return color

    def recolor(self, tokens) -> None:
        """React to ``ThemeManager.theme_changed``.

        The application sheet and palette are already re-pushed by the manager;
        what is left are the things it cannot reach: the three widgets that
        rasterise token-coloured SVG glyphs -- the rail, the sidebar rows, the
        bottom panel (whose strip takes the call too for shape, see
        :meth:`BottomPanel.recolor`) -- the delegate-painted playlist rows, and
        this window's scrim.
        """
        self._overlay_alpha = self._theme.alphas.overlay
        self._rail.recolor(tokens)
        self._sidebar.recolor(tokens)
        self._bottom_panel.recolor(tokens)
        self._playlist_view.recolor()
        self.update()

    def paintEvent(self, event) -> None:
        """Override paint event to draw scaled background image with semi-transparent overlay."""
        super().paintEvent(event)

        if self._background_pixmap and not self._background_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Restrict painting to the content area (central widget), avoiding the
            # native title bar on macOS and window frame area on all platforms.
            # Since Task 7 there is no menu bar row above the central widget,
            # so the content area is the whole client rect.
            cw = self.centralWidget()
            if cw:
                content_rect = QRect(cw.mapTo(self, cw.rect().topLeft()), cw.size())
            else:
                content_rect = self.rect()
            pixmap_size = self._background_pixmap.size()

            # Calculate scale factor to fit the shorter edge
            scale_x = content_rect.width() / pixmap_size.width()
            scale_y = content_rect.height() / pixmap_size.height()
            scale = max(scale_x, scale_y)  # Use larger scale to cover window

            # Calculate scaled dimensions
            scaled_width = int(pixmap_size.width() * scale)
            scaled_height = int(pixmap_size.height() * scale)

            # Center the image within the content area
            x = content_rect.x() + (content_rect.width() - scaled_width) // 2
            y = content_rect.y() + (content_rect.height() - scaled_height) // 2

            # Draw scaled pixmap centered
            target_rect = QRect(x, y, scaled_width, scaled_height)
            painter.drawPixmap(target_rect, self._background_pixmap)

            # Draw the theme scrim over the image (scrim token + overlay alpha)
            painter.fillRect(content_rect, self.scrim_color())

    # === Public API for Presenter ===

    def set_libraries(self, libraries: List[Any]) -> None:
        """
        Set the list of available libraries for the floating panel.

        Args:
            libraries: List of LibraryConfig objects
        """
        self._libraries = libraries
        self._sidebar.set_libraries(libraries)

    def set_current_library(self, library_path: str) -> None:
        """
        Set the current active library.

        Args:
            library_path: Path to the current library
        """
        self._current_library_path = library_path
        self._sidebar.set_current(library_path)

    def update_track_info(self, title: str, artist: str = "", album: str = "") -> None:
        """Update the now playing strip's info display."""
        self._bottom_panel.update_track_info(title, artist, album)

    def update_album_art(self, art_data: Optional[bytes]) -> None:
        """Update the now playing strip's cover thumbnail."""
        self._bottom_panel.update_album_art(art_data)

    def update_progress(self, position: float, duration: float) -> None:
        """Update the progress slider."""
        self._bottom_panel.update_progress(position, duration)

    def set_playing_state(self, is_playing: bool, is_paused: bool = False) -> None:
        """Update the play/pause button state."""
        self._bottom_panel.set_playing_state(is_playing, is_paused)

    def set_volume(self, volume: float) -> None:
        """Set the volume slider."""
        self._bottom_panel.set_volume(volume)

    def set_loop_mode(self, mode: str) -> None:
        """Set the loop mode button."""
        self._bottom_panel.set_loop_mode(mode)

    def highlight_current_track(self, display_idx: int) -> None:
        """Highlight the currently playing track in the playlist."""
        self._playlist_view.set_current_playing(display_idx)

    def set_playlist_entries(self, entries: List[DisplayEntry]) -> None:
        """Set the playlist entries."""
        self._playlist_view.set_entries(entries)

    def clear_playlist(self) -> None:
        """Clear the visible list. Zero production callers; kept for the matrix.

        The presenter does not use this -- clearing goes through ``QueueService.clear``
        and comes back down as ``display_changed([])`` -- and no test drives it either.
        Its one caller in the repo is ``tests/tools/render_matrix.py``, an automated
        path this batch ships, so the pair (with ``PlaylistView.clear``) stays until
        that call goes; delete the two together, not one at a time.
        """
        self._playlist_view.clear()

    def clear_now_playing(self) -> None:
        """Clear the now playing strip."""
        self._bottom_panel.clear_now_playing()

    def reset_progress(self) -> None:
        """Reset the progress slider."""
        self._bottom_panel.reset_progress()

    def set_playlist_alpha(self, alpha: float) -> None:
        """Set playlist background transparency (forwarded to the theme manager)."""
        self._theme.set_alpha('playlist', alpha)

    def set_controls_alpha(self, alpha: float) -> None:
        """Set bottom panel background transparency (forwarded to the theme manager)."""
        self._theme.set_alpha('controls', alpha)

    def show_error(self, title: str, message: str) -> None:
        """Show an error dialog."""
        QMessageBox.critical(self, title, message)

    def show_info(self, title: str, message: str) -> None:
        """Show an info dialog."""
        QMessageBox.information(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        # Could emit a signal for presenter to save state
        event.accept()
