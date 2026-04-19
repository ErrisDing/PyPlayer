#!/usr/bin/env python3
"""
Queue Service - Unified queue state management
Solves the index confusion problem by providing a single source of truth
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from library_manager import (
    QueueNode, FileNode, FolderNode, Track,
    DisplayIndexMap, PlaybackQueue, PlaybackState
)


@dataclass
class PlaybackPosition:
    """Current playback position in the queue."""
    node_index: int = -1      # Index in queue_nodes list
    sub_index: int = -1       # For folders: index within folder's tracks
    display_index: int = -1   # Index in the display list


@dataclass
class DisplayEntry:
    """Entry for display in playlist view."""
    display_text: str
    node_idx: int
    is_folder: bool
    path: str
    sub_index: int = -1
    full_path: str = ""
    is_playing: bool = False  # True if this is the currently playing entry


class QueueService(QObject):
    """
    Unified queue state management service.

    Provides:
    - Single source of truth for playback position
    - Display list generation with proper indexing
    - Navigation (next/prev) with loop mode support
    """

    # Signals
    position_changed = pyqtSignal(object)     # PlaybackPosition
    queue_changed = pyqtSignal()              # Emitted when queue structure changes
    display_changed = pyqtSignal(list)        # Emitted with new DisplayEntry list

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # Queue nodes (FileNode or FolderNode)
        self._queue_nodes: List[QueueNode] = []

        # Display entries (flattened for UI)
        self._display_entries: List[DisplayEntry] = []

        # Current position
        self._position = PlaybackPosition()

        # Loop mode: "OFF", "ONE", "ALL"
        self._loop_mode: str = "OFF"

        # Library ID for this queue
        self._library_id: str = ""

    # === Queue Building ===

    def set_library_id(self, library_id: str) -> None:
        """Set the library ID for this queue."""
        self._library_id = library_id

    def build_from_tracks(self, tracks: List[Track]) -> None:
        """
        Build queue from a list of tracks (flat list of files).
        Creates FileNode for each track.
        """
        self._queue_nodes.clear()

        for track in tracks:
            node = FileNode(track=track)
            self._queue_nodes.append(node)

        self._rebuild_display_entries()
        self.queue_changed.emit()

    def build_from_folders(self, folder_data: Dict[str, List[Track]]) -> None:
        """
        Build queue from folder structure.
        Creates FolderNode for each folder with tracks.

        Args:
            folder_data: Dict mapping folder_path -> list of tracks
        """
        self._queue_nodes.clear()

        for folder_path, tracks in folder_data.items():
            if tracks:
                folder_name = Path(folder_path).name
                node = FolderNode(
                    display_text=folder_name,
                    path=folder_path,
                    tracks=tracks
                )
                self._queue_nodes.append(node)

        self._rebuild_display_entries()
        self.queue_changed.emit()

    def build_from_nodes(self, nodes: List[QueueNode]) -> None:
        """Build queue directly from QueueNode objects."""
        self._queue_nodes = list(nodes)
        self._rebuild_display_entries()
        self.queue_changed.emit()

    def _rebuild_display_entries(self) -> None:
        """Rebuild display entries from queue nodes."""
        self._display_entries.clear()
        display_idx = 0

        for node_idx, node in enumerate(self._queue_nodes):
            if node.is_folder():
                # Folder node - add folder entry
                folder_node: FolderNode = node
                entry = DisplayEntry(
                    display_text=f"[D] {folder_node.display_text}",
                    node_idx=node_idx,
                    is_folder=True,
                    path=folder_node.path
                )
                self._display_entries.append(entry)
                display_idx += 1

                # Add entries for each track in the folder
                for sub_idx, track in enumerate(folder_node.tracks):
                    file_entry = DisplayEntry(
                        display_text=f"    [F] {track.title}",
                        node_idx=node_idx,
                        is_folder=False,
                        path=folder_node.path,
                        sub_index=sub_idx,
                        full_path=track.path
                    )
                    self._display_entries.append(file_entry)
                    display_idx += 1
            else:
                # File node
                file_node: FileNode = node
                entry = DisplayEntry(
                    display_text=f"[F] {file_node.display_text}",
                    node_idx=node_idx,
                    is_folder=False,
                    path=file_node.path,
                    full_path=file_node.path
                )
                self._display_entries.append(entry)
                display_idx += 1

        self.display_changed.emit(self._display_entries)

    # === Position Management ===

    def set_current_position(self, node_idx: int, sub_idx: int = -1) -> None:
        """
        Set the current playback position.

        Args:
            node_idx: Index in queue_nodes
            sub_idx: For folders, index within folder's tracks
        """
        self._position.node_index = node_idx
        self._position.sub_index = sub_idx

        # Update display index
        self._position.display_index = self._find_display_index(node_idx, sub_idx)

        # Update is_playing flags on display entries
        self._update_playing_highlight()

        self.position_changed.emit(self._position)

    def set_position_by_display_index(self, display_idx: int) -> Optional[Track]:
        """
        Set position by display index and return the track to play.

        Args:
            display_idx: Index in the display list

        Returns:
            Track to play, or None if invalid/folder entry
        """
        if not (0 <= display_idx < len(self._display_entries)):
            return None

        entry = self._display_entries[display_idx]

        # Can't play a folder entry directly
        if entry.is_folder:
            return None

        # Update position
        self._position.node_index = entry.node_idx
        self._position.sub_index = entry.sub_index
        self._position.display_index = display_idx

        # Get the track
        track = self._get_track_at_position(entry.node_idx, entry.sub_index)

        # Update highlights
        self._update_playing_highlight()

        self.position_changed.emit(self._position)
        return track

    def _find_display_index(self, node_idx: int, sub_idx: int) -> int:
        """Find display index for given node/sub index."""
        for i, entry in enumerate(self._display_entries):
            if entry.node_idx == node_idx and entry.sub_index == sub_idx:
                return i
        return -1

    def _get_track_at_position(self, node_idx: int, sub_idx: int) -> Optional[Track]:
        """Get track at given position."""
        if not (0 <= node_idx < len(self._queue_nodes)):
            return None

        node = self._queue_nodes[node_idx]

        if node.is_folder():
            folder_node: FolderNode = node
            if 0 <= sub_idx < len(folder_node.tracks):
                return folder_node.tracks[sub_idx]
        else:
            file_node: FileNode = node
            return file_node.track

        return None

    def _update_playing_highlight(self) -> None:
        """Update is_playing flags on display entries."""
        for entry in self._display_entries:
            entry.is_playing = (
                entry.node_idx == self._position.node_index and
                entry.sub_index == self._position.sub_index
            )

    # === Navigation ===

    def advance_to_next(self) -> Optional[Track]:
        """
        Advance to next track.

        Returns:
            Next track to play, or None if end of queue
        """
        if not self._queue_nodes:
            return None

        node_idx = self._position.node_index
        sub_idx = self._position.sub_index

        # First track if not started
        if node_idx < 0:
            return self._play_first_track()

        node = self._queue_nodes[node_idx]

        if node.is_folder():
            folder_node: FolderNode = node

            # Try next track within folder
            if self._loop_mode == "ONE":
                # Stay on same track
                return self._get_track_at_position(node_idx, sub_idx)

            next_sub = sub_idx + 1
            if next_sub < len(folder_node.tracks):
                # Next track in folder
                return self._set_and_get_position(node_idx, next_sub)

            elif self._loop_mode == "ALL":
                # Wrap within folder
                return self._set_and_get_position(node_idx, 0)

            else:
                # Move to next node
                return self._advance_to_next_node(node_idx)

        else:
            # File node - move to next node
            if self._loop_mode == "ONE":
                return self._get_track_at_position(node_idx, sub_idx)
            return self._advance_to_next_node(node_idx)

    def _advance_to_next_node(self, current_node_idx: int) -> Optional[Track]:
        """Advance to the next node in queue."""
        next_node_idx = current_node_idx + 1

        if next_node_idx < len(self._queue_nodes):
            next_node = self._queue_nodes[next_node_idx]
            if next_node.is_folder():
                folder_node: FolderNode = next_node
                if folder_node.tracks:
                    return self._set_and_get_position(next_node_idx, 0)
            else:
                return self._set_and_get_position(next_node_idx, -1)

        elif self._loop_mode == "ALL":
            # Wrap to beginning
            return self._play_first_track()

        return None

    def advance_to_prev(self) -> Optional[Track]:
        """Go to previous track."""
        if not self._queue_nodes:
            return None

        node_idx = self._position.node_index
        sub_idx = self._position.sub_index

        if node_idx < 0:
            return None

        node = self._queue_nodes[node_idx]

        if node.is_folder() and sub_idx > 0:
            # Previous track in folder
            return self._set_and_get_position(node_idx, sub_idx - 1)
        elif node_idx > 0:
            # Previous node
            prev_node_idx = node_idx - 1
            prev_node = self._queue_nodes[prev_node_idx]

            if prev_node.is_folder():
                folder_node: FolderNode = prev_node
                if folder_node.tracks:
                    return self._set_and_get_position(prev_node_idx, len(folder_node.tracks) - 1)

            return self._set_and_get_position(prev_node_idx, -1)

        return None

    def _play_first_track(self) -> Optional[Track]:
        """Play the first track in the queue."""
        if not self._queue_nodes:
            return None

        first_node = self._queue_nodes[0]
        if first_node.is_folder():
            folder_node: FolderNode = first_node
            if folder_node.tracks:
                return self._set_and_get_position(0, 0)
        else:
            return self._set_and_get_position(0, -1)

        return None

    def _set_and_get_position(self, node_idx: int, sub_idx: int) -> Optional[Track]:
        """Set position and return the track."""
        self.set_current_position(node_idx, sub_idx)
        return self._get_track_at_position(node_idx, sub_idx)

    # === Accessors ===

    def get_display_entries(self) -> List[DisplayEntry]:
        """Get all display entries."""
        return list(self._display_entries)

    def get_current_position(self) -> PlaybackPosition:
        """Get current position."""
        return self._position

    def get_current_track(self) -> Optional[Track]:
        """Get the track at current position."""
        return self._get_track_at_position(
            self._position.node_index,
            self._position.sub_index
        )

    def get_loop_mode(self) -> str:
        """Get current loop mode."""
        return self._loop_mode

    def set_loop_mode(self, mode: str) -> None:
        """Set loop mode ("OFF", "ONE", "ALL")."""
        if mode in ("OFF", "ONE", "ALL"):
            self._loop_mode = mode

    def get_queue_length(self) -> int:
        """Get total number of playable tracks."""
        count = 0
        for node in self._queue_nodes:
            count += len(node.get_tracks())
        return count

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._queue_nodes) == 0

    # === Modification ===

    def clear(self) -> None:
        """Clear the queue."""
        self._queue_nodes.clear()
        self._display_entries.clear()
        self._position = PlaybackPosition()
        self.queue_changed.emit()
        self.display_changed.emit([])

    def remove_at_display_index(self, display_idx: int) -> bool:
        """
        Remove entry at display index.
        Returns True if successful.
        """
        if not (0 <= display_idx < len(self._display_entries)):
            return False

        entry = self._display_entries[display_idx]

        if entry.is_folder:
            # Remove entire folder
            if 0 <= entry.node_idx < len(self._queue_nodes):
                del self._queue_nodes[entry.node_idx]
        else:
            # Remove single file from folder or nodes
            node = self._queue_nodes[entry.node_idx]
            if node.is_folder():
                folder_node: FolderNode = node
                if 0 <= entry.sub_index < len(folder_node.tracks):
                    del folder_node.tracks[entry.sub_index]
                    # Remove folder if empty
                    if not folder_node.tracks:
                        del self._queue_nodes[entry.node_idx]
            else:
                del self._queue_nodes[entry.node_idx]

        self._rebuild_display_entries()
        return True
