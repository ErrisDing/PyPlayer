#!/usr/bin/env python3
"""
Library Selector - Widget for switching between media libraries
"""

from typing import Optional, List, Any
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class LibrarySelector(QWidget):
    """
    Widget for selecting between multiple media libraries.

    Displays as a horizontal row of buttons, one for each library.
    The currently selected library is highlighted.
    """

    # Signal emitted when a library is selected
    library_selected = pyqtSignal(str)  # library_path

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._libraries: List[Any] = []
        self._current_path: str = ""
        self._buttons: List[QPushButton] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(5)

        # Add stretch to push buttons to the left
        self._layout.addStretch()

    def set_libraries(self, libraries: List[Any]) -> None:
        """
        Set the list of available libraries.

        Args:
            libraries: List of LibraryConfig objects
        """
        self._libraries = libraries
        self._rebuild_buttons()

    def set_current_library(self, library_path: str) -> None:
        """
        Set the currently selected library.

        Args:
            library_path: Path to the current library
        """
        self._current_path = library_path
        self._update_button_styles()

    def _rebuild_buttons(self) -> None:
        """Rebuild the button list from current libraries."""
        # Clear existing buttons
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()

        # Create new buttons
        for lib in self._libraries:
            name = lib.name if lib.name else Path(lib.path).name
            button = QPushButton(name)
            button.setProperty("library_path", lib.path)
            # Scope for the generated sheet: QPushButton[chip="true"] styles the
            # media-library chips, since objectNames would not scale per library.
            button.setProperty("chip", "true")
            button.clicked.connect(lambda checked, p=lib.path: self._on_button_click(p))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            # No per-widget stylesheet: the sheet owns the chip's resting,
            # hover, selected, disabled and focus looks.

            self._buttons.append(button)
            # Insert before stretch
            self._layout.insertWidget(self._layout.count() - 1, button)

        # Update styles for current selection
        self._update_button_styles()

    def _update_button_styles(self) -> None:
        """Update button styles based on current selection."""
        for button in self._buttons:
            lib_path = button.property("library_path")
            is_selected = lib_path == self._current_path
            # "selected"/"chip" are QSS property selectors. Strings are the
            # declared contract of this widget tree, and the structure test
            # asserts them as strings; Qt would in fact also match a Python
            # bool, because its attribute selector special-cases
            # QMetaType::Bool into "true"/"false". The strings stay anyway --
            # they are what the sheet is written against and what a reader can
            # grep.
            button.setProperty("selected", "true" if is_selected else "false")
            # Force style refresh
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_button_click(self, library_path: str) -> None:
        """Handle button click."""
        if library_path != self._current_path:
            self._current_path = library_path
            self._update_button_styles()
            self.library_selected.emit(library_path)

    def clear(self) -> None:
        """Clear all libraries."""
        self._libraries = []
        self._current_path = ""
        self._rebuild_buttons()
