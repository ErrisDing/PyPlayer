#!/usr/bin/env python3
"""
Playlist Model - QAbstractListModel for playlist display
Solves rendering issues with incremental updates and proper highlighting
"""

from typing import List, Optional, Any
from dataclasses import dataclass
from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QVariant, pyqtSignal
)
from PyQt6.QtGui import QColor, QFont

# Import DisplayEntry from queue_service for type hinting
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from service.queue_service import DisplayEntry as QueueDisplayEntry


@dataclass
class DisplayEntry:
    """Entry for display in playlist model."""
    display_text: str
    node_idx: int
    is_folder: bool
    path: str
    sub_index: int = -1
    full_path: str = ""
    is_playing: bool = False


class PlaylistModel(QAbstractListModel):
    """
    Qt model for playlist display.

    Features:
    - Incremental updates (no flicker)
    - Playing track highlighting
    - Custom display text with indentation
    """

    # Custom roles
    IsPlayingRole = Qt.ItemDataRole.UserRole + 1
    IsFolderRole = Qt.ItemDataRole.UserRole + 2
    NodeIndexRole = Qt.ItemDataRole.UserRole + 3
    SubIndexRole = Qt.ItemDataRole.UserRole + 4
    FullPathRole = Qt.ItemDataRole.UserRole + 5

    # Colors
    PLAYING_BG_COLOR = QColor(200, 230, 255)  # Light blue for playing track
    FOLDER_COLOR = QColor(60, 60, 60)         # Darker for folder text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[DisplayEntry] = []
        self._current_playing_idx: int = -1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return number of entries."""
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return data for the given role."""
        if not index.isValid():
            return QVariant()

        row = index.row()
        if not (0 <= row < len(self._entries)):
            return QVariant()

        entry = self._entries[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return entry.display_text

        elif role == Qt.ItemDataRole.BackgroundRole:
            if entry.is_playing:
                return self.PLAYING_BG_COLOR
            return QVariant()

        elif role == Qt.ItemDataRole.ForegroundRole:
            if entry.is_folder:
                return self.FOLDER_COLOR
            return QVariant()

        elif role == Qt.ItemDataRole.FontRole:
            if entry.is_folder:
                font = QFont()
                font.setBold(True)
                return font
            return QVariant()

        elif role == self.IsPlayingRole:
            return entry.is_playing

        elif role == self.IsFolderRole:
            return entry.is_folder

        elif role == self.NodeIndexRole:
            return entry.node_idx

        elif role == self.SubIndexRole:
            return entry.sub_index

        elif role == self.FullPathRole:
            return entry.full_path

        return QVariant()

    def set_entries(self, entries: List[DisplayEntry]) -> None:
        """
        Set all entries. Uses beginResetModel/endResetModel for full update.

        For partial updates, use update_entry or insert_entries.
        """
        self.beginResetModel()
        self._entries = list(entries)
        self._current_playing_idx = -1
        self.endResetModel()

    def update_entries(self, entries: List[DisplayEntry]) -> None:
        """
        Update entries with minimal model changes.
        Compares with current entries and only updates changed rows.
        """
        old_count = len(self._entries)
        new_count = len(entries)

        if old_count == 0 or new_count == 0 or abs(old_count - new_count) > 10:
            # Large change or empty - use reset
            self.set_entries(entries)
            return

        # Find the playing index in new entries
        new_playing_idx = -1
        for i, entry in enumerate(entries):
            if entry.is_playing:
                new_playing_idx = i
                break

        # Check if only playing highlight changed
        if (old_count == new_count and
            self._current_playing_idx != new_playing_idx and
            self._only_playing_changed(entries)):

            # Only update the two rows that changed
            old_playing = self._current_playing_idx
            self._entries = list(entries)
            self._current_playing_idx = new_playing_idx

            if old_playing >= 0 and old_playing < new_count:
                self.dataChanged.emit(
                    self.index(old_playing),
                    self.index(old_playing),
                    [Qt.ItemDataRole.BackgroundRole, self.IsPlayingRole]
                )

            if new_playing_idx >= 0 and new_playing_idx != old_playing:
                self.dataChanged.emit(
                    self.index(new_playing_idx),
                    self.index(new_playing_idx),
                    [Qt.ItemDataRole.BackgroundRole, self.IsPlayingRole]
                )
            return

        # Check for incremental changes
        if old_count == new_count:
            # Same size - check if content changed
            changed_indices = []
            for i, (old, new) in enumerate(zip(self._entries, entries)):
                if (old.display_text != new.display_text or
                    old.is_playing != new.is_playing):
                    changed_indices.append(i)

            if len(changed_indices) < old_count // 2:
                # Less than half changed - update individually
                self._entries = list(entries)
                self._current_playing_idx = new_playing_idx

                for idx in changed_indices:
                    self.dataChanged.emit(
                        self.index(idx),
                        self.index(idx)
                    )
                return

        # Fallback to full reset
        self.set_entries(entries)

    def _only_playing_changed(self, new_entries: List[DisplayEntry]) -> bool:
        """Check if only the is_playing flag changed."""
        if len(self._entries) != len(new_entries):
            return False

        for old, new in zip(self._entries, new_entries):
            if old.node_idx != new.node_idx:
                return False
            if old.sub_index != new.sub_index:
                return False
            if old.display_text != new.display_text:
                return False
            if old.is_folder != new.is_folder:
                return False

        return True

    def set_current_playing(self, display_idx: int) -> None:
        """
        Set the currently playing entry by display index.
        Only updates the affected rows for minimal redraw.
        """
        old_idx = self._current_playing_idx

        if old_idx == display_idx:
            return  # No change

        # Update internal state
        self._current_playing_idx = display_idx

        # Update the entries
        if old_idx >= 0 and old_idx < len(self._entries):
            self._entries[old_idx].is_playing = False
            self.dataChanged.emit(
                self.index(old_idx),
                self.index(old_idx),
                [Qt.ItemDataRole.BackgroundRole, self.IsPlayingRole]
            )

        if display_idx >= 0 and display_idx < len(self._entries):
            self._entries[display_idx].is_playing = True
            self.dataChanged.emit(
                self.index(display_idx),
                self.index(display_idx),
                [Qt.ItemDataRole.BackgroundRole, self.IsPlayingRole]
            )

    def get_entry(self, row: int) -> Optional[DisplayEntry]:
        """Get entry at row."""
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def get_playing_index(self) -> int:
        """Get the index of the currently playing entry."""
        return self._current_playing_idx

    def clear(self) -> None:
        """Clear all entries."""
        self.beginResetModel()
        self._entries.clear()
        self._current_playing_idx = -1
        self.endResetModel()

    def insert_entries(self, row: int, entries: List[DisplayEntry]) -> None:
        """Insert entries at the given row."""
        if row < 0:
            row = 0
        elif row > len(self._entries):
            row = len(self._entries)

        self.beginInsertRows(QModelIndex(), row, row + len(entries) - 1)
        for i, entry in enumerate(entries):
            self._entries.insert(row + i, entry)
        self.endInsertRows()

    def remove_entries(self, row: int, count: int) -> None:
        """Remove count entries starting at row."""
        if row < 0 or row >= len(self._entries) or count <= 0:
            return

        end_row = min(row + count - 1, len(self._entries) - 1)
        self.beginRemoveRows(QModelIndex(), row, end_row)
        del self._entries[row:end_row + 1]
        self.endRemoveRows()

        # Update playing index if needed
        if self._current_playing_idx >= row:
            if self._current_playing_idx <= end_row:
                self._current_playing_idx = -1
            else:
                self._current_playing_idx -= count
