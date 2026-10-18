#!/usr/bin/env python3
"""
PyPlayer Library Sidebar

The floating media-library panel of batch 2 (spec §3.2, §6, §11): the rail's
library button opens it, and it answers exactly two questions -- *which* library
and *add one*. Refresh, refresh-all, appearance and about stay on the icon rail,
so the same action never exists in two places.

Why a panel and not a column: audit item B3 was the old chip row overflowing its
row as libraries accumulated (``LibrarySelector`` laid buttons out in a
``QHBoxLayout`` and pushed them left with an ``addStretch``). The panel owns a
vertical list inside a ``QScrollArea``, so thirty libraries cost a scrollbar and
nothing else -- and it floats over the playlist instead of taking width from it,
which is what let batch 2 give the list the full window.

Three constraints shape the code below:

* **It is a child widget, not a window.** ``show_panel`` positions it inside the
  parent's content area (``raise_()`` + ``setGeometry``) rather than opening a
  top-level popup, for the same reason the toast does: a child cannot land on
  the wrong monitor, cannot be reordered below the window on macOS, and does not
  have to be re-positioned when the window moves. The cost is that clicks
  outside it are not delivered to it, so dismissal needs an event filter -- see
  :meth:`LibrarySidebar.eventFilter`.
* **Rows carry a name and nothing else.** A per-library track count is not
  available: ``library_manager.scan_directory()`` returns paths and never reads
  metadata (batch 1 ruling, restated in the plan), so the only honest number this
  batch could show is a fabricated ``0``. Batch 4's column work is what brings
  counts here.
* **No stylesheet of its own.** Fills, borders, the current-row marker and the
  empty state are ``#librarySidebar`` / ``#sidebarTitle`` / ``#libraryRow`` /
  ``#sidebarEmpty`` in ``core/theme_qss.py``; the only pixels this widget draws
  itself are the ``folder`` and ``add`` glyphs, which QSS cannot recolour, so
  :meth:`recolor` re-rasterises them. ``add`` is the file Task 3 authored for
  this footer; ``folder`` is already the rail's library toggle and 打开文件夹
  glyph, and a row *is* a folder, so the third use of it names the same object.
"""

from typing import Any, List, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core import i18n
from core.theme import (
    RAIL_WIDTH,
    ROW_HEIGHT,
    SIDEBAR_WIDTH,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
)
from view.icons import icon

#: Glyph size inside a :data:`core.theme.ROW_HEIGHT` row. Same token arithmetic
#: as the rail (``TRANSPORT_SIZE // 2`` there): the ink is half the control.
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

    ``path`` is ``None`` for the footer's add entry: the footer is a row in every
    respect (same glyph slot, same hover, same height) except that it selects no
    library, and giving it its own objectName would mean a fifth styled name the
    brief does not list. Tests and :class:`LibrarySidebar` tell the two apart with
    the ``library_path`` dynamic property, the same key ``LibrarySelector`` used.
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
        """The library this row selects, or ``None`` for the add entry."""
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
    """Floating panel that picks and adds media libraries.

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
        add_library_requested(str): The footer entry was used and a folder was
            chosen. The path is emitted, not a ``LibraryConfig`` -- the presenter
            owns configuration.
    """

    library_selected = pyqtSignal(str)
    add_library_requested = pyqtSignal(str)

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

        self._add_row = LibraryRow(i18n.get('sidebar.add'), None, self)
        self._add_row.clicked.connect(lambda checked=False: self._on_add_clicked())
        layout.addWidget(self._add_row)

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
        self._is_open = False
        self._remove_outside_filter()
        self.hide()

    def toggle(self) -> None:
        """Open when closed, close when open. Two calls are therefore a no-op."""
        if self.is_panel_open():
            self.hide_panel()
        else:
            self.show_panel()

    def _place_panel(self) -> None:
        """Spec §6 geometry: right of the rail, clamped by the parent.

        ``min(SIDEBAR_WIDTH, parent - RAIL_WIDTH)`` is the whole contract. The
        ``max(0, ...)`` floor keeps a pathological parent from producing a
        negative width (Qt would take that as "use the size hint", i.e. a panel
        wider than the window -- the exact overflow this task removes), and the
        height is capped by the parent so the list always scrolls internally
        instead of running past the window.
        """
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(SIDEBAR_WIDTH, max(0, parent.width() - RAIL_WIDTH))
        available = max(_MIN_PANEL_HEIGHT, parent.height() - 2 * SPACE_2)
        height = min(self._preferred_height(), available, parent.height())
        # ``x`` never pushes the panel past the right edge: with the clamp above
        # it cannot, but the parent may be narrower than the rail itself.
        x = max(0, min(RAIL_WIDTH, parent.width() - width))
        self.setGeometry(x, SPACE_2, width, height)

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
        :meth:`eventFilter` still restricts itself to the parent's own subtree,
        so a modal dialog opened over the panel is untouched.
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Dismiss the panel on a mouse press inside its own window, outside itself."""
        if (self._is_open
                and event.type() == QEvent.Type.MouseButtonPress
                and isinstance(watched, QWidget)):
            # *Position*, not the receiver, decides "inside the panel". A press on a
            # part of the panel that handles nothing -- its padding, the title
            # label -- is ignored by that widget and Qt then re-delivers it to the
            # parent, so a receiver-based test would dismiss the panel when the
            # user clicks its own frame (measured while writing this: the filter
            # saw the row widget, then the parent, for one press).
            point = _global_press_point(event)
            if point is not None and self.rect().contains(self.mapFromGlobal(point)):
                return False
            parent = self.parentWidget()
            if parent is not None and (watched is parent or parent.isAncestorOf(watched)):
                self.hide_panel()
                # Consume the press. A real popup does this, and here it is the
                # only way the rail's own library button can close the panel:
                # left to propagate, the press would become a click on the button
                # and ``toggle()`` would immediately re-open the panel the user
                # just closed.
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        """Escape closes. Any other key falls through to the base widget."""
        if self._is_open and event.key() == Qt.Key.Key_Escape:
            self.hide_panel()
            event.accept()
            return
        super().keyPressEvent(event)

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
        """Ask for a folder and emit it. A cancelled chooser emits nothing."""
        folder = QFileDialog.getExistingDirectory(
            self, i18n.get('dialog.add_library'))
        if folder:
            self.add_library_requested.emit(folder)


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
