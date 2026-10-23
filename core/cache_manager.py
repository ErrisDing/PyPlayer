#!/usr/bin/env python3
"""
Cache Manager - JSON-based library cache management
Provides persistent caching for scanned media libraries
"""

import os
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

from core.metadata import normalize_duration


#: Format stamped on every cache file this build writes (spec 4.3). 2.0 is the
#: first version whose entries may carry the ``md`` key.
CACHE_VERSION = "2.0"

#: The pre-batch-4 format: same file table, no ``md`` key on any entry.
LEGACY_CACHE_VERSION = "1.0"

#: Versions the read side accepts. 1.0 stays readable on purpose -- rejecting it
#: would invalidate every existing library's *file table* on the day 2.0 ships
#: and force a full re-scan (spec criterion 7). Kept as a set rather than a
#: second "if version ==" so the window has exactly one spelling.
SUPPORTED_CACHE_VERSIONS: frozenset[str] = frozenset(
    {LEGACY_CACHE_VERSION, CACHE_VERSION})

#: The canonical key set of an entry's ``md`` dict (ruling B4-R1). Later batch-4
#: tasks are *expected* to consume these three names -- as of this task nothing
#: outside this module imports them, and the round-trip test only spot-checks part
#: of the set, so this is the contract, not a surveyed list of consumers.
MD_KEYS = ("artist", "album", "duration")


@dataclass
class CachedFile:
    """Represents a cached media file entry.

    ``md`` carries the metadata tri-state (spec 4.1) as
    ``{"artist": Optional[str], "album": Optional[str], "duration": Optional[float]}``:

    * ``None`` -- the JSON has **no** ``md`` key: nothing was ever extracted,
      the entry is pending and a background sweep still has to fill it;
    * a dict whose values are all ``None`` -- extraction was tried and the tag
      had nothing (or the format is excluded, e.g. NCM): the entry must not be
      retried, and the view shows "no metadata" rather than "not fetched yet";
      a damaged payload (a bare ``null`` or a non-mapping) reads as exactly this
      dict, and a mapping with gaps gets its missing canonical keys added as
      ``None`` -- see :func:`_read_md`. A value of the *wrong type* (a string
      duration, an ``int`` artist) reads as ``None`` for that one key while the
      key stays present -- see :func:`_read_md_value`;
    * a dict with values -- known metadata.

    The two first states differ by key *presence*, never by value, which is why
    ``to_dict`` drops the key entirely instead of writing ``"md": null``.
    """
    path: str
    title: str
    file_type: str      # 'audio' or 'video'
    extension: str
    size_bytes: int = 0
    modified_time: float = 0.0
    md: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entry, omitting ``md`` when it is ``None``."""
        data: Dict[str, Any] = {
            "path": self.path,
            "title": self.title,
            "file_type": self.file_type,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "modified_time": self.modified_time,
        }
        if self.md is not None:
            data["md"] = dict(self.md)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CachedFile':
        """Build an entry from its JSON object (see :meth:`to_dict`)."""
        return cls(
            path=data["path"],
            title=data["title"],
            file_type=data["file_type"],
            extension=data["extension"],
            size_bytes=data.get("size_bytes", 0),
            modified_time=data.get("modified_time", 0.0),
            md=_read_md(data),
        )


def _read_md_value(key: str, value: Any) -> Any:
    """Keep one ``md`` value only if it can be the value the contract declares.

    Final-review C1. The container's shape was guarded (see :func:`_read_md`) and
    the values were not, and that stopped mattering until batch 4 made this file a
    **display source**: a hand-edited, third-party, or half-written cache holding
    ``{"duration": "227.0"}`` read back as a *known* row, rode the queue onto a
    display entry, and reached ``PlaylistItemDelegate.paint`` -> ``format_time``,
    which compares ``seconds < 0`` and raised ``TypeError`` inside a Python
    override of a C++ virtual. Measured on this host: **exit 127, no traceback**,
    on every launch, because the file is still there -- spec criteria 4 and 7
    inverted into "this library will not open".

    The answer is ``None``, never a raise and never the value: the reader is the
    single place that knows what a cache entry may hold, and the consumers
    (store -> queue -> model -> delegate) are all written to paint ``None`` as
    "this file has no such tag". Two type traps, both measured:

    * ``bool`` is an ``int`` subclass, so ``True`` would pass a plain numeric test
      and ``format_time(True)`` paints a fabricated ``0:01`` -- the very
      invented-length shape spec 4.2 exists to remove, arriving from the other
      direction.
    * a non-positive number is refused through ``normalize_duration``, the same
      function ``LibraryMetadataStore.record`` applies on the write side
      (ruling B4-R7 keeps that rule's author one, not several): the cache is not
      allowed to contain ``0.0``, because a known duration of zero paints ``0:00``.

    ``artist``/``album`` accept ``str`` only, and **empty strings stay**: presence,
    not truthiness, is what makes a value an answer (ruling B4-R8), so an artist
    the extractor reported as blank survives and an ``int`` does not.
    """
    if key == 'duration':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        # The one non-negative value legal in this cell is a real length; a float
        # NaN is not (it compares false against 0 and then formats as garbage).
        normalized = normalize_duration(value)
        return normalized if normalized is not None and normalized == normalized else None
    return value if isinstance(value, str) else None


def _read_md(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map an entry's ``md`` key to the tri-state value ``CachedFile`` stores.

    Absent key -> ``None`` (pending). Key present -> always a dict holding the
    three canonical keys: a ``null`` payload, a non-mapping payload and a mapping
    with gaps all land in the same bucket. The key existing is already the claim
    that extraction was tried, so a damaged or partial payload cannot mean
    "not tried", and filling the gaps keeps the consumers' index on
    ``md["album"]`` total without inventing values for the keys that are there.

    Values are checked against their declared types too -- each one that fails
    becomes ``None`` **while its key stays** (see :func:`_read_md_value`). That
    pairing is the whole decision: downgrading a value into *dropping the key*
    would send the row back to pending, and spec 4.1 makes key presence the only
    claim that anything was ever tried, so a damaged file would then be retried
    forever and its row would advertise a loading state that cannot complete.
    """
    if "md" not in entry:
        return None
    value = entry["md"]
    if value is None or not isinstance(value, dict):
        # A corrupt md value is read as "already tried": no retry, no raise.
        # ``dict(5)``/``dict("abc")`` would raise ValueError/TypeError, and
        # load_cache only catches (OSError, IOError, JSONDecodeError), so the
        # exception would escape load_cache, has_valid_cache, is_cache_fresh and
        # get_cached_files and cost the library its whole file table for one bad
        # cell -- while the same reader refuses a truncated JSON quietly. Marking
        # it tried instead keeps the sweep from retrying damage forever.
        return {key: None for key in MD_KEYS}
    normalized = dict(value)
    for key in MD_KEYS:
        normalized[key] = _read_md_value(key, normalized.get(key))
    return normalized


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
    version: str = CACHE_VERSION
    library_path: str = ""
    library_name: str = ""
    scan_timestamp: float = 0.0
    files: List[CachedFile] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary.

        Entries go through ``CachedFile.to_dict``, not ``dataclasses.asdict``:
        ``asdict`` always emits ``"md"`` -- as ``null`` for pending entries --
        and that single key would collapse the two states spec 4.1 separates.
        """
        return {
            "version": self.version,
            "library_path": self.library_path,
            "library_name": self.library_name,
            "scan_timestamp": self.scan_timestamp,
            "files": [f.to_dict() for f in self.files]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LibraryCache':
        """Create from dictionary.

        ``version`` is reported as the file states it, even when the reader then
        accepts it: ``LibraryCacheManager.load_cache`` needs the raw value to
        decide compatibility, and a silent normalization here would make every
        version look current.
        """
        files = [CachedFile.from_dict(f) for f in data.get("files", [])]
        return cls(
            version=data.get("version", LEGACY_CACHE_VERSION),
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

    ``CACHE_VERSION``/``SUPPORTED_CACHE_VERSIONS`` are aliased from the module
    constants so both spellings stay valid: the module names are the contract
    later code imports, the class attributes keep ``self.CACHE_VERSION`` and
    ``LibraryCacheManager.CACHE_VERSION`` readers working.
    """

    CACHE_VERSION = CACHE_VERSION
    SUPPORTED_CACHE_VERSIONS = SUPPORTED_CACHE_VERSIONS
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

            # os.replace works on Windows to overwrite existing files
            os.replace(temp_file, cache_file)
            return True

        except (OSError, IOError, TypeError) as e:
            print(f"Failed to save cache for {cache.library_path}: {e}")
            return False

    def load_cache(self, library_path: str) -> Optional[LibraryCache]:
        """
        Load library cache from JSON file.

        A 1.0 file loads as-is: its entries have no ``md`` key, so they come back
        pending, and the version stamped on the returned object is the current
        one -- that in-place upgrade is what makes the next ``save_cache`` write
        2.0 without a re-scan (spec 4.3).

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

            # Verify version compatibility against the accepted window, not
            # against CACHE_VERSION alone -- that would reject 1.0 and throw
            # away the file table of every library scanned before this shipped.
            # Any other version has no defined meaning for `md`, so it stays
            # unusable rather than being guessed at.
            if cache.version not in self.SUPPORTED_CACHE_VERSIONS:
                print(f"Cache version mismatch for {library_path}: {cache.version}")
                return None

            cache.version = self.CACHE_VERSION
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
