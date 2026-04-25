#!/usr/bin/env python3
"""
Appearance Configuration Dialog - Dialog for customizing UI appearance
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QGroupBox, QFileDialog, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n
from core.constants import AppearanceDefaults


class AppearanceDialog(QDialog):
    """
    Dialog for configuring application appearance.

    Features:
    - Background image selection and clearing
    - Background overlay transparency slider
    - Playlist transparency slider
    - Playback controls transparency slider

    Follows MVP pattern: emits signals, does not call services directly.
    """

    # Signals for Presenter to handle
    background_image_changed = pyqtSignal(str)       # image path (empty string to clear)
    overlay_alpha_changed = pyqtSignal(float)        # 0.0 - 1.0
    playlist_alpha_changed = pyqtSignal(float)       # 0.0 - 1.0
    controls_alpha_changed = pyqtSignal(float)       # 0.0 - 1.0

    def __init__(
        self,
        background_image: Optional[str],
        overlay_alpha: float,
        playlist_alpha: float,
        controls_alpha: float,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        # Ensure i18n is initialized
        i18n.detect_init()

        self._background_image = background_image

        # Store current values (0.0-1.0 scale)
        self._overlay_alpha = overlay_alpha
        self._playlist_alpha = playlist_alpha
        self._controls_alpha = controls_alpha

        self._setup_ui()
        self._populate_values()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        self.setWindowTitle(i18n.dialog('dialog.title.appearance'))
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # === Background Image Group ===
        bg_group = QGroupBox(i18n.dialog('appearance.group.background'))
        bg_layout = QVBoxLayout(bg_group)

        # Current background display
        self._bg_path_label = QLabel(i18n.dialog('appearance.no_background'))
        self._bg_path_label.setWordWrap(True)
        self._bg_path_label.setStyleSheet("color: #666; font-style: italic;")
        bg_layout.addWidget(self._bg_path_label)

        # Background buttons
        bg_btn_layout = QHBoxLayout()

        self._select_bg_btn = QPushButton(i18n.dialog('appearance.select_image'))
        self._select_bg_btn.clicked.connect(self._on_select_background)
        bg_btn_layout.addWidget(self._select_bg_btn)

        self._clear_bg_btn = QPushButton(i18n.dialog('appearance.clear_image'))
        self._clear_bg_btn.clicked.connect(self._on_clear_background)
        bg_btn_layout.addWidget(self._clear_bg_btn)

        bg_btn_layout.addStretch()
        bg_layout.addLayout(bg_btn_layout)

        # Overlay transparency slider
        overlay_label = QLabel(i18n.dialog('appearance.overlay_transparency'))
        bg_layout.addWidget(overlay_label)

        overlay_slider_layout = QHBoxLayout()
        self._overlay_slider = QSlider(Qt.Orientation.Horizontal)
        self._overlay_slider.setRange(AppearanceDefaults.SLIDER_MIN, AppearanceDefaults.SLIDER_MAX)
        self._overlay_slider.valueChanged.connect(self._on_overlay_changed)
        overlay_slider_layout.addWidget(self._overlay_slider)

        self._overlay_value_label = QLabel("100%")
        self._overlay_value_label.setMinimumWidth(45)
        overlay_slider_layout.addWidget(self._overlay_value_label)

        bg_layout.addLayout(overlay_slider_layout)
        layout.addWidget(bg_group)

        # === Playlist Group ===
        playlist_group = QGroupBox(i18n.dialog('appearance.group.playlist'))
        playlist_layout = QVBoxLayout(playlist_group)

        playlist_label = QLabel(i18n.dialog('appearance.playlist_transparency'))
        playlist_layout.addWidget(playlist_label)

        playlist_slider_layout = QHBoxLayout()
        self._playlist_slider = QSlider(Qt.Orientation.Horizontal)
        self._playlist_slider.setRange(AppearanceDefaults.SLIDER_MIN, AppearanceDefaults.SLIDER_MAX)
        self._playlist_slider.valueChanged.connect(self._on_playlist_changed)
        playlist_slider_layout.addWidget(self._playlist_slider)

        self._playlist_value_label = QLabel("100%")
        self._playlist_value_label.setMinimumWidth(45)
        playlist_slider_layout.addWidget(self._playlist_value_label)

        playlist_layout.addLayout(playlist_slider_layout)
        layout.addWidget(playlist_group)

        # === Controls Group ===
        controls_group = QGroupBox(i18n.dialog('appearance.group.controls'))
        controls_layout = QVBoxLayout(controls_group)

        controls_label = QLabel(i18n.dialog('appearance.controls_transparency'))
        controls_layout.addWidget(controls_label)

        controls_slider_layout = QHBoxLayout()
        self._controls_slider = QSlider(Qt.Orientation.Horizontal)
        self._controls_slider.setRange(AppearanceDefaults.SLIDER_MIN, AppearanceDefaults.SLIDER_MAX)
        self._controls_slider.valueChanged.connect(self._on_controls_changed)
        controls_slider_layout.addWidget(self._controls_slider)

        self._controls_value_label = QLabel("100%")
        self._controls_value_label.setMinimumWidth(45)
        controls_slider_layout.addWidget(self._controls_value_label)

        controls_layout.addLayout(controls_slider_layout)
        layout.addWidget(controls_group)

        # === Dialog Buttons ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._reset_btn = QPushButton(i18n.dialog('button.reset_defaults'))
        self._reset_btn.clicked.connect(self._on_reset_defaults)
        btn_layout.addWidget(self._reset_btn)

        self._close_btn = QPushButton(i18n.get('button.close'))
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

    def _populate_values(self) -> None:
        """Populate UI with current values."""
        # Background image path
        if self._background_image:
            self._bg_path_label.setText(self._background_image)
            self._bg_path_label.setStyleSheet("color: #333; font-style: normal;")
        else:
            self._bg_path_label.setText(i18n.dialog('appearance.no_background'))
            self._bg_path_label.setStyleSheet("color: #666; font-style: italic;")

        # Sliders (convert 0.0-1.0 to 0-100)
        self._overlay_slider.blockSignals(True)
        self._overlay_slider.setValue(int(self._overlay_alpha * 100))
        self._overlay_value_label.setText(f"{int(self._overlay_alpha * 100)}%")
        self._overlay_slider.blockSignals(False)

        self._playlist_slider.blockSignals(True)
        self._playlist_slider.setValue(int(self._playlist_alpha * 100))
        self._playlist_value_label.setText(f"{int(self._playlist_alpha * 100)}%")
        self._playlist_slider.blockSignals(False)

        self._controls_slider.blockSignals(True)
        self._controls_slider.setValue(int(self._controls_alpha * 100))
        self._controls_value_label.setText(f"{int(self._controls_alpha * 100)}%")
        self._controls_slider.blockSignals(False)

    def _on_select_background(self) -> None:
        """Handle select background button click."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            i18n.get('dialog.select_background', default='Select Background Image'),
            "",
            i18n.get('dialog.image_files', default='Image Files') + " (*.jpg *.jpeg *.png *.bmp *.gif *.webp)"
        )
        if file_path:
            self._background_image = file_path
            self._bg_path_label.setText(file_path)
            self._bg_path_label.setStyleSheet("color: #333; font-style: normal;")
            self.background_image_changed.emit(file_path)

    def _on_clear_background(self) -> None:
        """Handle clear background button click."""
        self._background_image = None
        self._bg_path_label.setText(i18n.dialog('appearance.no_background'))
        self._bg_path_label.setStyleSheet("color: #666; font-style: italic;")
        self.background_image_changed.emit("")

    def _on_overlay_changed(self, value: int) -> None:
        """Handle overlay slider change."""
        self._overlay_alpha = value / 100.0
        self._overlay_value_label.setText(f"{value}%")
        self.overlay_alpha_changed.emit(self._overlay_alpha)

    def _on_playlist_changed(self, value: int) -> None:
        """Handle playlist slider change."""
        self._playlist_alpha = value / 100.0
        self._playlist_value_label.setText(f"{value}%")
        self.playlist_alpha_changed.emit(self._playlist_alpha)

    def _on_controls_changed(self, value: int) -> None:
        """Handle controls slider change."""
        self._controls_alpha = value / 100.0
        self._controls_value_label.setText(f"{value}%")
        self.controls_alpha_changed.emit(self._controls_alpha)

    def _on_reset_defaults(self) -> None:
        """Reset all values to defaults."""
        self._overlay_alpha = AppearanceDefaults.BACKGROUND_OVERLAY_ALPHA
        self._playlist_alpha = AppearanceDefaults.PLAYLIST_BG_ALPHA
        self._controls_alpha = AppearanceDefaults.BOTTOM_PANEL_BG_ALPHA

        self._populate_values()

        # Emit signals for all changed values
        self.overlay_alpha_changed.emit(self._overlay_alpha)
        self.playlist_alpha_changed.emit(self._playlist_alpha)
        self.controls_alpha_changed.emit(self._controls_alpha)

    # === Public API for Presenter ===

    def set_background_image(self, path: Optional[str]) -> None:
        """Update background image display."""
        self._background_image = path
        if path:
            self._bg_path_label.setText(path)
            self._bg_path_label.setStyleSheet("color: #333; font-style: normal;")
        else:
            self._bg_path_label.setText(i18n.dialog('appearance.no_background'))
            self._bg_path_label.setStyleSheet("color: #666; font-style: italic;")

    def set_overlay_alpha(self, alpha: float) -> None:
        """Update overlay slider value."""
        self._overlay_alpha = alpha
        self._overlay_slider.blockSignals(True)
        self._overlay_slider.setValue(int(alpha * 100))
        self._overlay_value_label.setText(f"{int(alpha * 100)}%")
        self._overlay_slider.blockSignals(False)

    def set_playlist_alpha(self, alpha: float) -> None:
        """Update playlist slider value."""
        self._playlist_alpha = alpha
        self._playlist_slider.blockSignals(True)
        self._playlist_slider.setValue(int(alpha * 100))
        self._playlist_value_label.setText(f"{int(alpha * 100)}%")
        self._playlist_slider.blockSignals(False)

    def set_controls_alpha(self, alpha: float) -> None:
        """Update controls slider value."""
        self._controls_alpha = alpha
        self._controls_slider.blockSignals(True)
        self._controls_slider.setValue(int(alpha * 100))
        self._controls_value_label.setText(f"{int(alpha * 100)}%")
        self._controls_slider.blockSignals(False)