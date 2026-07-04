#!/usr/bin/env python3
"""
Main Window - Primary application window
Assembles all UI components and provides the public View interface
"""

from typing import Optional, List, Any
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMenuBar, QMenu, QToolBar, QFileDialog, QMessageBox,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QRect
from PyQt6.QtGui import QAction, QKeySequence, QCloseEvent, QPixmap, QPainter, QColor

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import i18n
from view.widgets import NowPlayingPanel, PlaylistView, BottomPanel
from view.models import PlaylistModel, DisplayEntry
from core.constants import AppearanceDefaults


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
    manage_libraries_requested = pyqtSignal()   # open library management dialog
    manage_appearance_requested = pyqtSignal()  # open appearance settings dialog
    background_image_changed = pyqtSignal(str)  # background image path

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Ensure i18n is initialized
        i18n.detect_init()

        # Current library tracking
        self._current_library_path: str = ""
        self._libraries: List[Any] = []

        # Background image for custom painting
        self._background_pixmap: Optional[QPixmap] = None
        self._overlay_alpha: float = AppearanceDefaults.BACKGROUND_OVERLAY_ALPHA

        self._setup_window()
        self._setup_menu()
        self._setup_ui()
        self._setup_connections()

    def _setup_window(self) -> None:
        """Set up window properties."""
        self.setWindowTitle(i18n.get('window.title'))

        # Size window relative to available screen space
        app = QApplication.instance()
        if app and app.primaryScreen():
            screen_geom = app.primaryScreen().availableGeometry()
            target_w = min(max(int(screen_geom.width() * 0.8), 800), 1400)
            target_h = min(max(int(screen_geom.height() * 0.75), 500), 900)
            target_x = screen_geom.x() + (screen_geom.width() - target_w) // 2
            target_y = screen_geom.y() + (screen_geom.height() - target_h) // 2
            self.setGeometry(target_x, target_y, target_w, target_h)
        else:
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

        manage_libraries_action = QAction(i18n.get('menu.manage_libraries'), self)
        manage_libraries_action.triggered.connect(self.manage_libraries_requested.emit)
        file_menu.addAction(manage_libraries_action)

        file_menu.addSeparator()

        refresh_library_action = QAction(i18n.get('menu.refresh_library'), self)
        refresh_library_action.triggered.connect(self._on_refresh_library)
        file_menu.addAction(refresh_library_action)

        refresh_all_action = QAction(i18n.get('menu.refresh_all'), self)
        refresh_all_action.triggered.connect(self._on_refresh_all)
        file_menu.addAction(refresh_all_action)

        file_menu.addSeparator()

        appearance_action = QAction(i18n.get('menu.appearance', default='外观设置'), self)
        appearance_action.triggered.connect(self.manage_appearance_requested.emit)
        file_menu.addAction(appearance_action)

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

        # Left panel - Now Playing (fixed size)
        self._now_playing = NowPlayingPanel()
        self._now_playing.setMinimumWidth(250)
        self._now_playing.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
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

        # Make splitter handle resizable but keep now playing fixed
        splitter.setStretchFactor(0, 0)  # Now playing doesn't stretch
        splitter.setStretchFactor(1, 1)  # Playlist stretches

        main_layout.addWidget(splitter, stretch=1)

        # Bottom panel - Combined progress and controls
        self._bottom_panel = BottomPanel()
        main_layout.addWidget(self._bottom_panel)

        # Store base window title for status updates
        self._base_title = i18n.get('window.title')
        self.setWindowTitle(self._base_title)

    def _setup_connections(self) -> None:
        """Connect internal widget signals to main window signals."""
        # Bottom panel connections
        self._bottom_panel.play_pause_clicked.connect(self.play_pause_requested.emit)
        self._bottom_panel.stop_clicked.connect(self.stop_requested.emit)
        self._bottom_panel.next_clicked.connect(self.next_track_requested.emit)
        self._bottom_panel.prev_clicked.connect(self.prev_track_requested.emit)
        self._bottom_panel.volume_changed.connect(self.volume_changed.emit)
        self._bottom_panel.loop_mode_changed.connect(self.loop_mode_changed.emit)
        self._bottom_panel.seek_requested.connect(self.seek_requested.emit)

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

    def _on_set_background(self) -> None:
        """Handle set background image action."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            i18n.get('dialog.select_background', default='选择背景图片'),
            "",
            i18n.get('dialog.image_files', default='图片文件') + " (*.jpg *.jpeg *.png *.bmp *.gif *.webp)"
        )
        if file_path:
            self.set_background_image(file_path)
            self.background_image_changed.emit(file_path)

    def _on_clear_background(self) -> None:
        """Handle clear background image action."""
        self.set_background_image(None)
        self.background_image_changed.emit("")

    def _check_background_image(self, config) -> None:
        """
        Check if configured background image exists.
        Show warning and clear config if file not found.

        Args:
            config: SettingsManager instance
        """
        bg_path = config.get_background_image()
        if bg_path and not os.path.exists(bg_path):
            QMessageBox.warning(
                self,
                i18n.get('dialog.title.warning', default='警告'),
                i18n.get('warning.background_not_found', default='背景图片文件不存在，已恢复默认背景')
            )
            config.set_background_image(None)

    def set_background_image(self, path: Optional[str]) -> None:
        """
        Set the background image for the main window.
        Uses aspect ratio preserving scale, fitting the shorter edge.

        Args:
            path: Path to the background image, or None to clear.
        """
        if path and os.path.exists(path):
            self._background_pixmap = QPixmap(path)
            self.update()  # Trigger repaint
        else:
            # Clear background, restore default
            self._background_pixmap = None
            self.update()

    def set_overlay_alpha(self, alpha: float) -> None:
        """Set the background overlay transparency."""
        self._overlay_alpha = alpha
        self.update()  # Trigger repaint

    def paintEvent(self, event) -> None:
        """Override paint event to draw scaled background image with semi-transparent overlay."""
        super().paintEvent(event)

        if self._background_pixmap and not self._background_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Restrict painting to the content area (central widget), avoiding the
            # native title bar on macOS and window frame area on all platforms.
            cw = self.centralWidget()
            if cw:
                content_rect = QRect(cw.mapTo(self, cw.rect().topLeft()), cw.size())
            else:
                content_rect = self.rect()
            pixmap_size = self._background_pixmap.size()

            # Calculate scale factor to fit the shorter edge
            scale_x = content_rect.width() / pixmap_size.width()
            scale_y = content_rect.height() / pixmap_size.height()
            scale = max(scale_x, scale_y)  # Use larger scale to cover window

            # Calculate scaled dimensions
            scaled_width = int(pixmap_size.width() * scale)
            scaled_height = int(pixmap_size.height() * scale)

            # Center the image within the content area
            x = content_rect.x() + (content_rect.width() - scaled_width) // 2
            y = content_rect.y() + (content_rect.height() - scaled_height) // 2

            # Draw scaled pixmap centered
            target_rect = QRect(x, y, scaled_width, scaled_height)
            painter.drawPixmap(target_rect, self._background_pixmap)

            # Draw semi-transparent overlay using configured alpha
            # Convert 0.0-1.0 to 0-255
            alpha_int = int(self._overlay_alpha * 255)
            painter.fillRect(content_rect, QColor(255, 255, 255, alpha_int))

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
        self._bottom_panel.update_progress(position, duration)

    def set_playing_state(self, is_playing: bool, is_paused: bool = False) -> None:
        """Update the play/pause button state."""
        self._bottom_panel.set_playing_state(is_playing, is_paused)

    def set_volume(self, volume: float) -> None:
        """Set the volume slider."""
        self._bottom_panel.set_volume(volume)

    def set_loop_mode(self, mode: str) -> None:
        """Set the loop mode button."""
        self._bottom_panel.set_loop_mode(mode)

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
        """Update window title with status message."""
        if message:
            self.setWindowTitle(f"{self._base_title} - {message}")
        else:
            self.setWindowTitle(self._base_title)

    def reset_progress(self) -> None:
        """Reset the progress slider."""
        self._bottom_panel.reset_progress()

    def set_playlist_alpha(self, alpha: float) -> None:
        """Set playlist background transparency."""
        self._playlist_view.set_bg_alpha(alpha)

    def set_controls_alpha(self, alpha: float) -> None:
        """Set bottom panel background transparency."""
        self._bottom_panel.set_bg_alpha(alpha)

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
