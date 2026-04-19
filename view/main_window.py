#!/usr/bin/env python3
"""
Main Window - Primary application window
Assembles all UI components and provides the public View interface
"""

from typing import Optional, List, Any
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMenuBar, QMenu, QToolBar, QStatusBar, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QKeySequence, QCloseEvent

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import i18n
from view.widgets import NowPlayingPanel, PlaylistView, ProgressSlider, ControlPanel
from view.models import PlaylistModel, DisplayEntry


class MainWindow(QMainWindow):
    """
    Main application window implementing the View layer.

    Features:
    - Clean separation of UI from business logic
    - Signals for all user actions
    - Public API for Presenter to update UI
    """

    # === User Action Signals ===
    # These signals are emitted when the user performs actions
    play_pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    next_track_requested = pyqtSignal()
    prev_track_requested = pyqtSignal()
    seek_requested = pyqtSignal(float)          # position in seconds
    volume_changed = pyqtSignal(float)          # 0.0 - 1.0
    loop_mode_changed = pyqtSignal(str)         # "OFF", "ONE", "ALL"
    track_double_clicked = pyqtSignal(int)      # display index
    add_library_requested = pyqtSignal(str)     # library path
    remove_library_requested = pyqtSignal(str)  # library path
    refresh_library_requested = pyqtSignal(str) # library path
    refresh_all_requested = pyqtSignal()        # refresh all libraries
    scan_folder_requested = pyqtSignal(str)     # folder path
    library_selected = pyqtSignal(str)          # library path selected

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Ensure i18n is initialized
        i18n.detect_init()

        # Current library tracking
        self._current_library_path: str = ""
        self._libraries: List[Any] = []

        self._setup_window()
        self._setup_menu()
        self._setup_ui()
        self._setup_connections()

    def _setup_window(self) -> None:
        """Set up window properties."""
        self.setWindowTitle(i18n.get('window.title'))
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(800, 500)

    def _setup_menu(self) -> None:
        """Set up menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(i18n.get('menu.file'))

        open_action = QAction(i18n.get('menu.open'), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_open_file)
        file_menu.addAction(open_action)

        open_folder_action = QAction(i18n.get('menu.open_folder'), self)
        open_folder_action.triggered.connect(self._on_open_folder)
        file_menu.addAction(open_folder_action)

        file_menu.addSeparator()

        add_library_action = QAction(i18n.get('menu.add_library'), self)
        add_library_action.triggered.connect(self._on_add_library)
        file_menu.addAction(add_library_action)

        refresh_library_action = QAction(i18n.get('menu.refresh_library'), self)
        refresh_library_action.triggered.connect(self._on_refresh_library)
        file_menu.addAction(refresh_library_action)

        refresh_all_action = QAction(i18n.get('menu.refresh_all'), self)
        refresh_all_action.triggered.connect(self._on_refresh_all)
        file_menu.addAction(refresh_all_action)

        file_menu.addSeparator()

        exit_action = QAction(i18n.get('menu.exit'), self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu(i18n.get('menu.help'))

        about_action = QAction(i18n.get('menu.about'), self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _setup_ui(self) -> None:
        """Set up the main UI layout."""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout with splitter
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Horizontal splitter for now playing and playlist
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Now Playing
        self._now_playing = NowPlayingPanel()
        self._now_playing.setMinimumWidth(250)
        splitter.addWidget(self._now_playing)

        # Right panel - Playlist
        playlist_container = QWidget()
        playlist_layout = QVBoxLayout(playlist_container)
        playlist_layout.setContentsMargins(0, 0, 0, 0)
        playlist_layout.setSpacing(0)

        self._playlist_view = PlaylistView()
        playlist_layout.addWidget(self._playlist_view)

        splitter.addWidget(playlist_container)

        # Set initial sizes (30% now playing, 70% playlist)
        splitter.setSizes([300, 700])

        main_layout.addWidget(splitter, stretch=1)

        # Bottom panel - Progress and Controls
        bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        # Progress slider
        self._progress_slider = ProgressSlider()
        bottom_layout.addWidget(self._progress_slider)

        # Control panel
        self._control_panel = ControlPanel()
        bottom_layout.addWidget(self._control_panel)

        main_layout.addWidget(bottom_panel)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(i18n.get('status.ready'))

    def _setup_connections(self) -> None:
        """Connect internal widget signals to main window signals."""
        # Control panel connections
        self._control_panel.play_pause_clicked.connect(self.play_pause_requested.emit)
        self._control_panel.stop_clicked.connect(self.stop_requested.emit)
        self._control_panel.next_clicked.connect(self.next_track_requested.emit)
        self._control_panel.prev_clicked.connect(self.prev_track_requested.emit)
        self._control_panel.volume_changed.connect(self.volume_changed.emit)
        self._control_panel.loop_mode_changed.connect(self.loop_mode_changed.emit)

        # Progress slider connections
        self._progress_slider.seek_requested.connect(self.seek_requested.emit)

        # Playlist connections
        self._playlist_view.track_double_clicked.connect(self.track_double_clicked.emit)

        # Now playing panel connections
        self._now_playing.library_selected.connect(self._on_library_selected)

    # === Menu handlers ===

    def _on_open_file(self) -> None:
        """Handle open file action."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            i18n.get('dialog.open_file'),
            "",
            i18n.get('dialog.audio_files') + " (*.mp3 *.wav *.flac *.ogg *.m4a *.aac)"
        )
        if files:
            # Emit signal for first file, or add all to playlist
            if len(files) == 1:
                self.scan_folder_requested.emit(str(Path(files[0]).parent))
            else:
                # Add all files - for now just play first
                self.scan_folder_requested.emit(str(Path(files[0]).parent))

    def _on_open_folder(self) -> None:
        """Handle open folder action."""
        folder = QFileDialog.getExistingDirectory(
            self,
            i18n.get('dialog.open_folder')
        )
        if folder:
            self.scan_folder_requested.emit(folder)

    def _on_add_library(self) -> None:
        """Handle add library action."""
        folder = QFileDialog.getExistingDirectory(
            self,
            i18n.get('dialog.add_library')
        )
        if folder:
            self.add_library_requested.emit(folder)

    def _on_refresh_library(self) -> None:
        """Handle refresh library action."""
        # Emit signal with current library path if available
        if self._current_library_path:
            self.refresh_library_requested.emit(self._current_library_path)

    def _on_refresh_all(self) -> None:
        """Handle refresh all libraries action."""
        self.refresh_all_requested.emit()

    def _on_library_selected(self, library_path: str) -> None:
        """Handle library selection from now playing panel."""
        self._current_library_path = library_path
        self.library_selected.emit(library_path)

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            i18n.get('dialog.about.title'),
            i18n.get('dialog.about.text')
        )

    # === Public API for Presenter ===

    def set_libraries(self, libraries: List[Any]) -> None:
        """
        Set the list of available libraries for the selector.

        Args:
            libraries: List of LibraryConfig objects
        """
        self._libraries = libraries
        self._now_playing.set_libraries(libraries)

    def set_current_library(self, library_path: str) -> None:
        """
        Set the current active library.

        Args:
            library_path: Path to the current library
        """
        self._current_library_path = library_path
        self._now_playing.set_current_library(library_path)

    def update_track_info(self, title: str, artist: str = "", album: str = "") -> None:
        """Update the now playing info display."""
        self._now_playing.update_track_info(title, artist, album)

    def update_album_art(self, art_data: Optional[bytes]) -> None:
        """Update the album art display."""
        self._now_playing.update_album_art(art_data)

    def update_progress(self, position: float, duration: float) -> None:
        """Update the progress slider."""
        self._progress_slider.update_progress(position, duration)

    def set_playing_state(self, is_playing: bool, is_paused: bool = False) -> None:
        """Update the play/pause button state."""
        self._control_panel.set_playing_state(is_playing, is_paused)

    def set_volume(self, volume: float) -> None:
        """Set the volume slider."""
        self._control_panel.set_volume(volume)

    def set_loop_mode(self, mode: str) -> None:
        """Set the loop mode button."""
        self._control_panel.set_loop_mode(mode)

    def highlight_current_track(self, display_idx: int) -> None:
        """Highlight the currently playing track in the playlist."""
        self._playlist_view.set_current_playing(display_idx)

    def set_playlist_entries(self, entries: List[DisplayEntry]) -> None:
        """Set the playlist entries."""
        self._playlist_view.set_entries(entries)

    def clear_playlist(self) -> None:
        """Clear the playlist."""
        self._playlist_view.clear()

    def clear_now_playing(self) -> None:
        """Clear the now playing display."""
        self._now_playing.clear()

    def set_status_message(self, message: str) -> None:
        """Set the status bar message."""
        self._status_bar.showMessage(message)

    def reset_progress(self) -> None:
        """Reset the progress slider."""
        self._progress_slider.reset()

    def show_error(self, title: str, message: str) -> None:
        """Show an error dialog."""
        QMessageBox.critical(self, title, message)

    def show_info(self, title: str, message: str) -> None:
        """Show an info dialog."""
        QMessageBox.information(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        # Could emit a signal for presenter to save state
        event.accept()
