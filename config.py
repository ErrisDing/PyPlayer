#!/usr/bin/env python3
"""
PyPlayer Configuration Management Module
Handles reading/writing settings.xml and provides persistent storage for media library configuration
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import xml.etree.ElementTree as ET
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


class SettingsManager:
    """Configuration file read/write manager"""

    DEFAULT_FILE = "settings.json"
    XML_FILE = "settings.xml"
    CONFIG_VERSION = "2.0"

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = Path(config_file or self.DEFAULT_FILE).resolve()
        self._settings: Optional[Settings] = None
        # Auto-load configuration
        _ = self.settings
        # Check for and perform migration from XML to JSON if needed
        self._check_and_migrate()

    def _check_and_migrate(self) -> None:
        """Check and perform configuration migration from XML to JSON if needed"""
        json_path = self.config_file
        xml_path = json_path.parent / self.XML_FILE

        # Case 1: JSON already exists, no migration needed
        if json_path.exists():
            return

        # Case 2: XML exists, JSON doesn't, perform migration
        if xml_path.exists():
            self._migrate_xml_to_json(xml_path, json_path)

        # Case 3: Neither exists, first run (will create JSON later)

    def _migrate_xml_to_json(self, xml_path: Path, json_path: Path) -> bool:
        """Migrate configuration from XML to JSON format"""
        try:
            # 1. Parse XML
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # 2. Extract data
            last_updated = root.get('last_updated', datetime.now().isoformat())

            libraries = []
            media_libs_elem = root.find("media_libraries")
            if media_libs_elem is not None:
                for lib_elem in media_libs_elem.findall("library"):
                    path = lib_elem.get("path", "")
                    if path:
                        name = lib_elem.get("name", None)
                        libraries.append({
                            "path": os.path.normpath(path),
                            "name": name
                        })

            # 3. Build JSON data
            data = {
                "version": self.CONFIG_VERSION,
                "last_updated": last_updated,
                "media_libraries": libraries
            }

            # 4. Atomic write to JSON
            temp_path = json_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            temp_path.rename(json_path)

            # 5. Backup original XML file
            backup_path = xml_path.with_suffix('.xml.backup')
            try:
                xml_path.rename(backup_path)
                print(f"Migrated configuration to {json_path}, backup at {backup_path}")
            except OSError as e:
                print(f"Migration successful but backup failed: {e}")

            return True

        except (ET.ParseError, OSError, IOError, TypeError) as e:
            print(f"Migration failed: {e}")
            if 'temp_path' in locals() and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return False

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

        return Settings(media_libraries=libraries)

    def _create_empty_settings(self) -> Settings:
        """Create empty settings object"""
        return Settings()

    def load(self) -> Settings:
        """Load configuration file (supports JSON with XML fallback)"""
        try:
            # Priority 1: Load JSON
            if self.config_file.exists():
                self._settings = self._load_json()
                return self._settings

            # JSON doesn't exist, check XML (migration might have failed)
            xml_path = self.config_file.parent / self.XML_FILE
            if xml_path.exists():
                print(f"JSON config missing but XML exists, attempting migration...")
                if self._migrate_xml_to_json(xml_path, self.config_file):
                    self._settings = self._load_json()
                    return self._settings

            # Neither exists, create new configuration
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
                "media_libraries": libraries
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
