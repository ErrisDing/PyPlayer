#!/usr/bin/env python3
"""
Appearance Configuration Dialog - Dialog for customizing UI appearance
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QGroupBox, QRadioButton, QFileDialog, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n
from core.config import DEFAULT_THEME_MODE, THEME_MODES
from core.constants import AppearanceDefaults

# The three modes in display order: follow the system, then the two overrides.
# The first element is the value ``theme_selected`` emits and the suffix of the
# i18n key ``appearance.theme_<mode>``; the second is the widget's objectName,
# which is what the tests and any future sheet rule address the radio by. The
# allowed set itself is ``core.config.THEME_MODES`` -- one list, three consumers
# (dialog, settings file, ``core.theme.resolve``).
THEME_CHOICES = (
    ('auto', 'themeAuto'),
    ('light', 'themeLight'),
    ('dark', 'themeDark'),
)


class AppearanceDialog(QDialog):
    """
    Dialog for configuring application appearance.

    Features:
    - Theme mode radio group: follow the system, or force light/dark
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
    theme_selected = pyqtSignal(str)                 # 'auto' | 'light' | 'dark'

    def __init__(
        self,
        background_image: Optional[str],
        overlay_alpha: float,
        playlist_alpha: float,
        controls_alpha: float,
        theme_mode: str = DEFAULT_THEME_MODE,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        # Ensure i18n is initialized
        i18n.detect_init()

        self._background_image = background_image

        # Degrade like the loader does: an unrecognised mode must not leave the
        # group with nothing checked, and this dialog is handed whatever
        # ``ConfigService.get_theme()`` answered.
        self._theme_mode = theme_mode if theme_mode in THEME_MODES else DEFAULT_THEME_MODE

        # Store current values (0.0-1.0 scale)
        self._overlay_alpha = overlay_alpha
        self._playlist_alpha = playlist_alpha
        self._controls_alpha = controls_alpha

        self._setup_ui()
        self._populate_values()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        # Style scope for the generated sheet (QDialog#appearanceDialog, plus
        # #bgPathLabel and the three dialog sliders by objectName). No styling
        # happens in this file.
        self.setObjectName('appearanceDialog')
        self.setWindowTitle(i18n.dialog('dialog.title.appearance'))
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # === Theme Mode Group ===
        # Above the background group on purpose: the mode decides the colours of
        # everything below it, including this dialog's own chrome.
        theme_group = QGroupBox(i18n.dialog('appearance.group.theme'))
        theme_layout = QVBoxLayout(theme_group)

        # Sharing the group box as their parent widget is what makes these three
        # radios mutually exclusive, so no ``QButtonGroup`` is needed; the modes
        # are addressed by objectName, which is also how any future sheet rule
        # would scope them (the generated stylesheet does not style them yet).
        self._theme_buttons = {}
        for mode, object_name in THEME_CHOICES:
            radio = QRadioButton(i18n.dialog(f'appearance.theme_{mode}'))
            radio.setObjectName(object_name)
            radio.toggled.connect(
                lambda checked, selected=mode: self._on_theme_toggled(
                    checked, selected))
            theme_layout.addWidget(radio)
            self._theme_buttons[mode] = radio

        layout.addWidget(theme_group)

        # === Background Image Group ===
        bg_group = QGroupBox(i18n.dialog('appearance.group.background'))
        bg_layout = QVBoxLayout(bg_group)

        # Current background display
        self._bg_path_label = QLabel(i18n.dialog('appearance.no_background'))
        self._bg_path_label.setObjectName('bgPathLabel')
        self._bg_path_label.setWordWrap(True)
        self._update_bg_path_state()
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
        self._overlay_slider.setObjectName('overlaySlider')
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
        self._playlist_slider.setObjectName('playlistSlider')
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
        self._controls_slider.setObjectName('controlsSlider')
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

    def _update_bg_path_state(self) -> None:
        """Sync the ``empty`` dynamic property the generated sheet selects on.

        ``core/theme_qss.py`` styles ``#bgPathLabel[empty="true"]`` (the muted
        italic placeholder) apart from a ``#bgPathLabel`` holding a real path.
        Strings are the declared contract of this widget tree; Qt would also
        match a Python ``bool``, because its attribute selector special-cases
        QMetaType::Bool into ``"true"``/``"false"``. The strings stay because
        they are what the sheet is written against. unpolish/polish is what
        makes the sheet re-read the property -- this is the only styling hook
        in the dialog, the old per-widget inline sheets are gone.
        """
        label = self._bg_path_label
        label.setProperty('empty', 'false' if self._background_image else 'true')
        label.style().unpolish(label)
        label.style().polish(label)

    def _populate_values(self) -> None:
        """Populate UI with current values."""
        # Theme mode radio (no signal: see ``set_theme_mode``)
        self.set_theme_mode(self._theme_mode)

        # Background image path
        if self._background_image:
            self._bg_path_label.setText(self._background_image)
        else:
            self._bg_path_label.setText(i18n.dialog('appearance.no_background'))
        self._update_bg_path_state()

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

    def _on_theme_toggled(self, checked: bool, mode: str) -> None:
        """Handle a theme radio toggle.

        ``toggled`` fires for both halves of an exclusive switch, so only the
        button becoming checked carries a decision, and a mode that is already
        the current one is not worth persisting again -- the presenter writes
        ``settings.json`` on every emission, and re-clicking the checked radio
        must not rewrite the file.
        """
        if not checked or mode == self._theme_mode:
            return
        self._theme_mode = mode
        self.theme_selected.emit(mode)

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
            self._update_bg_path_state()
            self.background_image_changed.emit(file_path)

    def _on_clear_background(self) -> None:
        """Handle clear background button click."""
        self._background_image = None
        self._bg_path_label.setText(i18n.dialog('appearance.no_background'))
        self._update_bg_path_state()
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
        """Reset all values to defaults.

        The theme mode is deliberately not included: this button answers the
        three sliders, and silently flipping the app's colours while a user is
        adjusting opacity would be a much bigger change than they asked for.
        The mode has its own three-way control.
        """
        self._overlay_alpha = AppearanceDefaults.BACKGROUND_OVERLAY_ALPHA
        self._playlist_alpha = AppearanceDefaults.PLAYLIST_BG_ALPHA
        self._controls_alpha = AppearanceDefaults.BOTTOM_PANEL_BG_ALPHA

        self._populate_values()

        # Emit signals for all changed values
        self.overlay_alpha_changed.emit(self._overlay_alpha)
        self.playlist_alpha_changed.emit(self._playlist_alpha)
        self.controls_alpha_changed.emit(self._controls_alpha)

    # === Public API for Presenter ===

    @property
    def theme_mode(self) -> str:
        """``'auto'``, ``'light'`` or ``'dark'`` as the dialog currently stands."""
        return self._theme_mode

    def set_theme_mode(self, mode: str) -> None:
        """Check the radio for ``mode`` without emitting ``theme_selected``.

        ``_theme_mode`` is assigned before the widget state so the toggled
        handler sees "already current" and stays quiet -- which is exactly what
        makes this safe to call from :meth:`_populate_values` and from the
        presenter when something else changed the theme. Anything outside
        :data:`core.config.THEME_MODES` is shown as ``'auto'``, the same
        degradation the loader performs.
        """
        mode = mode if mode in THEME_MODES else DEFAULT_THEME_MODE
        self._theme_mode = mode
        self._theme_buttons[mode].setChecked(True)

    def set_background_image(self, path: Optional[str]) -> None:
        """Update background image display."""
        self._background_image = path
        if path:
            self._bg_path_label.setText(path)
        else:
            self._bg_path_label.setText(i18n.dialog('appearance.no_background'))
        self._update_bg_path_state()

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