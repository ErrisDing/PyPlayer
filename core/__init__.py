#!/usr/bin/env python3
"""
PyPlayer Core Module
Provides core functionality: playback, library management, configuration, i18n
"""

from .player import AudioPlayer, PlayerManager, PlayerState, create_manager
from .library_manager import (
    LibraryManager, LibraryRuntime, PlaybackQueue, PlaybackState,
    QueueNode, FileNode, FolderNode, Track, DisplayIndexMap, MediaFile
)
from .config import SettingsManager, Settings, LibraryConfig
from .cache_manager import LibraryCacheManager, LibraryCache, CachedFile
from .metadata import SongMetadata, extract_metadata
from . import i18n

__all__ = [
    # Player
    'AudioPlayer', 'PlayerManager', 'PlayerState', 'create_manager',
    # Library
    'LibraryManager', 'LibraryRuntime', 'PlaybackQueue', 'PlaybackState',
    'QueueNode', 'FileNode', 'FolderNode', 'Track', 'DisplayIndexMap', 'MediaFile',
    # Config
    'SettingsManager', 'Settings', 'LibraryConfig',
    # Cache
    'LibraryCacheManager', 'LibraryCache', 'CachedFile',
    # Metadata
    'SongMetadata', 'extract_metadata',
    # i18n
    'i18n',
]
