#!/usr/bin/env python3
"""
PyPlayer QSS Generator

The single stylesheet source of the theme layer (spec
``docs/superpowers/specs/2026-10-16-ui-batch1-theme-tokens-design.md`` §4.2).
It replaces ``view/resources/styles.qss`` and, with it, the split between a
global stylesheet and per-widget ``setStyleSheet`` calls: one call to
:func:`build_qss` produces the complete application stylesheet from the
:class:`core.theme.ThemeTokens` plus the user's :class:`core.theme.AlphaSettings`.

Two structural rules make this the root-cause fix for the inconsistent
widgets (A1):

* **No bare widget rules.** Every ``QPushButton`` / ``QSlider`` / ``QListView``
  / ``QLabel`` rule is scoped behind an ``#objectName`` or a
  ``[prop="value"]`` dynamic-property selector, so a style can never leak
  onto a widget that never asked for it (that leak is what made the progress
  slider and the volume slider render differently side by side).
* **No colour literals.** Every colour resolves to a token field, so LIGHT
  and DARK can be asserted identical in structure and the palette stays the
  one contrast-checked source of truth (see ``tests/test_theme.py``).

The module is pure Python (no Qt import), so its output can be unit-tested
without a display (see ``tests/test_theme_qss.py``).

:data:`REQUIRED_OBJECT_NAMES` and :data:`REQUIRED_DYN_PROPERTIES` are the
contract with the widget tree: Task 5 guarantees the widgets carry these
names/properties, and ``build_qss`` guarantees every one of them is styled.
"""

from core.theme import (
    AlphaSettings,
    ThemeTokens,
    FONT_SIZE_LG,
    FONT_SIZE_MD,
    FONT_SIZE_SM,
    FONT_SIZE_XL,
    PLAY_SIZE,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    TRANSPORT_SIZE,
)

# Every objectName referenced by the generated stylesheet, exactly as spec §4.2
# scopes the widget tree. The structure test in Task 5 asserts the real widgets
# carry each of these; renaming a widget without updating both sides fails.
REQUIRED_OBJECT_NAMES: tuple[str, ...] = (
    'nowPlayingPanel',
    'albumArt',
    'trackTitle',
    'trackArtist',
    'trackAlbum',
    'playlistHeader',
    'playlistView',
    'bottomPanel',
    'progressSlider',
    'volumeSlider',
    'playButton',
    'loopButton',
    'timeLabel',
    'appearanceDialog',
    'bgPathLabel',
)

# Dynamic properties used to scope rules for repeated elements (media-library
# chips, transport-group buttons) where objectNames would not scale.
REQUIRED_DYN_PROPERTIES: tuple[tuple[str, str], ...] = (
    ('chip', 'true'),
    ('role', 'transport'),
)


def _clamp_alpha(alpha: float) -> float:
    """Squeeze an alpha onto 0.0..1.0; out-of-range input is clamped, never raised."""
    return min(1.0, max(0.0, float(alpha)))


def _format_alpha(alpha: float) -> str:
    """Two-decimal alpha with trailing zeros trimmed, keeping one decimal digit.

    ``0.5`` renders as ``0.5`` (not ``0.50``), clamped extremes keep the
    ``0.0``/``1.0`` form so the value is greppable in the produced QSS.
    """
    text = f'{_clamp_alpha(alpha):.2f}'.rstrip('0')
    if text.endswith('.'):
        text += '0'
    return text


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a ``#rrggbb`` token into an ``rgba(r, g, b, a)`` QSS colour.

    ``alpha`` is clamped to 0.0..1.0 (the user-facing sliders have already
    been squeezed by config; this keeps a bad value from producing an invalid
    colour). The alpha keeps two decimals at most, trailing zeros trimmed:
    ``hex_to_rgba('#1976d2', 0.5) == 'rgba(25, 118, 210, 0.5)'``.
    """
    if not (isinstance(hex_color, str) and len(hex_color) == 7
            and hex_color.startswith('#')):
        raise ValueError(f'hex_color must be #rrggbb, got {hex_color!r}')
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    return f'rgba({red}, {green}, {blue}, {_format_alpha(alpha)})'


def _rule(selectors: tuple[str, ...] | str, declarations: list[tuple[str, str]]) -> str:
    """Render one QSS rule; selectors are joined comma-style, one per line."""
    if isinstance(selectors, str):
        selectors = (selectors,)
    body = ''.join(f'    {prop}: {value};\n' for prop, value in declarations)
    return ',\n'.join(selectors) + ' {\n' + body + '}\n'


def _px(value: int) -> str:
    return f'{value}px'


def build_qss(tokens: ThemeTokens, alphas: AlphaSettings) -> str:
    """Generate the complete application stylesheet for one theme.

    Args:
        tokens: The :data:`core.theme.LIGHT` or :data:`core.theme.DARK` token
            set (whatever ``resolve`` returned).
        alphas: User transparency settings. ``playlist`` composites the
            ``surface`` token for ``#playlistView`` and ``controls`` for
            ``#bottomPanel``; ``overlay`` is consumed by the main window's
            ``paintEvent`` scrim, **not** here, but is clamped defensively.

    Returns:
        A QSS string ready for ``QApplication.setStyleSheet``. Every colour
        comes from ``tokens`` (no literals), every widget rule is scoped, and
        every name in :data:`REQUIRED_OBJECT_NAMES` /
        :data:`REQUIRED_DYN_PROPERTIES` appears in the output.
    """
    t = tokens
    # Surfaces the two panels composite from `surface` at the user's alpha.
    playlist_bg = hex_to_rgba(t.surface, _clamp_alpha(alphas.playlist))
    controls_bg = hex_to_rgba(t.surface, _clamp_alpha(alphas.controls))
    # Both sliders share this groove so they finally render identically (A1).
    groove_bg = hex_to_rgba(t.border_strong, 0.5)

    transport = 'QPushButton[role="transport"]'
    chip = 'QPushButton[chip="true"]'
    sliders = ('#progressSlider', '#volumeSlider')

    rules: list[str] = []
    emit = rules.append

    # -- 窗口与面板 / window & panels --------------------------------------
    # Background image + scrim are painted by the main window's paintEvent;
    # the stylesheet keeps these containers transparent/translucent only.
    emit(_rule(('QMainWindow', '#nowPlayingPanel'), [
        ('background-color', 'transparent'),
    ]))
    emit(_rule('#bottomPanel', [
        ('background-color', controls_bg),
        ('border-top', f'1px solid {t.border}'),
    ]))

    # -- 菜单 / menus -------------------------------------------------------
    emit(_rule('QMenuBar', [
        ('background-color', t.surface),
        ('border-bottom', f'1px solid {t.border}'),
        ('padding', _px(SPACE_1)),
        ('color', t.text_primary),
    ]))
    emit(_rule('QMenuBar::item', [
        ('padding', f'{_px(SPACE_2)} {_px(SPACE_3)}'),
        ('background-color', 'transparent'),
        ('border-radius', _px(RADIUS_SM)),
    ]))
    emit(_rule('QMenuBar::item:selected', [
        ('background-color', t.hover_bg),
    ]))
    emit(_rule('QMenuBar::item:pressed', [
        ('background-color', t.hover_bg),
    ]))
    emit(_rule('QMenu', [
        ('background-color', t.surface),
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_SM)),
        ('padding', _px(SPACE_1)),
        ('color', t.text_primary),
    ]))
    emit(_rule('QMenu::item', [
        ('padding', f'{_px(SPACE_2)} {_px(SPACE_4)} {_px(SPACE_2)} {_px(SPACE_3)}'),
        ('border-radius', _px(RADIUS_SM)),
    ]))
    emit(_rule('QMenu::item:selected', [
        ('background-color', t.accent_soft),
        ('color', t.text_primary),
    ]))
    emit(_rule('QMenu::separator', [
        ('height', '1px'),
        ('background-color', t.divider),
        ('margin', f'{_px(SPACE_1)} 10px'),
    ]))

    # -- 播放列表 / playlist -------------------------------------------------
    # surface_header replaces the old hardcoded dark-grey header band (A3).
    emit(_rule('#playlistHeader', [
        ('background-color', t.surface_header),
        ('color', t.text_primary),
        ('font-size', _px(FONT_SIZE_LG)),
        ('font-weight', '600'),
        ('padding', f'{_px(SPACE_2)} {_px(SPACE_3)}'),
    ]))
    emit(_rule('#playlistView', [
        ('background-color', playlist_bg),
        ('border', f'1px solid {t.border}'),
    ]))
    # Row height comes from PlaylistItemDelegate.sizeHint() (ROW_HEIGHT);
    # setting height here would fight the delegate.
    emit(_rule('#playlistView::item', [
        ('padding', f'0 {_px(SPACE_2)}'),
        ('border-bottom', f'1px solid {t.divider}'),
    ]))

    # -- 滑块 / sliders ------------------------------------------------------
    # One rule set for both sliders: same groove, same accent sub-page, same
    # handle. The progress/volume divergence is gone by construction.
    emit(_rule(tuple(f'{name}::groove:horizontal' for name in sliders), [
        ('height', '6px'),
        ('background-color', groove_bg),
        ('border-radius', '3px'),
    ]))
    emit(_rule(tuple(f'{name}::sub-page:horizontal' for name in sliders), [
        ('background-color', t.accent),
        ('border-radius', '3px'),
    ]))
    emit(_rule(tuple(f'{name}::handle:horizontal' for name in sliders), [
        ('width', '14px'),
        ('height', '14px'),
        ('margin', '-4px 0px'),
        ('background-color', t.accent),
        ('border-radius', '7px'),
    ]))
    emit(_rule(tuple(f'{name}::handle:horizontal:hover' for name in sliders), [
        ('background-color', t.accent_hover),
    ]))
    emit(_rule(tuple(f'{name}::handle:horizontal:pressed' for name in sliders), [
        ('background-color', t.accent_pressed),
    ]))

    # -- 按钮 / buttons ------------------------------------------------------
    emit(_rule((transport, '#loopButton'), [
        ('background-color', t.button_bg),
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_MD)),
        ('min-width', _px(TRANSPORT_SIZE)),
        ('max-width', _px(TRANSPORT_SIZE)),
        ('min-height', _px(TRANSPORT_SIZE)),
        ('max-height', _px(TRANSPORT_SIZE)),
    ]))
    emit(_rule((f'{transport}:hover', '#loopButton:hover'), [
        ('background-color', t.button_hover),
        ('border-color', t.border_strong),
    ]))
    emit(_rule((f'{transport}:pressed', '#loopButton:pressed'), [
        ('background-color', t.button_pressed),
    ]))
    emit(_rule('#playButton', [
        ('background-color', t.accent),
        ('color', t.text_on_accent),
        ('border', 'none'),
        ('border-radius', _px(PLAY_SIZE // 2)),
        ('min-width', _px(PLAY_SIZE)),
        ('max-width', _px(PLAY_SIZE)),
        ('min-height', _px(PLAY_SIZE)),
        ('max-height', _px(PLAY_SIZE)),
    ]))
    emit(_rule('#playButton:hover', [
        ('background-color', t.accent_hover),
    ]))
    emit(_rule('#playButton:pressed', [
        ('background-color', t.accent_pressed),
    ]))
    # Media-library chips: pill buttons; [selected="true"] is set by the
    # widget side with unpolish/polish, no per-widget stylesheet involved.
    emit(_rule(chip, [
        ('background-color', t.button_bg),
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_PILL)),
        ('padding', f'{_px(SPACE_1)} {_px(SPACE_3)}'),
        ('color', t.text_primary),
    ]))
    emit(_rule(f'{chip}:hover', [
        ('background-color', t.button_hover),
    ]))
    # Controller ruling (deviates from the brief's mapping table): the selected
    # chip is an OUTLINED chip -- `accent` text and border on `surface` -- not a
    # filled `accent_soft` one. No single `accent_*` foreground clears 4.5:1 on
    # `accent_soft` in both themes (LIGHT `accent` 4.03, DARK `accent_pressed`
    # 4.44 -- the accent family's lightness ordering inverts between themes),
    # while `accent` on `surface` is 4.60 LIGHT / 6.91 DARK. Guarded in
    # tests/test_theme_qss.py::SelectedChipContrastTest.
    emit(_rule(f'{chip}[selected="true"]', [
        ('background-color', t.surface),
        ('border-color', t.accent),
        ('color', t.accent),
    ]))

    # Disabled states for every button family (spec §4.2 last table row).
    emit(_rule((f'{transport}:disabled', '#loopButton:disabled',
                '#playButton:disabled', f'{chip}:disabled'), [
        ('background-color', t.button_disabled_bg),
        ('color', t.button_disabled_text),
        ('border-color', t.button_disabled_bg),
    ]))

    # -- 正在播放文字区 / now-playing labels ---------------------------------
    emit(_rule('#trackTitle', [
        ('color', t.text_primary),
        ('font-size', _px(FONT_SIZE_XL)),
        ('font-weight', 'bold'),
    ]))
    emit(_rule('#trackArtist', [
        ('color', t.text_secondary),
        ('font-size', _px(FONT_SIZE_MD)),
    ]))
    emit(_rule('#trackAlbum', [
        ('color', t.text_muted),
        ('font-size', _px(FONT_SIZE_MD)),
    ]))
    emit(_rule('#timeLabel', [
        ('color', t.text_secondary),
        ('font-size', _px(FONT_SIZE_SM)),
    ]))
    emit(_rule('#albumArt', [
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_MD)),
        ('background-color', t.surface_alt),
    ]))

    # -- 背景路径标签 / background-path label --------------------------------
    # The dialog toggles state via setProperty('empty', ...) + unpolish/polish
    # instead of the old seven setStyleSheet call sites (spec §4.2).
    emit(_rule('#bgPathLabel', [
        ('color', t.text_primary),
    ]))
    emit(_rule('#bgPathLabel[empty="true"]', [
        ('color', t.text_muted),
        ('font-style', 'italic'),
    ]))

    # -- 焦点环 / focus rings --------------------------------------------------
    # Scoped rings only; the old-era `*:focus` wildcard never comes back.
    emit(_rule('#playlistView:focus', [
        ('border', f'2px solid {t.focus_ring}'),
    ]))
    emit(_rule((f'{transport}:focus', '#loopButton:focus',
                '#playButton:focus', f'{chip}:focus'), [
        ('border', f'2px solid {t.focus_ring}'),
    ]))

    # -- 滚动条 / scrollbars ---------------------------------------------------
    emit(_rule('QScrollBar:vertical', [
        ('background-color', 'transparent'),
        ('width', '10px'),
        ('margin', '0px'),
        ('border', 'none'),
    ]))
    emit(_rule('QScrollBar::handle:vertical', [
        ('background-color', t.scrollbar_thumb),
        ('border-radius', '5px'),
        ('min-height', '30px'),
    ]))
    emit(_rule('QScrollBar::handle:vertical:hover', [
        ('background-color', t.scrollbar_thumb_hover),
    ]))
    emit(_rule(('QScrollBar::add-line:vertical', 'QScrollBar::sub-line:vertical'), [
        ('height', '0px'),
    ]))
    emit(_rule(('QScrollBar::add-page:vertical', 'QScrollBar::sub-page:vertical'), [
        ('background-color', 'transparent'),
    ]))
    # The old stylesheet only styled vertical bars, leaving horizontal ones in
    # raw Fusion grey; the full :horizontal set closes that hole.
    emit(_rule('QScrollBar:horizontal', [
        ('background-color', 'transparent'),
        ('height', '10px'),
        ('margin', '0px'),
        ('border', 'none'),
    ]))
    emit(_rule('QScrollBar::handle:horizontal', [
        ('background-color', t.scrollbar_thumb),
        ('border-radius', '5px'),
        ('min-width', '30px'),
    ]))
    emit(_rule('QScrollBar::handle:horizontal:hover', [
        ('background-color', t.scrollbar_thumb_hover),
    ]))
    emit(_rule(('QScrollBar::add-line:horizontal', 'QScrollBar::sub-line:horizontal'), [
        ('width', '0px'),
    ]))
    emit(_rule(('QScrollBar::add-page:horizontal', 'QScrollBar::sub-page:horizontal'), [
        ('background-color', 'transparent'),
    ]))

    # -- 浮层与分隔 / overlays & splitters ------------------------------------
    emit(_rule('QToolTip', [
        ('background-color', t.tooltip_bg),
        ('color', t.tooltip_text),
        ('border', 'none'),
        ('padding', f'{_px(SPACE_1)} {_px(SPACE_2)}'),
        ('border-radius', _px(RADIUS_SM)),
    ]))
    emit(_rule('QSplitter::handle', [
        ('background-color', t.divider),
    ]))
    emit(_rule('QSplitter::handle:horizontal', [
        ('width', '1px'),
    ]))

    # -- 对话框 / dialogs -------------------------------------------------------
    # appearanceDialog now sits on window_bg, so dialogs match the main
    # window's tone in both themes (A4).
    emit(_rule('QDialog#appearanceDialog', [
        ('background-color', t.window_bg),
        ('color', t.text_primary),
    ]))
    emit(_rule('QGroupBox', [
        ('background-color', t.surface),
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_MD)),
        ('margin-top', _px(SPACE_2)),
        ('padding', _px(SPACE_3)),
        ('color', t.text_primary),
    ]))
    emit(_rule('QGroupBox::title', [
        ('subcontrol-origin', 'margin'),
        ('subcontrol-position', 'top left'),
        ('padding', f'0 {_px(SPACE_1)}'),
        ('color', t.text_secondary),
    ]))

    return '\n'.join(rules)
