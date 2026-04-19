#!/usr/bin/env python3
"""
Cache Manager - JSON-based library cache management
Provides persistent caching for scanned media libraries
"""

import os
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class CachedFile:
    """Represents a cached media file entry."""
    path: str
    title: str
    file_type: str      # 'audio' or 'video'
    extension: str
    size_bytes: int = 0
    modified_time: float = 0.0


@dataclass
class LibraryCache:
    """
    JSON-serializable cache structure for a media library.

    Attributes:
        version: Cache format version
        library_path: Absolute path to the library root
        library_name: Display name of the library
        scan_timestamp: Unix timestamp when the scan was performed
        files: List of cached file entries
    """
    version: str = "1.0"
    library_path: str = ""
    library_name: str = ""
    scan_timestamp: float = 0.0
    files: List[CachedFile] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "version": self.version,
            "library_path": self.library_path,
            "library_name": self.library_name,
            "scan_timestamp": self.scan_timestamp,
            "files": [asdict(f) for f in self.files]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LibraryCache':
        """Create from dictionary."""
        files = [CachedFile(**f) for f in data.get("files", [])]
        return cls(
            version=data.get("version", "1.0"),
            library_path=data.get("library_path", ""),
            library_name=data.get("library_name", ""),
            scan_timestamp=data.get("scan_timestamp", 0.0),
            files=files
        )


class LibraryCacheManager:
    """
    Manages JSON-based cache files for media libraries.

    Cache files are stored in ~/.pyplayer/cache/libraries/
    Each library gets a cache file named by hashing its path.
    """

    CACHE_VERSION = "1.0"
    CACHE_DIR_NAME = "cache"
    LIBRARIES_DIR_NAME = "libraries"

    def __init__(self):
        self._cache_dir = self._get_cache_dir()
        self._ensure_cache_dir()

    def _get_cache_dir(self) -> Path:
        """Get the cache directory path."""
        return Path.home() / '.pyplayer' / self.CACHE_DIR_NAME / self.LIBRARIES_DIR_NAME

    def _ensure_cache_dir(self) -> None:
        """Ensure the cache directory exists."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_filename(self, library_path: str) -> str:
        """
        Generate cache filename from library path.

        Uses SHA-256 hash of the normalized path to create a unique filename.
        """
        normalized = os.path.normpath(library_path)
        path_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        return f"{path_hash}.json"

    def _get_cache_filepath(self, library_path: str) -> Path:
        """Get full path to cache file for a library."""
        return self._cache_dir / self._get_cache_filename(library_path)

    def save_cache(self, cache: LibraryCache) -> bool:
        """
        Save library cache to JSON file.

        Args:
            cache: LibraryCache object to save

        Returns:
            True if successful, False otherwise
        """
        if not cache.library_path:
            return False

        cache_file = self._get_cache_filepath(cache.library_path)

        try:
            # Atomic write using temp file
            temp_file = cache_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(cache.to_dict(), f, indent=2, ensure_ascii=False)

            temp_file.rename(cache_file)
            return True

        except (OSError, IOError, json.JSONEncodeError) as e:
            print(f"Failed to save cache for {cache.library_path}: {e}")
            return False

    def load_cache(self, library_path: str) -> Optional[LibraryCache]:
        """
        Load library cache from JSON file.

        Args:
            library_path: Path to the media library

        Returns:
            LibraryCache if found and valid, None otherwise
        """
        cache_file = self._get_cache_filepath(library_path)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cache = LibraryCache.from_dict(data)

            # Verify version compatibility
            if cache.version != self.CACHE_VERSION:
                print(f"Cache version mismatch for {library_path}: {cache.version}")
                return None

            return cache

        except (OSError, IOError, json.JSONDecodeError) as e:
            print(f"Failed to load cache for {library_path}: {e}")
            return None

    def delete_cache(self, library_path: str) -> bool:
        """
        Delete cache file for a library.

        Args:
            library_path: Path to the media library

        Returns:
            True if deleted, False if not found or error
        """
        cache_file = self._get_cache_filepath(library_path)

        if not cache_file.exists():
            return False

        try:
            cache_file.unlink()
            return True
        except OSError as e:
            print(f"Failed to delete cache for {library_path}: {e}")
            return False

    def has_valid_cache(self, library_path: str) -> bool:
        """
        Check if a valid cache exists for the library.

        Args:
            library_path: Path to the media library

        Returns:
            True if valid cache exists
        """
        cache = self.load_cache(library_path)
        return cache is not None and cache.scan_timestamp > 0

    def is_cache_fresh(self, library_path: str) -> bool:
        """
        Check if cache is fresh (directory hasn't been modified since scan).

        Args:
            library_path: Path to the media library

        Returns:
            True if cache is still fresh
        """
        cache = self.load_cache(library_path)
        if not cache:
            return False

        try:
            dir_stat = os.stat(library_path)
            # Cache is fresh if directory wasn't modified after scan
            return dir_stat.st_mtime <= cache.scan_timestamp
        except OSError:
            return False

    def create_cache(
        self,
        library_path: str,
        library_name: str,
        files: List[CachedFile]
    ) -> LibraryCache:
        """
        Create a new LibraryCache object.

        Args:
            library_path: Absolute path to library
            library_name: Display name
            files: List of cached file entries

        Returns:
            New LibraryCache object
        """
        return LibraryCache(
            version=self.CACHE_VERSION,
            library_path=library_path,
            library_name=library_name,
            scan_timestamp=datetime.now().timestamp(),
            files=files
        )

    def get_cached_files(self, library_path: str) -> Optional[List[CachedFile]]:
        """
        Get cached files for a library if cache is valid and fresh.

        Args:
            library_path: Path to the media library

        Returns:
            List of CachedFile if valid cache exists, None otherwise
        """
        if not self.is_cache_fresh(library_path):
            return None

        cache = self.load_cache(library_path)
        return cache.files if cache else None

    def clear_all_caches(self) -> int:
        """
        Clear all library cache files.

        Returns:
            Number of cache files deleted
        """
        count = 0
        for cache_file in self._cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
        return count
