#!/usr/bin/env python3
"""
Playlist View - List view for playlist with custom rendering
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QAbstractItemView, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex, QPoint, QItemSelectionModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n
from view.models.playlist_model import PlaylistModel
from view.delegates.playlist_delegate import PlaylistItemDelegate
from view.widgets.playlist_context_menu import (
    MENU_CLEAR, MENU_PLAY, MENU_REMOVE, build_playlist_menu
)


def _global_menu_point(event):
    """Where a context-menu event asked for the menu, in global coordinates.

    ``QContextMenuEvent.globalPosition()`` is Qt 6.6+; ``requirements.txt`` floors
    the dependency at ``PyQt6>=6.5.0``, where only the deprecated ``globalPos()``
    exists, so the newer accessor is probed rather than assumed. This is the same
    idiom as ``library_sidebar._global_press_point`` for the same version gap --
    duplicated rather than imported because that helper is private to a widget
    module this one has no reason to depend on.
    """
    getter = getattr(event, 'globalPosition', None)
    if callable(getter):
        return getter().toPoint()
    return event.globalPos()


class PlaylistView(QWidget):
    """
    Playlist display widget using QListView with custom model.

    Features:
    - Double-click to play
    - Current track highlighting
    - Hover feedback on the row under the cursor: the delegate paints
      ``tokens.hover_bg`` for it, below the playing and selection tints
    - Windows-Explorer multi-selection (Ctrl/Shift+click), readable through
      :meth:`selected_display_indices` and :meth:`display_index_at`
    - Windows-Explorer right-click: a row outside the selection is narrowed to,
      a row inside it keeps the batch, blank space opens nothing -- and the
      clicked entry leaves as one of ``play_requested`` / ``remove_requested`` /
      ``clear_playlist_requested``.
    - ``Delete`` removes the batch and ``Enter`` plays it. Those two keys are the
      exception to "all key bindings live on ``MainWindow``" (spec §5), and ruling
      R11 put them here on purpose: see :meth:`keyPressEvent`.

    The header and the list are styled by the application sheet through
    ``#playlistHeader`` / ``#playlistView``; the row states are painted by
    :class:`PlaylistItemDelegate`, which reads the theme manager's tokens.
    """

    # Signals
    track_double_clicked = pyqtSignal(int)       # display index
    # 批次 3：右键菜单接口。**A deliberate observation hook, with no production slot.**
    # Batch 1 declared it, Task 3 wired the emit, and nothing in ``view/``,
    # ``presenter/`` or ``service/`` connects to it -- verified by grep, not assumed.
    # Ruling R9 calls "emitted and connected, landing nowhere, all green" a defect, so
    # the absence is stated here instead of left to be rediscovered, and it is *not*
    # an oversight to close: the signal is this batch's witness that a right-click
    # routed through ``contextMenuEvent`` at all, and its payload is the only read of
    # ``targets[0]`` available to the two automated listeners --
    # ``tests/test_playlist_selection.py`` (``ContextMenuTargetTest``, which records
    # every emission in order) and ``tests/tools/render_matrix.py`` (the menu frame).
    # What production *acts* on is the dispatch that follows the popup:
    # ``play_requested`` / ``remove_requested`` / ``clear_playlist_requested``.
    # Payload is the smallest selected display index, not the row under the cursor;
    # see the emit comment in :meth:`contextMenuEvent`.
    context_menu_requested = pyqtSignal(int, object)  # display index, event
    # Declared here, in the task that first emits them (ruling R1): a signal nobody
    # emits is dead code, and the dead-signal census that enforces that is a batch 1
    # asset. ``play_requested`` / ``remove_requested`` carry ascending *display*
    # indices -- the same space as ``selected_display_indices()``, not
    # ``DisplayEntry.node_idx`` -- and the receiver must not re-sort them: batch
    # removal reverses them itself (spec §4.2). ``clear_playlist_requested`` carries
    # nothing, because clearing the playlist is not scoped to the target.
    play_requested = pyqtSignal(list)
    remove_requested = pyqtSignal(list)
    clear_playlist_requested = pyqtSignal()

    def __init__(self, manager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header (A6: the English literal is gone; #playlistHeader's text is
        # the i18n value, re-read whenever the widget tree is built).
        header = QLabel(i18n.get('playlist.header'))
        header.setObjectName("playlistHeader")
        layout.addWidget(header)

        # List view with custom model
        self._list_view = QListView()
        self._list_view.setObjectName("playlistView")
        self._model = PlaylistModel(self)
        self._list_view.setModel(self._model)

        # Set custom delegate for rendering relative position. The delegate is
        # handed the manager because the row colours and the playing highlight
        # are theme values, not model data.
        self._list_view.setItemDelegate(PlaylistItemDelegate(self._theme, self._list_view))

        # Configure list view
        # Windows-Explorer semantics (batch 3, spec §4.3): Ctrl+click toggles a
        # row, Shift+click extends a range, and a right-click target only
        # replaces the selection when that row is not already in it -- both
        # need a multi-row selection, which SingleSelection can never hold.
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list_view.setAlternatingRowColors(True)

        # Hover tracking for the row delegate (batch 3, C2). Mouse *motion* only
        # puts ``QStyle.State_MouseOver`` on the option of the row under the
        # cursor while this attribute is set, and it has to be the *viewport*'s
        # attribute: measured on this host (Qt 6.11.0, offscreen), setting it on
        # the ``QListView`` leaves every option at ``State_Enabled|State_Active``
        # -- so without this line ``PlaylistItemDelegate``'s hover branch is dead
        # code. (Scoped to motion on purpose: a hand-posted ``QHoverEvent`` can
        # set the bit without the attribute, which is why the tests move the
        # cursor rather than invent events.) It is also what makes the view
        # repaint when the hover changes, in both directions -- the leave half is
        # pinned by the un-hover claim in ``tests/test_playlist_hover.py``.
        self._list_view.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # Enable smooth scrolling
        self._list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)

        # Connect signals
        self._list_view.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self._list_view)

    def _on_double_click(self, index: QModelIndex) -> None:
        """Handle double-click on item."""
        self.track_double_clicked.emit(index.row())

    def recolor(self) -> None:
        """Repaint the rows after a theme change.

        ``PlaylistItemDelegate`` reads the manager's tokens at paint time, so
        nothing has to be rebuilt here -- the viewport just has to be asked to
        paint again (the sheet itself is re-pushed by the manager).
        """
        self._list_view.viewport().update()

    def set_entries(self, entries: list) -> None:
        """
        Set playlist entries.

        Args:
            entries: List of DisplayEntry objects
        """
        self._model.update_entries(entries)

    def set_current_playing(self, display_idx: int) -> None:
        """
        Highlight the currently playing track.

        Args:
            display_idx: Index in display list, or -1 to clear
        """
        self._model.set_current_playing(display_idx)

        # Scroll to show the playing track
        if display_idx >= 0:
            index = self._model.index(display_idx)
            self._list_view.scrollTo(index, QListView.ScrollHint.EnsureVisible)

    def selected_display_indices(self) -> list:
        """Every selected row, ascending and without duplicates.

        These are *display* rows -- positions in the visible list -- not the
        queue's node indices, which the two differ by once folders are expanded
        (``DisplayEntry.node_idx``). Feed them to the display-index API the
        presenter already has, never straight to the node list.

        Batch 3's removal path is the consumer. The indices have to come back
        ascending here because they describe the *selection*: the batch-removal
        loop reverses them itself (spec §4.2 -- deleting row 3 shifts row 5 up
        to 4), while ``Enter`` plays ``indices[0]``, the smallest display index
        (spec §5). Returns ``[]`` for an empty selection, which spec §7 says a
        caller must act on rather than forward to the presenter.
        """
        rows = (index.row() for index in
                self._list_view.selectionModel().selectedRows())
        return sorted(set(rows))

    def display_index_at(self, pos: QPoint, widget: QWidget) -> int:
        """The row under ``pos``, read in ``widget``'s coordinate space.

        ``widget`` is required, not defaulted to the viewport. The list does not
        fill this widget -- a header label sits above it -- so the two spaces are
        offset by the header's height, and a right-click arrives in whichever
        widget took the event (spec §4.3). Guessing the space is not a cosmetic
        error: outer-widget coordinates would target every row one header too
        high and report the header strip as row 0. Pass the widget ``pos`` came
        from and this maps it.

        Blank means no row: the strip below the last entry, the header, or an
        empty model. ``-1``, and spec §4.3 requires the context menu to stay
        closed there.
        """
        index = self._list_view.indexAt(self._list_view.viewport().mapFrom(widget, pos))
        if not index.isValid():
            return -1
        return index.row()

    # -- right-click (batch 3, spec §4.3) ---------------------------------

    def contextMenuEvent(self, event) -> None:
        """Resolve the target, show the menu, and emit what was clicked.

        The event reaches *this* widget because ``QAbstractItemView`` ignores it:
        measured on this host, a right-click aimed at the list viewport arrives
        here with ``pos()`` re-expressed in this widget's space (the viewport sits
        at (1, 13) inside it, below the header). That is why the target lookup
        passes ``self`` as the coordinate source -- the second argument of
        :meth:`display_index_at` exists precisely so this line cannot guess.

        Blank space (``-1``) returns without touching the selection and without
        emitting anything, per spec §4.3 and §7. That path neither accepts nor
        ignores the event, so nothing here asserts whether it then reaches an
        ancestor: under ``offscreen`` the tests post the event directly, and the
        behaviour of a spontaneous right-click is left to the real-hardware check
        (Task 8) rather than guessed at from a docstring.
        """
        row = self.display_index_at(event.pos(), self)
        if row < 0:
            return

        if row not in self.selected_display_indices():
            # Explorer's rule, and the reason the view is ExtendedSelection: only
            # a row that is *not* part of the batch may collapse it. Qt does not
            # do this itself -- right-clicking never changes a selection and never
            # fires ``clicked`` -- so the mutation belongs here.
            self._select_only(row)

        targets = self.selected_display_indices()
        menu = build_playlist_menu(targets, self._is_playing_index_in(targets), self)
        if menu is None:
            # Unreachable through this handler (``targets`` is never empty here);
            # the builder owns the "no target, no menu" contract and Task 2 pinned
            # it, so this is the caller honouring that contract, not a second
            # expression of it.
            return

        # Emitted before the popup rather than after the dispatch: this names the
        # *request*, and both halves of its payload still describe the state the menu
        # was built from -- nothing has acted on the selection or the rows yet. Once an
        # action signal has run, the row can be gone (Task 5's removal) and the event is
        # what the dispatch consumed.
        # ``targets[0]`` is NOT "the row the user pointed at". Under the Explorer rule
        # above, a cursor inside an existing batch keeps the batch, so ``targets`` is the
        # whole selection and ``targets[0]`` is its **smallest display index**; the cursor
        # row is ``row``, still on this stack, and is deliberately not the payload --
        # pointing at one row of a batch requests that batch, so the minimum is the
        # value that describes what the menu acted on. ``tests/tools/render_matrix.py``
        # already measures this shape and pins ``min(BATCH_ROWS)``.
        self.context_menu_requested.emit(targets[0], event)

        try:
            action = self._popup_menu(menu, _global_menu_point(event))
        finally:
            # Ruling R7: the builder parented this menu to the view, so without
            # this the live tree grows one QMenu per right-click, forever -- and
            # no other test in the suite can see it, because the structure
            # contract that walks the window never right-clicks. ``deleteLater()``
            # rather than an immediate delete: the menu is a widget that has just
            # run a modal loop, and Qt's own rule for that is deferral. The
            # deferred delete runs when control returns to the event loop (see the
            # residue test for how that is proven here).
            menu.deleteLater()

        self._dispatch_menu_action(action, targets)
        event.accept()

    def _popup_menu(self, menu, global_pos):
        """Show the menu modally and return the action it triggered, or ``None``.

        A seam, not a convenience: ``QMenu.exec()`` spins a nested event loop, so
        no automated test may reach it. The tests patch this method (and assert
        through it, which is how the target list is read *while the menu is open*)
        while production runs the real call.
        """
        return menu.exec(global_pos)

    def _dispatch_menu_action(self, action, targets: list) -> None:
        """Turn a clicked menu entry into the view's signal for it.

        Dispatch is on ``action.data()`` -- the ``MENU_*`` id the builder stamped
        -- and the indices come from the local ``targets``, because the menu
        carries no target of its own (Task 2's contract). A cancelled menu hands
        back ``None`` and acts on nothing.
        """
        if action is None:
            return

        menu_id = action.data()
        if menu_id == MENU_PLAY:
            self.play_requested.emit(list(targets))
        elif menu_id == MENU_REMOVE:
            self.remove_requested.emit(list(targets))
        elif menu_id == MENU_CLEAR:
            self.clear_playlist_requested.emit()

    def _select_only(self, row: int) -> None:
        """Make ``row`` the whole selection, through the selection model."""
        self._list_view.selectionModel().select(
            self._model.index(row),
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows)

    def _is_playing_index_in(self, targets: list) -> bool:
        """Whether the target batch includes the playing row: Play or Pause?

        This decides the first entry's *label* only -- the action keeps id
        ``MENU_PLAY`` either way (Task 2's contract), so "any target is playing"
        versus "the target is exactly the playing row" can never change what a
        click dispatches to. Batch semantics: pausing a batch that contains the
        playing track is the reading that stays honest to the label.
        """
        playing = self._model.get_playing_index()
        return playing >= 0 and playing in targets

    # -- keyboard (batch 3, Task 6 / ruling R11) ---------------------------

    #: The two keys whose meaning is "the rows this list is showing", answered here
    #: rather than by a window ``QAction`` (ruling R11, fix round 1).
    #:
    #: Why they are not window bindings: ``QAction.setShortcutWidget`` -- the API that
    #: would scope a window-level shortcut to this subtree -- **does not exist in
    #: PyQt6 6.11** (measured: ``hasattr(QAction, 'setShortcutWidget')`` is ``False``,
    #: calling it raises ``AttributeError``), and the in-slot focus gate that was
    #: shipped in their place cannot undo a match. Once a window-level shortcut matches,
    #: Qt has consumed the press; returning early from the slot leaves the focused
    #: widget with nothing. Measured at ``3356222`` with ``#playButton`` focused: the
    #: button's own ``keyPressEvent`` saw the ``Enter`` and the ``Delete`` **zero**
    #: times, while the same button in a window with no bindings at all saw each of
    #: them once.
    #:
    #: What this widget does see (measured, focus on the inner ``QListView``):
    #: ``Delete``, ``Enter`` and numpad ``Key_Enter`` -- ``QListView`` accepts neither,
    #: so Qt walks the press up the parent chain and lands here -- and **not** bare
    #: ``Space`` or the bare arrows, which the list accepts downstairs. That asymmetry
    #: is the design: a key that reaches this method is by construction a key the list
    #: was not using, so the override cannot steal the native navigation the spec §5
    #: "不劫持" criterion protects, and it needs no focus bookkeeping to know that.
    REMOVE_KEYS = (Qt.Key.Key_Delete,)
    PLAY_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)

    def keyPressEvent(self, event) -> None:
        """``Delete`` removes the batch, ``Enter`` plays it (spec §5).

        Both go through :meth:`request_remove_selection` /
        :meth:`request_play_selection`, where the "empty selection emits nothing"
        rule (spec §7) is enforced once. The right-click menu does **not** use
        them: :meth:`_dispatch_menu_action` emits with the batch it resolved at
        open time, so a menu press and a key press carry deliberately different
        payloads -- see the note in :meth:`request_play_selection`.

        Modifiers are deliberately not consulted. Numpad ``Enter`` arrives with
        ``KeypadModifier`` set, so a ``NoModifier`` test would silently drop half of
        spec §5's ``Enter`` row, and neither key carries a second meaning inside this
        list. ``Ctrl+Space`` / ``Ctrl+Up`` / ``Ctrl+Down`` are not this method's
        business either: those three stay window-level (they are not about rows), and
        the window consumes them before the press reaches here.
        """
        if event.key() in self.REMOVE_KEYS:
            event.accept()
            self.request_remove_selection()
            return
        if event.key() in self.PLAY_KEYS:
            event.accept()
            self.request_play_selection()
            return
        super().keyPressEvent(event)

    def request_play_selection(self) -> None:
        """Emit ``play_requested`` for the selection the way ``Enter`` means it.

        Reached from :meth:`keyPressEvent` (this widget's own ``Enter``) only -- the
        context menu emits ``play_requested`` itself, with the batch it resolved when
        it opened. It lives here rather than in the window because the selection's
        meaning is this widget's to decide (plan
        Architecture -- 选择与索引解析留在 `PlaylistView`), and routing the keyboard
        through the same signal the context menu emits gives the two entries one
        forward, one presenter handler and one empty-selection rule.

        The payload is a **one-element** list holding the smallest selected display
        index: spec §5 pins ``Enter`` on that row, the same one a double-click on the
        batch starts from. The menu's Play entry hands over the whole batch and
        ``MainPresenter._on_play_tracks`` reduces it with the same ``min`` (Task 5),
        so the two spellings of the payload cannot start two different songs.

        An empty selection emits nothing -- spec §7 puts the "no rows, no request"
        rule here rather than in a presenter loop that would merely do nothing.
        """
        indices = self.selected_display_indices()
        if not indices:
            return
        self.play_requested.emit([min(indices)])

    def request_remove_selection(self) -> None:
        """Emit ``remove_requested`` for the whole selection, ascending.

        Reached from :meth:`keyPressEvent` (this widget's own ``Delete``). Same
        no-empty rule as
        :meth:`request_play_selection`, and the batch -- not one row -- is the point:
        the removal is multi-row by design, and the presenter sorts it into
        descending order itself (spec §4.2), so this layer must not re-order anything
        either (the ``remove_requested`` contract from Task 1).
        """
        indices = self.selected_display_indices()
        if not indices:
            return
        self.remove_requested.emit(indices)

    def clear(self) -> None:
        """Clear the visible list. No production caller -- and it still stays.

        Kept on evidence rather than habit: the only route in the repo that reaches
        this line is :meth:`MainWindow.clear_playlist`, whose only caller is
        ``tests/tools/render_matrix.py`` -- an automated path this batch ships, so
        deleting the pair here would break a file this wave does not own. The
        presenter never uses it: clearing goes through ``QueueService.clear`` and
        comes back down as ``display_changed([])``, which is why the context menu's
        clear entry needs no view-side call. Retire this pair together with the
        matrix's call, not before.
        """
        self._model.clear()

    def get_entry_at(self, row: int) -> Optional[object]:
        """Get entry at the given row."""
        return self._model.get_entry(row)
