#!/usr/bin/env python3
"""
Main Presenter - Coordinates View and Service layers
Implements MVP pattern for clean separation of concerns
"""

from typing import Optional, List, TYPE_CHECKING
from PyQt6.QtCore import QObject, QTimer, pyqtSlot

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from view.main_window import MainWindow
from view.models import DisplayEntry
from view.dialogs import LibraryManagementDialog
from service.playback_service import PlaybackService

if TYPE_CHECKING:
    pass
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
        parent: Optional[QObject] = None
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

        # Library management
        self._view.add_library_requested.connect(self._on_add_library)
        self._view.scan_folder_requested.connect(self._on_scan_folder)
        self._view.refresh_library_requested.connect(self._on_refresh_library)
        self._view.refresh_all_requested.connect(self._on_refresh_all)
        self._view.library_selected.connect(self._on_library_selected)
        self._view.manage_libraries_requested.connect(self._on_manage_libraries)

        # Background image
        self._view.background_image_changed.connect(self._on_background_image_changed)

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
    def _on_add_library(self, path: str) -> None:
        """Handle add library request."""
        if self._config.add_library(path):
            self._library.load_library(path)
            # Refresh library list in UI
            libraries = self._config.get_libraries()
            self._view.set_libraries(libraries)
            self._view.set_status_message(f"Added library: {path}")

    @pyqtSlot(str)
    def _on_scan_folder(self, folder: str) -> None:
        """Handle scan folder request."""
        self._library.load_library(folder)

    @pyqtSlot(str)
    def _on_refresh_library(self, library_path: str) -> None:
        """Handle refresh library request."""
        self._view.set_status_message(i18n.get('status.refreshing'))
        files = self._library.refresh_library(library_path)
        if files:
            self._view.set_status_message(
                i18n.get('status.library_refreshed').format(name=library_path)
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
        """Handle refresh all libraries request."""
        self._view.set_status_message(i18n.get('status.refresh_all'))
        results = self._library.refresh_all_libraries()
        total_files = sum(len(files) for files in results.values())
        self._view.set_status_message(f"Refreshed {total_files} files from {len(results)} libraries")

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
            self._view.set_status_message(f"Switched to library: {library_path}")

    @pyqtSlot()
    def _on_manage_libraries(self) -> None:
        """Handle manage libraries menu action - open dialog."""
        libraries = self._config.get_libraries()
        dialog = LibraryManagementDialog(libraries, self._view)

        # Connect dialog signals with dialog reference for refresh
        dialog.add_library_requested.connect(lambda path: self._handle_add_library_dialog(dialog, path))
        dialog.remove_library_requested.connect(lambda path: self._handle_remove_library_dialog(dialog, path))
        dialog.reorder_requested.connect(lambda old, new: self._handle_reorder_library_dialog(dialog, old, new))

        # Show dialog
        dialog.exec()

    def _handle_add_library_dialog(self, dialog: LibraryManagementDialog, path: str) -> None:
        """Handle add library from dialog."""
        if self._config.add_library(path):
            self._library.load_library(path)
            # Refresh both main window and dialog
            libraries = self._config.get_libraries()
            self._view.set_libraries(libraries)
            dialog.set_libraries(libraries)

    def _handle_remove_library_dialog(self, dialog: LibraryManagementDialog, library_path: str) -> None:
        """Handle library removal from dialog."""
        if self._config.remove_library(library_path):
            # Refresh both main window and dialog
            libraries = self._config.get_libraries()
            self._view.set_libraries(libraries)
            dialog.set_libraries(libraries)
            self._view.set_status_message(i18n.get('status.library_removed', default=f"Library removed: {library_path}"))

    def _handle_reorder_library_dialog(self, dialog: LibraryManagementDialog, old_index: int, new_index: int) -> None:
        """Handle library reorder from dialog."""
        if self._config.reorder_library(old_index, new_index):
            # Refresh both main window and dialog
            libraries = self._config.get_libraries()
            self._view.set_libraries(libraries)
            dialog.set_libraries(libraries)

    @pyqtSlot(str)
    def _on_background_image_changed(self, path: str) -> None:
        """Handle background image change from UI."""
        if path:
            self._config.set_background_image(path)
            self._view.set_status_message(i18n.get('status.background_set', default='背景图片已设置'))
        else:
            self._config.set_background_image(None)
            self._view.set_status_message(i18n.get('status.background_cleared', default='背景图片已清除'))

    # === Service Signal Handlers ===

    @pyqtSlot(object)
    def _on_playback_state_changed(self, state: PlayerState) -> None:
        """Handle playback state change."""
        is_playing = state == PlayerState.PLAYING
        is_paused = state == PlayerState.PAUSED

        self._view.set_playing_state(is_playing, is_paused)

        if is_playing:
            self._position_timer.start(self.POSITION_UPDATE_INTERVAL)
            self._view.set_status_message(i18n.get('status.playing'))
        elif is_paused:
            self._position_timer.stop()
            self._view.set_status_message(i18n.get('status.paused'))
        elif state == PlayerState.IDLE:
            self._position_timer.stop()

    @pyqtSlot(object)
    def _on_track_changed(self, track: Optional[Track]) -> None:
        """Handle track change."""
        if track is None:
            self._view.clear_now_playing()
            self._view.highlight_current_track(-1)
            return

        # Update UI with track info
        title = track.title if track.title else "Unknown Title"
        artist = track.artist if track.artist else ""
        album = track.album if track.album else ""

        self._view.update_track_info(title, artist, album)

        # Load metadata for album art
        self._metadata.load_async(track.path)

        # Update playlist highlight
        position = self._queue.get_current_position()
        if position.display_index >= 0:
            self._view.highlight_current_track(position.display_index)

        # Update status
        self._view.set_status_message(f"Now playing: {title}")

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
            self._view.set_status_message(i18n.get('status.completed'))

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
        """Handle display entries change from queue service."""
        # Convert to view model DisplayEntry
        view_entries = []
        for entry in entries:
            view_entry = DisplayEntry(
                display_text=entry.display_text,
                node_idx=entry.node_idx,
                is_folder=entry.is_folder,
                path=entry.path,
                sub_index=entry.sub_index,
                full_path=entry.full_path,
                is_playing=entry.is_playing,
                relative_position=entry.relative_position
            )
            view_entries.append(view_entry)

        self._view.set_playlist_entries(view_entries)

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

        # Update status
        self._view.set_status_message(f"Loaded {len(tracks)} tracks from library")

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
