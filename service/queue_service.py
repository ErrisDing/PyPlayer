#!/usr/bin/env python3
"""
Queue Service - Unified queue state management
Solves the index confusion problem by providing a single source of truth
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from PyQt6.QtCore import QObject, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.library_manager import (
    QueueNode, FileNode, FolderNode, Track,
    DisplayIndexMap, PlaybackQueue, PlaybackState
)
from service.metadata_store import (
    RowMetadata,
    STATE_PENDING,
    state_for_values,
)


def _write_metadata(entry: 'DisplayEntry', md: Optional[RowMetadata],
                    state: str) -> None:
    """Put one table row onto one display entry -- the single place that does it.

    ``md is None`` clears all three columns rather than leaving whatever the entry
    carried: a row that went back to pending (``set_metadata({})`` on a library
    switch, or the sweep answering "still nothing") must not keep showing the
    previous library's length. The values and the ``state`` are always written
    together, so no path through this class can leave a column and a state word
    describing different moments.
    """
    entry.duration = md.duration if md is not None else None
    entry.artist = md.artist if md is not None else None
    entry.album = md.album if md is not None else None
    entry.metadata_state = state


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
    relative_position: str = ""  # Relative position to library root (e.g., "root", "Rock/Albums")
    # Batch 4's three columns (spec §4.9). These are carried here, never on
    # ``Track``: ``Track.duration`` is ``float`` with ``0.0`` for "no length",
    # so the value that means "unknown" and the value that means "zero seconds"
    # are the same number, and a delegate reading it cannot tell them apart.
    # ``None`` is the only spelling of "no value" at this layer (ruling B4-R8).
    #
    # ``metadata_state`` is one of the three strings owned by
    # ``service.metadata_store`` (ruling B4-R5); this layer only ever produces
    # ``STATE_PENDING`` itself (the default below), so it imports that one word
    # plus ``state_for_values`` rather than re-typing any of them. The word is
    # *not* derived at paint time: the values and the state are written by the
    # queue's path-keyed table when the table is *built*, so a rebuild cannot
    # lose them (see ``_rebuild_display_entries``). A folder header row owns no
    # columns and stays ``STATE_PENDING`` forever -- Task 8's grid is what keeps
    # it out of sight.
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[float] = None
    metadata_state: str = STATE_PENDING


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

        # Current library path for display optimization
        self._current_library_path: str = ""

        # Batch 4: ``full_path -> (values, state)`` for the rows this queue shows.
        #
        # This table -- not the ``DisplayEntry`` objects -- is where the metadata
        # lives, because ``_rebuild_display_entries()`` throws every entry away and
        # builds new ones on each structural change (call sites at the four build
        # methods and ``remove_at_display_index``). Writing values only onto the
        # entries of the moment would mean "remove one song, the rest of the
        # playlist falls back to ``⋯``" -- green tests, broken UI.
        #
        # The value is a pair rather than a bare ``RowMetadata`` so the state word
        # survives the same rebuild (ruling B4-R17): ``md=None`` stands for both
        # "never tried" and "tried, got nothing", so one value cannot express the
        # two states spec §4.1 asks a cell to distinguish, and a rebuild that
        # re-derived the word from the values alone would silently turn an
        # extraction failure back into "still loading". ``apply_metadata`` is
        # therefore stored verbatim, while ``set_metadata`` -- which receives values
        # only -- names the word through the store's single ``state_for_values``
        # rather than a second copy of the rule. A single dict keeps the two from
        # ever disagreeing about one path.
        self._row_metadata: Dict[str, Tuple[Optional[RowMetadata], str]] = {}

        # Batch 4, final review I4 (ruling B4-R32): ``full_path -> the display rows
        # that show it``, rebuilt with the rows themselves.
        #
        # This exists for one reason: ``apply_metadata`` used to answer every single
        # delivery by filtering the whole display list. A sweep delivers once per
        # answered row, so the GUI-thread cost of filling a library went quadratic in
        # its size -- measured by the review on this host, real queue, no mocks: 147 us
        # per delivery, 441 ms cumulative at N=3000, against the ~0.95 s of extraction
        # the spec §8 probe recorded. That probe measured extraction, the pre-write
        # ``os.stat`` walk and the JSON dump, and never the row lookup, because the
        # lookup is not part of the write -- which is exactly how the term survived the
        # batch's own cost review.
        #
        # It is a *view of the rows*, not a second source of truth: the one place that
        # knows where a path lives is the loop that fills the columns
        # (:meth:`_fill_display_metadata`), so the index cannot drift from the layout it
        # indexes -- a stale one would repaint the wrong row, which is worse than being
        # slow. Unlike ``_row_metadata`` it does **not** survive the rows: an emptied
        # playlist has no rows to point at (see :meth:`clear`).
        self._rows_by_full_path: Dict[str, List[int]] = {}

    # === Queue Building ===

    def set_library_id(self, library_id: str) -> None:
        """Set the library ID for this queue."""
        self._library_id = library_id

    def set_current_library(self, library_path: str) -> None:
        """Set the current library path for display optimization."""
        self._current_library_path = library_path

    def _calculate_relative_position(self, file_path: str) -> str:
        """
        Calculate the relative position of a file to the library root.

        Args:
            file_path: Full path to the media file

        Returns:
            "root" if file is in library root directory,
            relative path (e.g., "Rock/Albums") if in subdirectory,
            empty string if not under library or on error
        """
        import os

        if not self._current_library_path or not file_path:
            return ""

        try:
            file_path = os.path.normpath(file_path)
            library_path = os.path.normpath(self._current_library_path)

            # Get parent directory of the file
            parent_dir = os.path.dirname(file_path)

            # Check if file is directly in library root
            if parent_dir == library_path:
                return "root"

            # Calculate relative path from library to parent directory
            rel_path = os.path.relpath(parent_dir, library_path)
            if rel_path == ".":
                return "root"

            return rel_path
        except (ValueError, OSError):
            # ValueError: different drives on Windows
            # OSError: other path-related errors
            return ""

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
        """Rebuild display entries from queue nodes.

        Skips library root nodes when a current library is set,
        showing only the contents within the library.
        Calculates relative position for each file entry.
        """
        self._display_entries.clear()
        display_idx = 0

        for node_idx, node in enumerate(self._queue_nodes):
            # Check if this is a library root node that should be skipped
            node_path = node.path
            is_library_root = (
                self._current_library_path and
                node_path == self._current_library_path
            )

            if node.is_folder():
                # Folder node - add folder entry (unless it's library root)
                folder_node: FolderNode = node

                if not is_library_root:
                    entry = DisplayEntry(
                        display_text=folder_node.display_text,
                        node_idx=node_idx,
                        is_folder=True,
                        path=folder_node.path
                    )
                    self._display_entries.append(entry)
                    display_idx += 1

                # Add entries for each track in the folder
                for sub_idx, track in enumerate(folder_node.tracks):
                    # Calculate indentation based on whether we skipped library root
                    indent = "    " if not is_library_root else ""
                    relative_pos = self._calculate_relative_position(track.path)
                    file_entry = DisplayEntry(
                        display_text=f"{indent}{track.title}",
                        node_idx=node_idx,
                        is_folder=False,
                        path=folder_node.path,
                        sub_index=sub_idx,
                        full_path=track.path,
                        relative_position=relative_pos
                    )
                    self._display_entries.append(file_entry)
                    display_idx += 1
            else:
                # File node
                file_node: FileNode = node
                relative_pos = self._calculate_relative_position(file_node.path)
                entry = DisplayEntry(
                    display_text=file_node.display_text,
                    node_idx=node_idx,
                    is_folder=False,
                    path=file_node.path,
                    full_path=file_node.path,
                    relative_position=relative_pos
                )
                self._display_entries.append(entry)
                display_idx += 1

        # Batch 4: the columns are filled **here**, from the queue's own table, and
        # never looked up again while a row is painted -- spec §4.9's "no second
        # lookup" is about the drawing side, and this is the one place the table is
        # read. A freshly built entry whose path the table does not know is pending
        # with three empty columns, which is the same thing a brand-new scan shows.
        self._fill_display_metadata()

        self.display_changed.emit(self._display_entries)

    # === Row Metadata (batch 4) ===

    def _fill_display_metadata(self) -> None:
        """Write the table onto every entry that exists right now.

        Shared by the rebuild (new objects) and :meth:`set_metadata` (existing
        ones), so the two can never disagree about what a path means.

        Walking the rows for the values is also the only moment that knows where a
        path *is*, so the ``full_path -> rows`` index is rebuilt here in the same
        pass (ruling B4-R32). A second reader of the layout would be the drift this
        batch keeps finding: an index maintained by anyone other than the loop that
        fills the columns repaints a wrong row silently.
        """
        index: Dict[str, List[int]] = {}
        for row, entry in enumerate(self._display_entries):
            if entry.is_folder or not entry.full_path:
                # A folder header owns no columns; ``full_path`` is empty for it by
                # construction, and the guard also keeps an empty path from ever
                # matching the table.
                continue
            index.setdefault(entry.full_path, []).append(row)
            md, state = self._row_metadata.get(
                entry.full_path, (None, STATE_PENDING))
            _write_metadata(entry, md, state)
        self._rows_by_full_path = index

    def set_metadata(self, mapping: Dict[str, Optional[RowMetadata]]) -> None:
        """Replace the whole row-metadata table, then refresh the visible rows.

        Two uses, one operation: the one-shot fill right after a scan built the
        display (every value the library cache already holds), and the wipe on a
        library switch (``set_metadata({})``, which Task 7 calls *after*
        ``cancel_sweep`` so an in-flight row of the library being left cannot land
        in this one's rows).

        It is a **replacement**, not a merge: a path missing from ``mapping`` is
        pending again, because keeping the previous library's values under paths
        that happen to exist in both would be exactly the cross-library leak
        spec §10 risk 1 names. The state word is named from the payload here by
        :func:`service.metadata_store.state_for_values` -- the one author of the
        tri-state rule, shared with ``LibraryMetadataStore.state_of`` so the two
        sides can never hold two copies of it (batch 4 review finding I1). The
        sweep path instead hands the store's own word through
        :meth:`apply_metadata`, and that word is stored verbatim.

        No signal is emitted: the caller already holds the list it would send, and
        :class:`~view.models.playlist_model.PlaylistModel` is refreshed by the
        presenter through the existing ``display_changed`` route or, for single
        rows, by :meth:`apply_metadata`'s return value (batch 3 ruling R9).
        """
        self._row_metadata = {
            full_path: (md, state_for_values(md))
            for full_path, md in mapping.items()
        }
        self._fill_display_metadata()

    def apply_metadata(self, full_path: str, md: Optional[RowMetadata],
                       state: str) -> List[int]:
        """Update the rows showing ``full_path``; return their **row numbers**.

        Returns every display row that carries this path, ascending, and updates
        all of them: one file inside a folder node can legitimately occupy several
        rows, and updating only the first would show the same song with a length
        in one place and ``⋯`` in the other. ``[]`` means no row of this queue
        shows that path -- the caller (Task 7's sweep callback) then updates
        nothing, and the result is deliberately not remembered: this table mirrors
        the rows, the store is what persists an answer for a file nobody is
        looking at.

        The numbers are *display* rows -- the same space as
        ``PlaylistView.selected_display_indices()`` and ``remove_at_display_index``,
        never ``DisplayEntry.node_idx``; with a folder in front of them the two
        differ by one per folder row. They exist so the caller can hand each row to
        ``PlaylistModel.update_row_metadata`` without a reset, which is why there is
        no signal on this method.

        ``state`` is stored verbatim (it is the store's ``state_of`` answer, and
        re-deriving it here would put a second owner on the tri-state), and it
        travels into the table with the values so a later rebuild sees both.

        The rows come from :attr:`_rows_by_full_path`, the index the fill loop
        rebuilds (ruling B4-R32) -- **not** from a scan of the display list. One
        delivery per answered row is the sweep's own rhythm, so a scan here made
        filling a library quadratic on the GUI thread (measured: 147 us per delivery,
        441 ms cumulative at N=3000, which is the entire write-back budget again);
        a lookup costs one dict read plus one entry per row that really carries the
        path. The folder shape above is why the value is a *list*: a path can own
        several rows, and every one of them is still returned.
        """
        if not full_path:
            return []

        rows = list(self._rows_by_full_path.get(full_path, ()))
        if not rows:
            return []

        self._row_metadata[full_path] = (md, state)
        for idx in rows:
            _write_metadata(self._display_entries[idx], md, state)
        return rows

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

        # First track if not started or invalid position
        if node_idx < 0 or node_idx >= len(self._queue_nodes):
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

        # Invalid position - nothing to go back from
        if node_idx < 0 or node_idx >= len(self._queue_nodes):
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
        """Clear the queue.

        The row-metadata **table** stays (ruling B4-R18: ``clear`` serves "empty the
        playlist", a library switch is :meth:`set_metadata` ``({})``), but the
        ``full_path -> rows`` **index** goes with the rows it indexes -- it is a view
        of the layout, and an index pointing at rows that no longer exist would make
        :meth:`apply_metadata` hand back row numbers the view cannot paint.
        """
        self._queue_nodes.clear()
        self._display_entries.clear()
        self._rows_by_full_path = {}
        self._position = PlaybackPosition()
        self.queue_changed.emit()
        self.display_changed.emit([])

    def remove_at_display_index(self, display_idx: int) -> bool:
        """
        Remove entry at display index.
        Returns True if successful.

        Known debt (batch 3, ruling R8): this rebuilds the display list but does
        **not** maintain ``self._position`` -- unlike :meth:`clear`, which resets
        it. Measured with a five-row queue playing T2: removing T2, or removing
        any row above it, leaves ``get_current_track()`` answering **T3**. The
        only caller so far compensates in the presenter by re-finding the track
        by path before it removes anything; that compensation is this method's
        job and batch 5 (queue mutation contract) owns the fix. The pin to update
        when it lands is ``QueuePositionAfterRemovalCharacterizationTest`` in
        ``tests/test_playlist_actions.py``.
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
