#!/usr/bin/env python3
"""
Playlist Model - QAbstractListModel for playlist display
Solves rendering issues with incremental updates and proper highlighting
"""

from typing import List, Optional, Any
from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QVariant, pyqtSignal
)

# Single DTO for the whole queue -> presenter -> model path: the service owns it
# and the view only re-exports it, so `view.models.DisplayEntry is
# service.queue_service.DisplayEntry`.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from service.queue_service import DisplayEntry
from service.metadata_store import RowMetadata


class PlaylistModel(QAbstractListModel):
    """
    Qt model for playlist display.

    Features:
    - Incremental updates (no flicker)
    - Playing track highlighting
    - Custom display text with indentation

    Data only: colours and fonts are the delegate's business
    (``view.delegates.playlist_delegate``), which reads them from the theme
    manager's tokens. Keeping ``QColor``/``QFont`` here used to pin the
    presentation to whatever theme the model happened to be built for, so a
    live theme flip could not reach it.
    """

    # Custom roles
    IsPlayingRole = Qt.ItemDataRole.UserRole + 1
    IsFolderRole = Qt.ItemDataRole.UserRole + 2
    NodeIndexRole = Qt.ItemDataRole.UserRole + 3
    SubIndexRole = Qt.ItemDataRole.UserRole + 4
    FullPathRole = Qt.ItemDataRole.UserRole + 5
    RelativePositionRole = Qt.ItemDataRole.UserRole + 6
    # Batch 4's three columns plus the state word that decides which mark a cell
    # shows. They continue the block above (nothing here may renumber a role the
    # delegate already reads), and ``MetadataStateRole`` answers one of the three
    # ``service.metadata_store`` strings as a ``str`` -- no enum, no int (ruling
    # B4-R5), so the delegate and the store cannot drift into two spellings.
    DurationRole = Qt.ItemDataRole.UserRole + 7
    ArtistRole = Qt.ItemDataRole.UserRole + 8
    AlbumRole = Qt.ItemDataRole.UserRole + 9
    MetadataStateRole = Qt.ItemDataRole.UserRole + 10

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

        elif role == self.RelativePositionRole:
            return entry.relative_position

        elif role == self.DurationRole:
            return entry.duration

        elif role == self.ArtistRole:
            return entry.artist

        elif role == self.AlbumRole:
            return entry.album

        elif role == self.MetadataStateRole:
            return entry.metadata_state

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

        "Changed" means the row would be **painted** differently: the display text,
        the playing flag, and since batch 4 the three metadata columns plus their
        state word (see :meth:`_metadata_differs`, ruling B4-R31). A library switch
        between two libraries that hold same-named files is exactly the input where
        the first two say "nothing happened" and the screen keeps the previous
        library's artist, album and length.
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
                    [self.IsPlayingRole]
                )

            if new_playing_idx >= 0 and new_playing_idx != old_playing:
                self.dataChanged.emit(
                    self.index(new_playing_idx),
                    self.index(new_playing_idx),
                    [self.IsPlayingRole]
                )
            return

        # Check for incremental changes
        if old_count == new_count:
            # Same size - check if content changed
            changed_indices = []
            for i, (old, new) in enumerate(zip(self._entries, entries)):
                if (old.display_text != new.display_text or
                    old.is_playing != new.is_playing or
                    self._metadata_differs(old, new)):
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

    @staticmethod
    def _metadata_differs(old: DisplayEntry, new: DisplayEntry) -> bool:
        """Whether the two rows would be **painted differently** in the data columns.

        Final review I2 (ruling B4-R31): this class used to decide "changed" from
        ``display_text`` and ``is_playing`` alone, which was a complete answer until
        batch 4 put three more painted cells on the row. Two libraries holding
        same-named files produce a row-for-row identical ``display_text`` list
        (``display_text`` for a file node *is* the filename), so a switch left the
        model holding library B's values while the view was told zero times --
        measured: ``dataChanged`` 0, reset 0, screen still showing A's artist. The
        stale frame then cleared on the first hover/scroll repaint, which is the
        shape that survives a demo and arrives as "the playlist showed the wrong
        artist".

        Compared **by value, not by identity**, and that is what keeps this and
        Task 7's pin on the other side of the same seam alive together (both are
        asserted in ``tests/test_playlist_metadata_model.py`` and in
        ``tests/test_metadata_wiring.py::TargetedUpdateIsTheOnlyRepaintTest``):
        the queue and the model share the ``DisplayEntry`` objects, so a re-push of
        a table the queue updated behind the model's back still announces nothing --
        a row compared against itself cannot differ, and the sweep's fill stays the
        only repaint route. What this closes is the case the old comparison missed
        for the *new* objects a rebuild produces.

        ``full_path`` is deliberately not in here: the delegate paints no path, so a
        path that differs under an identical name is a routing question (batch 3's
        row-targeting contract), not a stale cell.
        """
        return (old.duration != new.duration
                or old.artist != new.artist
                or old.album != new.album
                or old.metadata_state != new.metadata_state)

    def _only_playing_changed(self, new_entries: List[DisplayEntry]) -> bool:
        """Check if only the is_playing flag changed.

        The metadata cells count as content (ruling B4-R31): without this the fast
        path below would answer "only the highlight moved" for a library switch whose
        rows changed artist, announce ``IsPlayingRole`` on two rows, and leave every
        other row -- including the ones holding the new columns -- unpainted.
        """
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
            if self._metadata_differs(old, new):
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
                [self.IsPlayingRole]
            )

        if display_idx >= 0 and display_idx < len(self._entries):
            self._entries[display_idx].is_playing = True
            self.dataChanged.emit(
                self.index(display_idx),
                self.index(display_idx),
                [self.IsPlayingRole]
            )

    def update_row_metadata(self, row: int, md: Optional[RowMetadata],
                            state: str) -> None:
        """Refresh **one** row's three columns and its state word, in place.

        This is the view-side half of Task 5's targeted update: ``QueueService.
        apply_metadata`` hands back the row numbers it wrote, and the presenter
        calls this for each of them. Two rules make it worth a method of its own:

        * **No reset, ever.** ``beginResetModel`` would be one line shorter and
          would drop the selection, the current index and the scroll position on
          every row the background sweep fills -- spec §6's "no flicker" criterion
          read at the model boundary. The only emission here is one ``dataChanged``
          over ``[row, row]`` carrying exactly the four metadata roles, so a view
          that is not showing those columns does not repaint either.
        * **An out-of-range row is a no-op.** A late sweep result landing after the
          queue got shorter is the normal case, not an error: there is nothing to
          update, and raising would take the presenter (and on this platform the
          process) down with it.

        ``md is None`` clears the columns, and ``state`` is stored as handed -- the
        store owns the tri-state, this class only carries the word to the delegate
        (ruling B4-R5, and Task 5's ``apply_metadata`` for the same reasoning).
        """
        if not (0 <= row < len(self._entries)):
            return

        entry = self._entries[row]
        entry.duration = md.duration if md is not None else None
        entry.artist = md.artist if md is not None else None
        entry.album = md.album if md is not None else None
        entry.metadata_state = state

        self.dataChanged.emit(
            self.index(row),
            self.index(row),
            [self.DurationRole, self.ArtistRole,
             self.AlbumRole, self.MetadataStateRole]
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
