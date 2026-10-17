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
    appearance_changed = pyqtSignal()     # emitted when appearance settings change
    theme_changed = pyqtSignal(str)       # emitted with the new mode (auto/light/dark)

    def __init__(
        self,
        config_file: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        """Create the service.

        Args:
            config_file: Settings file to read and write. Defaults to the
                cache location (``~/.pyplayer/cache/settings.json``), with the
                one-time migration from the project root that
                :class:`SettingsManager` performs. Tests pass a temporary path
                so a signal test cannot rewrite a real user's configuration.
            parent: Optional ``QObject`` parent.
        """
        super().__init__(parent)
        self._manager = SettingsManager(config_file)

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

    def get_background_image(self) -> Optional[str]:
        """Get the background image path from settings."""
        return self._manager.get_background_image()

    def set_background_image(self, path: Optional[str]) -> bool:
        """
        Set the background image path.

        Args:
            path: Path to the background image, or None to clear.

        Returns:
            True if saved successfully.
        """
        result = self._manager.set_background_image(path)
        if result:
            self.config_saved.emit()
        return result

    # === Theme Methods ===

    def get_theme(self) -> str:
        """Get the theme mode: ``'auto'``, ``'light'`` or ``'dark'``."""
        return self._manager.get_theme()

    def set_theme(self, mode: str) -> bool:
        """Persist the theme mode and emit :attr:`theme_changed`.

        Returns:
            True if the mode was saved; False (and no signal) for a mode the
            theme layer cannot resolve. The listener order matters here: the
            presenter persists first and only then hands the mode to
            ``ThemeManager.set_mode``, which raises on a bad value.
        """
        result = self._manager.set_theme(mode)
        if result:
            self.theme_changed.emit(mode)
        return result

    # === Appearance Settings Methods ===

    def get_overlay_alpha(self) -> float:
        """Get background overlay transparency."""
        return self._manager.get_overlay_alpha()

    def set_overlay_alpha(self, alpha: float) -> bool:
        """Set background overlay transparency."""
        result = self._manager.set_overlay_alpha(alpha)
        if result:
            self.appearance_changed.emit()
        return result

    def get_playlist_alpha(self) -> float:
        """Get playlist background transparency."""
        return self._manager.get_playlist_alpha()

    def set_playlist_alpha(self, alpha: float) -> bool:
        """Set playlist background transparency."""
        result = self._manager.set_playlist_alpha(alpha)
        if result:
            self.appearance_changed.emit()
        return result

    def get_controls_alpha(self) -> float:
        """Get playback controls transparency."""
        return self._manager.get_controls_alpha()

    def set_controls_alpha(self, alpha: float) -> bool:
        """Set playback controls transparency."""
        result = self._manager.set_controls_alpha(alpha)
        if result:
            self.appearance_changed.emit()
        return result
