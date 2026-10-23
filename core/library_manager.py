#!/usr/bin/env python3
"""
PyPlayer Media Library Management Module
Scans directories for media files and provides caching to avoid repeated scans
"""

import os
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Set
from datetime import datetime

from .config import SettingsManager
from .cache_manager import LibraryCacheManager, CachedFile, LibraryCache


# ============================================================================
# QueueNode Architecture - Core data structures for playlist queue management
# ============================================================================

class QueueNode(ABC):
    """可播放队列节点的抽象基类

    Each node represents a playable unit in the playlist queue.
    Subclasses: FileNode (single file), FolderNode (folder with multiple files).
    """
    display_text: str
    path: str

    @abstractmethod
    def get_tracks(self) -> List['Track']:
        """返回此节点包含的所有轨道"""
        pass

    @abstractmethod
    def is_folder(self) -> bool:
        """是否为文件夹节点"""
        pass


@dataclass
class FileNode(QueueNode):
    """单文件节点"""
    track: 'Track'
    display_text: str = ""
    path: str = ""

    def __post_init__(self):
        if not self.display_text:
            self.display_text = self.track.title
        if not self.path:
            self.path = self.track.path

    def get_tracks(self) -> List['Track']:
        return [self.track]

    def is_folder(self) -> bool:
        return False


@dataclass
class FolderNode(QueueNode):
    """文件夹节点，维护内部播放状态

    Attributes:
        display_text: Display name for the folder
        path: Full path to the folder
        tracks: List of Track objects in this folder
        current_sub_index: Current playing index within the folder (-1 = not started)
        loop_mode: Loop mode for this folder ("OFF", "ONE", "ALL")
    """
    display_text: str
    path: str
    tracks: List['Track'] = field(default_factory=list)
    current_sub_index: int = -1
    loop_mode: str = "OFF"  # "OFF", "ONE", "ALL"

    def get_tracks(self) -> List['Track']:
        return self.tracks

    def is_folder(self) -> bool:
        return True

    def get_current_track(self) -> Optional['Track']:
        """获取当前正在播放的轨道"""
        if 0 <= self.current_sub_index < len(self.tracks):
            return self.tracks[self.current_sub_index]
        return None

    def advance_to_next(self) -> Optional['Track']:
        """前进到下一首，返回轨道或 None 表示文件夹播放完毕

        Handles loop modes:
        - OFF: Returns None when reaching end
        - ONE: Returns same track (handled by caller)
        - ALL: Wraps around to first track
        """
        if not self.tracks:
            return None

        next_idx = self.current_sub_index + 1

        if self.loop_mode == "ALL":
            # Wrap around
            next_idx = next_idx % len(self.tracks)
            self.current_sub_index = next_idx
            return self.tracks[next_idx]
        elif self.loop_mode == "ONE":
            # Stay on same track - caller handles this
            return self.get_current_track()
        else:
            # OFF mode - advance without wrap
            if next_idx >= len(self.tracks):
                return None  # 文件夹播放完毕
            self.current_sub_index = next_idx
            return self.tracks[next_idx]

    def advance_to_prev(self) -> Optional['Track']:
        """后退到上一首"""
        if not self.tracks:
            return None

        prev_idx = self.current_sub_index - 1

        if self.loop_mode == "ALL":
            # Wrap around
            prev_idx = (prev_idx + len(self.tracks)) % len(self.tracks)
            self.current_sub_index = prev_idx
            return self.tracks[prev_idx]
        else:
            # OFF/ONE mode - go back without wrap
            if prev_idx < 0:
                return None  # Already at first track
            self.current_sub_index = prev_idx
            return self.tracks[prev_idx]

    def reset(self) -> None:
        """重置文件夹状态"""
        self.current_sub_index = -1

    def set_sub_index(self, index: int) -> Optional['Track']:
        """设置当前播放索引并返回对应轨道"""
        if 0 <= index < len(self.tracks):
            self.current_sub_index = index
            return self.tracks[index]
        return None


@dataclass
class DisplayIndexMap:
    """显示索引到队列节点的映射

    Maps the display listbox indices to the actual queue nodes.
    This is needed because the display shows hierarchical structure
    (folders + files), but the queue_nodes list only contains nodes.
    """
    entries: List[dict] = field(default_factory=list)

    def add_entry(self, display_idx: int, node_idx: int, is_folder: bool,
                  path: str, sub_index: int = -1, full_path: str = "") -> None:
        """添加一个映射条目

        Args:
            display_idx: Index in the display listbox
            node_idx: Index in the queue_nodes list
            is_folder: Whether this entry is a folder
            path: Path of the folder or file
            sub_index: For files within folders, the index within the folder's tracks
            full_path: Full path for file entries
        """
        self.entries.append({
            'display_idx': display_idx,
            'node_idx': node_idx,
            'is_folder': is_folder,
            'path': path,
            'sub_index': sub_index,
            'full_path': full_path
        })

    def get_by_display_idx(self, display_idx: int) -> Optional[dict]:
        """根据显示索引获取映射条目"""
        if 0 <= display_idx < len(self.entries):
            return self.entries[display_idx]
        return None

    def get_by_full_path(self, full_path: str) -> Optional[dict]:
        """根据完整路径获取映射条目"""
        for entry in self.entries:
            if entry.get('full_path') == full_path:
                return entry
        return None

    def clear(self) -> None:
        """清空所有映射条目"""
        self.entries.clear()

    def __len__(self) -> int:
        return len(self.entries)


@dataclass
class MediaFile:
    """Represents information about a single media file"""
    path: str
    title: str
    file_type: str      # 'audio' or 'video'
    extension: str      # File extension (e.g., .mp3)
    size_bytes: int = 0
    modified_time: float = 0.0

    def __post_init__(self):
        try:
            stat_info = os.stat(self.path)
            self.size_bytes = stat_info.st_size
            self.modified_time = stat_info.st_mtime
        except OSError:
            pass


@dataclass
class Track:
    """Playlist item - defined at module level for queue management"""
    path: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: float = 0.0

    def __str__(self):
        return self.title


# Forward reference for LibraryConfig type hint in method signatures
LIBRARY_CONFIG_TYPE_NAME = "LibraryConfig"


# Supported media file extensions
SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.ncm'}
SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}
ALL_SUPPORTED = SUPPORTED_AUDIO | SUPPORTED_VIDEO

# Directories to skip
SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'vendor', 'build', 'dist'}


# ============================================================================
# NEW: Runtime Management Objects for Queue State Machine
# ============================================================================

@dataclass
class PlaybackState:
    """播放状态机 - 追踪每队列的位置和导航历史"""
    current_position: int = 0      # 当前播放索引 (0-based)
    history: List[int] = field(default_factory=list)  # 位置变化历史
    loop_mode: str = "OFF"         # "OFF", "ONE", "ALL"

    def record_position(self, new_pos: int) -> None:
        """记录位置变化到历史"""
        if self.current_position != new_pos:
            self.history.append(self.current_position)
            self.current_position = new_pos


@dataclass
class PlaybackQueue:
    """每个文件夹/媒体库独立的播放队列"""
    library_id: str                # 队列唯一标识（图书馆名或路径）
    track_list: List[Track] = field(default_factory=list)
    current_index: int = -1        # 指针指向当前轨道 (-1=空闲)
    state: str = "IDLE"            # IDLE, LOADING, PLAYING, PAUSED, COMPLETED
    position_state: PlaybackState = field(init=False)

    def __post_init__(self):
        self.position_state = PlaybackState(current_position=self.current_index, loop_mode="OFF")

    def add_track(self, track: Track) -> None:
        """添加轨道到队列末尾"""
        self.track_list.append(track)

    def clear(self) -> None:
        """清空队列"""
        self.track_list.clear()
        self.current_index = -1
        self.position_state = PlaybackState(current_position=-1, loop_mode="OFF")

    def is_valid_position(self) -> bool:
        """检查当前位置是否有效"""
        return 0 <= self.current_index < len(self.track_list) if self.track_list else False


@dataclass
class LibraryRuntime:
    """单个媒体库的运行时对象（每个图书馆一个实例）"""
    config: Any                    # 引用静态配置 (LibraryConfig)
    media_files: List[MediaFile] = field(default_factory=list)  # 缓存的文件列表
    playback_queue: PlaybackQueue = field(init=False)

    def __post_init__(self):
        self.playback_queue = PlaybackQueue(library_id=self.config.path, track_list=[])


class LibraryRuntimeManager:
    """管理所有媒体库运行时对象（单例模式）"""

    _instance: Optional['LibraryRuntimeManager'] = None

    def __new__(cls) -> 'LibraryRuntimeManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._runtimes: Dict[str, LibraryRuntime] = {}
        return cls._instance

    @classmethod
    def get_runtime(cls, lib_path: str) -> Optional['LibraryRuntime']:
        """根据库路径获取运行时对象（不存在则创建）"""
        instance = cls()
        lib_key = os.path.normpath(lib_path)

        if lib_key not in instance._runtimes:
            # 懒加载：从配置中读取并创建
            sm = SettingsManager()
            lib_config = get_library_for_file(lib_path, sm.settings.media_libraries)

            if lib_config:
                runtime = LibraryRuntime(
                    config=lib_config,
                    media_files=[]
                )
                # 使用标准化路径作为 key
                normalized_key = os.path.normpath(lib_config.path)
                instance._runtimes[normalized_key] = runtime

        return instance._runtimes.get(lib_key)

    @classmethod
    def get_all_runtimes(cls) -> Dict[str, 'LibraryRuntime']:
        """获取所有已创建的运行时对象"""
        instance = cls()
        return dict(instance._instance._runtimes) if instance._instance else {}

    @classmethod
    def clear_cache(cls) -> None:
        """清空运行时缓存（用于重置）"""
        if cls._instance:
            cls._instance._runtimes.clear()


class LibraryScanner:
    """Recursively scan directories to get media files"""

    def __init__(self):
        self._scanned_times: Dict[str, float] = {}  # path -> scan timestamp
        self._cache_manager = LibraryCacheManager()

    def _is_supported_file(self, filename: str) -> bool:
        """Check if file is a supported media file"""
        ext = Path(filename).suffix.lower()
        return ext in ALL_SUPPORTED

    def _is_skip_directory(self, directory: str) -> bool:
        """Check if directory should be skipped"""
        dir_name = os.path.basename(directory.lower())
        return dir_name in SKIP_DIRS or any(skip in directory.lower() for skip in ['node_modules', '.git'])

    def scan_directory(self, directory: str, force_refresh: bool = False) -> List[MediaFile]:
        """
        Scan directory to get list of media files
        :param directory: Directory path to scan
        :param force_refresh: Whether to force rescan (ignore cache)
        :return: List of MediaFile objects
        """
        directory = os.path.normpath(directory)

        # Check JSON cache (unless forced refresh)
        if not force_refresh:
            cached_files = self._cache_manager.get_cached_files(directory)
            if cached_files:
                # Convert CachedFile to MediaFile
                return [self._cached_to_media_file(cf) for cf in cached_files]

        files = []

        if not Path(directory).exists():
            return files

        for root, dirs, filenames in os.walk(directory):
            # Skip specified directories (modify dirs in-place to prevent os.walk from entering subdirectories)
            dirs[:] = [d for d in dirs if not self._is_skip_directory(os.path.join(root, d))]

            for filename in filenames:
                if self._is_supported_file(filename):
                    filepath = os.path.join(root, filename)
                    ext = Path(filename).suffix.lower()

                    file_type = 'audio' if ext in SUPPORTED_AUDIO else 'video'

                    media_file = MediaFile(
                        path=filepath,
                        title=filename,
                        file_type=file_type,
                        extension=ext
                    )
                    files.append(media_file)

        # Sort by full path
        files.sort(key=lambda f: f.path)

        # Update cache
        self._save_to_cache(directory, files)
        self._scanned_times[directory] = datetime.now().timestamp()
        return files

    def _cached_to_media_file(self, cached: CachedFile) -> MediaFile:
        """Convert CachedFile to MediaFile."""
        return MediaFile(
            path=cached.path,
            title=cached.title,
            file_type=cached.file_type,
            extension=cached.extension,
            size_bytes=cached.size_bytes,
            modified_time=cached.modified_time
        )

    def _media_to_cached_file(self, media: MediaFile) -> CachedFile:
        """Convert MediaFile to CachedFile."""
        return CachedFile(
            path=media.path,
            title=media.title,
            file_type=media.file_type,
            extension=media.extension,
            size_bytes=media.size_bytes,
            modified_time=media.modified_time
        )

    def _save_to_cache(self, library_path: str, files: List[MediaFile]) -> None:
        """Save scan results to JSON cache, carrying over the metadata that still fits.

        Batch 4's write-back lands in this same file, which makes this the one place a
        re-scan can destroy it: ``_media_to_cached_file`` builds each entry from a
        ``MediaFile``, and ``MediaFile`` has no ``md`` -- so an unconditional save here
        would drop every answer the sweep had just persisted and a refreshed library
        would re-extract from scratch (spec §4.3's "the version bump must not silently
        re-scan the file table" applies to the metadata just as much).

        The carry-over rule is the store's own, applied at the writer (ruling B4-R10):
        a payload travels only with the fingerprint it describes, so an old ``md`` is
        copied when and only when ``(size_bytes, modified_time)`` came back the same.
        A file that moved is written *without* an ``md`` key -- pending again, the one
        shape that asks the next sweep for it -- rather than with a stale answer
        stamped as if it were current.
        """
        library_name = Path(library_path).name
        previous = self._cache_manager.load_cache(library_path)
        held: Dict[str, Tuple[Dict[str, Any], int, float]] = {}
        # ``is not None``, not a truth test (ruling B4-R8) -- the same reason
        # ``load_cache_entries`` below spells the check out: an ``Optional[LibraryCache]``
        # must never collapse "an empty table" into "no cache".
        if previous is not None:
            for cached in previous.files:
                if cached.md is not None:
                    held[cached.path] = (cached.md, cached.size_bytes,
                                         cached.modified_time)

        cached_files = []
        for media in files:
            cached = self._media_to_cached_file(media)
            keep = held.get(cached.path)
            if keep is not None:
                md, size_bytes, modified_time = keep
                if (cached.size_bytes, cached.modified_time) == (size_bytes,
                                                                 modified_time):
                    cached.md = md
            cached_files.append(cached)

        cache = self._cache_manager.create_cache(
            library_path=library_path,
            library_name=library_name,
            files=cached_files
        )
        self._cache_manager.save_cache(cache)

    def load_cache_entries(self, directory: str) -> List[CachedFile]:
        """The cached entries of one library, ``md`` included -- a warm start's input.

        ``get_cached_files`` cannot serve this: it converts to ``MediaFile``, which has
        no ``md``, and it only answers while the root directory is untouched (its
        ``is_cache_fresh`` check), which a refresh by definition is not. Task 3's store
        wants the entries as they were written, fingerprints and all, and is the layer
        that decides whether they still describe the files on disk.

        A missing, unreadable or out-of-window cache file answers ``[]``: that is
        "nothing warm to start from", the same state as a first scan, and the sweep
        fills it. ``LibraryCacheManager.load_cache`` already reports its own failures.

        ``is None``, not a truth test (ruling B4-R8): ``LibraryCache`` is a plain
        dataclass today, so an empty ``files`` list must not be readable as "there is
        no cache" the moment the class grows a ``__len__``. Same shape as
        :meth:`update_cache_metadata` below.
        """
        cache = self._cache_manager.load_cache(directory)
        if cache is None:
            return []
        return list(cache.files)

    def update_cache_metadata(self, directory: str,
                              updates: Dict[str, Tuple[Optional[Dict[str, Any]],
                                                       int, float]]) -> int:
        """Stamp one write-back batch onto the cached entries, in one save.

        ``updates`` maps a full path to the ``(md, size_bytes, modified_time)`` triple
        the caller asserts about that file. Payload and fingerprint are one argument
        and not two *because* of ruling B4-R10: they describe one version of one file
        or they describe nothing, and a signature that let one move without the other
        is the shape that made the silent loss possible. It is also what lets this
        method tell "not in this batch" (no key) from "answered as nothing" (a triple
        whose ``md`` is ``None``), which a ``Dict[str, dict]`` could not.

        This is the mechanism, not the policy: it writes exactly what it is handed, and
        the caller that holds the store is the one that decides a pending row is never
        offered. Two rules it does own, because they are about this file:

        * **No entry is invented.** Only paths already in the table are stamped, so a
          result for a file outside the scan cannot add a row to the library's list
          (which would then be served as if the scan had found it).
        * **One save per batch, and none at all for an empty one.** ``save_cache``
          dumps the whole document every call, which is why Task 7 batches; a batch
          whose paths were all gone by the time it got here costs zero writes.

        The ``scan_timestamp`` travels with the loaded object: this is not a re-scan,
        and claiming one would make the file table look fresher than it is.
        """
        cache = self._cache_manager.load_cache(directory)
        if cache is None:
            return 0

        stamped = 0
        for cached in cache.files:
            update = updates.get(cached.path)
            if update is None:
                continue
            md, size_bytes, modified_time = update
            cached.md = dict(md) if md is not None else None
            cached.size_bytes = size_bytes
            cached.modified_time = modified_time
            stamped += 1
        if not stamped:
            return 0

        self._cache_manager.save_cache(cache)
        return stamped

    def _get_cached_files(self, path: str) -> Tuple[Optional[float], List[MediaFile]]:
        """Get cached file list (legacy method for backward compatibility)."""
        cache = self._cache_manager.load_cache(path)
        if not cache:
            return None, []

        files = [self._cached_to_media_file(cf) for cf in cache.files]
        return cache.scan_timestamp, files


class LibraryManager:
    """Unified management of scanning and caching for multiple media libraries

    Maintains both legacy cache dictionary (for backward compatibility) and new
    runtime objects with queue state machines.
    """

    def __init__(self):
        self._scanner = LibraryScanner()
        self._cache: Dict[str, List[MediaFile]] = {}  # path -> cached files (legacy)
        self._runtime_manager = LibraryRuntimeManager()

    def get_runtime(self, path: str) -> Optional['LibraryRuntime']:
        """根据库路径获取运行时对象

        Args:
            path: Media library path to look up

        Returns:
            LibraryRuntime instance or None if not found
        """
        # First check our local cache for already scanned libraries
        normalized_path = os.path.normpath(path)
        for runtime in self._runtime_manager.get_all_runtimes().values():
            if os.path.normpath(runtime.config.path) == normalized_path:
                return runtime

        # Fall back to LibraryRuntimeManager class method (lazy load from config)
        return LibraryRuntimeManager.get_runtime(path)

    def get_queue_for_library(self, path: str) -> Optional[PlaybackQueue]:
        """获取指定媒体库的播放队列

        Args:
            path: Media library path

        Returns:
            PlaybackQueue instance or None if not found
        """
        runtime = self.get_runtime(path)
        return runtime.playback_queue if runtime else None

    def ensure_library_scanned(self, lib_config: Any) -> Optional['LibraryRuntime']:
        """确保库已扫描并返回运行时对象 (lib_config 应为 LibraryConfig 类型)"""
        path_norm = os.path.normpath(lib_config.path)

        # Check existing runtimes
        for runtime in self._runtime_manager.get_all_runtimes().values():
            if os.path.normpath(runtime.config.path) == path_norm:
                return runtime

        # Create new runtime and scan library
        runtime = LibraryRuntime(
            config=lib_config,
            media_files=[]
        )

        # Scan the library files
        from pathlib import Path
        if not Path(lib_config.path).exists():
            return None

        # Use scanner to get files and populate runtime
        files = self._scanner.scan_directory(lib_config.path)
        runtime.media_files = list(files)

        # Use normalized path as key for consistency
        lib_key = os.path.normpath(lib_config.path)
        self._runtime_manager.get_all_runtimes()[lib_key] = runtime

        return runtime

    def refresh_library_from_runtime(self, path: str) -> List[MediaFile]:
        """通过运行时刷新库缓存"""
        runtime = self.get_runtime(path)
        if not runtime:
            # Try to create it from config
            sm = SettingsManager()
            lib_config = get_library_for_file(path, sm.settings.media_libraries)
            if not lib_config:
                return []
            runtime = LibraryRuntime(config=lib_config, media_files=[])

        # Re-scan
        files = self._scanner.scan_directory(runtime.config.path, force_refresh=True)
        runtime.media_files = list(files)

        # Update cache for backward compatibility
        normalized_path = os.path.normpath(path)
        self._cache[normalized_path] = files

        return list(files)

    @classmethod
    def load_libraries(cls) -> 'LibraryManager':
        """Load all media libraries from config and create Manager"""
        from .config import SettingsManager
        manager = cls()

        try:
            sm = SettingsManager()
            libs = sm.settings.media_libraries
            for lib in libs:
                files = manager.refresh_library(lib.path)
                print(f"Loaded {len(files)} files from '{lib.name or lib.path}'")
        except (ImportError, AttributeError, OSError, IOError) as e:
            print(f"Failed to load libraries: {e}")

        return manager

    def refresh_library(self, path: str) -> List[MediaFile]:
        """Refresh single library cache"""
        if not Path(path).exists():
            return []

        files = self._scanner.scan_directory(path, force_refresh=True)
        self._cache[path] = files
        return list(files)

    def get_cached_files(self, path: str) -> List[MediaFile]:
        """Get cached file list"""
        if path in self._cache:
            return list(self._cache[path])

        # Try scanning (without using cache)
        cached = self._scanner.scan_directory(path)
        self._cache[path] = cached
        return list(cached)

    def get_cache_entries(self, path: str) -> List[CachedFile]:
        """The raw cached entries of one library, ``md`` included.

        Separate from :meth:`get_cached_files` on purpose: that one returns the
        *file table* (``MediaFile``, no metadata, and a freshness rule that a refresh
        deliberately bypasses), while batch 4's store needs the entries as written --
        payload and fingerprint together -- to warm-start its three states from.
        """
        return self._scanner.load_cache_entries(path)

    def save_cache_metadata(self, path: str,
                            updates: Dict[str, Tuple[Optional[Dict[str, Any]],
                                                     int, float]]) -> int:
        """Write one metadata batch into a library's cache file; entries stamped.

        The write-back half of batch 4 (spec §4.4: by batch, never per row), reached
        through the scanner because it owns the cache and its path hashing. The policy
        -- which rows may be offered, and the disk re-check each one must pass -- is
        the caller's, because that caller holds the store and the sweep's fingerprints.
        """
        return self._scanner.update_cache_metadata(path, updates)

    def get_all_files(self) -> Dict[str, List[MediaFile]]:
        """Get files from all media libraries"""
        result = {}
        for path in self._cache.keys():
            if Path(path).exists():
                result[path] = list(self._cache[path])
        return result

    def scan_all_libraries(self) -> Dict[str, List[MediaFile]]:
        """Scan all media libraries"""
        from .config import SettingsManager
        try:
            sm = SettingsManager()
            libs = sm.settings.media_libraries
        except (ImportError, AttributeError, OSError, IOError) as e:
            print(f"Failed to load libraries for scanning: {e}")
            return {}

        result = {}
        for lib in libs:
            files = self.refresh_library(lib.path)
            result[lib.path] = files

        return result


# Convenience functions
def scan_directory(path: str, force_refresh: bool = False) -> List[MediaFile]:
    """Convenience function to scan directory"""
    scanner = LibraryScanner()
    return scanner.scan_directory(path, force_refresh=force_refresh)


def get_media_files(directories: List[str]) -> Dict[str, List[MediaFile]]:
    """Get media files from multiple directories"""
    manager = LibraryManager()
    return manager.get_all_files()


def get_library_for_file(filepath: str, libraries) -> Optional[Any]:
    """Determine which library a file belongs to.

    Args:
        filepath: Full path to the media file
        libraries: List of LibraryConfig objects to check against

    Returns:
        The matching LibraryConfig if found, None otherwise
    """
    from pathlib import Path

    if not libraries:
        return None

    filepath_norm = Path(filepath).resolve().as_posix()

    for lib in libraries:
        lib_path = Path(lib.path).resolve().as_posix()
        # Check if file path starts with library path
        if filepath_norm.startswith(lib_path + '/') or filepath_norm == lib_path:
            return lib

    return None


class _HierarchicalPlaylist:
    """Helper class for hierarchical playlist display.

    Supports two modes of operation:
    1. Without library info: Standard recursive hierarchy from file path
    2. With library info: 2-level structure (Library Name → Files/Subdirs within that library)
    """

    def __init__(self):
        # folder_name -> {'files': [], 'children': {}, 'path': str, 'is_folder': True}
        self.root_folders = {}
        self._library_roots: Set[str] = set()  # Library names for 2-level mode

    def add_track(self, full_path: str, display_title: str,
                  library_path: Optional[str] = None,
                  library_name: Optional[str] = None) -> None:
        """Add a track and build hierarchy from its path.

        Args:
            full_path: Complete file path like "/Music/Artists/Artist/song.mp3"
            display_title: Name for display like "song.mp3" or relative path
            library_path: The root path of the media library this file belongs to
            library_name: The display name of the media library (e.g., folder name)

        Notes:
            When library_name is provided, builds a 2-level hierarchy:
                LibraryName
                    relative/path/to/file.mp3
            Otherwise, builds standard recursive hierarchy.
        """
        if library_path and library_name:
            self._build_library_hierarchy(full_path, display_title, library_path, library_name)
        else:
            self._build_standard_hierarchy(full_path, display_title)

    def _build_library_hierarchy(self, full_path: str, display_title: str,
                                  library_path: str, library_name: str) -> None:
        """Build 2-level hierarchy with library as root.

        Structure:
            LibraryName
                relative/path/to/file.mp3
        """
        self._library_roots.add(library_name)
        path_obj = Path(full_path).resolve()
        lib_path_obj = Path(library_path).resolve()

        try:
            # Calculate relative path from library root
            rel_path = path_obj.relative_to(lib_path_obj)
            rel_str = str(rel_path.as_posix())

            # At library level - create top-level entry
            if library_name not in self.root_folders:
                self.root_folders[library_name] = {
                    'files': [],
                    'children': {},
                    'path': lib_path_obj.as_posix(),
                    'is_folder': True,
                    'lib_name': library_name
                }

            # Parse the relative path to build sub-hierarchy within library
            parts = list(rel_path.parts)
            current = self.root_folders[library_name]['children']

            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    # Build full absolute path for this subfolder
                    sub_full_path = lib_path_obj / Path(*parts[:i+1])
                    sub_path = sub_full_path.as_posix()
                    current[part] = {
                        'files': [],
                        'children': {},
                        'path': sub_path,
                        'is_folder': True,
                        'lib_name': library_name
                    }
                current = current[part]['children']

            # Add file to final level within library
            # Calculate parent folder path for the file
            parent_folder_path = str(Path(full_path).parent)
            current[parts[-1]] = {
                'is_file': True,
                'title': display_title,
                'full_path': full_path,
                'lib_name': library_name,
                'rel_path': parts[-1],  # Just the filename for files at leaf level
                'file_rel_full': rel_str,  # Full relative path for display
                'parent_folder_path': parent_folder_path  # For matching with FolderNode
            }

        except ValueError:
            # File is not within the library - add as top-level file in that library
            if library_name not in self.root_folders:
                self.root_folders[library_name] = {
                    'files': [],
                    'children': {},
                    'path': lib_path_obj.as_posix(),
                    'is_folder': True,
                    'lib_name': library_name
                }
            self.root_folders[library_name]['files'].append({
                'is_file': True,
                'title': display_title,
                'full_path': full_path,
                'rel_path': display_title,
                'parent_folder_path': str(Path(full_path).parent)
            })

    def _build_standard_hierarchy(self, full_path: str, display_title: str) -> None:
        """Build standard recursive hierarchy from file path."""
        path_obj = Path(full_path)
        parts = list(path_obj.parts)
        current = self.root_folders

        for i, part in enumerate(parts[:-1]):  # All but last part are folder levels
            if part not in current:
                parent_path_obj = Path(*parts[:i+1])
                parent_path = parent_path_obj.as_posix()
                current[part] = {
                    'files': [],
                    'children': {},
                    'path': parent_path,
                    'is_folder': True
                }
            current = current[part]['children']

        # Add file to final folder level
        current[parts[-1]] = {
            'is_file': True,
            'title': display_title,
            'full_path': full_path,
            'parent_folder_path': str(Path(full_path).parent)
        }

    def build_display_list(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Build list of (display_text, track_info) tuples with indentation.

        Returns:
            List[('Folder Name' or 'Filename', {'is_folder': bool, 'path': str or None, 'title': str})]
        """
        result = []
        self._collect_items(self.root_folders, "", result, is_library_mode=bool(self._library_roots))
        return result

    def _collect_items(self, items: Dict[str, Any], indent: str, result: List[Tuple[str, Dict[str, Any]]],
                       is_library_mode: bool = False) -> None:
        """Recursively collect folders and files."""
        for name in sorted(items.keys()):
            data = items[name]

            if isinstance(data, dict):
                if data.get('is_file'):
                    # File item - use relative path for display
                    track_indent = "  " * (len(indent.split('/')) + 1)
                    file_title = data.get('file_rel_full', data['title'])
                    display_text = track_indent + file_title
                    track_info = {
                        'is_folder': False,
                        'path': data.get('parent_folder_path', data.get('full_path')),
                        'title': data['title'],
                        'full_path': data.get('full_path')
                    }
                    result.append((display_text, track_info))

                elif data.get('is_folder'):
                    # Determine if this is the library root or a subfolder
                    if name in self._library_roots:
                        display_text = name  # MediaLibrary marker
                        folder_indent = ""
                    else:
                        folder_indent = indent + "/ " if indent else "    "
                        display_text = folder_indent + name

                    track_info = {
                        'is_folder': True,
                        'path': data.get('path'),
                        'title': name,
                        'children': data.get('children', {}),
                        'lib_name': data.get('lib_name')
                    }
                    result.append((display_text, track_info))

                    # Recurse into children with proper indent handling
                    children = data.get('children', {})
                    if children:
                        new_indent = folder_indent + "/ " if folder_indent else ""
                        self._collect_items(children, new_indent, result, is_library_mode)
            elif isinstance(data, list):
                # This handles files at library root level (from _build_library_hierarchy fallback)
                for file_item in sorted(data, key=lambda x: x.get('title', '')):
                    track_indent = "    "  # Indent from ML root to files
                    display_text = track_indent + file_item.get('rel_path', file_item['title'])
                    track_info = {
                        'is_folder': False,
                        'path': file_item.get('parent_folder_path', file_item.get('full_path')),
                        'title': file_item['title'],
                        'full_path': file_item.get('full_path')
                    }
                    result.append((display_text, track_info))
