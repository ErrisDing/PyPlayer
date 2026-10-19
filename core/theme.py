#!/usr/bin/env python3
"""
PyPlayer Theme Tokens Module

Single source of truth for the UI's semantic colours, geometry and typography
(spec ``docs/superpowers/specs/2026-10-16-ui-batch1-theme-tokens-design.md`` §4.1).

This module is deliberately pure Python: colours are ``#rrggbb`` strings rather
than ``QColor``, and nothing here imports Qt, so the tokens can be unit-tested
without a display (see ``tests/test_theme.py``). Qt-facing code (palette mapping,
QSS generation) consumes these tokens but never redefines them.
"""

from dataclasses import dataclass, fields

from core.constants import AppearanceDefaults


@dataclass(frozen=True)
class ThemeTokens:
    """Semantic colour tokens for one theme.

    Field names are the contract with ``core.theme_qss`` and the delegate
    painters; the ordered list is exported as :data:`TOKEN_FIELDS`.
    """

    # 表面 / surfaces
    window_bg: str
    surface: str
    surface_alt: str
    surface_header: str
    scrim: str

    # 文字 / text
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_accent: str

    # 强调 / accent
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str

    # 列表状态 / list states
    selection_bg: str
    playing_bg: str
    playing_text: str
    playing_bar: str
    hover_bg: str

    # 线 / lines
    border: str
    border_strong: str
    divider: str

    # 控件 / controls
    button_bg: str
    button_hover: str
    button_pressed: str
    button_disabled_bg: str
    button_disabled_text: str
    icon: str
    icon_muted: str
    icon_on_accent: str
    focus_ring: str

    # 浮层 / overlays
    tooltip_bg: str
    tooltip_text: str
    scrollbar_thumb: str
    scrollbar_thumb_hover: str


TOKEN_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(ThemeTokens))


LIGHT = ThemeTokens(
    # 表面
    window_bg='#fafafa',
    surface='#ffffff',
    surface_alt='#f5f5f5',
    surface_header='#f0f2f5',
    scrim='#ffffff',
    # 文字
    text_primary='#1f1f1f',
    text_secondary='#5a5a5a',
    text_muted='#6a6a6a',
    text_on_accent='#ffffff',
    # 强调
    accent='#1976d2',
    accent_hover='#1565c0',
    accent_pressed='#0d47a1',
    accent_soft='#e3f2fd',
    # 列表状态
    selection_bg='#eceff1',
    playing_bg='#e3f2fd',
    playing_text='#0d47a1',
    playing_bar='#1976d2',
    hover_bg='#f0f0f0',
    # 线
    border='#d5d5d5',
    border_strong='#bdbdbd',
    divider='#eeeeee',
    # 控件
    button_bg='#ffffff',
    button_hover='#f0f0f0',
    button_pressed='#e0e0e0',
    button_disabled_bg='#f7f7f7',
    button_disabled_text='#a8a8a8',
    icon='#444444',
    icon_muted='#6e6e6e',
    icon_on_accent='#ffffff',
    focus_ring='#1976d2',
    # 浮层
    tooltip_bg='#323232',
    tooltip_text='#ffffff',
    scrollbar_thumb='#c0c0c0',
    scrollbar_thumb_hover='#9e9e9e',
)


DARK = ThemeTokens(
    # 表面
    window_bg='#1e1e1e',
    surface='#252526',
    surface_alt='#2d2d30',
    surface_header='#2f3338',
    scrim='#121212',
    # 文字
    text_primary='#e4e4e4',
    text_secondary='#b0b0b0',
    text_muted='#a3a3a3',
    text_on_accent='#0b1c2c',
    # 强调
    accent='#64b5f6',
    accent_hover='#90caf9',
    accent_pressed='#42a5f5',
    accent_soft='#1f3a52',
    # 列表状态
    selection_bg='#2f343a',
    playing_bg='#1f3a52',
    playing_text='#90caf9',
    playing_bar='#64b5f6',
    hover_bg='#2a2d2e',
    # 线
    border='#3f3f46',
    border_strong='#555555',
    divider='#333333',
    # 控件
    button_bg='#2d2d30',
    button_hover='#3e3e42',
    button_pressed='#4a4a4e',
    button_disabled_bg='#2a2a2c',
    button_disabled_text='#6a6a6a',
    icon='#d0d0d0',
    icon_muted='#9a9a9a',
    icon_on_accent='#0b1c2c',
    focus_ring='#64b5f6',
    # 浮层
    tooltip_bg='#3b3b3b',
    tooltip_text='#e4e4e4',
    scrollbar_thumb='#4a4a4a',
    scrollbar_thumb_hover='#6a6a6a',
)


THEMES: dict[str, ThemeTokens] = {'light': LIGHT, 'dark': DARK}


@dataclass(frozen=True)
class AlphaSettings:
    """Transparency values applied on top of the colour tokens.

    The three fields mirror the user-visible sliders of the appearance dialog
    and keep their existing defaults (``core.constants.AppearanceDefaults``).
    Values are on a 0.0-1.0 scale.
    """

    overlay: float = AppearanceDefaults.BACKGROUND_OVERLAY_ALPHA
    playlist: float = AppearanceDefaults.PLAYLIST_BG_ALPHA
    controls: float = AppearanceDefaults.BOTTOM_PANEL_BG_ALPHA


# Shared geometry / typography tokens (theme independent, px units).
RADIUS_SM = 4
RADIUS_MD = 6

# The media-library chip's pill radius. NOT a "big number that means pill":
# Qt 6.11's QSS border-radius clamping does not clamp, it gives up. Measured on
# a 122x29 chip, every radius from 15px upward (including 999px, and 50%, which
# Qt does not parse as a radius at all) rasterises to *square* corners,
# pixel-identical to emitting no border-radius at all; only 14 and below round.
# The threshold is the pairwise one -- 2r must not exceed height-1 -- so a
# radius that means "pill" has to be a real number, and 12 pills the chip's
# actual 29px height (2x12 = 24 <= 28) with 4px of headroom before the corner
# collapses. Verified through the render matrix (tests/tools/render_matrix.py).
RADIUS_PILL = 12

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16

ROW_HEIGHT = 28
TRANSPORT_SIZE = 40
PLAY_SIZE = 50

# Batch 2 (icon rail + full-width list + floating library panel) retired
# ``ART_SIZE``: the 200 px cover box belonged to the left panel, and the left
# panel is gone. The three replacements are sized for the shells that do exist.
# ``STRIP_ART_SIZE`` is the now-playing strip's cover box (one row tall, next to
# the transport buttons, hence 48 against ``TRANSPORT_SIZE`` 40); ``RAIL_WIDTH``
# is the icon rail's fixed width -- 56 px holds a 40 px button with 8 px of
# gutter on each side, so a rail button and a transport button are the same
# object on screen; ``SIDEBAR_WIDTH`` is the floating library panel's preferred
# width, clamped by its parent container, which in the shipped shell is the
# window minus the rail.
STRIP_ART_SIZE = 48
RAIL_WIDTH = 56
SIDEBAR_WIDTH = 240

FONT_SIZE_SM = 12
FONT_SIZE_MD = 13
FONT_SIZE_LG = 15
FONT_SIZE_XL = 18


def resolve(mode: str, system_scheme: str) -> ThemeTokens:
    """Pick the token set for a theme mode plus the OS colour scheme.

    Args:
        mode: ``'auto'``, ``'light'`` or ``'dark'``. Anything else raises
            ``ValueError`` so a typo'd preference can never silently render
            the wrong theme.
        system_scheme: ``QColorScheme.name`` value, i.e. ``'Dark'``,
            ``'Light'`` or ``'Unknown'``. Only consulted when ``mode`` is
            ``'auto'``; ``'Unknown'`` (offscreen platform, older Qt) falls
            back to ``LIGHT`` deterministically.

    Returns:
        The :data:`LIGHT` or :data:`DARK` instance itself (identity is stable,
        so callers may compare with ``is`` or use it as a dict key).
    """
    if mode == 'light':
        return LIGHT
    if mode == 'dark':
        return DARK
    if mode == 'auto':
        if system_scheme == 'Dark':
            return DARK
        if system_scheme in ('Light', 'Unknown'):
            return LIGHT
        raise ValueError(
            f'Unknown system colour scheme: {system_scheme!r} '
            "(expected 'Dark', 'Light' or 'Unknown')"
        )
    raise ValueError(f'Unknown theme mode: {mode!r} (expected auto, light or dark)')
