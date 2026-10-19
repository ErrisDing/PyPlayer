#!/usr/bin/env python3
"""
Playlist View - List view for playlist with custom rendering
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QAbstractItemView, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex, QPoint
from PyQt6.QtGui import QStandardItemModel, QStandardItem

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n
from view.models.playlist_model import PlaylistModel
from view.delegates.playlist_delegate import PlaylistItemDelegate


class PlaylistView(QWidget):
    """
    Playlist display widget using QListView with custom model.

    Features:
    - Double-click to play
    - Current track highlighting
    - Windows-Explorer multi-selection (Ctrl/Shift+click), readable through
      :meth:`selected_display_indices` and :meth:`display_index_at`
    - Context menu for actions

    The header and the list are styled by the application sheet through
    ``#playlistHeader`` / ``#playlistView``; the row states are painted by
    :class:`PlaylistItemDelegate`, which reads the theme manager's tokens.
    """

    # Signals
    track_double_clicked = pyqtSignal(int)       # display index
    # 批次 3：右键菜单接口，尚未 emit
    context_menu_requested = pyqtSignal(int, object)  # index, event
    # ``play_requested`` / ``remove_requested`` / ``clear_playlist_requested``
    # are declared in Task 3, where they first get an emitter -- a signal that
    # nobody emits is dead code and ``tests/test_dead_code_removed.py`` is the
    # standing guard for that (batch 1 Task 2). Task 1 ships the selection mode
    # and the two display-index helpers only.

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
