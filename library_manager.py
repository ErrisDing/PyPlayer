#!/usr/bin/env python3
"""
PyPlayer Media Library Management Module
Scans directories for media files and provides caching to avoid repeated scans
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime


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


# Supported media file extensions
SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}
ALL_SUPPORTED = SUPPORTED_AUDIO | SUPPORTED_VIDEO

# Directories to skip
SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'vendor', 'build', 'dist'}


class LibraryScanner:
    """Recursively scan directories to get media files"""

    def __init__(self):
        self._scanned_times: Dict[str, float] = {}  # path -> scan timestamp

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

        # Check cache (unless forced refresh)
        cache_key = os.path.normpath(directory)
        if not force_refresh and cache_key in self._scanned_times:
            cached_time, files = self._get_cached_files(cache_key)
            # Simple check: if directory modification time unchanged, return cache
            try:
                dir_stat = os.stat(directory)
                if dir_stat.st_mtime <= cached_time:
                    return list(files)
            except OSError:
                pass

        files = []

        if not Path(directory).exists():
            return files

        for root, dirs, filenames in os.walk(directory):
            # Skip specified directories (modify dirs in-place to prevent os.walk from entering subdirectories)
            dirs[:] = [d for d in dirs if not self._is_skip_directory(os.path.join(root, d))]

            for filename in sorted(filenames):
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

        # Update cache
        self._scanned_times[cache_key] = datetime.now().timestamp()
        return files

    def _get_cached_files(self, path: str) -> Tuple[Optional[float], List[MediaFile]]:
        """Get cached file list"""
        cache_dir = Path.home() / '.pyplayer' / 'cache'
        cache_file = cache_dir / f'{hash(path)}.cache'

        if not cache_file.exists():
            return None, []

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Simple parsing: first line is timestamp, subsequent lines are file paths
                lines = content.strip().split('\n')
                if not lines:
                    return None, []
                cached_time = float(lines[0])
                file_paths = [l for l in lines[1:] if l]

                # Reconstruct MediaFile objects
                files = []
                for p in file_paths:
                    try:
                        stat_info = os.stat(p)
                        ext = Path(p).suffix.lower()
                        file_type = 'audio' if ext in SUPPORTED_AUDIO else 'video'
                        files.append(MediaFile(
                            path=p,
                            title=Path(p).name,
                            file_type=file_type,
                            extension=ext,
                            size_bytes=stat_info.st_size,
                            modified_time=stat_info.st_mtime
                        ))
                    except OSError:
                        pass

                return cached_time, files
        except (OSError, IOError, ValueError, UnicodeDecodeError):
            return None, []


class LibraryManager:
    """Unified management of scanning and caching for multiple media libraries"""

    def __init__(self):
        self._scanner = LibraryScanner()
        self._cache: Dict[str, List[MediaFile]] = {}  # path -> cached files

    @classmethod
    def load_libraries(cls) -> 'LibraryManager':
        """Load all media libraries from config and create Manager"""
        from config import SettingsManager
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

    def get_all_files(self) -> Dict[str, List[MediaFile]]:
        """Get files from all media libraries"""
        result = {}
        for path in self._cache.keys():
            if Path(path).exists():
                result[path] = list(self._cache[path])
        return result

    def scan_all_libraries(self) -> Dict[str, List[MediaFile]]:
        """Scan all media libraries"""
        from config import SettingsManager
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


class _HierarchicalPlaylist:
    """Helper class for hierarchical playlist display with full path support"""

    def __init__(self):
        # folder_name -> {'files': [], 'children': {}, 'path': str, 'is_folder': True}
        self.root_folders = {}

    def add_track(self, full_path: str, display_title: str) -> None:
        """Add a track and build hierarchy from its path

        Args:
            full_path: Complete file path like "/Music/Artists/Artist/song.mp3"
            display_title: Name for display like "song.mp3" or relative path
        """
        # Parse the full path to build hierarchy - use Path object for cross-platform compatibility
        path_obj = Path(full_path)
        parts = list(path_obj.parts)  # Get path components as tuple
        current = self.root_folders

        for i, part in enumerate(parts[:-1]):  # All but last part are folder levels
            if part not in current:
                # Use Path object to build cross-platform path
                parent_path_obj = Path(*parts[:i+1])
                parent_path = parent_path_obj.as_posix()  # Use forward slashes for consistency
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
            'full_path': full_path
        }

    def build_display_list(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Build list of (display_text, track_info) tuples with indentation

        Returns:
            List[('[D] Folder Name' or '[F] Filename', {'is_folder': bool, 'path': str or None, 'title': str})]
        """
        result = []
        self._collect_items(self.root_folders, "", result)
        return result

    def _collect_items(self, items: Dict[str, Any], indent: str, result: List[Tuple[str, Dict[str, Any]]]) -> None:
        """Recursively collect folders and files"""
        for name, data in sorted(items.items()):
            if data.get('is_file'):
                track_indent = "  " * len(indent.split('/')) + "  " if indent else ""
                # Use ASCII-compatible symbols: F=File, D=Directory (folder)
                display_text = track_indent + "[F] " + data['title']
                track_info = {
                    'is_folder': False,
                    'path': data.get('full_path'),
                    'title': data['title'],
                    'full_path': data.get('full_path')
                }
                result.append((display_text, track_info))
            else:
                folder_indent = indent + "/ " if indent else ""
                # Use ASCII-compatible symbol for folders
                display_text = folder_indent + "[D] " + name
                track_info = {
                    'is_folder': True,
                    'path': data.get('path'),
                    'title': name,
                    'children': data.get('children', {})
                }
                result.append((display_text, track_info))
                self._collect_items(data.get('children', {}), folder_indent, result)
