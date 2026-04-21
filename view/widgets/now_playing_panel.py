#!/usr/bin/env python3
"""
Now Playing Panel - Displays current track info and album art
"""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage

import sys
from pathlib import Path

# Project root path (for sys.path)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.resource_utils import get_resource_path
DEFAULT_COVER_PATH = get_resource_path("resource/default_cover.png")

from view.widgets.library_selector import LibrarySelector

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import io


class NowPlayingPanel(QWidget):
    """
    Panel showing current track information and album art.

    Features:
    - Album art display with aspect ratio preservation
    - Track title, artist, album display
    - Library selector for switching between libraries
    - Placeholder when no track playing
    """

    # Signals
    art_clicked = pyqtSignal()
    library_selected = pyqtSignal(str)  # library path

    # Default art size
    ART_SIZE = 200

    # Class-level cache for default cover
    _default_pixmap: Optional[QPixmap] = None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._load_default_cover()
        self._setup_ui()

    @classmethod
    def _load_default_cover(cls) -> None:
        """Load and cache the default cover image."""
        if cls._default_pixmap is not None:
            return

        if DEFAULT_COVER_PATH.exists():
            cls._default_pixmap = QPixmap(str(DEFAULT_COVER_PATH))
            if cls._default_pixmap.isNull():
                cls._default_pixmap = None
                print(f"Warning: Failed to load default cover from {DEFAULT_COVER_PATH}")
        else:
            print(f"Warning: Default cover not found at {DEFAULT_COVER_PATH}")

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Album art label
        self._art_label = QLabel()
        self._art_label.setFixedSize(self.ART_SIZE, self.ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
            }
        """)
        self._art_label.setText("No Art")
        self._art_label.mousePressEvent = self._on_art_click
        layout.addWidget(self._art_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Track info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)

        # Title
        self._title_label = QLabel("No Track Playing")
        self._title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        info_layout.addWidget(self._title_label)

        # Artist
        self._artist_label = QLabel("")
        self._artist_label.setStyleSheet("font-size: 12px; color: #666;")
        self._artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._artist_label.setWordWrap(True)
        info_layout.addWidget(self._artist_label)

        # Album
        self._album_label = QLabel("")
        self._album_label.setStyleSheet("font-size: 11px; color: #888;")
        self._album_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._album_label.setWordWrap(True)
        info_layout.addWidget(self._album_label)

        layout.addLayout(info_layout)

        # Library selector
        self._library_selector = LibrarySelector()
        self._library_selector.library_selected.connect(self.library_selected.emit)
        layout.addWidget(self._library_selector)

        layout.addStretch()

    def _on_art_click(self, event) -> None:
        """Handle click on album art."""
        self.art_clicked.emit()

    def update_track_info(self, title: str, artist: str = "", album: str = "") -> None:
        """
        Update track information display.

        Args:
            title: Track title
            artist: Artist name
            album: Album name
        """
        self._title_label.setText(title if title else "Unknown Title")
        self._artist_label.setText(artist if artist else "")
        self._album_label.setText(album if album else "")

    def update_album_art(self, art_data: Optional[bytes]) -> None:
        """
        Update album art from raw image data.

        Args:
            art_data: Raw image bytes (PNG, JPEG, etc.) or None for placeholder
        """
        if not art_data:
            self._clear_art()
            return

        try:
            # Use PIL for better image handling
            if PIL_AVAILABLE:
                image = Image.open(io.BytesIO(art_data))
                # Resize to fit while maintaining aspect ratio
                image.thumbnail((self.ART_SIZE, self.ART_SIZE), Image.Resampling.LANCZOS)

                # Convert to Qt format
                if image.mode == 'RGBA':
                    data = image.tobytes('raw', 'RGBA')
                    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
                elif image.mode == 'RGB':
                    data = image.tobytes('raw', 'RGB')
                    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGB888)
                else:
                    image = image.convert('RGB')
                    data = image.tobytes('raw', 'RGB')
                    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGB888)

                pixmap = QPixmap.fromImage(qimage)
            else:
                # Fallback to Qt-only
                pixmap = QPixmap()
                pixmap.loadFromData(art_data)

                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        self.ART_SIZE, self.ART_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )

            if not pixmap.isNull():
                self._art_label.setPixmap(pixmap)
            else:
                self._clear_art()

        except Exception as e:
            print(f"Error loading album art: {e}")
            self._clear_art()

    def _clear_art(self) -> None:
        """Clear album art and show default cover or placeholder."""
        if self._default_pixmap and not self._default_pixmap.isNull():
            # Scale the default cover to fit
            scaled = self._default_pixmap.scaled(
                self.ART_SIZE, self.ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._art_label.setPixmap(scaled)
        else:
            # Fallback to text placeholder
            self._art_label.clear()
            self._art_label.setText("No Art")
            self._art_label.setStyleSheet("""
                QLabel {
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 5px;
                }
            """)

    def clear(self) -> None:
        """Clear all display."""
        self.update_track_info("No Track Playing", "", "")
        self._clear_art()

    def set_libraries(self, libraries: List) -> None:
        """
        Set the list of available libraries.

        Args:
            libraries: List of LibraryConfig objects
        """
        self._library_selector.set_libraries(libraries)

    def set_current_library(self, library_path: str) -> None:
        """
        Set the currently selected library.

        Args:
            library_path: Path to the current library
        """
        self._library_selector.set_current_library(library_path)

    def sizeHint(self) -> QSize:
        """Return suggested size."""
        return QSize(250, 400)
