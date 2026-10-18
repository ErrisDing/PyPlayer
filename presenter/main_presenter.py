#!/usr/bin/env python3
"""
Main Presenter - Coordinates View and Service layers
Implements MVP pattern for clean separation of concerns
"""

from typing import Optional, List
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
from service.config_service import ConfigService

from core import i18n
from core.player import PlayerState
from core.library_manager import Track


class MainPresenter(QObject):
    """
    Main presenter coordinating all UI and business logic.

    Responsibilities:
    - Connect View signals to Service methods
    - Update View based on Service state changes
    - Handle track end events and navigation
    - Manage playback position updates
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
            import os
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

    @pyqtSlot(str)
    def _on_scan_folder(self, folder: str) -> None:
        """Handle scan folder request."""
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
        """Handle library selection from UI."""
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
