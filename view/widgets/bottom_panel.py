#!/usr/bin/env python3
"""
Bottom Panel - Combined progress slider and playback controls
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QMouseEvent

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n
from core.theme import PLAY_SIZE, TRANSPORT_SIZE
from view.icons import icon

# Glyph sizes, both derived from the geometry tokens so a button and its glyph
# cannot drift apart. ``TRANSPORT_SIZE // 2`` is the 20 px the transport row has
# always shown; ``PLAY_SIZE // 2 - 1`` keeps the play disc's 24 px glyph (an
# even size, so the triangle's apex lands on a whole pixel at dpr 1).
TRANSPORT_ICON_SIZE = TRANSPORT_SIZE // 2
PLAY_ICON_SIZE = PLAY_SIZE // 2 - 1

# Loop mode -> glyph. OFF is drawn with ``icon_muted`` and the two active modes
# with ``accent``: a mode that is not on must not compete for attention.
_LOOP_GLYPHS = {
    'OFF': 'loop_off',
    'ONE': 'loop_one',
    'ALL': 'loop_all',
}


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


def volume_glyph(volume: float) -> str:
    """The speaker glyph for a 0.0-1.0 level: 0/1/2/3 arcs.

    Quartiles rather than the old three-step thresholds, because the set has
    four levels and ``volume_mute`` is only ever shown at exactly zero.
    """
    if volume <= 0.0:
        return 'volume_mute'
    if volume < 1 / 3:
        return 'volume_low'
    if volume < 2 / 3:
        return 'volume_mid'
    return 'volume_high'


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
    - Unified translucent background

    Styling is the application sheet's job (``#bottomPanel``, ``#progressSlider``
    / ``#volumeSlider``, ``[role="transport"]``, ``#playButton``,
    ``#loopButton``, ``#timeLabel``, ``#volumeLabel``). What QSS cannot reach is
    the *glyphs*: every one of them is an SVG from ``resource/icons`` rasterised
    through :func:`view.icons.icon` with a theme token, which is why
    :meth:`recolor` still exists and why no widget here owns a stylesheet.
    """

    # Signals
    play_pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    prev_clicked = pyqtSignal()
    next_clicked = pyqtSignal()
    volume_changed = pyqtSignal(float)  # 0.0 - 1.0
    loop_mode_changed = pyqtSignal(str)  # "OFF", "ONE", "ALL"
    seek_requested = pyqtSignal(float)  # position in seconds

    def __init__(self, manager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = manager
        self._loop_mode = "OFF"
        self._is_playing = False
        self._duration: float = 0.0
        self._position: float = 0.0
        self._is_seeking: bool = False
        self._setup_ui()
        self._generate_icons()

    def _generate_icons(self) -> None:
        """(Re)rasterise every glyph from the SVG set in the current tokens.

        One colour per role, no literals anywhere: ``icon`` for the transport
        buttons and the volume speaker, ``icon_on_accent`` for the play disc,
        ``accent`` / ``icon_muted`` for the loop button's on / off states. Each
        colour is what the WCAG guards in ``tests/test_theme.py`` measured
        against the background the widget actually paints it on.
        """
        tokens = self._theme.tokens
        dpr = self.devicePixelRatioF()

        self._prev_btn.setIcon(
            icon('prev', tokens.icon, TRANSPORT_ICON_SIZE, dpr))
        self._stop_btn.setIcon(
            icon('stop', tokens.icon, TRANSPORT_ICON_SIZE, dpr))
        self._next_btn.setIcon(
            icon('next', tokens.icon, TRANSPORT_ICON_SIZE, dpr))
        self._set_play_icon(tokens.icon_on_accent)
        self._set_loop_icon(tokens)
        self._set_volume_icon(self.get_volume(), tokens)

    def _set_play_icon(self, color: str) -> None:
        """Rasterise the play or pause glyph for the current state in ``color``."""
        name = 'pause' if self._is_playing else 'play'
        self._play_btn.setIcon(
            icon(name, color, PLAY_ICON_SIZE, self.devicePixelRatioF()))

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        # Style scopes for the theme sheet (core/theme_qss.py selects on
        # #bottomPanel / #progressSlider / #volumeSlider / #playButton /
        # #loopButton / #timeLabel / #volumeLabel and on [role="transport"]).
        self.setObjectName("bottomPanel")

        # Enable transparency for the widget
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 5, 10, 5)
        main_layout.setSpacing(5)

        # === Progress row ===
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(10)

        # Current time label
        self._current_time = QLabel("0:00")
        self._current_time.setObjectName("timeLabel")
        self._current_time.setMinimumWidth(50)
        self._current_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(self._current_time)

        # Progress slider
        self._slider = ClickableSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("progressSlider")
        self._slider.setRange(0, 1000)
        self._slider.setValue(0)
        self._slider.setEnabled(False)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        progress_layout.addWidget(self._slider, stretch=1)

        # Duration label
        self._duration_label = QLabel("0:00")
        self._duration_label.setObjectName("timeLabel")
        self._duration_label.setMinimumWidth(50)
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        progress_layout.addWidget(self._duration_label)

        main_layout.addLayout(progress_layout)

        # === Controls row ===
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        # The glyphs are rasterised by ``_generate_icons``, called at the end of
        # ``__init__`` and again from ``recolor``; that keeps every icon colour
        # anchored to the theme tokens instead of a local literal.
        # Previous button
        self._prev_btn = QPushButton()
        # QSS matches dynamic properties as strings, so the transport scope is
        # the literal "transport" (QPushButton[role="transport"]).
        self._prev_btn.setProperty("role", "transport")
        self._prev_btn.setFixedSize(TRANSPORT_SIZE, TRANSPORT_SIZE)
        self._prev_btn.setIconSize(QSize(TRANSPORT_ICON_SIZE, TRANSPORT_ICON_SIZE))
        self._prev_btn.setToolTip(i18n.get('button.prev') if hasattr(i18n, 'get') else "Previous")
        self._prev_btn.clicked.connect(self.prev_clicked.emit)
        controls_layout.addWidget(self._prev_btn)

        # Play/Pause button
        self._play_btn = QPushButton()
        self._play_btn.setObjectName("playButton")
        self._play_btn.setFixedSize(PLAY_SIZE, PLAY_SIZE)
        self._play_btn.setIconSize(QSize(PLAY_ICON_SIZE, PLAY_ICON_SIZE))
        self._play_btn.clicked.connect(self.play_pause_clicked.emit)
        controls_layout.addWidget(self._play_btn)

        # Stop button
        self._stop_btn = QPushButton()
        self._stop_btn.setProperty("role", "transport")
        self._stop_btn.setFixedSize(TRANSPORT_SIZE, TRANSPORT_SIZE)
        self._stop_btn.setIconSize(QSize(TRANSPORT_ICON_SIZE, TRANSPORT_ICON_SIZE))
        self._stop_btn.clicked.connect(self.stop_clicked.emit)
        controls_layout.addWidget(self._stop_btn)

        # Next button
        self._next_btn = QPushButton()
        self._next_btn.setProperty("role", "transport")
        self._next_btn.setFixedSize(TRANSPORT_SIZE, TRANSPORT_SIZE)
        self._next_btn.setIconSize(QSize(TRANSPORT_ICON_SIZE, TRANSPORT_ICON_SIZE))
        self._next_btn.clicked.connect(self.next_clicked.emit)
        controls_layout.addWidget(self._next_btn)

        # Spacer
        controls_layout.addSpacing(20)

        # Loop mode button. The glyph is the button's *icon*, never its text:
        # a character would be coloured by the palette (and be at the mercy of
        # whatever font on the platform has that codepoint), which is what the
        # old loop character was.
        self._loop_btn = QPushButton()
        self._loop_btn.setObjectName("loopButton")
        self._loop_btn.setFixedSize(TRANSPORT_SIZE, TRANSPORT_SIZE)
        self._loop_btn.setIconSize(QSize(TRANSPORT_ICON_SIZE, TRANSPORT_ICON_SIZE))
        self._loop_btn.setToolTip("Loop: OFF")
        self._loop_btn.clicked.connect(self._on_loop_clicked)
        controls_layout.addWidget(self._loop_btn)

        # Spacer
        controls_layout.addStretch()

        # Volume indicator: one of the four speaker glyphs. Named so the tree
        # can find it, deliberately unstyled by the sheet: it holds a pixmap
        # already painted from ``tokens.icon``, so there is no colour left for a
        # rule to reach (see the report for the full reasoning).
        self._volume_icon = QLabel()
        self._volume_icon.setObjectName("volumeIcon")
        controls_layout.addWidget(self._volume_icon)

        # Volume slider
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setObjectName("volumeSlider")
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self._volume_slider)

        # Volume percentage: text, so it does need the sheet's reach
        # (``#volumeLabel`` in core/theme_qss.py).
        self._volume_label = QLabel("100%")
        self._volume_label.setObjectName("volumeLabel")
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
        """Switch the speaker glyph for the level (0/1/2/3 arcs)."""
        self._set_volume_icon(volume, self._theme.tokens)

    def _set_volume_icon(self, volume: float, tokens) -> None:
        """Put the level's glyph on the volume label in ``tokens.icon``.

        The pixmap is requested *with the panel's device pixel ratio*, so a
        HiDPI screen gets the 2x sheet rather than a 1x one upscaled by the
        label: ``QIcon.pixmap(size)`` alone would answer in the caller's default
        ratio and quietly throw the ``dpr`` argument away.
        """
        dpr = self.devicePixelRatioF()
        glyph = icon(volume_glyph(volume), tokens.icon, TRANSPORT_ICON_SIZE, dpr)
        self._volume_icon.setPixmap(glyph.pixmap(
            QSize(TRANSPORT_ICON_SIZE, TRANSPORT_ICON_SIZE), dpr))

    def _set_loop_icon(self, tokens) -> None:
        """Rasterise the current loop mode's glyph in its state colour."""
        colour = (tokens.icon_muted if self._loop_mode == 'OFF'
                  else tokens.accent)
        self._loop_btn.setIcon(
            icon(_LOOP_GLYPHS[self._loop_mode], colour, TRANSPORT_ICON_SIZE,
                 self.devicePixelRatioF()))

    def _update_loop_button(self) -> None:
        """Update loop button glyph and tooltip for the mode.

        Three glyphs, two colours: OFF is muted because a mode that is not
        active must not compete with the two that are, ONE and ALL take
        ``accent``, the state colour the plan reserves for "this is on". Both
        are icons, so no palette colour and no inline stylesheet can reach them
        -- the per-mode ``#999`` / ``#2196F3`` / ``#4CAF50`` literals Task 6
        deleted have no successor here.
        """
        self._set_loop_icon(self._theme.tokens)
        tips = {
            "OFF": "Loop: OFF",
            "ONE": "Loop: ONE",
            "ALL": "Loop: ALL",
        }
        self._loop_btn.setToolTip(tips[self._loop_mode])

    # === Public API ===

    def recolor(self, tokens) -> None:
        """Regenerate every glyph for a new theme.

        Called from ``MainWindow.recolor`` on every ``theme_changed``. The
        button chrome itself is QSS's business; the glyphs are the one thing
        here that QSS cannot restyle, so they are the one thing redrawn.
        """
        self._generate_icons()

    def set_playing_state(self, is_playing: bool, is_paused: bool = False) -> None:
        """Update the play/pause button state."""
        self._is_playing = is_playing and not is_paused
        self._set_play_icon(self._theme.tokens.icon_on_accent)

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
