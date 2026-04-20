#!/usr/bin/env python3
"""
Control Panel - Playback control buttons
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSlider, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n


class ControlPanel(QWidget):
    """
    Playback control panel with buttons and volume slider.

    Features:
    - Play/Pause button
    - Stop button
    - Previous/Next buttons
    - Volume slider
    - Loop mode button
    """

    # Signals
    play_pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    prev_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    volume_changed = pyqtSignal(float)  # 0.0 - 1.0
    loop_mode_changed = pyqtSignal(str)  # "OFF", "ONE", "ALL"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._loop_mode = "OFF"
        self._is_playing = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        # Previous button
        self._prev_btn = QPushButton("◀◀")
        self._prev_btn.setFixedSize(40, 40)
        self._prev_btn.setToolTip(i18n.get('button.prev') if hasattr(i18n, 'get') else "Previous")
        self._prev_btn.clicked.connect(self.prev_clicked.emit)
        layout.addWidget(self._prev_btn)

        # Play/Pause button
        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(50, 50)
        self._play_btn.setStyleSheet("font-size: 18px;")
        self._play_btn.clicked.connect(self._on_play_clicked)
        layout.addWidget(self._play_btn)

        # Stop button
        self._stop_btn = QPushButton("■")
        self._stop_btn.setFixedSize(40, 40)
        self._stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self._stop_btn)

        # Next button
        self._next_btn = QPushButton("▶▶")
        self._next_btn.setFixedSize(40, 40)
        self._next_btn.clicked.connect(self.next_clicked.emit)
        layout.addWidget(self._next_btn)

        # Spacer
        layout.addSpacing(20)

        # Loop mode button
        self._loop_btn = QPushButton("↺")
        self._loop_btn.setFixedSize(40, 40)
        self._loop_btn.setToolTip("Loop: OFF")
        self._loop_btn.clicked.connect(self._on_loop_clicked)
        self._loop_btn.setStyleSheet("QPushButton { color: #999; }")
        layout.addWidget(self._loop_btn)

        # Spacer
        layout.addStretch()

        # Volume icon
        self._volume_icon = QLabel("🔊")
        layout.addWidget(self._volume_icon)

        # Volume slider
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        layout.addWidget(self._volume_slider)

        # Volume label
        self._volume_label = QLabel("100%")
        self._volume_label.setFixedWidth(45)
        layout.addWidget(self._volume_label)

    def _on_play_clicked(self) -> None:
        """Handle play/pause button click."""
        self.play_pause_clicked.emit()

    def _on_loop_clicked(self) -> None:
        """Handle loop button click - cycle through modes."""
        modes = ["OFF", "ONE", "ALL"]
        current_idx = modes.index(self._loop_mode)
        next_idx = (current_idx + 1) % len(modes)
        self._loop_mode = modes[next_idx]
        self._update_loop_button()
        self.loop_mode_changed.emit(self._loop_mode)

    def _on_volume_changed(self, value: int) -> None:
        """Handle volume slider change."""
        volume = value / 100.0
        self._volume_label.setText(f"{value}%")
        self._update_volume_icon(volume)
        self.volume_changed.emit(volume)

    def _update_volume_icon(self, volume: float) -> None:
        """Update volume icon based on level."""
        if volume == 0:
            self._volume_icon.setText("🔇")
        elif volume < 0.5:
            self._volume_icon.setText("🔉")
        else:
            self._volume_icon.setText("🔊")

    def _update_loop_button(self) -> None:
        """Update loop button appearance based on mode."""
        if self._loop_mode == "OFF":
            self._loop_btn.setStyleSheet("QPushButton { color: #999; }")
            self._loop_btn.setToolTip("Loop: OFF")
        elif self._loop_mode == "ONE":
            self._loop_btn.setStyleSheet("QPushButton { color: #2196F3; }")
            self._loop_btn.setToolTip("Loop: ONE")
        else:  # ALL
            self._loop_btn.setStyleSheet("QPushButton { color: #4CAF50; }")
            self._loop_btn.setToolTip("Loop: ALL")

    def set_playing_state(self, is_playing: bool, is_paused: bool = False) -> None:
        """
        Update the play/pause button state.

        Args:
            is_playing: Whether a track is loaded and playing
            is_paused: Whether playback is paused
        """
        self._is_playing = is_playing and not is_paused

        if self._is_playing:
            self._play_btn.setText("❚❚")
        else:
            self._play_btn.setText("▶")

    def set_volume(self, volume: float) -> None:
        """
        Set the volume level.

        Args:
            volume: Volume level 0.0-1.0
        """
        volume = max(0.0, min(1.0, volume))
        value = int(volume * 100)
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(value)
        self._volume_slider.blockSignals(False)
        self._volume_label.setText(f"{value}%")
        self._update_volume_icon(volume)

    def get_volume(self) -> float:
        """Get current volume level (0.0-1.0)."""
        return self._volume_slider.value() / 100.0

    def set_loop_mode(self, mode: str) -> None:
        """
        Set the loop mode.

        Args:
            mode: "OFF", "ONE", or "ALL"
        """
        if mode in ("OFF", "ONE", "ALL"):
            self._loop_mode = mode
            self._update_loop_button()

    def get_loop_mode(self) -> str:
        """Get current loop mode."""
        return self._loop_mode

    def sizeHint(self) -> QSize:
        """Return suggested size."""
        return QSize(400, 60)
