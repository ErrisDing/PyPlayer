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
  / ``QLabel`` rule carries a scope: an ``#objectName``, a
  ``[prop="value"]`` dynamic-property selector, or an ancestor
  (``QDialog QPushButton`` -- the dialog families, whose widgets get no
  objectName anywhere in the plan). A style can then never leak onto a widget
  that never asked for it (that leak is what made the progress slider and the
  volume slider render differently side by side). Application chrome
  (``QMenuBar``, ``QMenu``, ``QScrollBar``, ``QToolTip``, ``QSplitter``,
  ``QGroupBox``) is the recorded exemption -- not because it is single-instance
  (``QMenu``, ``QScrollBar`` and ``QGroupBox`` recur many times per window) but
  because the brief's mapping table mandates those rules bare; per-widget
  scoping there is not what the table asks for. ``QMainWindow`` is the one
  genuinely single-instance member, listed for the same table-mandated reason
  (its first table row is ``QMainWindow, #nowPlayingPanel``). The test lists
  the exemption by name, so a new bare class has to be argued for rather than
  slipped in.
* **No colour literals.** Every colour resolves to a token field, so LIGHT
  and DARK can be asserted identical in structure and the palette stays the
  one contrast-checked source of truth (see ``tests/test_theme.py``).
  ``tests/test_theme_qss.py::PaletteOnlyColoursTest`` enforces this per theme,
  so an edited rule that invents a hex fails the suite instead of shipping.

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
    # filled `accent_soft` one. Two reasons, both about meaning rather than
    # contrast arithmetic alone:
    #   1. `accent_hover` on `accent_soft` would clear 4.5:1 (5.03 LIGHT /
    #      6.72 DARK), but it is a *state* token. Pinning it as the resting
    #      text colour collides with the chip's `:hover` rule emitted just
    #      above and makes the hover state of a selected chip indistinguishable.
    #   2. `accent_soft` is numerically identical to `playing_bg` in both
    #      themes (`#e3f2fd` LIGHT / `#1f3a52` DARK), so a filled `accent_soft`
    #      chip renders exactly like the "now playing" row -- a library
    #      switcher that mimics track state.
    # The table's own pair (`accent` on `accent_soft`) is what forced the
    # background to move: 4.03 LIGHT / 5.31 DARK, i.e. under the 4.5 text bar in
    # LIGHT. `accent` on `surface` is 4.60 LIGHT / 6.91 DARK. Guarded in
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
    # Controller ruling on review finding 5: the buttons of
    # ``view/dialogs/library_dialog.py`` (add / delete / up / down / close) and
    # ``view/dialogs/appearance_dialog.py`` (select / clear / reset / close),
    # plus the library ``QListWidget``, are plain widgets that the plan's Task 5
    # objectName mandate never reaches. Without a rule of their own they would
    # drop back to raw Fusion metrics the moment ``styles.qss`` is deleted, so
    # the old global ``QPushButton`` / ``QListView`` rules migrate here as an
    # ANCESTOR-SCOPED family -- the ancestor is the scope, which satisfies the
    # no-bare-widget constraint and needs no widget change.
    # Token mapping of the old literals: ``#ffffff`` -> ``button_bg``,
    # ``#f5f5f5`` -> ``button_hover``, ``#e0e0e0`` -> ``button_pressed``,
    # ``#bdbdbd`` -> ``border_strong`` (hover border), ``#ffffff`` (list) ->
    # ``surface``; the base ``border`` uses the generic ``border`` token
    # (old ``#e0e0e0`` has no border-family twin and must stay legible in DARK),
    # disabled states reuse the same ``button_disabled_*`` pair as the rest of
    # the sheet. Geometry (4px radius, 6px 12px padding, 30px min-width) is the
    # old rule's, kept verbatim so the dialogs do not resize.
    emit(_rule('QDialog QPushButton', [
        ('background-color', t.button_bg),
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_SM)),
        ('padding', '6px 12px'),
        ('min-width', '30px'),
    ]))
    emit(_rule('QDialog QPushButton:hover', [
        ('background-color', t.button_hover),
        ('border-color', t.border_strong),
    ]))
    emit(_rule('QDialog QPushButton:pressed', [
        ('background-color', t.button_pressed),
    ]))
    emit(_rule('QDialog QPushButton:disabled', [
        ('background-color', t.button_disabled_bg),
        ('color', t.button_disabled_text),
        ('border-color', t.button_disabled_bg),
    ]))
    emit(_rule('QDialog QListWidget', [
        ('background-color', t.surface),
        ('border', 'none'),
    ]))
    # Item-level states of the library list (review round: the base-list
    # migration above left styles.qss:120-132's ``QListView::item`` family with
    # no successor). ``PlaylistItemDelegate`` paints ``#playlistView``'s item
    # states, but this ``QListWidget`` carries no delegate, so its row padding,
    # dividers and selection/hover colours must migrate too -- ``library_
    # dialog.py:113`` builds two-line rows (``f"{name}\n{path}"``) whose
    # legibility depends on exactly the ``6px 8px`` padding. Old literals ->
    # tokens: ``border-bottom #f0f0f0`` -> ``divider``, selected bg ``#e3f2fd``
    # -> ``accent_soft``, selected fg ``#333333`` -> ``text_primary``, hover bg
    # ``#f5f5f5`` -> ``hover_bg``. The ``6px 8px`` padding is not a tokenised
    # metric and the two-line rows need it, so it is kept verbatim. Ancestor-
    # scoped with two compounds, so it stays legal under the scope gate.
    emit(_rule('QDialog QListWidget::item', [
        ('padding', '6px 8px'),
        ('border-bottom', f'1px solid {t.divider}'),
    ]))
    emit(_rule('QDialog QListWidget::item:selected', [
        ('background-color', t.accent_soft),
        ('color', t.text_primary),
    ]))
    emit(_rule('QDialog QListWidget::item:hover', [
        ('background-color', t.hover_bg),
    ]))

    return '\n'.join(rules)
