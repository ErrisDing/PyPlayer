#!/usr/bin/env python3
"""
PyPlayer 媒体库管理模块
负责扫描目录获取媒体文件列表，提供缓存机制避免重复扫描
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class MediaFile:
    """表示单个媒体文件信息"""
    path: str
    title: str
    file_type: str      # 'audio' or 'video'
    extension: str      # 扩展名 (如 .mp3)
    size_bytes: int = 0
    modified_time: float = 0.0

    def __post_init__(self):
        try:
            stat_info = os.stat(self.path)
            self.size_bytes = stat_info.st_size
            self.modified_time = stat_info.st_mtime
        except OSError:
            pass


# 支持的媒体文件扩展名
SUPPORTED_AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
SUPPORTED_VIDEO = {'.avi', '.mp4', '.mkv', '.mov', '.wmv'}
ALL_SUPPORTED = SUPPORTED_AUDIO | SUPPORTED_VIDEO

# 需要跳过的目录
SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'vendor', 'build', 'dist'}


class LibraryScanner:
    """递归扫描目录获取媒体文件"""

    def __init__(self):
        self._scanned_times: Dict[str, float] = {}  # path -> scan timestamp

    def _is_supported_file(self, filename: str) -> bool:
        """判断是否为支持的媒体文件"""
        ext = Path(filename).suffix.lower()
        return ext in ALL_SUPPORTED

    def _is_skip_directory(self, directory: str) -> bool:
        """判断是否为需要跳过的目录"""
        dir_name = os.path.basename(directory.lower())
        return dir_name in SKIP_DIRS or any(skip in directory.lower() for skip in ['node_modules', '.git'])

    def scan_directory(self, directory: str, force_refresh: bool = False) -> List[MediaFile]:
        """
        扫描目录获取媒体文件列表
        :param directory: 要扫描的目录路径
        :param force_refresh: 是否强制重新扫描（忽略缓存）
        :return: MediaFile 列表
        """
        directory = os.path.normpath(directory)

        # 检查缓存（除非强制刷新）
        cache_key = os.path.normpath(directory)
        if not force_refresh and cache_key in self._scanned_times:
            cached_time, files = self._get_cached_files(cache_key)
            # 简单检查：如果目录修改时间未变化，返回缓存
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
            # 跳过指定目录（原地修改 dirs 以阻止 os.walk 进入子目录）
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

        # 更新缓存
        self._scanned_times[cache_key] = datetime.now().timestamp()
        return files

    def _get_cached_files(self, path: str):
        """获取已缓存的文件列表"""
        cache_dir = Path.home() / '.pyplayer' / 'cache'
        cache_file = cache_dir / f'{hash(path)}.cache'

        if not cache_file.exists():
            return None, []

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 简单解析：第一行是时间戳，后续是文件路径
                lines = content.strip().split('\n')
                if not lines:
                    return None, []
                cached_time = float(lines[0])
                file_paths = [l for l in lines[1:] if l]

                # 重新构建 MediaFile 对象
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
        except Exception:
            return None, []


class LibraryManager:
    """统一管理多个媒体库的扫描和缓存"""

    def __init__(self):
        self._scanner = LibraryScanner()
        self._cache: Dict[str, List[MediaFile]] = {}  # path -> cached files

    @classmethod
    def load_libraries(cls) -> 'LibraryManager':
        """从配置加载所有媒体库并创建 Manager"""
        from config import SettingsManager
        manager = cls()

        try:
            sm = SettingsManager()
            libs = sm.settings.media_libraries
            for lib in libs:
                files = manager.refresh_library(lib.path)
                print(f"Loaded {len(files)} files from '{lib.name or lib.path}'")
        except Exception as e:
            print(f"Failed to load libraries: {e}")

        return manager

    def refresh_library(self, path: str) -> List[MediaFile]:
        """刷新单个库缓存"""
        if not Path(path).exists():
            return []

        files = self._scanner.scan_directory(path, force_refresh=True)
        self._cache[path] = files
        return list(files)

    def get_cached_files(self, path: str) -> List[MediaFile]:
        """获取已缓存文件列表"""
        if path in self._cache:
            return list(self._cache[path])

        # 尝试扫描（不使用缓存）
        cached = self._scanner.scan_directory(path)
        self._cache[path] = cached
        return list(cached)

    def get_all_files(self) -> Dict[str, List[MediaFile]]:
        """获取所有媒体库的文件"""
        result = {}
        for path in self._cache.keys():
            if Path(path).exists():
                result[path] = list(self._cache[path])
        return result

    def scan_all_libraries(self) -> Dict[str, List[MediaFile]]:
        """扫描所有媒体库"""
        from config import SettingsManager
        try:
            sm = SettingsManager()
            libs = sm.settings.media_libraries
        except Exception as e:
            print(f"Failed to load libraries for scanning: {e}")
            return {}

        result = {}
        for lib in libs:
            files = self.refresh_library(lib.path)
            result[lib.path] = files

        return result


# 便捷函数
def scan_directory(path: str, force_refresh: bool = False) -> List[MediaFile]:
    """扫描目录的便捷函数"""
    scanner = LibraryScanner()
    return scanner.scan_directory(path, force_refresh=force_refresh)


def get_media_files(directories: List[str]) -> Dict[str, List[MediaFile]]:
    """从多个目录获取媒体文件"""
    manager = LibraryManager()
    return manager.get_all_files()


class _HierarchicalPlaylist:
    """Helper class for hierarchical playlist display with full path support"""

    def __init__(self):
        # folder_name -> {'files': [], 'children': {}, 'path': str, 'is_folder': True}
        self.root_folders = {}

    def add_track(self, full_path: str, display_title: str):
        """Add a track and build hierarchy from its path

        Args:
            full_path: 完整的文件路径如 "/Music/Artists/Artist/song.mp3"
            display_title: 用于显示的名称如 "song.mp3" or relative path
        """
        # Parse the full path to build hierarchy - normalize separators first
        normalized_path = str(Path(full_path)).replace('\\', '/')
        parts = [p for p in normalized_path.split('/') if p]  # Filter out empty strings
        current = self.root_folders

        for i, part in enumerate(parts[:-1]):  # All but last part are folder levels
            if part not in current:
                parent_path = '/' + '/'.join(parts[:i+1])
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

    def build_display_list(self):
        """Build list of (display_text, track_info) tuples with indentation

        Returns:
            List[('[D] Folder Name' or '[F] Filename', {'is_folder': bool, 'path': str or None, 'title': str})]
        """
        result = []
        self._collect_items(self.root_folders, "", result)
        return result

    def _collect_items(self, items, indent, result):
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
