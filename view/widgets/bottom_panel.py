#!/usr/bin/env python3
"""
Bottom Panel - Combined progress slider and playback controls
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QMouseEvent, QIcon, QPixmap, QPainter, QColor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n
from core.constants import AppearanceDefaults


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


def create_colored_icon(icon: QIcon, color: QColor, size: int = 32) -> QIcon:
    """Create a colored version of an icon."""
    pixmap = icon.pixmap(size, size)
    colored_pixmap = QPixmap(size, size)
    colored_pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(colored_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(colored_pixmap.rect(), color)
    painter.end()

    return QIcon(colored_pixmap)


def draw_play_icon(painter: QPainter, rect) -> None:
    """Draw a play triangle icon centered at visual center."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QPolygonF

    cx, cy = rect.center().x(), rect.center().y()
    size = min(rect.width(), rect.height())
    w = size * 0.35  # half width
    h = size * 0.38  # half height

    # Offset to the right for visual centering (triangle points right, feels left-heavy)
    visual_offset = size * 0.08
    cx += visual_offset

    points = [
        QPointF(cx - w, cy - h),
        QPointF(cx + w, cy),
        QPointF(cx - w, cy + h)
    ]
    painter.drawPolygon(QPolygonF(points))


def draw_pause_icon(painter: QPainter, rect) -> None:
    """Draw a pause icon (two vertical bars) centered."""
    cx, cy = rect.center().x(), rect.center().y()
    size = min(rect.width(), rect.height())
    bar_w = size * 0.18
    bar_h = size * 0.6
    gap = size * 0.16

    # Two bars centered
    painter.drawRect(int(cx - gap/2 - bar_w), int(cy - bar_h/2), int(bar_w), int(bar_h))
    painter.drawRect(int(cx + gap/2), int(cy - bar_h/2), int(bar_w), int(bar_h))


def draw_stop_icon(painter: QPainter, rect) -> None:
    """Draw a stop icon (square) centered."""
    cx, cy = rect.center().x(), rect.center().y()
    size = min(rect.width(), rect.height())
    sq_size = size * 0.55

    painter.drawRect(int(cx - sq_size/2), int(cy - sq_size/2), int(sq_size), int(sq_size))


def draw_prev_icon(painter: QPainter, rect) -> None:
    """Draw a previous track icon (vertical bar + triangle pointing left)."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QPolygonF

    cx, cy = rect.center().x(), rect.center().y()
    size = min(rect.width(), rect.height())

    bar_w = size * 0.12
    bar_h = size * 0.55
    tri_w = size * 0.35  # triangle half-width
    tri_h = size * 0.32  # triangle half-height

    # Total width = bar_w + tri_w
    total_half_w = (bar_w + tri_w) / 2

    # Vertical bar on left side
    bar_x = cx - total_half_w
    painter.drawRect(int(bar_x), int(cy - bar_h/2), int(bar_w), int(bar_h))

    # Triangle pointing left, touching the bar
    points = [
        QPointF(cx + total_half_w, cy - tri_h),
        QPointF(cx - total_half_w + bar_w, cy),
        QPointF(cx + total_half_w, cy + tri_h)
    ]
    painter.drawPolygon(QPolygonF(points))


def draw_next_icon(painter: QPainter, rect) -> None:
    """Draw a next track icon (triangle pointing right + vertical bar)."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QPolygonF

    cx, cy = rect.center().x(), rect.center().y()
    size = min(rect.width(), rect.height())

    bar_w = size * 0.12
    bar_h = size * 0.55
    tri_w = size * 0.35  # triangle half-width
    tri_h = size * 0.32  # triangle half-height

    # Total width = bar_w + tri_w
    total_half_w = (bar_w + tri_w) / 2

    # Triangle pointing right, touching the bar
    points = [
        QPointF(cx - total_half_w, cy - tri_h),
        QPointF(cx + total_half_w - bar_w, cy),
        QPointF(cx - total_half_w, cy + tri_h)
    ]
    painter.drawPolygon(QPolygonF(points))

    # Vertical bar on right side
    bar_x = cx + total_half_w - bar_w
    painter.drawRect(int(bar_x), int(cy - bar_h/2), int(bar_w), int(bar_h))


def create_vector_icon(draw_func, color: QColor, size: int = 32) -> QIcon:
    """Create a vector icon using a draw function for smooth scaling."""
    # Use 2x size for high DPI, then scale down
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QBrush, QPen
    painter.setBrush(QBrush(color))
    painter.setPen(QPen(Qt.PenStyle.NoPen))

    rect = QRectF(0, 0, size * 2, size * 2)
    draw_func(painter, rect)

    painter.end()

    return QIcon(pixmap)


class ClickableSlider(QSlider):
    """Slider that allows clicking on the track to jump to a position."""

    def __init__(self, orientation: Qt.Orientation, parent: Optional[QWidget] = None):
        super().__init__(orientation, parent)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press - jump to clicked position."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.orientation() == Qt.Orientation.Horizontal:
                click_pos = event.position().x()
                value = self.minimum() + int(
                    click_pos / self.width() * (self.maximum() - self.minimum())
                )
                value = max(self.minimum(), min(self.maximum(), value))
                self.setValue(value)
                self.sliderMoved.emit(value)
                self.sliderReleased.emit()
                return
        super().mousePressEvent(event)


class BottomPanel(QWidget):
    """
    Combined bottom panel with progress slider and playback controls.

    Features:
    - Progress slider with time labels
    - Play/Pause, Stop, Previous, Next buttons
    - Volume slider
    - Loop mode button
    - Unified transparent background
    """

    # Signals
    play_pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    prev_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    volume_changed = pyqtSignal(float)  # 0.0 - 1.0
    loop_mode_changed = pyqtSignal(str)  # "OFF", "ONE", "ALL"
    seek_requested = pyqtSignal(float)  # position in seconds

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._loop_mode = "OFF"
        self._is_playing = False
        self._duration: float = 0.0
        self._position: float = 0.0
        self._is_seeking: bool = False
        # Transparency settings
        self._bg_alpha = AppearanceDefaults.BOTTOM_PANEL_BG_ALPHA
        self._button_alpha = AppearanceDefaults.BOTTOM_PANEL_BUTTON_ALPHA
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        # Enable transparency for the widget
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 5, 10, 5)
        main_layout.setSpacing(5)

        # Set semi-transparent background using instance variables
        self._update_stylesheet()

        # === Progress row ===
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(10)

        # Current time label
        self._current_time = QLabel("0:00")
        self._current_time.setMinimumWidth(50)
        self._current_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(self._current_time)

        # Progress slider
        self._slider = ClickableSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(0)
        self._slider.setEnabled(False)
        self._slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: rgba(200, 200, 200, 0.5);
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: rgba(33, 150, 243, 0.9);
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(33, 150, 243, 0.7);
                border-radius: 3px;
            }
        """)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        progress_layout.addWidget(self._slider, stretch=1)

        # Duration label
        self._duration_label = QLabel("0:00")
        self._duration_label.setMinimumWidth(50)
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(self._duration_label)

        main_layout.addLayout(progress_layout)

        # === Controls row ===
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        # Icon colors
        icon_color = QColor(80, 80, 80)  # Gray for normal buttons
        play_icon_color = QColor(255, 255, 255)  # White for play button

        # Previous button
        self._prev_btn = QPushButton()
        self._prev_btn.setFixedSize(40, 40)
        self._prev_btn.setIcon(create_vector_icon(draw_prev_icon, icon_color, 20))
        self._prev_btn.setIconSize(QSize(20, 20))
        self._prev_btn.setToolTip(i18n.get('button.prev') if hasattr(i18n, 'get') else "Previous")
        self._prev_btn.clicked.connect(self.prev_clicked.emit)
        controls_layout.addWidget(self._prev_btn)

        # Play/Pause button
        self._play_btn = QPushButton()
        self._play_btn.setFixedSize(50, 50)
        self._play_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(33, 150, 243, 0.85);
                border: none;
                border-radius: 25px;
            }
            QPushButton:hover {
                background-color: rgba(25, 118, 210, 0.95);
            }
            QPushButton:pressed {
                background-color: rgba(21, 101, 192, 0.95);
            }
        """)
        self._play_btn.setIcon(create_vector_icon(draw_play_icon, play_icon_color, 24))
        self._play_btn.setIconSize(QSize(24, 24))
        self._play_btn.clicked.connect(self.play_pause_clicked.emit)
        controls_layout.addWidget(self._play_btn)

        # Stop button
        self._stop_btn = QPushButton()
        self._stop_btn.setFixedSize(40, 40)
        self._stop_btn.setIcon(create_vector_icon(draw_stop_icon, icon_color, 20))
        self._stop_btn.setIconSize(QSize(20, 20))
        self._stop_btn.clicked.connect(self.stop_clicked.emit)
        controls_layout.addWidget(self._stop_btn)

        # Next button
        self._next_btn = QPushButton()
        self._next_btn.setFixedSize(40, 40)
        self._next_btn.setIcon(create_vector_icon(draw_next_icon, icon_color, 20))
        self._next_btn.setIconSize(QSize(20, 20))
        self._next_btn.clicked.connect(self.next_clicked.emit)
        controls_layout.addWidget(self._next_btn)

        # Spacer
        controls_layout.addSpacing(20)

        # Loop mode button
        self._loop_btn = QPushButton("↺")
        self._loop_btn.setFixedSize(40, 40)
        self._loop_btn.setToolTip("Loop: OFF")
        self._loop_btn.clicked.connect(self._on_loop_clicked)
        self._loop_btn.setStyleSheet("QPushButton { color: #999; background-color: rgba(255, 255, 255, 0.7); }")
        controls_layout.addWidget(self._loop_btn)

        # Spacer
        controls_layout.addStretch()

        # Volume icon
        self._volume_icon = QLabel("🔊")
        controls_layout.addWidget(self._volume_icon)

        # Volume slider
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self._volume_slider)

        # Volume label
        self._volume_label = QLabel("100%")
        self._volume_label.setFixedWidth(45)
        controls_layout.addWidget(self._volume_label)

        main_layout.addLayout(controls_layout)

    # === Progress slider handlers ===

    def _on_slider_pressed(self) -> None:
        """Handle slider press - start seeking."""
        self._is_seeking = True

    def _on_slider_released(self) -> None:
        """Handle slider release - finish seeking."""
        self._is_seeking = False
        position = (self._slider.value() / 1000.0) * self._duration
        self.seek_requested.emit(position)

    def _on_slider_moved(self, value: int) -> None:
        """Handle slider move - update time display during seeking."""
        if self._duration > 0:
            position = (value / 1000.0) * self._duration
            self._current_time.setText(format_time(position))

    # === Control button handlers ===

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
            self._loop_btn.setStyleSheet("QPushButton { color: #999; background-color: rgba(255, 255, 255, 0.7); }")
            self._loop_btn.setToolTip("Loop: OFF")
        elif self._loop_mode == "ONE":
            self._loop_btn.setStyleSheet("QPushButton { color: #2196F3; background-color: rgba(227, 242, 253, 0.85); }")
            self._loop_btn.setToolTip("Loop: ONE")
        else:  # ALL
            self._loop_btn.setStyleSheet("QPushButton { color: #4CAF50; background-color: rgba(232, 245, 233, 0.85); }")
            self._loop_btn.setToolTip("Loop: ALL")

    def _update_stylesheet(self) -> None:
        """Update the stylesheet based on current alpha values."""
        self.setStyleSheet(f"""
            BottomPanel {{
                background-color: rgba(245, 245, 245, {self._bg_alpha});
            }}
            QPushButton {{
                background-color: rgba(255, 255, 255, {self._button_alpha});
                border: 1px solid rgba(200, 200, 200, 0.5);
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: rgba(230, 230, 230, 0.85);
            }}
            QPushButton:pressed {{
                background-color: rgba(200, 200, 200, 0.85);
            }}
            QSlider::groove:horizontal {{
                background: rgba(200, 200, 200, 0.5);
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: rgba(100, 100, 100, 0.85);
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QLabel {{
                background-color: transparent;
            }}
        """)

    def set_bg_alpha(self, alpha: float) -> None:
        """Set bottom panel background transparency."""
        self._bg_alpha = alpha
        self._update_stylesheet()

    # === Public API ===

    def set_playing_state(self, is_playing: bool, is_paused: bool = False) -> None:
        """Update the play/pause button state."""
        self._is_playing = is_playing and not is_paused
        play_icon_color = QColor(255, 255, 255)  # White for play button
        if self._is_playing:
            self._play_btn.setIcon(create_vector_icon(draw_pause_icon, play_icon_color, 24))
        else:
            self._play_btn.setIcon(create_vector_icon(draw_play_icon, play_icon_color, 24))

    def set_volume(self, volume: float) -> None:
        """Set the volume level (0.0-1.0)."""
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
        """Set the loop mode ("OFF", "ONE", or "ALL")."""
        if mode in ("OFF", "ONE", "ALL"):
            self._loop_mode = mode
            self._update_loop_button()

    def get_loop_mode(self) -> str:
        """Get current loop mode."""
        return self._loop_mode

    def update_progress(self, position: float, duration: float) -> None:
        """Update both position and duration at once."""
        if duration != self._duration:
            self._duration = max(0.0, duration)
            self._duration_label.setText(format_time(self._duration))
            self._slider.setEnabled(self._duration > 0)

        self._position = max(0.0, position)

        if not self._is_seeking and self._duration > 0:
            slider_value = int((self._position / self._duration) * 1000)
            self._slider.blockSignals(True)
            self._slider.setValue(slider_value)
            self._slider.blockSignals(False)

        self._current_time.setText(format_time(self._position))

    def reset_progress(self) -> None:
        """Reset progress to initial state."""
        self._position = 0.0
        self._duration = 0.0
        self._slider.setValue(0)
        self._slider.setEnabled(False)
        self._current_time.setText("0:00")
        self._duration_label.setText("0:00")

    def sizeHint(self):
        """Return suggested size."""
        from PyQt6.QtCore import QSize
        return QSize(400, 100)
