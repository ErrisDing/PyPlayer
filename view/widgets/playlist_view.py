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

    The header and the list are styled by the application sheet through
    ``#playlistHeader`` / ``#playlistView``; the row states are painted by
    :class:`PlaylistItemDelegate`, which reads the theme manager's tokens.
    """

    # Signals
    track_double_clicked = pyqtSignal(int)       # display index
    # 批次 3：右键菜单接口。Batch 1 declared this one and nothing emitted it until
    # Task 3 wired the right-click; ``tests/test_dead_code_removed.py`` pins that it
    # must survive cleanup.
    context_menu_requested = pyqtSignal(int, object)  # index, event
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

        # Hover tracking for the row delegate (batch 3, C2). ``QListView`` only
        # puts ``QStyle.State_MouseOver`` on the option of the row under the
        # cursor while this attribute is set, and it has to be the *viewport*'s
        # attribute: measured on this host (Qt 6.11.0, offscreen), setting it on
        # the ``QListView`` leaves every option at ``State_Enabled|State_Active``
        # and only the viewport one flips the bit -- so without this line
        # ``PlaylistItemDelegate``'s hover branch is dead code. It is also what
        # makes the view repaint on a hover change, which is the other half of
        # why a row stops being tinted once the cursor leaves it.
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

    def get_current_selection(self) -> int:
        """Get currently selected row index, or -1 if none."""
        indexes = self._list_view.selectedIndexes()
        if indexes:
            return indexes[0].row()
        return -1

    def set_selection(self, row: int) -> None:
        """Select the specified row."""
        if row >= 0 and row < self._model.rowCount():
            index = self._model.index(row)
            self._list_view.setCurrentIndex(index)

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
        # *request*, and its payload is ``targets[0]`` plus the live event -- both
        # are only guaranteed to still describe what the user pointed at while
        # nothing has acted on them yet. Once an action signal has run, the row can
        # be gone (Task 5's removal) and the event is what the dispatch consumed.
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

    def clear(self) -> None:
        """Clear the playlist."""
        self._model.clear()

    def get_entry_at(self, row: int) -> Optional[object]:
        """Get entry at the given row."""
        return self._model.get_entry(row)

    def scroll_to_playing(self) -> None:
        """Scroll to show the currently playing track."""
        playing_idx = self._model.get_playing_index()
        if playing_idx >= 0:
            index = self._model.index(playing_idx)
            self._list_view.scrollTo(index, QListView.ScrollHint.EnsureVisible)
