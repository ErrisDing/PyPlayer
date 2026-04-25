#!/usr/bin/env python3
"""
Playlist View - List view for playlist with custom rendering
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QAbstractItemView, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex
from PyQt6.QtGui import QStandardItemModel, QStandardItem

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from view.models.playlist_model import PlaylistModel
from view.delegates.playlist_delegate import PlaylistItemDelegate


class PlaylistView(QWidget):
    """
    Playlist display widget using QListView with custom model.

    Features:
    - Double-click to play
    - Current track highlighting
    - Context menu for actions
    """

    # Signals
    track_double_clicked = pyqtSignal(int)       # display index
    track_selected = pyqtSignal(int)             # display index
    context_menu_requested = pyqtSignal(int, object)  # index, event

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QLabel("Playlist")
        header.setStyleSheet("""
            QLabel {
                background-color: rgba(58, 58, 58, 0.85);
                color: white;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(header)

        # List view with custom model
        self._list_view = QListView()
        self._model = PlaylistModel(self)
        self._list_view.setModel(self._model)

        # Set custom delegate for rendering relative position
        self._list_view.setItemDelegate(PlaylistItemDelegate(self._list_view))

        # Configure list view
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list_view.setAlternatingRowColors(True)

        # Enable smooth scrolling
        self._list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)

        # Styling with transparency
        self._list_view.setStyleSheet("""
            QListView {
                background-color: rgba(250, 250, 250, 0.75);
                border: 1px solid rgba(200, 200, 200, 0.5);
                outline: none;
            }
            QListView::item {
                padding: 5px;
                border-bottom: 1px solid rgba(230, 230, 230, 0.5);
            }
            QListView::item:selected {
                background-color: rgba(227, 242, 253, 0.85);
                color: #333;
            }
            QListView::item:hover {
                background-color: rgba(245, 245, 245, 0.85);
            }
        """)

        # Connect signals
        self._list_view.doubleClicked.connect(self._on_double_click)
        self._list_view.clicked.connect(self._on_click)

        layout.addWidget(self._list_view)

    def _on_double_click(self, index: QModelIndex) -> None:
        """Handle double-click on item."""
        self.track_double_clicked.emit(index.row())

    def _on_click(self, index: QModelIndex) -> None:
        """Handle click on item."""
        self.track_selected.emit(index.row())

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
