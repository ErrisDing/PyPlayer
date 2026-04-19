#!/usr/bin/env python3
"""
Progress Slider - Custom slider for playback progress
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QSlider, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    if seconds < 0:
        return "0:00"

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class ProgressSlider(QWidget):
    """
    Progress bar with time labels and seeking support.

    Features:
    - Click/drag to seek
    - Current position and duration display
    - Disabled when no track loaded
    """

    # Signals
    seek_requested = pyqtSignal(float)  # position in seconds

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._duration: float = 0.0
        self._position: float = 0.0
        self._is_seeking: bool = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        # Current time label
        self._current_time = QLabel("0:00")
        self._current_time.setMinimumWidth(50)
        self._current_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._current_time)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)  # Use 0-1000 for precision
        self._slider.setValue(0)
        self._slider.setEnabled(False)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self._slider, stretch=1)

        # Duration label
        self._duration_label = QLabel("0:00")
        self._duration_label.setMinimumWidth(50)
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._duration_label)

    def _on_slider_pressed(self) -> None:
        """Handle slider press - start seeking."""
        self._is_seeking = True

    def _on_slider_released(self) -> None:
        """Handle slider release - finish seeking."""
        self._is_seeking = False

        # Calculate position from slider value
        position = (self._slider.value() / 1000.0) * self._duration
        self.seek_requested.emit(position)

    def _on_slider_moved(self, value: int) -> None:
        """Handle slider move - update time display during seeking."""
        if self._duration > 0:
            position = (value / 1000.0) * self._duration
            self._current_time.setText(format_time(position))

    def set_position(self, position: float) -> None:
        """
        Update current playback position.

        Args:
            position: Current position in seconds
        """
        self._position = max(0.0, position)

        # Don't update slider while user is seeking
        if not self._is_seeking:
            if self._duration > 0:
                slider_value = int((self._position / self._duration) * 1000)
                self._slider.blockSignals(True)
                self._slider.setValue(slider_value)
                self._slider.blockSignals(False)

            self._current_time.setText(format_time(self._position))

    def set_duration(self, duration: float) -> None:
        """
        Set total duration.

        Args:
            duration: Total duration in seconds
        """
        self._duration = max(0.0, duration)
        self._duration_label.setText(format_time(self._duration))
        self._slider.setEnabled(self._duration > 0)

        # Reset position if duration changed
        if self._duration <= 0:
            self._slider.setValue(0)
            self._current_time.setText("0:00")

    def update_progress(self, position: float, duration: float) -> None:
        """
        Update both position and duration at once.

        Args:
            position: Current position in seconds
            duration: Total duration in seconds
        """
        if duration != self._duration:
            self.set_duration(duration)
        self.set_position(position)

    def reset(self) -> None:
        """Reset to initial state."""
        self._position = 0.0
        self._duration = 0.0
        self._slider.setValue(0)
        self._slider.setEnabled(False)
        self._current_time.setText("0:00")
        self._duration_label.setText("0:00")

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the slider."""
        self._slider.setEnabled(enabled and self._duration > 0)

    @property
    def is_seeking(self) -> bool:
        """Check if user is currently seeking."""
        return self._is_seeking
