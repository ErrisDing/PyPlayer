#!/usr/bin/env python3
"""
PyPlayer Configuration Management Module
Handles reading/writing settings.json in cache directory
"""

import os
import json
import shutil
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime


@dataclass
class LibraryConfig:
    """Represents configuration for a single media library"""
    path: str
    name: Optional[str] = None

    def __post_init__(self):
        if self.name is None:
            self.name = Path(self.path).name


@dataclass
class Settings:
    """Represents the complete system configuration"""
    media_libraries: List[LibraryConfig] = field(default_factory=list)
    background_image: Optional[str] = None  # 自定义背景图片路径

    def add_library(self, path: str, name: Optional[str] = None) -> LibraryConfig:
        """Add a media library and return the configuration object"""
        lib_config = LibraryConfig(path=path, name=name)
        if not self.get_library_by_path(path):
            self.media_libraries.append(lib_config)
        return lib_config

    def remove_library(self, path: str) -> bool:
        """Delete media library at specified path, return success status"""
        path = os.path.normpath(path)
        for i, lib in enumerate(self.media_libraries):
            if os.path.normpath(lib.path) == path:
                del self.media_libraries[i]
                return True
        return False

    def get_library_by_path(self, path: str) -> Optional[LibraryConfig]:
        """Find media library configuration by path"""
        path = os.path.normpath(path)
        for lib in self.media_libraries:
            if os.path.normpath(lib.path) == path:
                return lib
        return None

    def reorder_library(self, old_index: int, new_index: int) -> bool:
        """
        Move a library from old_index to new_index.

        Args:
            old_index: Current position of the library
            new_index: Target position

        Returns:
            True if successful, False if indices are invalid
        """
        if old_index < 0 or old_index >= len(self.media_libraries):
            return False
        if new_index < 0 or new_index >= len(self.media_libraries):
            return False
        if old_index == new_index:
            return True

        library = self.media_libraries.pop(old_index)
        self.media_libraries.insert(new_index, library)
        return True


class SettingsManager:
    """Configuration file read/write manager"""

    CONFIG_VERSION = "2.0"

    @classmethod
    def _get_default_config_path(cls) -> Path:
        """Get the default configuration file path in cache directory."""
        cache_dir = Path.home() / '.pyplayer' / 'cache'
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / 'settings.json'

    def __init__(self, config_file: Optional[str] = None):
        if config_file is None:
            self.config_file = self._get_default_config_path()
            self._migrate_from_root()
        else:
            self.config_file = Path(config_file).resolve()
        self._settings: Optional[Settings] = None
        _ = self.settings

    def _migrate_from_root(self) -> None:
        """One-time migration from project root to cache directory."""
        if self.config_file.exists():
            return

        old_config = Path(__file__).parent.parent / 'settings.json'
        if old_config.exists():
            try:
                shutil.copy2(old_config, self.config_file)
                print(f"Migrated config to {self.config_file}")
            except (OSError, IOError) as e:
                print(f"Failed to migrate config: {e}")

    @property
    def settings(self) -> Settings:
        """Get current configuration (auto-read if not loaded)"""
        if self._settings is None:
            self.load()
        return self._settings

    def _load_json(self) -> Settings:
        """Load JSON configuration file"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate version
        version = data.get('version', '1.0')
        if version != self.CONFIG_VERSION:
            print(f"Warning: Config version {version} differs from expected {self.CONFIG_VERSION}")

        # Parse media libraries
        libraries = []
        for lib_data in data.get('media_libraries', []):
            path = lib_data.get('path', '')
            if path:
                libraries.append(LibraryConfig(
                    path=path,
                    name=lib_data.get('name', None)
                ))

        # Parse background image path
        background_image = data.get('background_image', None)

        return Settings(media_libraries=libraries, background_image=background_image)

    def _create_empty_settings(self) -> Settings:
        """Create empty settings object"""
        return Settings()

    def load(self) -> Settings:
        """Load configuration from JSON file."""
        try:
            if self.config_file.exists():
                self._settings = self._load_json()
                return self._settings

            # Create new empty configuration
            self._settings = self._create_empty_settings()
            return self._settings

        except Exception as e:
            print(f"Failed to load config: {e}, using empty config")
            self._settings = self._create_empty_settings()
            return self._settings

    def save(self) -> bool:
        """Save configuration to JSON file"""
        if self._settings is None:
            self._settings = Settings()

        try:
            # Build JSON data
            libraries = []
            for lib in self._settings.media_libraries:
                lib_dict = {"path": os.path.normpath(lib.path)}
                if lib.name and lib.name != Path(lib.path).name:
                    lib_dict["name"] = lib.name
                libraries.append(lib_dict)

            data = {
                "version": self.CONFIG_VERSION,
                "last_updated": datetime.now().isoformat(),
                "media_libraries": libraries,
                "background_image": self._settings.background_image
            }

            # Atomic write
            parent_dir = self.config_file.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

            temp_path = self.config_file.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Replace original file (os.replace works on Windows to overwrite existing files)
            os.replace(temp_path, self.config_file)
            return True

        except (OSError, IOError, TypeError) as e:
            print(f"Failed to save config: {e}")
            return False

    def add_library(self, path: str, name: Optional[str] = None) -> bool:
        """Add media library and save to file immediately"""
        if not os.path.exists(path):
            print(f"Path does not exist: {path}")
            return False

        self.settings.add_library(path=path, name=name)
        return self.save()

    def remove_library(self, path: str) -> bool:
        """Delete media library and save to file immediately"""
        if not self.settings.remove_library(path):
            print(f"Media library not found: {path}")
            return False

        return self.save()

    def reorder_library(self, old_index: int, new_index: int) -> bool:
        """
        Move a library from old_index to new_index and save.

        Args:
            old_index: Current position of the library
            new_index: Target position

        Returns:
            True if successful
        """
        if not self.settings.reorder_library(old_index, new_index):
            return False
        return self.save()

    def get_background_image(self) -> Optional[str]:
        """Get the background image path from settings."""
        return self.settings.background_image

    def set_background_image(self, path: Optional[str]) -> bool:
        """
        Set the background image path and save to file immediately.

        Args:
            path: Path to the background image, or None to clear.

        Returns:
            True if saved successfully.
        """
        self.settings.background_image = path
        return self.save()

    def _create_empty_config(self) -> None:
        """Create empty JSON configuration file"""
        data = {
            "version": self.CONFIG_VERSION,
            "last_updated": datetime.now().isoformat(),
            "media_libraries": []
        }

        parent_dir = self.config_file.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
