#!/usr/bin/env python3
"""
PyPlayer Library Sidebar

The floating media-library panel of batch 2 (spec §3.2, §6, §11): the rail's
library button opens it, and it answers the three *library* questions -- *which*
library, *add one*, and *manage the set*. Refresh and refresh-all stay on the icon
rail, so the same action never exists in two places.

Why the footer carries both administration entries (spec §3.2's Task 8
correction): §3.2 originally sent 管理媒体库 to the rail while §6 froze the rail at
exactly seven actions and management was not one of them, so after the menu bar
went away the management dialog -- and with it library *removal* -- had no route
from the shipped UI at all. Two library-administration verbs belong on the panel
that a user opens when thinking about libraries; the column stays at seven.

Why a panel and not a column: audit item B3 was the old chip row overflowing its
row as libraries accumulated -- a horizontal button row with an ``addStretch``
pushing it left. The panel owns a
vertical list inside a ``QScrollArea``, so thirty libraries cost a scrollbar and
nothing else -- and it floats over the playlist instead of taking width from it,
which is what let batch 2 give the list the full window.

Three constraints shape the code below:

* **It is a child widget, not a window.** ``show_panel`` positions it inside the
  parent's content area (``raise_()`` + ``setGeometry``) rather than opening a
  top-level popup, for the same reason the toast does: a child cannot land on
  the wrong monitor, cannot be reordered below the window on macOS, and does not
  have to be re-positioned when the window moves. The cost is that neither of the
  panel's two dismissal routes can come from itself: a click outside it is not
  delivered to it, and a key press is delivered to ``focusWidget()`` and only
  walks *up* the parent chain from there -- the panel is a sibling of the
  playlist, never its ancestor, and holds no focus of its own. Both routes
  therefore run through the application-level filter, see
  :meth:`LibrarySidebar.eventFilter`.
* **Rows carry a name and nothing else.** A per-library track count is not
  available: ``library_manager.scan_directory()`` returns paths and never reads
  metadata (batch 1 ruling, restated in the plan), so the only honest number this
  batch could show is a fabricated ``0``. Batch 4's column work is what brings
  counts here.
* **No stylesheet of its own.** Fills, borders, the current-row marker and the
  empty state are ``#librarySidebar`` / ``#sidebarTitle`` / ``#libraryRow`` /
  ``#sidebarEmpty`` in ``core/theme_qss.py``; the only pixels this widget draws
  itself are the ``folder``, ``add`` and ``settings`` glyphs, which QSS cannot
  recolour, so :meth:`recolor` re-rasterises them. ``add`` is the file Task 3
  authored for this footer and ``settings`` is the rail's 外观设置 glyph reused
  here for 管理媒体库 -- administration is what both of them mean, and the row's own
  text is what says *which* thing is being administered; ``folder`` is already the
  rail's library toggle and 打开文件夹 glyph, and a row *is* a folder, so the third
  use of it names the same object.
"""

from typing import Any, List, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core import i18n
from core.theme import (
    ROW_HEIGHT,
    SIDEBAR_WIDTH,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
)
from view.icons import icon

#: Glyph size inside a :data:`core.theme.ROW_HEIGHT` row. This is *not* the
#: rail's arithmetic (``TRANSPORT_SIZE // 2``, 20 px there): a rail button is a
#: 40 px square, a row here is a 28 px text line. The sheet gives a row
#: ``padding: SPACE_1 SPACE_3``, so its content box is
#: ``ROW_HEIGHT - 2 * SPACE_1`` = 20 px, and ``SPACE_4`` (16) is the largest
#: ``SPACE_*`` step that fits inside it while leaving the name's own line height
#: untouched. ``tests/test_library_sidebar.py`` asserts that inequality, so the
#: arithmetic in this comment is checked rather than narrated.
_ROW_ICON_SIZE = SPACE_4

#: ``#libraryRow``'s non-text width, mirrored here for the elide calculation:
#: the rule's ``padding: SPACE_1 SPACE_3`` (2 x SPACE_3 horizontally) plus its
#: 2 px current-marker border, plus the glyph and the icon-to-text gap Qt
#: reserves. Both sides read the same tokens, so a token change moves the sheet
#: and this number together; ``tests/test_library_sidebar.py`` asserts the elided
#: text still fits the control, which is the guard if they ever drift.
_ROW_TEXT_GUTTER = 2 * SPACE_3 + 2 + _ROW_ICON_SIZE + SPACE_2

#: Minimum vertical room the panel asks its parent for before it gives up. Below
#: this a row would be unreachable even by scrolling.
_MIN_PANEL_HEIGHT = 3 * ROW_HEIGHT


class LibraryRow(QPushButton):
    """One clickable library row of the floating panel.

    A ``QPushButton`` clips its text instead of eliding it, and a clipped path
    name is worse than an elided one -- ``Classic_Rock_2000`` and
    ``Classic_Rock_2023`` differ only past the clip. So the row elides against
    its own width on every resize and keeps the full name in the tooltip, which
    is the "elided, not clipped" half of spec §6.

    ``path`` is ``None`` for the two footer entries: the footer is a row in every
    respect (same glyph slot, same hover, same height) except that it selects no
    library, and giving it its own objectName would mean a fifth styled name the
    brief does not list. Tests and :class:`LibrarySidebar` tell the entries apart
    with the ``library_path`` dynamic property -- absent for both of them -- and
    their labels, since the footer carries 添加媒体库 *and* 管理媒体库 (spec §3.2's
    Task 8 correction).
    """

    def __init__(self, name: str, path: Optional[str] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._path = path

        self.setObjectName('libraryRow')
        # Strings, not bools: the QSS attribute selector is written against
        # ``current="true"``, and strings are this widget tree's declared contract
        # (same as the chips' ``selected`` and the rail's ``running``).
        self.setProperty('current', 'false')
        if path is not None:
            self.setProperty('library_path', path)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(ROW_HEIGHT)
        self.setToolTip(name)
        self._apply_elision()

    @property
    def path(self) -> Optional[str]:
        """The library this row selects, or ``None`` for a footer entry."""
        return self._path

    @property
    def full_name(self) -> str:
        """The un-elided name (the visible text is whatever fits)."""
        return self._name

    def set_current(self, is_current: bool) -> None:
        """Mark the row as the current library for ``#libraryRow[current="true"]``."""
        value = 'true' if is_current else 'false'
        if self.property('current') == value:
            return
        self.setProperty('current', value)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        """Fit ``self._name`` to the row's current width, with an ellipsis."""
        if self.width() <= 0:
            # Not laid out yet. Eliding against a zero width would replace the
            # name with a bare ellipsis for one frame and feed that back into the
            # layout's size hint, so the full name waits for the first resize.
            return
        available = self.width() - _ROW_TEXT_GUTTER
        if available <= 0:
            return
        text = self.fontMetrics().elidedText(
            self._name, Qt.TextElideMode.ElideRight, available)
        if text != self.text():
            # Guard, not tidiness: setText invalidates the layout, which can
            # resize this button, which lands back here.
            self.setText(text)


class LibrarySidebar(QFrame):
    """Floating panel that picks, adds and manages media libraries.

    Args:
        manager: The running :class:`view.theme_manager.ThemeManager`; only
            ``tokens`` is read, for the row glyphs. ``MainWindow.recolor``
            forwards every ``theme_changed`` into :meth:`recolor`.
        parent: The widget whose content area the panel floats in. Required for
            :meth:`show_panel` -- without one the panel would have to become a
            top-level window, which is the failure mode this widget exists to
            avoid.

    Signals:
        library_selected(str): A *different* library's row was clicked, with its
            path. Re-clicking the current library emits nothing: the presenter
            would re-scan a library that is already loaded.
        add_library_requested(str): The footer's add entry was used and a folder
            was chosen. The path is emitted, not a ``LibraryConfig`` -- the
            presenter owns configuration.
        manage_requested(): The footer's 管理媒体库 entry was used. No argument:
            the management dialog reads the configured libraries itself, and
            adding, renaming-free removing and reordering all live in it. Task 8
            added this signal to give ``MainWindow.manage_libraries_requested``
            the emitter the deleted menu bar took away, which is also the only
            route left to library *removal* (spec §3.2 correction).
    """

    library_selected = pyqtSignal(str)
    add_library_requested = pyqtSignal(str)
    manage_requested = pyqtSignal()

    def __init__(self, manager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = manager
        self._tokens = manager.tokens
        self._libraries: List[Any] = []
        self._current_path: str = ''
        self._rows: List[LibraryRow] = []
        self._is_open = False
        self._filter_host: Optional[QObject] = None

        self.setObjectName('librarySidebar')
        # The sheet draws the frame; a QFrame of our own would paint a second one.
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # A panel the user opens and dismisses: it must not take focus away from
        # the playlist just to be readable.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_1)

        self._title = QLabel(i18n.get('sidebar.title'), self)
        self._title.setObjectName('sidebarTitle')
        layout.addWidget(self._title)

        self._scroll = QScrollArea(self)
        # No frame and no horizontal bar: the panel is width-clamped by the
        # window (spec §6), so horizontal scrolling is a defect, not a fallback.
        # The viewport needs no rule of its own -- the palette's ``Base`` is the
        # same ``surface`` token ``#librarySidebar`` fills with, in both themes,
        # so the list background and the panel background are one colour by
        # construction.
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list = QWidget(self._scroll)
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(SPACE_1)
        self._empty = QLabel(i18n.get('sidebar.empty'), self._list)
        self._empty.setObjectName('sidebarEmpty')
        self._empty.setWordWrap(True)
        self._list_layout.addWidget(self._empty)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)
        layout.addWidget(self._scroll, 1)

        # The footer: both library-administration entries, one row each. They
        # share everything with a library row -- name, glyph slot, height, hover --
        # and carry no ``library_path``, because neither one selects a library.
        self._add_row = LibraryRow(i18n.get('sidebar.add'), None, self)
        self._add_row.clicked.connect(lambda checked=False: self._on_add_clicked())
        layout.addWidget(self._add_row)

        self._manage_row = LibraryRow(i18n.get('sidebar.manage'), None, self)
        self._manage_row.clicked.connect(
            lambda checked=False: self._on_manage_clicked())
        layout.addWidget(self._manage_row)

        self._generate_icons()
        self.hide()

    # === Content ===

    def set_libraries(self, libraries: List[Any]) -> None:
        """Rebuild the rows from ``LibraryConfig``-shaped objects (``.name``, ``.path``).

        Tolerated while the panel is open -- the presenter refreshes the list
        right after adding a library, and the new row has to be visible in the
        panel the user is already looking at.
        """
        self._libraries = list(libraries or [])
        self._rebuild_rows()

    def set_current(self, path: str) -> None:
        """Mark the row for ``path`` current. An unknown path marks nothing."""
        self._current_path = path or ''
        for row in self._rows:
            row.set_current(row.path == self._current_path and self._current_path != '')

    def _rebuild_rows(self) -> None:
        """Drop every library row and re-make them from :attr:`_libraries`."""
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []

        for index, library in enumerate(self._libraries):
            path = getattr(library, 'path', '')
            name = getattr(library, 'name', None) or _basename(path)
            row = LibraryRow(name, path, self._list)
            row.setToolTip(name)
            row.clicked.connect(
                lambda checked=False, p=path: self._on_row_clicked(p))
            # Rows go above the stretch, in list order; the empty label sits at
            # the end so it never pushes the first row down.
            self._list_layout.insertWidget(index, row)
            self._rows.append(row)

        self._empty.setVisible(not self._rows)
        self.set_current(self._current_path)
        self._generate_icons()
        if self._is_open:
            # The panel's height follows the row count, so a library added while
            # it floats has to be re-measured rather than clipped.
            self._place_panel()

    def _generate_icons(self) -> None:
        """Rasterise the row and footer glyphs for the current tokens."""
        for row in self._rows:
            row.setIcon(icon('folder', self._tokens.icon, _ROW_ICON_SIZE,
                             self.devicePixelRatioF()))
        self._add_row.setIcon(icon('add', self._tokens.icon, _ROW_ICON_SIZE,
                                   self.devicePixelRatioF()))
        # ``settings`` is the rail's 外观设置 glyph, used here for 管理媒体库: the
        # two entries are both administration, and the text says which kind. The
        # alternative was a fourth glyph for one more footer row, which is how the
        # icon set grows past what any test can still name.
        self._manage_row.setIcon(icon('settings', self._tokens.icon, _ROW_ICON_SIZE,
                                      self.devicePixelRatioF()))

    def recolor(self, tokens) -> None:
        """Regenerate every glyph for a new theme (``MainWindow.recolor``)."""
        self._tokens = tokens
        self._generate_icons()

    # === Panel state ===

    def is_panel_open(self) -> bool:
        """Whether the panel is showing, in the panel's own terms.

        A flag rather than ``isVisible()``: a child of a hidden window is
        ``isVisible() == False`` even when it was told to show, so the visibility
        call cannot answer "did the user open this" and ``toggle()`` would drift
        out of step with the rail button.

        The flag is only an honest answer while it tracks real visibility, and Qt
        can move visibility without asking this class in *both* directions --
        hiding a top-level fires ``QEvent.Hide`` on the visible children, but
        re-showing it silently restores them (``QWidgetPrivate::showChildren``
        replays the child visibilities that were on screen at hide time, and a
        ``QEvent.Show`` is not a ``show_panel()`` call). The two hooks below make
        the divergence impossible rather than merely unlikely:

        * :meth:`hideEvent` -- any route out, including a bypass ``hide()``,
          writes ``False``;
        * :meth:`showEvent` -- any show that did not follow ``show_panel()``
          (``_is_open`` still ``False``) is refused by re-hiding immediately.

        Together: while the window is on screen, ``is_panel_open()`` is true
        exactly when the panel paints, and the only state where the flag leads
        the pixels is the intended one -- ``show_panel()`` against a hidden
        window records the intent, and the pending ``show`` delivers it when the
        window returns.
        """
        return self._is_open

    def show_panel(self) -> None:
        """Position the panel over the parent's content area and show it."""
        if self.parentWidget() is None:
            print('Warning: LibrarySidebar.show_panel called without a parent; '
                  'the panel is not shown (it floats inside a window on purpose)')
            return
        self._is_open = True
        self._place_panel()
        self._install_outside_filter()
        self.raise_()
        self.show()

    def hide_panel(self) -> None:
        """Hide the panel and stop watching for outside clicks. Idempotent."""
        self._remove_outside_filter()
        self._is_open = False
        self.hide()

    def hideEvent(self, event) -> None:
        """Drop the application-level filter whenever the panel stops being visible.

        ``hide_panel()`` is not the only route out: a parent-window teardown, an
        explicit ``sidebar.hide()``/``setVisible(False)`` or a hide-through of the
        presenter all fire ``QEvent.Hide`` directly. Without this hook those paths
        leave the filter installed while ``_is_open`` still reads ``True``, so
        :meth:`eventFilter` continues to see -- and consume -- mouse presses in
        the parent subtree even though the panel is invisible. That makes the
        rail toggle look dead: the first press is swallowed, the second reopens
        because the flag says it was never open, and every click in the window
        between them is silently eaten.

        Both calls are idempotent, and :meth:`hide_panel` has already cleared them
        by the time Qt reaches here for the normal route, so this hook only ever
        repairs a bypass.
        """
        super().hideEvent(event)
        self._remove_outside_filter()
        self._is_open = False

    def showEvent(self, event) -> None:
        """Refuse any show that did not come from :meth:`show_panel`.

        The mirror half of the :meth:`is_panel_open` invariant, and the fix for
        the one divergence ``hideEvent`` alone could not close: when a top-level
        is hidden, Qt fires ``QEvent.Hide`` on the children that were on screen
        (clearing ``_is_open`` here), but when it is shown again Qt *restores*
        those children's visibility without any caller asking -- ``show_panel()``
        is not in the loop, so the flag says closed and the widget paints. The
        render matrix met this as a closed frame wearing a blank 240 px stripe
        of panel over the playlist, and the harness only stayed honest by closing
        through ``hide_panel()`` on every frame (see ``apply_state``).

        The guard is ``hide()``, not ``hide_panel()``: an explicit hide is what
        clears the attribute ``showChildren`` replays, so the refusal also stops
        the *next* restore from bringing the panel back. ``hide_panel()`` would
        do the same calls but reads as if a dismissal happened, and none did.
        Calling ``hide()`` from inside ``showEvent`` is Qt's own documented
        pattern for refusing a show; the resulting ``QEvent.Hide`` re-enters
        :meth:`hideEvent`, which is idempotent by contract.
        """
        super().showEvent(event)
        if not self._is_open:
            self.hide()

    def toggle(self) -> None:
        """Open when closed, close when open. Two calls are therefore a no-op."""
        if self.is_panel_open():
            self.hide_panel()
        else:
            self.show_panel()

    def _place_panel(self) -> None:
        """Spec §6 geometry: flush with the parent, clamped by the parent.

        The arithmetic is **parent-relative and names no rail**. Batch 2 reparented
        the panel to ``MainWindow``'s ``content_stack``, the container the shell
        lays out *right of* the ``RAIL_WIDTH`` column, so the parent's own origin is
        already the rail's right edge. Reading the rail again here paid for it twice
        -- 56 px of playlist left showing between rail and panel, and a clamp 56 px
        narrower than the parent -- which is the defect this method's geometry used
        to enshrine. The contract is therefore:

        * ``x = 0``, width ``min(SIDEBAR_WIDTH, parent.width())``;
        * the ``max(0, ...)`` floor is **carried over from batch 2 and is now dead
          arithmetic**: it was load-bearing only while the term read
          ``parent.width() - RAIL_WIDTH``, and ``QWidget.width()`` is never negative
          on its own. It stays because the plan mandates preserving it, not because
          anything can reach it; delete it together with this bullet if the clamp is
          ever rewritten.
        * ``y`` and the height keep the batch-2 arithmetic. Neither ever involved
          the rail: the height is capped by the parent so the list always scrolls
          internally instead of running past the window.

        Both coordinate spaces are pinned separately in
        ``tests/test_library_sidebar.py`` (``x == 0`` in the parent's space, and
        ``mapTo(window, QPoint(0, 0)).x() == RAIL_WIDTH`` in the window's), because
        either one alone is also satisfied by an offset that merely moved.
        """
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(SIDEBAR_WIDTH, max(0, parent.width()))
        available = max(_MIN_PANEL_HEIGHT, parent.height() - 2 * SPACE_2)
        height = min(self._preferred_height(), available, parent.height())
        # The parent's origin, not an inset from it: insetting would re-add the very
        # offset this method exists to remove. The clamp above keeps the right edge
        # inside the parent; below ``RAIL_WIDTH`` of parent width the panel simply
        # goes full-bleed, which batch 2 did not do (it collapsed to width 0 at
        # x == parent width) -- a difference no shipped window can reach, since the
        # window's own 800px minimum keeps this parent above 744.
        self.setGeometry(0, SPACE_2, width, height)

    def _preferred_height(self) -> int:
        """Title + rows + footer + chrome, without asking the scroll area."""
        return (self.layout().sizeHint().height()
                - self._scroll.sizeHint().height()
                + self._list.sizeHint().height())

    # === Dismissal ===

    def _install_outside_filter(self) -> None:
        """Watch the application while the panel floats.

        Installed on the ``QApplication``, not on the parent widget, because a
        press on the playlist view is delivered to the view: a parent-level
        filter only sees events the parent itself receives, so clicks on any
        widget that accepts its own press would leave the panel floating forever.
        The same install is what puts the keyboard and the parent's resize inside
        reach -- every event the window receives passes :meth:`eventFilter` first,
        whatever widget holds focus and whether the window holds any at all.
        The price is that the filter now sees events belonging to *every*
        top-level in the application, which is why the gate is window identity
        rather than the parent's subtree: see :meth:`_shares_window`.
        """
        if self._filter_host is not None:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._filter_host = app

    def _remove_outside_filter(self) -> None:
        if self._filter_host is None:
            return
        self._filter_host.removeEventFilter(self)
        self._filter_host = None

    def _shares_window(self, watched: QWidget) -> bool:
        """Whether ``watched`` lives in the top-level window the panel floats in.

        The gate is the window, not the parent's subtree, for two reasons:

        * a widget in another top-level -- a modal directory chooser, a menu, a
          tooltip -- must never disturb the panel and must never have its own
          mouse press eaten by it; and
        * a subtree test would be wrong in the other direction as soon as Task 7
          parents the panel to the content area: the rail, the strip and the toast
          are then *siblings* of that area, still inside ``MainWindow``, and a
          press on any of them has to dismiss the panel.

        ``isAncestorOf`` is not a substitute for the second point, and measured on
        Qt 6.11 it is not even a substitute for the first: it stops at window
        boundaries, so it already reports ``False`` for a dialog parented to the
        panel. Window identity is the question the filter actually needs.
        """
        parent = self.parentWidget()
        return parent is not None and watched.window() is parent.window()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Dismiss the panel on an outside press or an Escape; re-place it when
        the parent resizes.

        ``isVisible()`` is in the gate next to ``_is_open`` on purpose: the flag
        answers "did the user open this" (see :meth:`is_panel_open`) and can only
        be trusted while the panel really is on screen. A hide that bypassed
        :meth:`hide_panel` clears both from :meth:`hideEvent`; the gate means that
        even a route this class has not thought of cannot leave an invisible panel
        swallowing presses.
        """
        if not (self._is_open and self.isVisible() and isinstance(watched, QWidget)):
            return super().eventFilter(watched, event)
        etype = event.type()
        if etype == QEvent.Type.KeyPress:
            # Escape belongs to the filter, not to ``keyPressEvent``. Qt delivers
            # a key press to ``focusWidget()`` and only walks *up* the parent
            # chain when it is not accepted; this panel is ``NoFocus`` and is a
            # sibling of the playlist rather than its ancestor, so with the
            # keyboard where the user actually put it -- the list, right after
            # opening from the rail -- a press injected into the panel's own
            # handler could never be reached. Measured: the filter sees the key
            # both at the focus widget and at the top-level, so the route also
            # works when nothing has focus.
            if event.key() == Qt.Key.Key_Escape and self._shares_window(watched):
                self.hide_panel()
                event.accept()
                return True
        elif etype == QEvent.Type.MouseButtonPress:
            # *Position*, not the receiver, decides "inside the panel". A press on a
            # part of the panel that handles nothing -- its padding, the title
            # label -- is ignored by that widget and Qt then re-delivers it to the
            # parent, so a receiver-based test would dismiss the panel when the
            # user clicks its own frame (measured while writing this: the filter
            # saw the row widget, then the parent, for one press).
            point = _global_press_point(event)
            if point is not None and self.rect().contains(self.mapFromGlobal(point)):
                return False
            if self._shares_window(watched):
                self.hide_panel()
                # Consume the press. A real popup does this, and here it is the
                # only way the rail's own library button can close the panel:
                # left to propagate, the press would become a click on the button
                # and ``toggle()`` would immediately re-open the panel the user
                # just closed.
                return True
        elif etype == QEvent.Type.Resize and watched is self.parentWidget():
            # The width clamp in ``_place_panel`` is a function of the parent, so
            # placing once at show time is not a contract, it is a snapshot: shrink
            # the window under ``SIDEBAR_WIDTH + RAIL_WIDTH`` while the panel
            # floats and the snapshot overhangs the edge -- the exact overflow
            # audit item B3 exists to remove. ``_rebuild_rows`` re-places for the
            # row count; this re-places for the window.
            self._place_panel()
        return super().eventFilter(watched, event)

    # === Slots ===

    def _on_row_clicked(self, path: str) -> None:
        if not path or path == self._current_path:
            # The already-current library is a no-op, not a re-scan, and the
            # panel stays open so the user can pick a different row.
            return
        self.set_current(path)
        self.library_selected.emit(path)
        # spec §11: choosing, clicking outside and Escape are the three ways the
        # panel goes away; a selection is the one that has to reveal the list.
        self.hide_panel()

    def _on_add_clicked(self) -> None:
        """Ask for a folder and emit it. A cancelled chooser emits nothing.

        Parented to ``self`` on purpose -- the chooser belongs to the panel that
        opened it -- which is why :meth:`_shares_window` gates on window identity
        and not on the parent's subtree: a non-native ``QFileDialog`` keeps this
        widget in ``parentWidget()`` while being its own top-level, and a press
        inside it must neither collapse the panel nor be eaten by the filter.
        """
        folder = QFileDialog.getExistingDirectory(
            self, i18n.get('dialog.add_library'))
        if folder:
            self.add_library_requested.emit(folder)

    def _on_manage_clicked(self) -> None:
        """Close the panel, then ask the presenter for the management dialog.

        The order is the point: :meth:`MainWindow.manage_libraries_requested`'s
        handler runs ``dialog.exec()``, i.e. a modal loop, and the presenter's
        signal slot is *synchronous* -- emitting first would park this floating
        panel behind a modal dialog and only then take it away. It is also why the
        app-level filter goes first: while the panel is open it consumes presses
        inside the window, and a filter that outlives the panel by one dialog is
        the leak :meth:`hideEvent` exists to close.

        Unlike :meth:`_on_add_clicked` this emits unconditionally: a directory
        chooser can be cancelled and mean nothing happened, a dialog the user
        opened and closed always means they may have changed the set.
        """
        self.hide_panel()
        self.manage_requested.emit()


def _global_press_point(event):
    """The global position of a mouse press, on every PyQt6 this repo allows.

    ``QMouseEvent.globalPosition()`` is Qt 6.6+; ``requirements.txt`` floors the
    dependency at ``PyQt6>=6.5.0``, where only the deprecated ``globalPos()``
    exists, so the newer accessor is probed rather than assumed -- the same class
    of version trap Task 3's review recorded for ``QAction.ActionEvent``.
    """
    getter = getattr(event, 'globalPosition', None)
    if callable(getter):
        return getter().toPoint()
    return event.globalPos()


def _basename(path: str) -> str:
    """Last component of a library path, for a config whose name is empty."""
    from pathlib import PurePosixPath, PureWindowsPath

    if not path:
        return ''
    pure = PureWindowsPath(path) if '\\' in path or ':' in path[:3] else PurePosixPath(path)
    return pure.name or str(pure)
