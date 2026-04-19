#!/usr/bin/env python3
"""
Library Service - Media library management with PyQt signals
"""

from typing import List, Optional, Dict
from PyQt6.QtCore import QObject, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from library_manager import LibraryManager, MediaFile, LibraryRuntime, PlaybackQueue


class LibraryService(QObject):
    """
    Service for managing media libraries.
    Provides async library loading with progress signals.
    """

    # Signals
    library_loaded = pyqtSignal(str, list)    # library_id, files
    library_scanning = pyqtSignal(str)         # library_id
    library_error = pyqtSignal(str, str)       # library_id, error_message
    all_libraries_loaded = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = LibraryManager()
        self._libraries: Dict[str, LibraryRuntime] = {}

    def load_library(self, library_path: str, library_name: Optional[str] = None) -> None:
        """
        Load a media library.

        Args:
            library_path: Path to the library directory
            library_name: Optional display name
        """
        self.library_scanning.emit(library_path)

        try:
            # Use LibraryManager to scan
            files = self._manager.refresh_library(library_path)

            # Get or create runtime
            runtime = self._manager.get_runtime(library_path)

            if runtime:
                self._libraries[library_path] = runtime

            self.library_loaded.emit(library_path, files)

        except Exception as e:
            self.library_error.emit(library_path, str(e))

    def load_all_libraries(self) -> None:
        """Load all libraries from configuration."""
        from config import SettingsManager

        sm = SettingsManager()
        libraries = sm.settings.media_libraries

        for lib in libraries:
            self.load_library(lib.path, lib.name)

        self.all_libraries_loaded.emit()

    def get_files(self, library_path: str) -> List[MediaFile]:
        """Get cached files for a library."""
        return self._manager.get_cached_files(library_path)

    def get_runtime(self, library_path: str) -> Optional[LibraryRuntime]:
        """Get runtime for a library."""
        return self._libraries.get(library_path) or self._manager.get_runtime(library_path)

    def get_queue(self, library_path: str) -> Optional[PlaybackQueue]:
        """Get playback queue for a library."""
        runtime = self.get_runtime(library_path)
        return runtime.playback_queue if runtime else None

    def refresh_library(self, library_path: str) -> List[MediaFile]:
        """Force refresh a library."""
        return self._manager.refresh_library(library_path)

    def get_all_files(self) -> Dict[str, List[MediaFile]]:
        """Get files from all loaded libraries."""
        return self._manager.get_all_files()

    def scan_all(self) -> Dict[str, List[MediaFile]]:
        """Scan all configured libraries."""
        return self._manager.scan_all_libraries()
