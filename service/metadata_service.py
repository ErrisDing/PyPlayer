#!/usr/bin/env python3
"""
Metadata Service - Async metadata extraction with PyQt signals
Prevents UI blocking when loading album art from large files
"""

from typing import Optional, Dict
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.metadata import SongMetadata, extract_metadata


class MetadataLoadTask(QRunnable):
    """Runnable task for loading metadata in background thread."""

    def __init__(self, filepath: str, callback):
        super().__init__()
        self.filepath = filepath
        self.callback = callback

    def run(self):
        """Load metadata in background thread."""
        try:
            metadata = extract_metadata(self.filepath)
            self.callback(self.filepath, metadata, None)
        except Exception as e:
            self.callback(self.filepath, None, str(e))


class MetadataService(QObject):
    """
    Service for async metadata extraction.
    Uses QThreadPool for background loading.
    """

    # Signals
    metadata_loaded = pyqtSignal(str, object)   # filepath, SongMetadata
    album_art_loaded = pyqtSignal(str, bytes)   # filepath, album_art_bytes
    metadata_error = pyqtSignal(str, str)       # filepath, error_message

    # Cache
    _cache: Dict[str, SongMetadata] = {}

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._thread_pool = QThreadPool.globalInstance()

    def load_async(self, filepath: str) -> None:
        """
        Load metadata asynchronously.

        Args:
            filepath: Path to the audio file
        """
        # Check cache first
        if filepath in self._cache:
            self.metadata_loaded.emit(filepath, self._cache[filepath])
            if self._cache[filepath].album_art:
                self.album_art_loaded.emit(filepath, self._cache[filepath].album_art)
            return

        # Create and start task
        task = MetadataLoadTask(filepath, self._on_metadata_loaded)
        self._thread_pool.start(task)

    def _on_metadata_loaded(self, filepath: str, metadata: Optional[SongMetadata], error: Optional[str]) -> None:
        """Callback when metadata is loaded."""
        if error:
            self.metadata_error.emit(filepath, error)
            return

        if metadata:
            # Cache the result
            self._cache[filepath] = metadata

            # Emit signals
            self.metadata_loaded.emit(filepath, metadata)

            if metadata.album_art:
                self.album_art_loaded.emit(filepath, metadata.album_art)

    def get_cached(self, filepath: str) -> Optional[SongMetadata]:
        """Get cached metadata if available."""
        return self._cache.get(filepath)

    def load_sync(self, filepath: str) -> Optional[SongMetadata]:
        """
        Load metadata synchronously (blocking).

        Use sparingly - prefer load_async to avoid UI blocking.
        """
        if filepath in self._cache:
            return self._cache[filepath]

        try:
            metadata = extract_metadata(filepath)
            self._cache[filepath] = metadata
            return metadata
        except Exception:
            return None

    def clear_cache(self) -> None:
        """Clear the metadata cache."""
        self._cache.clear()

    def preload_files(self, filepaths: list) -> None:
        """
        Preload metadata for multiple files.

        Args:
            filepaths: List of file paths to preload
        """
        for filepath in filepaths:
            if filepath not in self._cache:
                self.load_async(filepath)
