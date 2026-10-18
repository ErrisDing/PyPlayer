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
from core import i18n
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

    # Temporary literal. ``core.theme.ART_SIZE`` was deleted in batch 2 Task 2
    # (the left panel it sized no longer exists), but this file still lives until
    # Task 9, so the value it used to read from the token layer is inlined here
    # at exactly the same 200 rather than left as an ImportError.
    # Task 9 随本文件一并删除。
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
        # Style scopes for the theme sheet (core/theme_qss.py emits
        # `QMainWindow, #nowPlayingPanel` and scopes every label here by its
        # own objectName). No styling below: the sheet is the only source.
        self.setObjectName("nowPlayingPanel")

        # Enable transparency
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Add top spacing to balance with left/right margins
        layout.addSpacing(15)

        # Album art label. A7: the initial state goes through ``_clear_art()``
        # like ``clear()`` does, so first launch and cleared playback show the
        # same thing -- the default cover, or the i18n'd text only when the
        # cover file itself is unavailable. No inline placeholder styling.
        self._art_label = QLabel()
        self._art_label.setObjectName("albumArt")
        self._art_label.setFixedSize(self.ART_SIZE, self.ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.mousePressEvent = self._on_art_click
        self._clear_art()
        layout.addWidget(self._art_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Track info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)

        # Title
        self._title_label = QLabel(i18n.get('metadata.no_track'))
        self._title_label.setObjectName("trackTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        info_layout.addWidget(self._title_label)

        # Artist
        self._artist_label = QLabel("")
        self._artist_label.setObjectName("trackArtist")
        self._artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._artist_label.setWordWrap(True)
        info_layout.addWidget(self._artist_label)

        # Album
        self._album_label = QLabel("")
        self._album_label.setObjectName("trackAlbum")
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

        Empty artist/album stay empty (controller ruling: showing
        ``metadata.unknown_artist`` / ``metadata.unknown_album`` would be new
        behaviour §4.6 never asked for; the two keys stay in the properties
        for batch 2's column work).
        """
        self._title_label.setText(title if title else i18n.get('metadata.unknown_title'))
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
            # No default cover on disk: the *text* placeholder is the last
            # resort, and it comes from i18n like everything else. #albumArt's
            # sheet rule paints the box, so no stylesheet is re-applied here.
            self._art_label.clear()
            self._art_label.setText(i18n.get('now_playing.no_art'))

    def clear(self) -> None:
        """Clear all display -- same path as the initial state (A7)."""
        self.update_track_info(i18n.get('metadata.no_track'), "", "")
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
