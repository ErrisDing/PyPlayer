#!/usr/bin/env python3
"""
Library Management Dialog - Dialog for managing media libraries
"""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import LibraryConfig
from core import i18n


class LibraryManagementDialog(QDialog):
    """
    Dialog for managing media libraries.

    Features:
    - List all configured libraries with names and paths
    - Add new library (opens folder dialog)
    - Delete selected library
    - Reorder libraries (up/down buttons)

    Follows MVP pattern: emits signals, does not call services directly.
    """

    # Signals for Presenter to handle
    add_library_requested = pyqtSignal(str)           # folder_path
    remove_library_requested = pyqtSignal(str)        # library_path
    reorder_requested = pyqtSignal(int, int)          # old_index, new_index

    def __init__(self, libraries: List[LibraryConfig],
                 parent: Optional[QWidget] = None):
        """
        Initialize dialog with current library state.

        Args:
            libraries: Current list of LibraryConfig objects
            parent: Parent widget
        """
        super().__init__(parent)

        # Ensure i18n is initialized
        i18n.detect_init()

        self._libraries = libraries

        self._setup_ui()
        self._populate_list()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle(i18n.dialog('dialog.title.library_management'))
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)

        # Library list
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list_widget)

        # Button row for list actions
        list_button_layout = QHBoxLayout()

        self._add_button = QPushButton(i18n.get('button.add'))
        self._add_button.clicked.connect(self._on_add)
        list_button_layout.addWidget(self._add_button)

        self._delete_button = QPushButton(i18n.get('button.delete'))
        self._delete_button.clicked.connect(self._on_delete)
        self._delete_button.setEnabled(False)
        list_button_layout.addWidget(self._delete_button)

        list_button_layout.addStretch()

        self._up_button = QPushButton(i18n.get('button.move_up'))
        self._up_button.clicked.connect(self._on_move_up)
        self._up_button.setEnabled(False)
        list_button_layout.addWidget(self._up_button)

        self._down_button = QPushButton(i18n.get('button.move_down'))
        self._down_button.clicked.connect(self._on_move_down)
        self._down_button.setEnabled(False)
        list_button_layout.addWidget(self._down_button)

        layout.addLayout(list_button_layout)

        # Close button row
        close_layout = QHBoxLayout()
        close_layout.addStretch()

        self._close_button = QPushButton(i18n.get('button.close'))
        self._close_button.clicked.connect(self.accept)
        close_layout.addWidget(self._close_button)

        layout.addLayout(close_layout)

    def _populate_list(self) -> None:
        """Populate the list widget with libraries."""
        self._list_widget.clear()

        for lib in self._libraries:
            item = QListWidgetItem(f"{lib.name}\n{lib.path}")
            item.setData(Qt.ItemDataRole.UserRole, lib.path)
            self._list_widget.addItem(item)

    def _on_selection_changed(self) -> None:
        """Handle selection change in the list."""
        has_selection = len(self._list_widget.selectedItems()) > 0
        self._delete_button.setEnabled(has_selection)
        self._up_button.setEnabled(has_selection)
        self._down_button.setEnabled(has_selection)

    def _on_add(self) -> None:
        """Handle add button click."""
        from PyQt6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(
            self,
            i18n.get('dialog.add_library')
        )
        if folder:
            self.add_library_requested.emit(folder)

    def _on_delete(self) -> None:
        """Handle delete button click."""
        selected = self._list_widget.currentItem()
        if not selected:
            return

        library_path = selected.data(Qt.ItemDataRole.UserRole)
        library_name = library_path.split('/')[-1] if '/' in library_path else library_path.split('\\')[-1]

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            i18n.dialog('dialog.title.confirm'),
            i18n.dialog('dialog.confirm_delete_media_lib').format(path=library_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.remove_library_requested.emit(library_path)

    def _on_move_up(self) -> None:
        """Handle move up button click."""
        current_row = self._list_widget.currentRow()
        if current_row > 0:
            self.reorder_requested.emit(current_row, current_row - 1)

    def _on_move_down(self) -> None:
        """Handle move down button click."""
        current_row = self._list_widget.currentRow()
        if current_row < self._list_widget.count() - 1:
            self.reorder_requested.emit(current_row, current_row + 1)

    # === Public API for Presenter ===

    def set_libraries(self, libraries: List[LibraryConfig]) -> None:
        """Update the library list display."""
        self._libraries = libraries
        self._populate_list()

    def get_selected_library_path(self) -> Optional[str]:
        """Get the path of the currently selected library."""
        selected = self._list_widget.currentItem()
        if selected:
            return selected.data(Qt.ItemDataRole.UserRole)
        return None
