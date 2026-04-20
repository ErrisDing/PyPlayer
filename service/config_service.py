#!/usr/bin/env python3
"""
Config Service - Configuration management with PyQt signals
"""

from typing import List, Optional
from PyQt6.QtCore import QObject, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import SettingsManager, Settings, LibraryConfig


class ConfigService(QObject):
    """
    Service for configuration management.
    Provides signals for configuration changes.
    """

    # Signals
    library_added = pyqtSignal(str)       # library_path
    library_removed = pyqtSignal(str)     # library_path
    libraries_reordered = pyqtSignal()    # emitted when library order changes
    config_saved = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = SettingsManager()

    @property
    def settings(self) -> Settings:
        """Get current settings."""
        return self._manager.settings

    def get_libraries(self) -> List[LibraryConfig]:
        """Get all configured libraries."""
        return self.settings.media_libraries

    def add_library(self, path: str, name: Optional[str] = None) -> bool:
        """
        Add a media library.

        Args:
            path: Path to the library directory
            name: Optional display name

        Returns:
            True if successful
        """
        result = self._manager.add_library(path, name)
        if result:
            self.library_added.emit(path)
        return result

    def remove_library(self, path: str) -> bool:
        """
        Remove a media library.

        Args:
            path: Path to the library

        Returns:
            True if successful
        """
        result = self._manager.remove_library(path)
        if result:
            self.library_removed.emit(path)
        return result

    def save(self) -> bool:
        """Save configuration to file."""
        result = self._manager.save()
        if result:
            self.config_saved.emit()
        return result

    def get_library_by_path(self, path: str) -> Optional[LibraryConfig]:
        """Get library configuration by path."""
        return self.settings.get_library_by_path(path)

    def reorder_library(self, old_index: int, new_index: int) -> bool:
        """
        Move a library from old_index to new_index.

        Args:
            old_index: Current position of the library
            new_index: Target position

        Returns:
            True if successful
        """
        result = self._manager.reorder_library(old_index, new_index)
        if result:
            self.libraries_reordered.emit()
        return result

    def move_library_up(self, index: int) -> bool:
        """
        Move library at index up one position.

        Args:
            index: Current position of the library

        Returns:
            True if successful
        """
        if index <= 0:
            return False
        return self.reorder_library(index, index - 1)

    def move_library_down(self, index: int) -> bool:
        """
        Move library at index down one position.

        Args:
            index: Current position of the library

        Returns:
            True if successful
        """
        if index < 0 or index >= len(self.settings.media_libraries) - 1:
            return False
        return self.reorder_library(index, index + 1)
