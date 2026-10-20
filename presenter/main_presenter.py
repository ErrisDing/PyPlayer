#!/usr/bin/env python3
"""
Main Presenter - Coordinates View and Service layers
Implements MVP pattern for clean separation of concerns
"""

import os
from typing import Dict, Optional, List, Tuple
from PyQt6.QtCore import QObject, QTimer, pyqtSlot

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
sys.path.insert(0, str(Path(__file__).parent.parent))

from view.main_window import MainWindow
# The rail's action ids are the wire format for progress reports (Task 3), so the
# presenter names them through the constants the widget dispatches on rather than
# repeating literals that can drift from the button they address.
from view.widgets.action_rail import ACTION_REFRESH, ACTION_REFRESH_ALL
# ``view.models.DisplayEntry`` is the service DTO since Task 2 merged the
# duplicate, so the presenter has no conversion left to do and no import of its
# own to make (see ``_on_display_changed``).
from view.dialogs import LibraryManagementDialog, AppearanceDialog
from service.playback_service import PlaybackService
from service.queue_service import QueueService, PlaybackPosition, DisplayEntry as QueueDisplayEntry
from service.library_service import LibraryService
from service.metadata_service import MetadataService
# Batch 4's Task 7 wiring. The store owns the three states and the per-file expiry, and
# the presenter is the one layer that meets all four parties -- the scan, the sweep, the
# queue's rows and the cache file. The state words are never spelled here (ruling B4-R5):
# every one that reaches a row was read back from the store that decided it.
from service.metadata_store import LibraryMetadataStore, RowMetadata
from service.config_service import ConfigService

from core import i18n
from core.player import PlayerState
from core.library_manager import Track

#: Rows the sweep may answer before the cache file is rewritten.
#:
#: Measured on this host through the repository's own paths. The raw output, the probe
#: and the derivation are recorded in ``task-7-report.md`` §6 (the probe itself is a
#: one-shot and is deliberately not committed). Samples are the repository's own real
#: recording, re-encoded into each container. Three costs make a sweep, and all three
#: were measured -- the second one is the reason the first round's derivation had to be
#: re-run:
#:
#: * **extraction** (pool thread, per file): medians of 0.129 ms (flac), 0.318 ms
#:   (mp3), 0.358 ms (the same mp3 carrying a 7 KB embedded cover) and 0.013 ms for a
#:   file no extractor claims (wav and an unknown suffix alike). The cover read
#:   B4-R15 leaves in place costs +0.040 ms on the mp3 and +0.010 ms on the flac.
#:   ogg/m4a were not measured: this host has no encoder for either, and they cross the
#:   same mutagen open-and-parse branch the containers that were measured cross.
#: * **the pre-write re-check** (GUI thread, one ``os.stat`` per dirty row, so one
#:   batch worth per flush): 15.3 us a row -- 7.7 ms for a full batch of 500, and
#:   76.7 ms for a 5000-row sweep *whatever* the batch size is.
#: * **the write-back** (GUI thread, whole file): ``save_cache`` dumps the entire
#:   document every call, and a flush is a ``load_cache`` plus a ``save_cache``
#:   (exactly what ``update_cache_metadata`` does) -- 7.95 ms at 200 rows, 18.88 at
#:   1000, 44.85 at 3000, 71.59 at 5000, i.e. about 14 us per entry once the fixed
#:   cost is amortised.
#:
#: This number therefore trades JSON writing, not row latency: rows are repainted as they
#: arrive whatever it is (``_on_metadata_row``), and the ``⋯`` marks are the sweep's
#: visible progress. With the plan's draft value of 25, a 5000-row library pays 200
#: flushes x 71.6 ms = 14.3 s of writing against 1.79 s of actual extraction (799% of it,
#: the O(n^2) shape spec §4.4 and §10 risk 2 exist to prevent); the stat walk is the same
#: 76.7 ms in total at any batch size, so it rides along rather than deciding anything.
#: Writing plus walk as a share of extraction puts the floor at B=250 (84.2% at 5000
#: rows) and 500 leaves the headroom: 10 flushes = 715.9 + 76.7 = 44.2% of extraction at
#: 5000 rows, 2 = 53.1 ms = 14.8% at 1000, 1 = 11.0 ms = 15.4% at 200. B=1000 would cut
#: that to 24.2% and is refused by what it costs instead: one flush blocks the GUI for
#: the write (71.6 ms at 5000 rows, set by the library size) *plus* the walk (B x 15.3 us,
#: set by this constant), so 79.3 ms at 500 rather than 86.9 ms at 1000 -- the walk is
#: the only term a bigger batch makes worse, and it is a tenth of a flush.
#: What the batch gives up is granularity: a lost batch is at most 500 rows, and those
#: rows are pending again after a restart, so re-extracting them costs
#: 500 x 0.358 ms ~ 0.18 s.
METADATA_WRITE_BATCH = 500


class MainPresenter(QObject):
    """
    Main presenter coordinating all UI and business logic.

    Responsibilities:
    - Connect View signals to Service methods
    - Update View based on Service state changes
    - Handle track end events and navigation
    - Manage playback position updates
    - Schedule the library's metadata sweep after a scan, hand each answered row to the
      view, and write the answers back in batches (batch 4, Task 7)
    """

    # Update interval for position polling (ms)
    POSITION_UPDATE_INTERVAL = 100

    def __init__(
        self,
        view: MainWindow,
        playback_service: PlaybackService,
        queue_service: QueueService,
        library_service: LibraryService,
        metadata_service: MetadataService,
        config_service: ConfigService,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)

        self._view = view
        self._playback = playback_service
        self._queue = queue_service
        self._library = library_service
        self._metadata = metadata_service
        self._config = config_service

        # Current library tracking
        self._current_library_path: str = ""

        # === batch 4: the metadata sweep ===
        #
        # The store belongs to one library and outlives a re-scan of *that* library, so
        # a row an earlier plan answered but never got as far as writing stays answered
        # (and a row invalidated between two scans keeps the shape that proves it was
        # invalidated -- see ``_flush_metadata_cache``). A switch replaces it, because
        # rows of the library being left must never reach this one's cache file
        # (spec §10 risk 1).
        self._metadata_store: Optional[LibraryMetadataStore] = None
        self._metadata_store_library: str = ""
        # The library the *next* ``_start_metadata_sweep`` belongs to. The scan entries
        # set it rather than deriving it from ``_current_library_path``, because
        # ``library_loaded`` fires for every library a refresh-all walks and only the
        # first of them is current.
        self._metadata_library_path: str = ""
        # The live plan's bookkeeping, per ``task-4-report.md`` §5.1's five conditions:
        # the count that decides completion is *this* generation's deliveries against
        # *this* generation's ``len(targets)``. ``_metadata_generation`` of -1 means no
        # plan is live, which is what makes a refusal (see ``_start_metadata_sweep``)
        # unable to leave a retired plan looking alive.
        self._metadata_generation: int = -1
        self._metadata_expected: int = 0
        self._metadata_delivered: int = 0
        self._metadata_since_flush: int = 0
        # ``(size, mtime)`` per path as this scan measured it -- the pair each stored
        # ``md`` claims to describe, and the one the write-back re-checks against the
        # disk. The store holds the same pair privately; a row missing from this map is
        # a row whose pairing this plan cannot vouch for, so it is not written.
        self._metadata_fingerprints: Dict[str, Tuple[int, float]] = {}

        # Position update timer
        self._position_timer = QTimer(self)
        self._position_timer.timeout.connect(self._update_position)

        # Setup connections
        self._setup_view_connections()
        self._setup_service_connections()
        self._setup_library_connections()

        # Load initial configuration
        self._load_config()

    def _setup_view_connections(self) -> None:
        """Connect View signals to handler methods."""
        # Playback controls
        self._view.play_pause_requested.connect(self._on_play_pause)
        self._view.stop_requested.connect(self._on_stop)
        self._view.next_track_requested.connect(self._on_next_track)
        self._view.prev_track_requested.connect(self._on_prev_track)
        self._view.seek_requested.connect(self._on_seek)
        self._view.volume_changed.connect(self._on_volume_changed)
        self._view.loop_mode_changed.connect(self._on_loop_mode_changed)

        # Playlist interactions
        self._view.track_double_clicked.connect(self._on_track_double_clicked)
        # Batch 3, Task 6: the two batch handlers of Task 5 finally get their caller,
        # plus the clear landing ruling R9 asked for (``clear_playlist_requested`` has
        # had an emitter since Task 3 and, until this line, nowhere to go). The payloads
        # arrive ascending and deduplicated from ``PlaylistView``; neither forward
        # re-sorts them, and neither receives an empty list (spec §7 is enforced in the
        # view *and* at the top of both handlers).
        self._view.play_tracks_requested.connect(self._on_play_tracks)
        self._view.remove_tracks_requested.connect(self._on_remove_tracks)
        self._view.clear_playlist_requested.connect(self._on_clear_playlist)

        # Library management. ``add_library_requested`` and
        # ``manage_libraries_requested`` both come from the floating panel's footer
        # since Task 8 (spec §3.2 correction): the add entry emits the chosen path,
        # the manage entry asks for this presenter's dialog. Before that, ``add``
        # had an emitter and no consumer, and ``manage`` had a consumer and no
        # emitter -- the two halves of Task 7's review finding.
        self._view.scan_folder_requested.connect(self._on_scan_folder)
        self._view.refresh_library_requested.connect(self._on_refresh_library)
        self._view.refresh_all_requested.connect(self._on_refresh_all)
        self._view.library_selected.connect(self._on_library_selected)
        self._view.add_library_requested.connect(self._on_add_library)
        self._view.manage_libraries_requested.connect(self._on_manage_libraries)

        # Appearance settings
        self._view.manage_appearance_requested.connect(self._on_manage_appearance)

    def _setup_service_connections(self) -> None:
        """Connect Service signals to handler methods."""
        # Playback state changes
        self._playback.state_changed.connect(self._on_playback_state_changed)
        self._playback.track_changed.connect(self._on_track_changed)
        self._playback.track_ended.connect(self._on_track_ended)
        self._playback.volume_changed.connect(self._on_volume_changed_from_service)

        # Queue changes
        self._queue.position_changed.connect(self._on_queue_position_changed)
        self._queue.display_changed.connect(self._on_display_changed)

        # Metadata loaded
        self._metadata.metadata_loaded.connect(self._on_metadata_loaded)
        self._metadata.album_art_loaded.connect(self._on_album_art_loaded)

    def _setup_library_connections(self) -> None:
        """Connect Library service signals."""
        self._library.library_loaded.connect(self._on_library_loaded)

    def _load_config(self) -> None:
        """Load initial configuration."""
        # Set initial volume
        self._view.set_volume(self._playback.get_volume())

        # Load configured libraries
        libraries = self._config.get_libraries()
        self._view.set_libraries(libraries)

        # Auto-load first library
        if libraries:
            first_lib = libraries[0]
            self._library.load_library(first_lib.path, first_lib.name)

        # Load and check background image
        bg_path = self._config.get_background_image()
        if bg_path:
            if os.path.exists(bg_path):
                self._view.set_background_image(bg_path)
            else:
                # Show warning and clear invalid config
                self._view._check_background_image(self._config._manager)

        # Load appearance settings
        self._view.set_overlay_alpha(self._config.get_overlay_alpha())
        self._view.set_playlist_alpha(self._config.get_playlist_alpha())
        self._view.set_controls_alpha(self._config.get_controls_alpha())

    # === Copy helpers ===

    def _library_label(self, library_path: str) -> str:
        """The label a library is known by, for copy that substitutes ``{name}``.

        The three status strings that name a library all take a ``{name}``
        parameter, and the honest value for it is the same string the floating
        panel's row shows: the configured name, or the folder when a library has no
        name at all (``LibrarySidebar._rebuild_rows`` makes exactly this choice, for
        exactly this reason -- a name and a path in the same list would read as two
        different libraries). A removal report always lands on the fallback:
        ``ConfigService.remove_library`` has written the file before this runs, so
        the path is no longer configured and only the folder is left to say.
        """
        for library in self._config.get_libraries():
            if getattr(library, 'path', None) == library_path:
                name = getattr(library, 'name', None)
                if name:
                    return name
                break
        return _basename(library_path) or library_path

    # === View Signal Handlers ===

    @pyqtSlot()
    def _on_play_pause(self) -> None:
        """Handle play/pause button click."""
        if self._playback.is_playing and not self._playback.is_paused:
            self._playback.pause()
        elif self._playback.is_paused:
            self._playback.resume()
        else:
            # No track playing - try to play from queue
            track = self._queue.get_current_track()
            if track:
                self._playback.play(track.path)
            elif not self._queue.is_empty():
                # Start from beginning
                track = self._queue.advance_to_next()
                if track:
                    self._playback.play(track.path)

    @pyqtSlot()
    def _on_stop(self) -> None:
        """Handle stop button click."""
        self._playback.stop()
        self._position_timer.stop()
        self._view.reset_progress()
        self._view.clear_now_playing()
        self._view.highlight_current_track(-1)

    @pyqtSlot()
    def _on_next_track(self) -> None:
        """Handle next track button click."""
        track = self._queue.advance_to_next()
        if track:
            self._playback.play(track.path)
        else:
            self._on_stop()

    @pyqtSlot()
    def _on_prev_track(self) -> None:
        """Handle previous track button click."""
        track = self._queue.advance_to_prev()
        if track:
            self._playback.play(track.path)

    @pyqtSlot(float)
    def _on_seek(self, position: float) -> None:
        """Handle seek request."""
        self._playback.seek(position)

    @pyqtSlot(float)
    def _on_volume_changed(self, volume: float) -> None:
        """Handle volume change from UI."""
        self._playback.set_volume(volume)

    @pyqtSlot(str)
    def _on_loop_mode_changed(self, mode: str) -> None:
        """Handle loop mode change from UI."""
        self._queue.set_loop_mode(mode)

    @pyqtSlot(int)
    def _on_track_double_clicked(self, display_idx: int) -> None:
        """Handle double-click on playlist entry."""
        track = self._queue.set_position_by_display_index(display_idx)
        if track:
            self._playback.play(track.path)

    @pyqtSlot(list)
    def _on_play_tracks(self, indices: List[int]) -> None:
        """Play a batch of selected rows: the lowest display index wins.

        spec §5 fixes ``Enter`` (and the context menu's Play) on the *smallest*
        display index, not on the last row clicked, "与双击语义一致" -- so this
        delegates to the double-click handler instead of repeating its two lines.
        One route means the three entries cannot drift apart later.

        An empty selection returns without touching anything: spec §7 puts the
        "no rows, no call" rule here as well as in the view, so the presenter is
        never one accidental ``[]`` away from a loop that does nothing while its
        caller believes something was removed.
        """
        if not indices:
            return
        self._on_track_double_clicked(min(indices))

    @pyqtSlot(list)
    def _on_remove_tracks(self, indices: List[int]) -> None:
        """Remove a batch of rows, then put the playback position back by identity.

        Two rules and one compensation, in that order.

        **Descending** (spec §4.2): ``remove_at_display_index`` addresses one row,
        so deleting row 3 turns former row 5 into row 4. ``sorted(set(...),
        reverse=True)`` dedupes and removes from the bottom up. An empty batch
        returns first, for the same reason as above (spec §7).

        **The compensation** is the reason this method is longer than the loop.
        Ruling R8, measured on this host and pinned by
        :class:`tests.test_playlist_actions.QueuePositionAfterRemovalCharacterizationTest`:
        ``QueueService.remove_at_display_index`` only rebuilds the display entries
        (``service/queue_service.py:486-513``) and **never touches
        ``PlaybackPosition``** -- unlike ``clear()`` at ``:478-484``, which does.
        After a removal the queue therefore answers its own stale ``node_index``
        against the shrunken node list, and reads back a *different song*: with T2
        playing on a flat five-row queue, removing T2 itself returns T3, and
        removing T0 -- a row *above* it, which does not delete the song at all --
        also returns T3. Only removing the tail so the index falls past the end
        answers ``None``, which is precisely why one test would have missed this.
        So the post-removal ``get_current_track()`` is not evidence of anything.

        The batch's scope line is 本批次不改队列契约, so the position cannot be fixed
        inside the service and no new queue API may be invented. The presenter
        re-establishes it **by track identity**: capture the playing track's path
        *before* mutating, then look for that path among the entries that survived.
        Found -- the song is still in the list, only at a new row -- re-point the
        position there through the existing ``set_position_by_display_index``, which
        recomputes the highlights and emits ``position_changed`` so the view's
        playing row follows the song instead of the old number. Not found -- the
        playing row was one of the removed ones -- there is nothing to re-point at:
        the position goes to "no track" and playback resets.

        The reset keeps to existing API as well. ``set_current_position(-1, -1)`` is
        the only way to un-point a position while rows remain: no display entry ever
        carries ``node_idx == -1``, so it recomputes to ``display_index == -1`` and
        clears every ``is_playing`` flag. Once nothing is left, spec §7 calls the
        batch equivalent to clearing the playlist, and ``clear()`` is what the queue
        itself uses to put ``_position`` back to -1 -- which matters beyond tidiness:
        a stale ``node_index`` into an emptied node list is one ``advance_to_next()``
        away from whatever row the user adds next.
        """
        targets = sorted(set(indices), reverse=True)
        if not targets:
            return

        # Identity first: after the first deletion the queue cannot be trusted to
        # say what was playing (R8). The display index is captured beside it
        # because it is the only *exact* answer to "was the playing row in this
        # batch" -- a path cannot answer that when the same file is queued twice.
        playing = self._queue.get_current_track()
        playing_path = playing.path if playing is not None else None
        playing_idx = self._queue.get_current_position().display_index

        removed = 0
        for display_idx in targets:
            if self._queue.remove_at_display_index(display_idx):
                removed += 1
        if not removed:
            # Every index was invalid, so the list is unchanged and nothing may
            # move: no re-pin, and no stop that the user never asked for.
            return

        entries = self._queue.get_display_entries()
        if playing_path is not None and playing_idx >= 0 and playing_idx not in targets:
            surviving = next((i for i, entry in enumerate(entries)
                              if not entry.is_folder
                              and entry.full_path == playing_path), -1)
            if surviving >= 0:
                # Same song, new row. Returns the track, but this is not a request
                # to play it: the engine is already playing it. Among two queued
                # copies of one path this re-pins the first -- the audio is the
                # same, exact identity of the copy is batch 5's to settle.
                self._queue.set_position_by_display_index(surviving)
                return

        # The playing row is gone (or there was no position at all). Whatever is
        # left in the list stays left; only the playback state resets.
        if entries:
            self._queue.set_current_position(-1, -1)
        else:
            self._queue.clear()
        self._on_stop()

    @pyqtSlot()
    def _on_clear_playlist(self) -> None:
        """清空播放列表: the queue goes, and playback goes with it (ruling R9).

        The menu entry has emitted ``PlaylistView.clear_playlist_requested`` since
        Task 3 and this window has forwarded it since Task 6; before this slot the
        route ended in nothing, which is exactly batch 2's inert-shortcut shape -- a
        signal emitted *and* connected still does no work if no slot sits at the end.

        Two calls, in this order, both existing API (本批次不改队列契约):

        * :meth:`QueueService.clear` is the only way to put ``PlaybackPosition`` back
          to -1 (ruling R8: ``remove_at_display_index`` never touches it, and a stale
          node index into an emptied list is one ``advance_to_next()`` away from
          playing whatever the user queues next). It also emits ``display_changed([])``,
          which empties the visible list through :meth:`_on_display_changed`.
        * :meth:`_on_stop` is the same reset the removal path runs when the last row
          goes -- engine stopped, position timer stopped, progress and
          ``NowPlayingStrip`` cleared, playing highlight dropped. The first call alone
          would leave a mock-free engine still headline-ing a track the queue no
          longer has.
        """
        self._queue.clear()
        self._on_stop()

    @pyqtSlot(str)
    def _on_scan_folder(self, folder: str) -> None:
        """Handle scan folder request.

        No progress report here, and none from the sweep this scan ends up starting
        (Task 7): ``ActionRail.set_progress`` *raises* for an id outside
        ``PROGRESSABLE_IDS`` (``view/widgets/action_rail.py:269-270``), this button's id
        is not in it, and the presenter reaches the rail from a Qt slot -- so a spinner
        for 打开文件夹 would promise a scan the button does not do *and* take the process
        with it. The unfilled ``⋯`` marks are that progress (spec §10 risk 4). The work
        is scheduled where the scan reports back, in ``_on_library_loaded``.
        """
        self._library.load_library(folder)

    @pyqtSlot(str)
    def _on_refresh_library(self, library_path: str) -> None:
        """Handle refresh library request: state on the button, result as feedback.

        spec §5's split, in one shape: the *scan* is progress, so the rail button
        carries it and no text is produced for the duration; the *count* is a
        result, so it goes to the toast. ``finally`` clears the state because
        ``_BLOCKED_PAIR`` disables the other refresh entry while this one runs --
        an unbalanced report would leave two dead buttons on a shell that has no
        other way to notice.
        """
        self._view.set_action_progress(ACTION_REFRESH, True)
        try:
            files = self._library.refresh_library(library_path)
        finally:
            self._view.set_action_progress(ACTION_REFRESH, False)

        if files:
            self._view.show_toast(
                i18n.get('status.library_refreshed',
                         name=self._library_label(library_path))
            )
            # Rebuild queue with refreshed files
            tracks = []
            for media_file in files:
                track = Track(
                    path=media_file.path,
                    title=media_file.title
                )
                tracks.append(track)
            self._queue.build_from_tracks(tracks)

    @pyqtSlot()
    def _on_refresh_all(self) -> None:
        """Handle refresh all libraries request.

        The count report replaces a hardcoded English sentence;
        ``status.refreshed_files`` is the key, and both numbers are passed as
        parameters rather than formatted here (spec §5: 文案改为走 i18n 并带参数).
        """
        self._view.set_action_progress(ACTION_REFRESH_ALL, True)
        try:
            results = self._library.refresh_all_libraries()
        finally:
            self._view.set_action_progress(ACTION_REFRESH_ALL, False)

        total_files = sum(len(files) for files in results.values())
        self._view.show_toast(
            i18n.get('status.refreshed_files',
                     count=total_files, libs=len(results))
        )

    @pyqtSlot(str)
    def _on_library_selected(self, library_path: str) -> None:
        """Handle library selection from UI.

        The first two metadata calls are an ordering ruling (B4-R18), not tidiness:
        retire the sweep that is running *before* wiping the rows it might still be
        filling. Reversed, a row of the library being left is delivered into a table that
        has just been cleared and re-filled from the new library's paths -- and two
        libraries are allowed to overlap on absolute paths, which is exactly how one
        library's length ends up on another library's row (spec §10 risk 1).

        The wipe is unconditional while the sweep is not: with no files to show the
        queue keeps the rows it has (pre-existing behaviour this task does not change),
        and starting a plan for a library nobody is looking at would hand its cache file
        the write-back target. ``_cancel_metadata_sweep`` already cleared the table.
        """
        self._cancel_metadata_sweep()
        self._current_library_path = library_path
        self._queue.set_current_library(library_path)

        # Set library path for NCM proxy support
        self._playback.set_library_path(library_path)

        # Load files from the selected library
        files = self._library.get_files(library_path)
        if files:
            tracks = []
            for media_file in files:
                track = Track(
                    path=media_file.path,
                    title=media_file.title
                )
                tracks.append(track)
            # Same rule as ``_on_library_loaded``: fill the columns and schedule what is
            # missing, then push -- the rebuild is where the table reaches the rows.
            self._metadata_library_path = library_path
            self._start_metadata_sweep(files)
            self._queue.build_from_tracks(tracks)
            self._view.show_toast(
                i18n.get('status.library_switched',
                         name=self._library_label(library_path))
            )

    @pyqtSlot()
    def _on_manage_libraries(self) -> None:
        """Handle manage libraries request - open dialog.

        Reachable since Task 8 through the floating panel's footer entry
        (:meth:`view.widgets.library_sidebar.LibrarySidebar.manage_requested` ->
        ``MainWindow.manage_libraries_requested``). This handler has been connected
        since Task 2 with nothing to fire it: the menu bar was the only emitter, and
        spec §3.2 then promised the rail would carry the action while §6 froze the
        rail at seven buttons that do not include it.
        """
        libraries = self._config.get_libraries()
        dialog = LibraryManagementDialog(libraries, self._view)

        # Connect dialog signals with dialog reference for refresh
        dialog.add_library_requested.connect(lambda path: self._handle_add_library_dialog(dialog, path))
        dialog.remove_library_requested.connect(lambda path: self._handle_remove_library_dialog(dialog, path))
        dialog.reorder_requested.connect(lambda old, new: self._handle_reorder_library_dialog(dialog, old, new))

        # Show dialog
        dialog.exec()

    @pyqtSlot(str)
    def _on_add_library(self, path: str) -> None:
        """Handle the floating panel's add entry: the same write, no dialog to refresh."""
        self._add_library(path)

    def _add_library(self, path: str) -> bool:
        """The one place a new library is written, scanned and re-published.

        Two entry points reach it -- the panel footer and the management dialog's
        Add button -- so splitting the write would mean one of them silently
        stopped scanning a new library. Returns the config write's verdict; a write
        that failed leaves the list, the scan and the panel untouched, exactly as
        the dialog path always did.

        ``MainWindow.set_libraries`` is what puts the new row in the panel the user
        is already looking at (Task 4's tolerate-while-open ruling). There is no
        toast: the row appearing *is* the report, and the panel is on screen.
        """
        if not self._config.add_library(path):
            return False
        self._library.load_library(path)
        self._view.set_libraries(self._config.get_libraries())
        return True

    def _remove_library(self, library_path: str) -> bool:
        """The one place a library is removed: config write, then the view's list.

        The removal report goes to the toast (spec §5) because the row disappearing
        from a panel the user has to open on purpose is not enough to tell them the
        write succeeded -- unlike adding, where the panel is already on screen.
        """
        if not self._config.remove_library(library_path):
            return False
        self._view.set_libraries(self._config.get_libraries())
        self._view.show_toast(
            i18n.get('status.library_removed',
                     name=self._library_label(library_path))
        )
        return True

    def _handle_add_library_dialog(self, dialog: LibraryManagementDialog, path: str) -> None:
        """Handle add library from dialog."""
        if self._add_library(path):
            dialog.set_libraries(self._config.get_libraries())

    def _handle_remove_library_dialog(self, dialog: LibraryManagementDialog, library_path: str) -> None:
        """Handle library removal from dialog."""
        if self._remove_library(library_path):
            dialog.set_libraries(self._config.get_libraries())

    def _handle_reorder_library_dialog(self, dialog: LibraryManagementDialog, old_index: int, new_index: int) -> None:
        """Handle library reorder from dialog."""
        if self._config.reorder_library(old_index, new_index):
            # Refresh both main window and dialog
            libraries = self._config.get_libraries()
            self._view.set_libraries(libraries)
            dialog.set_libraries(libraries)

    @pyqtSlot()
    def _on_manage_appearance(self) -> None:
        """Handle manage appearance menu action - open dialog."""
        dialog = AppearanceDialog(
            background_image=self._config.get_background_image(),
            overlay_alpha=self._config.get_overlay_alpha(),
            playlist_alpha=self._config.get_playlist_alpha(),
            controls_alpha=self._config.get_controls_alpha(),
            theme_mode=self._config.get_theme(),
            parent=self._view
        )

        # Connect dialog signals
        dialog.theme_selected.connect(self._handle_theme_change)
        dialog.background_image_changed.connect(
            lambda path: self._handle_background_change(dialog, path)
        )
        dialog.overlay_alpha_changed.connect(
            lambda alpha: self._handle_overlay_change(dialog, alpha)
        )
        dialog.playlist_alpha_changed.connect(
            lambda alpha: self._handle_playlist_alpha_change(dialog, alpha)
        )
        dialog.controls_alpha_changed.connect(
            lambda alpha: self._handle_controls_alpha_change(dialog, alpha)
        )

        dialog.exec()

    def _handle_theme_change(self, mode: str) -> None:
        """Handle a theme mode choice from the dialog: persist it, nothing else.

        Applying is the service's job. ``ConfigService.set_theme`` writes the
        mode and, only when the write succeeds, emits ``theme_changed``, and
        ``main.py`` has that signal connected to ``ThemeManager.set_mode``, so
        the flow is view -> presenter -> service -> theme layer, one apply per
        click. Calling ``set_mode`` from here too would be a second path,
        restyling twice and looping back once anything else listens on the
        signal.

        The return value is the write's verdict, so it is checked. A write that
        fails emits nothing, so the running theme and the file both keep the
        old mode -- that much is guaranteed. What is not: ``set_theme`` in
        ``core.config`` mutates ``settings.theme`` before saving, so after a
        failed write ``get_theme()`` already answers the mode the user did not
        get, and the dialog re-opened from it would lie. The presenter cannot
        fix that ordering from here, so it tells the user the save failed
        instead; a user-initiated click that silently does nothing is the bug.

        The report is a toast, never a dialog. spec §5 first filed this string
        under 错误, but it was never modal, and one failed settings write must not
        interrupt the whole window for it -- see the §5 correction in the spec.
        """
        if not self._config.set_theme(mode):
            self._view.show_toast(i18n.get('status.theme_save_failed'))

    def _handle_background_change(self, dialog: AppearanceDialog, path: str) -> None:
        """Handle background image change from dialog."""
        if path:
            self._config.set_background_image(path)
            self._view.set_background_image(path)
            self._view.show_toast(i18n.get('status.background_set'))
        else:
            self._config.set_background_image(None)
            self._view.set_background_image(None)
            self._view.show_toast(i18n.get('status.background_cleared'))

    def _handle_overlay_change(self, dialog: AppearanceDialog, alpha: float) -> None:
        """Handle overlay alpha change from dialog."""
        self._config.set_overlay_alpha(alpha)
        self._view.set_overlay_alpha(alpha)

    def _handle_playlist_alpha_change(self, dialog: AppearanceDialog, alpha: float) -> None:
        """Handle playlist alpha change from dialog."""
        self._config.set_playlist_alpha(alpha)
        self._view.set_playlist_alpha(alpha)

    def _handle_controls_alpha_change(self, dialog: AppearanceDialog, alpha: float) -> None:
        """Handle controls alpha change from dialog."""
        self._config.set_controls_alpha(alpha)
        self._view.set_controls_alpha(alpha)

    # === Service Signal Handlers ===

    @pyqtSlot(object)
    def _on_playback_state_changed(self, state: PlayerState) -> None:
        """Handle playback state change.

        The state goes to the transport button and nowhere else. spec §5 deleted
        the two strings this used to also report (``status.playing`` /
        ``status.paused``): a play/pause button whose glyph already changed is the
        same fact in the same place, and a text line repeating it is what criterion
        3 was written against.
        """
        is_playing = state == PlayerState.PLAYING
        is_paused = state == PlayerState.PAUSED

        self._view.set_playing_state(is_playing, is_paused)

        if is_playing:
            self._position_timer.start(self.POSITION_UPDATE_INTERVAL)
        elif is_paused:
            self._position_timer.stop()
        elif state == PlayerState.IDLE:
            self._position_timer.stop()

    @pyqtSlot(object)
    def _on_track_changed(self, track: Optional[Track]) -> None:
        """Handle track change."""
        if track is None:
            self._view.clear_now_playing()
            self._view.highlight_current_track(-1)
            return

        # Update UI with track info. The unknown title stays *empty* here:
        # ``NowPlayingStrip.update_track_info`` maps an empty title to
        # ``i18n.get('metadata.unknown_title')``. Pre-filling that copy in the
        # presenter used to jump over the view's fallback, so a zh_CN user saw
        # English in the headline (review finding 1: the view owns the
        # fallback, the presenter passes the raw data through).
        title = track.title if track.title else ""
        artist = track.artist if track.artist else ""
        album = track.album if track.album else ""

        self._view.update_track_info(title, artist, album)

        # Load metadata for album art
        self._metadata.load_async(track.path)

        # Update playlist highlight
        position = self._queue.get_current_position()
        if position.display_index >= 0:
            self._view.highlight_current_track(position.display_index)

        # And that is all of it. The old last line here reported
        # ``Now playing: {title}`` into the status channel: the strip two rows
        # above says the same thing in the place the user looks for it, so this
        # method now reports nothing (spec §5, 与控件重复的文本).

    @pyqtSlot()
    def _on_track_ended(self) -> None:
        """Handle track end - play next track."""
        # Check loop mode
        if self._queue.get_loop_mode() == "ONE":
            # Replay current track
            track = self._queue.get_current_track()
            if track:
                self._playback.play(track.path)
                return

        # Try next track
        track = self._queue.advance_to_next()
        if track:
            self._playback.play(track.path)
        else:
            # End of queue
            self._on_stop()
            self._view.show_toast(i18n.get('status.completed'))

    @pyqtSlot(float)
    def _on_volume_changed_from_service(self, volume: float) -> None:
        """Handle volume change from service."""
        self._view.set_volume(volume)

    @pyqtSlot(object)
    def _on_queue_position_changed(self, position: PlaybackPosition) -> None:
        """Handle queue position change."""
        if position.display_index >= 0:
            self._view.highlight_current_track(position.display_index)

    @pyqtSlot(list)
    def _on_display_changed(self, entries: List[QueueDisplayEntry]) -> None:
        """Handle display entries change from queue service.

        No conversion step: Task 2 merged the duplicate DTOs, so
        ``view.models.DisplayEntry is service.queue_service.DisplayEntry`` and
        rebuilding the list field-by-field only produced copies of objects the
        view was already free to read.
        """
        self._view.set_playlist_entries(entries)

    # === Metadata sweep wiring (batch 4, Task 7) ===
    #
    # The chain these eight methods form, in the order it runs:
    #
    #   scan -> ``_start_metadata_sweep`` -> ``_metadata_store_for`` (warm load)
    #        -> ``_metadata_plan`` (``validate`` + the ``(str, int, float)`` triples)
    #        -> ``QueueService.set_metadata`` (the columns as far as the cache knows them)
    #        -> ``MetadataService.start_sweep`` (background extraction)
    #        -> ``_on_metadata_row`` per answered row -> ``record`` -> ``apply_metadata``
    #        -> ``MainWindow.update_row_metadata`` -> ``_flush_metadata_cache`` by batch
    #        and once more when the plan's own deliveries reach its own ``len(targets)``.
    #
    # ``_cancel_metadata_sweep`` is the other way in, and the only one allowed to reorder
    # the two halves it calls (B4-R18).

    def _metadata_store_for(self, library_path: str) -> LibraryMetadataStore:
        """The store of one library: warm-loaded on sight, kept across a re-scan.

        Reuse is the point. ``load_cache_entries`` *replaces* the whole table, so
        reloading on every refresh would discard each row an earlier plan answered but a
        cancelled or superseded sweep never got as far as writing -- those files would be
        extracted again for nothing on the next scan. Keeping the store is also the only
        way ``take_dirty`` can answer a ``None`` at all (a row recorded here and
        invalidated by a later ``validate``), and that shape is what
        :meth:`_flush_metadata_cache` refuses to write (ruling B4-R10).

        A *different* library gets a fresh store: rows of the library being left must not
        be writable into this one's cache file (spec §10 risk 1).
        """
        store = self._metadata_store
        if store is not None and self._metadata_store_library == library_path:
            return store
        store = LibraryMetadataStore()
        store.load_cache_entries(self._library.get_cache_entries(library_path))
        self._metadata_store = store
        self._metadata_store_library = library_path
        return store

    @staticmethod
    def _numeric_pair(size_bytes, modified_time) -> Optional[Tuple[int, float]]:
        """One row's measured pair, or ``None`` when it is not a pair at all.

        The ``float()`` is the ruling (B4-R16), not a style choice: ``start_sweep``
        checks its payload strictly and refuses an ``int`` mtime, so a fingerprint that
        came back from a hand-edited (or externally written) cache as an integer would
        take the *whole* library's sweep down -- the symptom is three columns of ``⋯``
        forever, with nothing on screen saying why. The sweep's strictness stays where
        the review left it and the producer normalises instead.

        ``None`` for a value that is not a number at all, because such a row can be
        neither swept nor re-checked before a write: dropping it leaves that one row
        pending, which is the honest state, while raising would have cost the plan and an
        escaping exception from a slot would have cost the process.
        """
        try:
            return (int(size_bytes), float(modified_time))
        except (TypeError, ValueError):
            return None

    def _metadata_plan(self, store: LibraryMetadataStore, files: list) -> Tuple[
            List[Tuple[str, int, float]], Dict[str, Tuple[int, float]]]:
        """``(targets, fingerprints)`` for one scan -- the two halves of the pair rule.

        ``validate`` is the only place that decides what to extract: pending rows, rows
        whose fingerprint moved, and nothing else, with the excluded formats answered on
        the spot (so a ``.ncm`` row is never ``⋯``, and never a target either). It has to
        be asked before the columns are filled, because that record is the answer.

        The fingerprints are taken from the *same* file list as the triples, so every
        number this plan later compares against the disk is the one this scan measured
        (Task 3's "one instant" rule) rather than a re-stat three layers down -- and rows
        whose pair is not a number at all are missing from both halves, which is the only
        honest way to refuse them: no sweep, no write, still pending.
        """
        fingerprints: Dict[str, Tuple[int, float]] = {}
        for media in files:
            pair = self._numeric_pair(media.size_bytes, media.modified_time)
            if pair is not None:
                fingerprints[media.path] = pair

        targets: List[Tuple[str, int, float]] = []
        for full_path, size_bytes, modified_time in store.validate(files):
            pair = self._numeric_pair(size_bytes, modified_time)
            if pair is not None:
                targets.append((full_path, pair[0], pair[1]))
        return targets, fingerprints

    def _start_metadata_sweep(self, files: list) -> int:
        """Fill the rows from the cache, then schedule what the cache does not know.

        Returns the generation this plan runs under, or -1 when nothing was started. The
        value is the caller's to compare with ``current_generation()`` later (the brief's
        interface), and -1 is what makes "there is no live plan" distinguishable from the
        first real generation, which is 1.

        Three things about the order, all measured rather than assumed:

        * ``set_metadata`` before anything is pushed. A rebuild is where the queue's
          table reaches the rows, and a re-push at an unchanged row count repaints
          nothing (``tests/test_metadata_wiring.py`` pins both halves), so a later fill
          would be readable and invisible.
        * the counters are installed *before* ``start_sweep``, never after a callback:
          one of the five completion conditions is that a delivery can arrive as soon as
          the plan exists.
        * ``start_sweep`` is called even for an empty plan, because taking a generation
          is what retires the rows the previous plan left in flight (§5.1's fourth
          condition). ``start_sweep`` itself validates the whole list before queuing
          anything (ruling B4-R14) and *raises* in this thread when it refuses -- which
          is why the call sits inside the guard below rather than beside it.
        * an empty plan is flushed *here*, because it is the one plan that can never be
          flushed by ``_on_metadata_row``: with no targets there is no delivery, and the
          closing write-back is keyed to "every target came back". Spec §4.1's invariant
          is ``md`` missing ⟺ something is waiting to fetch it, so a library whose rows
          were all answered on the spot -- an all-``.ncm`` library, where ``validate``
          records "tried, nothing" itself -- would otherwise re-record the same answer on
          every start and never persist it. An *already warm* library is not a write: the
          rows ``validate`` left alone are not dirty, so ``take_dirty`` answers empty and
          :meth:`_flush_metadata_cache` saves nothing (criterion 6).

        A failure here is a library whose columns stay ``⋯``, so the except is not a
        courtesy: ``_on_library_loaded`` is a slot, and an exception leaving one on this
        host is ``qFatal``, not a traceback. Everything the failure touches is put back
        the way ``_cancel_metadata_sweep`` wants it found -- nothing live, nothing stale.
        """
        library_path = self._metadata_library_path
        try:
            store = self._metadata_store_for(library_path)
            targets, fingerprints = self._metadata_plan(store, files)
            mapping = {media.path: store.get(media.path) for media in files}
            self._queue.set_metadata(mapping)
            self._metadata_fingerprints = fingerprints
            self._metadata_expected = len(targets)
            self._metadata_delivered = 0
            self._metadata_since_flush = 0
            generation = self._metadata.start_sweep(targets, self._on_metadata_row)
            self._metadata_generation = generation
            if not targets:
                self._flush_metadata_cache()
            return generation
        except Exception as exc:
            print(f'PyPlayer: metadata for {library_path} was not scheduled: {exc}')
            self._cancel_metadata_sweep()
            return -1

    def _cancel_metadata_sweep(self) -> None:
        """Retire the live plan, then wipe the rows -- in that order (B4-R18).

        ``cancel_sweep`` is the only drop point (the service's generation comparison, and
        deliberately nothing else), so it has to run first; the wipe that follows is what
        makes sure that nothing which *did* arrive is still painted on rows that now
        belong to another library. ``QueueService.clear`` keeps the table by design
        (ruling B4-R18 says that is correct behaviour, not a gap), so ``set_metadata({})``
        is the only thing that empties it -- and a library switch that shows an empty file
        list never rebuilds the queue at all, which is why this half is unconditional.

        The counters go with the plan they counted: a retired plan delivers nothing, not
        "the rest of its rows", and a count carried over would let the next plan declare
        itself finished before its own work landed.
        """
        self._metadata.cancel_sweep()
        self._queue.set_metadata({})
        self._metadata_store = None
        self._metadata_store_library = ''
        self._metadata_generation = -1
        self._metadata_expected = 0
        self._metadata_delivered = 0
        self._metadata_since_flush = 0
        self._metadata_fingerprints = {}

    def _on_metadata_row(self, full_path: str, md: Optional[RowMetadata],
                         size: int, mtime: float) -> None:
        """One answered row: record it, repaint it, and flush when a batch is full.

        Called by ``MetadataService._deliver_sweep_row`` -- on the GUI thread, once per
        target of the live plan, with that target's own fingerprint.

        **It may not raise.** On this host (PyQt6 6.11) an exception leaving a pool
        worker's ``run`` aborts the process -- exit 127, no traceback, not even the
        runner's ``Ran`` line -- and the broad ``except`` on the delivery side only
        covers the ``emit``, not this callback. So the row work is guarded here, and
        :meth:`_flush_metadata_cache` guards its own disk access: a failed repaint costs
        one row and a failed write costs one batch, never the player.

        Record, then read back from the store, then repaint -- in that order, because the
        store is what normalizes the duration (ruling B4-R7). Handing ``md`` straight to
        the rows would put ``0.0`` on screen as ``0:00`` and disagree with the state word
        the same row carries.

        The trailing counter/flush block is *outside* the ``try`` on purpose: the write
        back must happen for a row whose repaint failed (the answer is real whether or not
        a widget was listening), and neither the arithmetic nor ``_flush_metadata_cache``
        can raise.
        """
        store = self._metadata_store
        if store is None:
            return
        if self._metadata_generation != self._metadata.current_generation():
            # The service already refused this row; the question asked here is about the
            # *counters*, which are this file's invention: a delivery of a retired plan
            # must not be added to the live plan's total (report §5.1's second condition)
            # and must not be recorded into the store of the library the user switched to.
            return
        try:
            store.record(full_path, md, size, mtime)
            self._metadata_fingerprints[full_path] = (size, mtime)
            row = store.get(full_path)
            state = store.state_of(full_path)
            # ``apply_metadata`` returns the rows it wrote, and only they get repainted:
            # the model shares the entry objects with the queue, so re-pushing the whole
            # table would let the new values be read and never drawn (fact 1 in the report).
            for display_row in self._queue.apply_metadata(full_path, row, state):
                self._view.update_row_metadata(display_row, row, state)
        except Exception as exc:
            print(f'PyPlayer: metadata row {full_path} was not applied: {exc}')

        self._metadata_delivered += 1
        self._metadata_since_flush += 1
        if (self._metadata_since_flush >= METADATA_WRITE_BATCH
                or self._metadata_delivered >= self._metadata_expected):
            self._flush_metadata_cache()

    def _fingerprint_still_current(self, full_path: str,
                                   pair: Tuple[int, float]) -> bool:
        """Whether the file on disk is still the one the stored answer describes.

        Review Focus 1: a file deleted or rewritten between the scan and the write-back
        must not have its metadata persisted, because the pair written beside it would
        claim a version nothing extracted. ``False`` also covers "cannot be stat'ed" --
        an unreadable file is not going into the cache either -- and leaves the cached
        entry exactly as it was, which is what makes the next scan ask for it again.
        """
        try:
            stat = os.stat(full_path)
        except OSError:
            return False
        return (stat.st_size, stat.st_mtime) == pair

    def _flush_metadata_cache(self) -> None:
        """Write the rows answered since the last flush, in one save -- or in no save.

        Three rules, all about the file rather than the rows:

        * **Only what the store says was answered.** ``take_dirty`` hands back
          ``(path, md | None)``, and a ``None`` is a row that went back to pending (a
          later ``validate`` invalidated one that had not been flushed yet). It must not
          be offered at all: writing it would either drop an answer the disk still
          supports or advance a fingerprint beside a payload that does not describe it,
          and either way the invalidation stops being re-fetchable after a restart
          (ruling B4-R10 -- this is the branch its ``dict | None`` was kept for).
        * **Re-checked against the disk, one row at a time.** The pair in
          ``_metadata_fingerprints`` is the instant the scan measured; a row the file has
          moved past is skipped, and so is a row this plan has no pair for (a leftover of
          a retired plan, which the store still holds an answer for). Skipping costs a
          re-extraction after a restart and nothing else.
        * **Never a row the cache file does not list.** The writer stamps paths it finds
          and invents none, so an answer for a file outside this library's table cannot
          become a row of it.

        Batching is why this exists: ``save_cache`` rewrites the whole document, so one
        call per row would make a sweep quadratic in the library size (spec §4.4, §10
        risk 2). A failed write leaves the in-memory rows and the repaints standing --
        spec §6's third item, with no new error channel -- and costs that batch's
        persistence, which is exactly the work the next start does again.
        """
        store = self._metadata_store
        library_path = self._metadata_store_library
        self._metadata_since_flush = 0
        if store is None or not library_path:
            return

        updates: Dict[str, Tuple[dict, int, float]] = {}
        for full_path, md in store.take_dirty():
            if md is None:
                continue
            pair = self._metadata_fingerprints.get(full_path)
            if pair is None or not self._fingerprint_still_current(full_path, pair):
                continue
            updates[full_path] = (md, pair[0], pair[1])
        if not updates:
            return

        try:
            self._library.save_cache_metadata(library_path, updates)
        except Exception as exc:
            print(f'PyPlayer: metadata cache write for {library_path} failed: {exc}')

    @pyqtSlot(str, object)
    def _on_metadata_loaded(self, filepath: str, metadata) -> None:
        """Handle metadata loaded."""
        # Check if this is for current track
        current = self._playback.current_track
        if current and current.path == filepath:
            self._view.update_track_info(
                metadata.title,
                metadata.artist,
                metadata.album
            )
            # If no album art, show default cover immediately
            if not metadata.album_art:
                self._view.update_album_art(None)

    @pyqtSlot(str, bytes)
    def _on_album_art_loaded(self, filepath: str, art_data: bytes) -> None:
        """Handle album art loaded."""
        current = self._playback.current_track
        if current and current.path == filepath:
            self._view.update_album_art(art_data)

    @pyqtSlot(str, list)
    def _on_library_loaded(self, library_path: str, files: list) -> None:
        """Handle library loaded - build queue from files."""
        if not files:
            return

        # Set library path for NCM proxy support
        self._playback.set_library_path(library_path)

        # Set as current library if this is the first one loaded
        if not self._current_library_path:
            self._current_library_path = library_path
            self._view.set_current_library(library_path)

        # Convert MediaFile objects to Tracks
        tracks = []
        for media_file in files:
            track = Track(
                path=media_file.path,
                title=media_file.title
            )
            tracks.append(track)

        # Set current library BEFORE building queue so display optimization works
        self._queue.set_current_library(library_path)
        # Batch 4, Task 7: fill the columns from the cache and schedule what is missing
        # *before* the table is pushed. That order is not cosmetic -- rebuilding the
        # display is the only place the queue's row table reaches the rows (spec §4.9),
        # and at an unchanged row count the model compares only display text and the
        # playing flag, so a fill that came after the push would be readable and unpainted.
        self._metadata_library_path = library_path
        self._start_metadata_sweep(files)
        # Build queue from tracks
        self._queue.build_from_tracks(tracks)

        # Report the count. The rows themselves are the result the user can see,
        # so this says only what the list cannot: how many tracks arrived.
        self._view.show_toast(i18n.get('status.tracks_loaded', count=len(tracks)))

    def _update_position(self) -> None:
        """Update progress display (called by timer)."""
        if self._playback.is_playing and not self._playback.is_paused:
            position = self._playback.get_position()
            duration = self._playback.get_duration()
            self._view.update_progress(position, duration)

    # === Public API ===

    def start(self) -> None:
        """Start the presenter - begin any necessary updates."""
        # Load default volume
        self._view.set_volume(self._playback.get_volume())

        # Start position timer if playing
        if self._playback.is_playing:
            self._position_timer.start(self.POSITION_UPDATE_INTERVAL)

    def stop(self) -> None:
        """Stop the presenter - cleanup."""
        self._position_timer.stop()
        self._playback.stop()


def _basename(path: str) -> str:
    """Last component of a library path, for copy that names an unnamed library.

    Deliberately a second copy of the same six lines
    :mod:`view.widgets.library_sidebar` keeps: the two callers answer the same
    question for the same object (what a library row is *called* when its config
    has no name), and the alternative was the presenter importing a private out of
    the view it is supposed to stay above. The separator sniff is the part that
    cannot be a one-liner -- ``PurePosixPath('C:\\\\music').name`` is the whole
    string, not ``music``.
    """
    if not path:
        return ''
    pure = PureWindowsPath(path) if '\\' in path or ':' in path[:3] else PurePosixPath(path)
    return pure.name or str(pure)
