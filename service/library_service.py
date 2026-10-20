#!/usr/bin/env python3
"""
Library Service - Media library management with PyQt signals
"""

from typing import List, Optional, Dict, Tuple, Any
from PyQt6.QtCore import QObject, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cache_manager import CachedFile
from core.library_manager import LibraryManager, MediaFile, LibraryRuntime, PlaybackQueue


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
        from core.config import SettingsManager

        sm = SettingsManager()
        libraries = sm.settings.media_libraries

        for lib in libraries:
            self.load_library(lib.path, lib.name)

        self.all_libraries_loaded.emit()

    def get_files(self, library_path: str) -> List[MediaFile]:
        """Get cached files for a library."""
        return self._manager.get_cached_files(library_path)

    def get_cache_entries(self, library_path: str) -> List[CachedFile]:
        """The library's cached entries, ``md`` included -- a warm start's input.

        Not :meth:`get_files`: ``MediaFile`` carries no ``md``, and the three states
        batch 4 shows are decided by the key's *presence*. The presenter asks for the
        entries so ``LibraryMetadataStore`` can fill the rows a scan cannot -- and can
        then compare each stored fingerprint against the file it now describes.
        """
        return self._manager.get_cache_entries(library_path)

    def save_cache_metadata(self, library_path: str,
                            updates: Dict[str, Tuple[Optional[Dict[str, Any]],
                                                     int, float]]) -> int:
        """Write one batch of answered rows into the cache file; entries stamped.

        Batched by design (spec §4.4): ``save_cache`` rewrites the whole document, so
        one write per row would be quadratic in the library size. Returns the number of
        entries the cache actually held -- a path that left the file table is dropped
        rather than added, and the caller's disk re-check is what keeps a deleted or
        rewritten file out of ``updates`` in the first place.
        """
        return self._manager.save_cache_metadata(library_path, updates)

    def get_runtime(self, library_path: str) -> Optional[LibraryRuntime]:
        """Get runtime for a library."""
        return self._libraries.get(library_path) or self._manager.get_runtime(library_path)

    def get_queue(self, library_path: str) -> Optional[PlaybackQueue]:
        """Get playback queue for a library."""
        runtime = self.get_runtime(library_path)
        return runtime.playback_queue if runtime else None

    def refresh_library(self, library_path: str) -> List[MediaFile]:
        """Force refresh a library."""
        files = self._manager.refresh_library(library_path)
        # Emit signal to notify listeners
        self.library_loaded.emit(library_path, files)
        return files

    def refresh_all_libraries(self) -> Dict[str, List[MediaFile]]:
        """
        Force refresh all configured libraries.

        Returns:
            Dict mapping library_path -> list of files
        """
        from core.config import SettingsManager

        sm = SettingsManager()
        libraries = sm.settings.media_libraries

        result = {}
        for lib in libraries:
            files = self.refresh_library(lib.path)
            result[lib.path] = files

        self.all_libraries_loaded.emit()
        return result

    def get_all_files(self) -> Dict[str, List[MediaFile]]:
        """Get files from all loaded libraries."""
        return self._manager.get_all_files()

    def scan_all(self) -> Dict[str, List[MediaFile]]:
        """Scan all configured libraries."""
        return self._manager.scan_all_libraries()
