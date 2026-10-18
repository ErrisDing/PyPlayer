#!/usr/bin/env python3
"""
PyPlayer QSS Generator

The single stylesheet source of the theme layer (spec
``docs/superpowers/specs/2026-10-16-ui-batch1-theme-tokens-design.md`` §4.2).
It replaces ``view/resources/styles.qss`` and, with it, the split between a
global style sheet and per-widget inline sheets: one call to
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
  (the mapping table's first row scopes it, and it is the one rule that carries
  the window's own ``window_bg`` fill -- see the Task 10 note where it is
  emitted). The test lists the exemption by name, so a new bare class has to be
  argued for rather than slipped in.
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
The reverse implication does not hold in batch 2: ``#actionRail``/``#railButton``
(Task 3), ``#librarySidebar``/``#sidebarTitle``/``#libraryRow``/``#sidebarEmpty``
(Task 4) and ``#nowPlayingStrip``/``#stripArt``/``#stripTitle``/``#stripArtist``
(Task 5) are emitted here before they are registered there, because the tuple is
asserted against the live ``MainWindow`` tree and those widgets only enter it in
Task 7. See the action-rail, library-sidebar and now-playing-strip sections for
the full ruling.
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
    ROW_HEIGHT,
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
    # The volume percentage read-out. Task 8 gave it a name because it is the
    # one label in the bottom row that is still *text* (the speaker beside it is
    # an icon rasterised from ``tokens.icon`` and needs no rule at all); left
    # unnamed it would take its colour from the palette -- ``QLabel`` asks
    # ``QWidget::foregroundRole()``, which is ``WindowText`` and maps to
    # ``text_primary`` -- instead of the sheet's secondary colour, so it would
    # sit brighter than the two time labels it pairs with.
    'volumeLabel',
    'appearanceDialog',
    'bgPathLabel',
    # The three transparency sliders of the appearance dialog. Task 5 named
    # them and deliberately left them unstyled; Task 6 gave them the same rule
    # set as the volume slider, so the styling contract closes here.
    'overlaySlider',
    'playlistSlider',
    'controlsSlider',
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
        A QSS string ready for the application-wide style sheet. Every colour
        comes from ``tokens`` (no literals), every widget rule is scoped, and
        every name in :data:`REQUIRED_OBJECT_NAMES` /
        :data:`REQUIRED_DYN_PROPERTIES` appears in the output.
    """
    t = tokens
    # Surfaces the two panels composite from `surface` at the user's alpha.
    playlist_bg = hex_to_rgba(t.surface, _clamp_alpha(alphas.playlist))
    controls_bg = hex_to_rgba(t.surface, _clamp_alpha(alphas.controls))
    # Every slider in the app composites its groove from this one value, so the
    # progress and volume bars can only render identically (A1).
    groove_bg = hex_to_rgba(t.border_strong, 0.5)

    transport = 'QPushButton[role="transport"]'
    chip = 'QPushButton[chip="true"]'
    # All five sliders share one rule set: the two transport sliders plus the
    # three appearance-dialog sliders. The dialog ones are named here rather
    # than left as bespoke Fusion widgets -- a transparency slider is a slider,
    # and Task 5 gave them objectNames precisely so this rule could reach them.
    sliders = (
        '#progressSlider',
        '#volumeSlider',
        '#overlaySlider',
        '#playlistSlider',
        '#controlsSlider',
    )

    rules: list[str] = []
    emit = rules.append

    # -- 窗口与面板 / window & panels --------------------------------------
    # Ruling from the Task 10 render matrix, deviating from the mapping table's
    # first row (``QMainWindow, #nowPlayingPanel`` -> both ``transparent``):
    # ``window_bg`` belongs on the window, and only the panel stays transparent.
    #
    # The table's version was inherited verbatim from ``styles.qss``, whose own
    # comment claimed "Fusion style provides the fallback for non-content
    # areas". It does not. Once a sheet sets ``background-color`` on
    # ``QMainWindow``, ``QStyleSheetStyle`` answers ``PE_Widget`` with that
    # brush, and a transparent brush fills nothing -- so the central widget, the
    # splitter and every margin of the window were left unpainted. Measured on a
    # real Windows desktop (``QScreen.grabWindow``, i.e. the composited pixels a
    # user sees, not ``grab()``): the whole now-playing column came back
    # ``#000000`` in BOTH themes, and the two translucent panels composited
    # against that black instead of against the window -- ``#playlistView``
    # measured ``#bfbfbf`` and ``#bottomPanel`` ``#d8d8d8``, i.e. exactly
    # ``rgba(#ffffff, 0.75)`` and ``rgba(#ffffff, 0.85)`` over ``#000000``.
    # Over ``window_bg`` (``#fafafa``) those two alphas both land on
    # ``#fefefe`` (253.75 and 254.25), which is what a live window grab of the
    # repaired sheet measures; the ``#f7f7f7`` / ``#fbfbfb`` this note used to
    # quote as the expected pair was arithmetic, not a measurement, and both
    # numbers were wrong. Dark mode hid the bug (``#000`` next to ``#1e1e1e``
    # reads as a deliberate gutter) and light mode wore it as a black slab.
    #
    # The background-image feature is untouched: ``MainWindow.paintEvent`` draws
    # the pixmap and the scrim in its own handler, which runs after this fill
    # and before the children paint, so a configured image still shows through
    # the transparent panel and the two alpha-composited surfaces.
    #
    # The value below is pinned by ``tests/test_theme_qss.py::MainWindowFillTest``:
    # "is the window filled at all" is invisible to a structural gate, since a
    # sheet that keeps the selector, the scope exemption and the token palette
    # passes every guard in that suite while filling the window with nothing.
    emit(_rule('QMainWindow', [
        ('background-color', t.window_bg),
    ]))
    # This one stays transparent on purpose: it is the panel the background
    # image has to show through when a user configures one.
    emit(_rule('#nowPlayingPanel', [
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
    # No ``#playlistView::item`` rule here, on purpose. The view carries
    # PlaylistItemDelegate, which overrides ``paint()`` and never asks the
    # style to draw the item sub-control, so ``padding`` and ``border-bottom``
    # written here cannot reach a pixel: Task 4 emitted the mapping table's row,
    # and the branch shipped 0 pixels of ``divider`` inside a live viewport
    # (measured -- a window grab with and without the rule is pixel-identical).
    # The delegate now paints both, the ``SPACE_2`` side inset and the 1px
    # ``divider`` at the row bottom, from the same two tokens, so the value the
    # table asked for is on screen while this sheet stops claiming pixels it does
    # not produce. Contrast ``QDialog QListWidget::item`` at the bottom of this
    # file: that list has no delegate, so its row padding and divider must live
    # here or they vanish (measured: 956 ``divider`` pixels in that viewport).
    #
    # Row height is the delegate's too (``ROW_HEIGHT`` via ``sizeHint``);
    # setting ``height`` here would fight it.

    # -- 滑块 / sliders ------------------------------------------------------
    # One rule set for every slider in the app: same groove, same accent
    # sub-page, same handle. The progress/volume divergence is gone by
    # construction, and the dialog's transparency sliders join the same family.
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
    #      above.
    #   2. `accent_soft` is numerically identical to `playing_bg` in both
    #      themes (`#e3f2fd` LIGHT / `#1f3a52` DARK), so a filled `accent_soft`
    #      chip renders exactly like the "now playing" row -- a library
    #      switcher that mimics track state.
    # The table's own pair (`accent` on `accent_soft`) is what forced the
    # background to move: 4.03 LIGHT / 5.31 DARK, i.e. under the 4.5 text bar in
    # LIGHT. `accent` on `surface` is 4.60 LIGHT / 6.91 DARK. Guarded in
    # tests/test_theme_qss.py::SelectedChipContrastTest.
    #
    # Correction from the Task 10 render matrix: reason 1 as originally written
    # claimed this keeps "the hover state of a selected chip" distinguishable.
    # It does not. `[chip="true"]:hover` and `[chip="true"][selected="true"]`
    # carry the same specificity (two attribute/pseudo-class terms each), so the
    # later rule wins and a selected chip keeps `surface` under the pointer:
    # a selected chip has no hover feedback at all. That is defensible --
    # `LibrarySelector._on_button_click` returns early on the already-current
    # library, so hovering a selected chip promises an action that does nothing
    # -- but it is not what the comment said, and the comment now says what is
    # true. (The hover state itself could not be photographed here: neither
    # `WA_UnderMouse` nor a synthetic mouse-move drives QSS `State_MouseOver`,
    # and this host's cursor is on a virtual display that will not hold a
    # `QCursor.setPos`. See the task report.)
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

    # -- 图标栏 / action rail (batch 2, Task 3) -------------------------------
    # ``#actionRail`` / ``#railButton`` are styled here but deliberately *not*
    # registered in ``REQUIRED_OBJECT_NAMES`` yet: that tuple's other consumer,
    # ``tests/test_view_structure.py::test_every_required_object_name_exists``,
    # walks the live ``MainWindow`` tree, and the rail enters it in Task 7. A
    # rule naming a widget that is not in the tree is inert; a registered name
    # without the widget is a red suite. Task 7 registers the rail's two names
    # together with the floating panel's.
    emit(_rule('#actionRail', [
        ('background-color', t.surface_alt),
        ('border-right', f'1px solid {t.divider}'),
    ]))
    # Flat by default: the rail's own fill is the column's, so a resting button
    # must not wear a plate. Geometry comes from ``TRANSPORT_SIZE``, the token
    # the transport row uses, so the two 40 px squares are one size class.
    emit(_rule('#railButton', [
        ('background-color', 'transparent'),
        ('border', 'none'),
        ('border-radius', _px(RADIUS_MD)),
        ('width', _px(TRANSPORT_SIZE)),
        ('height', _px(TRANSPORT_SIZE)),
    ]))
    emit(_rule('#railButton:hover', [
        ('background-color', t.hover_bg),
    ]))
    emit(_rule('#railButton:pressed', [
        ('background-color', t.button_pressed),
    ]))
    # A blocked partner of a running action: the widget side disables it, and
    # the disabled fill is the same token the other button families fall back to.
    emit(_rule('#railButton:disabled', [
        ('background-color', t.button_disabled_bg),
    ]))
    # The running state, marked by ``ActionRail`` with
    # ``setProperty('running', 'true')`` + unpolish/polish. ``accent_soft`` is the
    # sheet's "this is on" fill (it is what the selected chip would have worn);
    # the glyph inside it is the ``refresh`` spinner rasterised from ``tokens.icon``.
    #
    # This rule must stay *after* ``:disabled``: a running button is also a
    # disabled one, and the two selectors carry equal specificity
    # (``#railButton`` plus one attribute or pseudo-class term), so the later
    # declaration wins. Emit it first and the progress state renders as grey
    # disabled, i.e. the indicator is invisible exactly when it matters.
    emit(_rule('#railButton[running="true"]', [
        ('background-color', t.accent_soft),
    ]))
    emit(_rule('#railButton:focus', [
        ('border', f'2px solid {t.focus_ring}'),
    ]))

    # -- 曲库浮层 / library sidebar (batch 2, Task 4) ---------------------------
    # Same registration ruling as the rail: the rules land here, the four names
    # reach ``REQUIRED_OBJECT_NAMES`` in Task 7, when the panel enters the live
    # ``MainWindow`` tree the structure test walks.
    #
    # ``surface`` (not ``surface_alt``) is the deliberate choice: the panel floats
    # over ``#playlistView``, whose fill is ``surface`` composited at the user's
    # playlist alpha, and the palette's ``Base`` -- which is what the scroll area's
    # viewport paints behind the rows -- is ``surface`` too. A raised card has to
    # read as *above* the list, so it wears the list's own colour un-composited and
    # carries a ``border_strong`` edge to say "floating"; ``border`` would vanish
    # into the list's own 1px rule.
    emit(_rule('#librarySidebar', [
        ('background-color', t.surface),
        ('border', f'1px solid {t.border_strong}'),
        ('border-radius', _px(RADIUS_MD)),
        ('padding', f'{_px(SPACE_2)} {_px(SPACE_3)}'),
    ]))
    # The panel's heading is a small-cap label, not a second ``#playlistHeader``:
    # two 15px/600 headings in one window is what made the old left column look
    # like a second app.
    emit(_rule('#sidebarTitle', [
        ('color', t.text_secondary),
        ('font-size', _px(FONT_SIZE_SM)),
        ('font-weight', '600'),
    ]))
    # A row is a flat, left-aligned, full-width button. The 2px left border is
    # declared ``transparent`` at rest so the current state can paint it without
    # shifting the text by two pixels -- the same reserved-gutter trick the
    # delegate uses for the playing bar.
    emit(_rule('#libraryRow', [
        ('background-color', 'transparent'),
        ('border', 'none'),
        ('border-left', '2px solid transparent'),
        ('border-radius', _px(RADIUS_SM)),
        ('padding', f'{_px(SPACE_1)} {_px(SPACE_3)}'),
        ('min-height', _px(ROW_HEIGHT)),
        ('text-align', 'left'),
        ('color', t.text_primary),
    ]))
    emit(_rule('#libraryRow:hover', [
        ('background-color', t.hover_bg),
    ]))
    emit(_rule('#libraryRow:pressed', [
        ('background-color', t.button_pressed),
    ]))
    # The current library, marked by ``LibrarySidebar.set_current`` with
    # ``setProperty('current', 'true')`` + unpolish/polish. ``selection_bg`` is the
    # sheet's one "this row is chosen" fill (``PlaylistItemDelegate`` paints the
    # same token for a selected track); ``accent_soft`` is *not* used here, for the
    # two reasons the selected chip already records -- it is byte-identical to
    # ``playing_bg``, so a library switcher would mimic track state, and
    # ``accent`` on it is under the 4.5 text bar in LIGHT. ``text_primary`` on
    # ``selection_bg`` is a contrast-pinned pair, and the glyph in it is covered by
    # the ``icon``/``selection_bg`` pin in ``tests/test_theme.py``.
    emit(_rule('#libraryRow[current="true"]', [
        ('background-color', t.selection_bg),
        ('border-left', f'2px solid {t.accent}'),
        ('color', t.text_primary),
    ]))
    emit(_rule('#libraryRow:focus', [
        ('border', f'2px solid {t.focus_ring}'),
    ]))
    # First launch (spec §6): the panel is not empty, it is *explaining*.
    emit(_rule('#sidebarEmpty', [
        ('color', t.text_muted),
        ('font-size', _px(FONT_SIZE_SM)),
    ]))

    # -- 底部正在播放条 / now-playing strip (batch 2, Task 5) -------------------
    # Registration ruling as above: four names, styled now, in
    # ``REQUIRED_OBJECT_NAMES`` in Task 7.
    #
    # ``transparent`` rather than a fill of its own: the strip sits *inside*
    # ``#bottomPanel``, whose background is ``surface`` composited at the user's
    # controls alpha. Painting any token here would put an opaque plate over that
    # composite -- the exact divergence the theme layer was built to remove. The
    # box below is the one thing the strip may paint, because it is an inset frame
    # around an image, not a surface.
    emit(_rule('#nowPlayingStrip', [
        ('background-color', 'transparent'),
    ]))
    # The same box ``#albumArt`` draws around the 200 px panel cover, at the size
    # the 48 px thumbnail needs: ``surface_alt`` behind the image (so a partially
    # transparent PNG does not sit on the composited bar), ``border`` and a radius
    # one step down from the panel's.
    emit(_rule('#stripArt', [
        ('border', f'1px solid {t.border}'),
        ('border-radius', _px(RADIUS_SM)),
        ('background-color', t.surface_alt),
    ]))
    # Two lines, not three: the old ``#trackTitle`` was 18 px bold in a column of
    # its own, and a bar one row taller than the transport buttons cannot carry that.
    # ``font-weight: 600`` matches the sheet's other heading weights rather than
    # ``bold``, which at 13 px makes an elided title look like a header.
    emit(_rule('#stripTitle', [
        ('color', t.text_primary),
        ('font-size', _px(FONT_SIZE_MD)),
        ('font-weight', '600'),
    ]))
    emit(_rule('#stripArtist', [
        ('color', t.text_secondary),
        ('font-size', _px(FONT_SIZE_SM)),
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
    # The three read-outs of the bottom row share one rule: elapsed time, total
    # duration and the volume percentage are the same kind of small secondary
    # text, and giving the third its own copy of the declarations is how the
    # progress and volume sliders ended up looking different in the first place.
    emit(_rule(('#timeLabel', '#volumeLabel'), [
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
    # instead of the seven inline sheets it used to paste onto that label
    # (spec §4.2).
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
        # ``styles.qss:117`` had it; without it a focus rectangle can reappear
        # on the library list, and in DARK that rectangle is drawn from the
        # palette's Highlight, i.e. an accent ring around a row that is not
        # selected.
        ('outline', 'none'),
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
