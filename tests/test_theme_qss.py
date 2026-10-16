#!/usr/bin/env python3
"""Unit tests for the QSS generator (Task 4: ``core/theme_qss.py``).

The module is pure Python (no Qt import), so these tests need neither a
display nor PyQt6:

    python -m unittest tests.test_theme_qss -v

The generator is the single stylesheet source of the theme layer: every rule
must be scoped to an ``#objectName``, a ``[prop="value"]`` dynamic property or
an ancestor (the bare-widget rules of ``view/resources/styles.qss`` are exactly
what produced the two different-looking sliders), and every colour must come
from a ``core.theme`` token. Both invariants are tested here rather than
eyeballed once -- Tasks 5 and 6 edit the generator, and a regression in either
must fail the suite.
"""
import re
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The classes that recur per instance and therefore may never be styled
# globally: each one is scoped behind an objectName, a dynamic property or an
# ancestor in ``core/theme_qss.py``.
SCOPED_NEEDING_CLASSES = ('QPushButton', 'QSlider', 'QListView', 'QLabel')

# Recorded exemption (controller ruling on review finding 1): application
# chrome that stays bare *by decision* -- the brief's mapping table mandates
# these rules bare. This is NOT a single-instance claim: ``QMenu``, ``QScrollBar``
# and ``QGroupBox`` recur many times per window and are still named globally by
# the table (per-widget scoping would be noise and is not what the brief asks).
# Adding a class here is a review-visible decision, not a blind spot.
# ``QMainWindow`` is the seventh entry: the ruling named six, and the gate then
# caught the bare ``QMainWindow`` of the table's first row (brief line 33,
# ``QMainWindow, #nowPlayingPanel``). It belongs here rather than in the blind
# spot, so it is listed and explained.
EXEMPT_CHROME_CLASSES = (
    'QMenuBar',
    'QMenu',
    'QScrollBar',
    'QToolTip',
    'QSplitter',
    'QGroupBox',
    'QMainWindow',
)

# Bare-widget gate, line-anchored: a scoped-needing class at the start of a
# selector that is NOT immediately followed by an id (``#``), a property
# (``[``) or another word character. That catches the forms the old narrow
# regex missed -- ``QPushButton:disabled {``, ``QLabel:hover {`` and, with
# ``re.M``, a bare member of a comma list (``QPushButton, #foo {``), since
# ``_rule`` emits one selector per line.
BARE_WIDGET_RE = re.compile(
    r'^\s*(?:%s)(?![#\w\[])' % '|'.join(SCOPED_NEEDING_CLASSES), re.M)

# Any ``{placeholder}`` left in the output means a substitution silently
# failed and the raw template leaked into the stylesheet.
LEFTOVER_PLACEHOLDER_RE = re.compile(r'\{[a-z_]+\}')

# The alpha value of any ``rgba(r, g, b, a)`` produced by the generator.
RGBA_ALPHA_RE = re.compile(r'rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([0-9.]+)\s*\)')

# Colour constituents found in the generated sheet, and the properties that are
# allowed to contain a colour at all. ``{3,8}`` deliberately also catches the
# 3-digit shorthand, so `border-color: #bbb` -- the exact stray literal this
# task is meant to make impossible -- is reported instead of ignored.
HEX_COLOR_RE = re.compile(r'#[0-9a-fA-F]{3,8}\b')
RGBA_COLOR_RE = re.compile(r'rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[0-9.]+\s*\)')
RGBA_TRIPLE_RE = re.compile(
    r'rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*[0-9.]+\s*\)')
DECLARATION_RE = re.compile(r'^\s*([a-z-]+)\s*:\s*([^;]+);', re.M)
COLOUR_PROPERTIES = frozenset({
    'color', 'background', 'background-color', 'border', 'border-color',
    'border-top', 'border-bottom', 'border-left', 'border-right', 'outline',
    'outline-color',
})
# A declaration value with its hex/rgba colours removed may only keep the
# permitted named colours and the border-style keywords that always ride along
# with ``1px``. Anything else -- ``red``, ``#bbb``-equivalents, a CSS name --
# is an off-palette colour and fails.
PERMITTED_COLOUR_WORDS = frozenset({
    'transparent', 'none',                      # permitted named values
    'solid', 'dashed', 'dotted', 'double',      # border styles, never colours
    'groove', 'ridge', 'inset', 'outset', 'hidden',
})

# Selector parsing for the scope gate.
CLASS_COMPOUND_RE = re.compile(r'\.?Q[A-Za-z_][A-Za-z0-9_]*')
COMBINATOR_SPLIT_RE = re.compile(r'[\s>+~]+')

# The selected media-library chip rule, pinned so the contrast guard below
# reads the exact rule the generator emits rather than a substring hit on the
# base ``QPushButton[chip="true"]`` rule.
CHIP_SELECTED_SELECTOR = 'QPushButton[chip="true"][selected="true"]'

# Review finding 5: the ancestor-scoped dialog family. Task 5's objectName
# mandate does not reach these widgets, so a rename of the family -- or scoping
# it to one dialog only -- silently unstyles the other.
DIALOG_SELECTORS = (
    'QDialog QPushButton',
    'QDialog QPushButton:hover',
    'QDialog QPushButton:pressed',
    'QDialog QPushButton:disabled',
    'QDialog QListWidget',
    'QDialog QListWidget::item',
    'QDialog QListWidget::item:selected',
    'QDialog QListWidget::item:hover',
)


def _rule_block(qss: str, selector_pattern: str) -> str:
    """Return the declaration body of the rule whose selector matches.

    ``selector_pattern`` is matched literally against the text preceding
    ``{``, so callers pin the exact rule (``#playlistView {``) instead of the
    first substring hit (``#playlistView::item {``).
    """
    match = re.search(re.escape(selector_pattern) + r'\s*\{([^}]*)\}', qss)
    assert match, f'no rule block found for {selector_pattern!r}'
    return match.group(1)


def _selector_members(qss: str) -> list[str]:
    """Every comma-separated selector of every rule, in document order."""
    members = []
    for chunk in qss.split('}'):
        selector, brace, _body = chunk.partition('{')
        if not brace:
            continue
        members.extend(part.strip() for part in selector.split(',') if part.strip())
    return members


def _bare_class_selectors(qss: str) -> list[tuple[str, str]]:
    """``(selector, class)`` for every rule that styles a class globally.

    Bare means: a single compound naming a Qt class (or ``*``) with no
    ``#objectName``, no ``[prop="value"]`` and no leading ancestor attached.
    ``QPushButton``, ``QPushButton:disabled``, ``QLabel:hover``,
    ``QListView::item`` and the ``QPushButton`` member of
    ``QPushButton, #foo`` are bare; ``QPushButton[chip="true"]``, ``#playlistView``
    and ``QDialog QPushButton`` are not.
    """
    found = []
    for member in _selector_members(qss):
        if member.startswith('*'):
            found.append((member, '*'))
            continue
        compounds = COMBINATOR_SPLIT_RE.split(member)
        if len(compounds) != 1:
            continue        # ancestor-scoped: the scope is the ancestor
        compound = compounds[0]
        match = CLASS_COMPOUND_RE.match(compound)
        if not match or '#' in compound or '[' in compound:
            continue        # objectName / property scoped, or not a class
        found.append((member, match.group(0).lstrip('.')))
    return found


def _unexempted_bare_selectors(qss: str) -> list[tuple[str, str]]:
    """Bare selectors that the recorded chrome exemption does not cover."""
    return [(member, cls) for member, cls in _bare_class_selectors(qss)
            if cls not in EXEMPT_CHROME_CLASSES]


def _colour_declarations(qss: str):
    """Yield ``(property, value)`` for every colour-bearing declaration."""
    for prop, value in DECLARATION_RE.findall(qss):
        if prop in COLOUR_PROPERTIES:
            yield prop, value.strip()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _colour_declaration(block: str, prop: str) -> str:
    """Return the ``#rrggbb`` value ``prop`` is declared with in a rule body.

    Reading the emitted stylesheet (instead of re-deriving the mapping from the
    tokens) is what keeps the contrast guard below honest: change the mapping
    and the value under test changes with it.
    """
    match = re.search(
        rf'^\s*{re.escape(prop)}\s*:\s*(#[0-9a-fA-F]{{6}})\s*;', block, re.M)
    assert match, (
        f'{prop!r} is not declared with a #rrggbb token colour in: {block!r}')
    return match.group(1).lower()


class SelectedChipContrastTest(unittest.TestCase):
    """Task 4's own WCAG invariant for the selected media-library chip.

    The brief's mapping table (``task-4-brief.md`` line 42) paired ``accent``
    text with an ``accent_soft`` background for
    ``QPushButton[chip="true"][selected="true"]``. Measured with the shared
    WCAG helper that pairing is 4.03:1 in LIGHT, under the 4.5 text bar, so the
    background had to move. The ruled form is an outlined chip -- ``accent``
    text and border on ``surface`` -- which is 4.60:1 LIGHT / 6.91:1 DARK.

    Two further reasons the chip is not simply filled with an ``accent_*``
    tint, recorded because the numbers alone do not decide it: ``accent_hover``
    on ``accent_soft`` does clear the bar (5.03 LIGHT / 6.72 DARK) but is a
    *state* token, so using it as resting text would collide with the
    ``:hover`` rule; and ``accent_soft`` is byte-identical to ``playing_bg`` in
    both themes, so an ``accent_soft`` fill would make the library switcher
    look like the now-playing row.

    This lives here, not in Task 3's ``ThemeContrastTest.EXTRA_PAIRS``, because
    it is an invariant of the *mapping*, not of the palette: ``core/theme.py``
    is untouched and Task 3's file stays as it shipped.
    """

    def _blocks(self):
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        for name in ('LIGHT', 'DARK'):
            tokens = LIGHT if name == 'LIGHT' else DARK
            qss = build_qss(tokens, AlphaSettings())
            yield name, tokens, _rule_block(qss, CHIP_SELECTED_SELECTOR)

    def test_selected_chip_is_accent_on_surface(self):
        """The mapping is the outlined chip: accent text/border on surface."""
        for name, tokens, block in self._blocks():
            with self.subTest(theme=name):
                self.assertEqual(
                    tokens.surface, _colour_declaration(block, 'background-color'),
                    f'{name}: selected chip background must be the `surface` token '
                    f'-- an `accent_soft` fill puts `accent` text under 4.5:1',
                )
                self.assertEqual(
                    tokens.accent, _colour_declaration(block, 'color'),
                    f'{name}: selected chip text must be the `accent` token',
                )
                self.assertEqual(
                    tokens.accent, _colour_declaration(block, 'border-color'),
                    f'{name}: selected chip border must be the `accent` token',
                )

    def test_selected_chip_text_clears_wcag_aa(self):
        """Whatever the rule emits for text+background must clear 4.5:1, both themes."""
        from tests.test_theme import ThemeContrastTest

        failures = []
        for name, _tokens, block in self._blocks():
            fg = _colour_declaration(block, 'color')
            bg = _colour_declaration(block, 'background-color')
            ratio = ThemeContrastTest.contrast(fg, bg)
            if ratio < 4.5:
                failures.append(
                    f'{name}: selected chip text {fg} on {bg} = {ratio:.2f}:1, '
                    f'needs 4.5:1')

        self.assertEqual([], failures, '\n'.join(failures))


class BuildQssTest(unittest.TestCase):
    """``build_qss`` output contract: complete, scoped, token-driven."""

    def _all_qss(self):
        """Yield (label, qss) over LIGHT/DARK x three alpha settings."""
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        alpha_sets = (
            ('default', AlphaSettings()),
            ('mid', AlphaSettings(overlay=0.2, playlist=0.5, controls=0.9)),
            ('extremes', AlphaSettings(overlay=0.0, playlist=1.0, controls=0.47)),
        )
        for theme_name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            for alpha_name, alphas in alpha_sets:
                yield f'{theme_name}/{alpha_name}', build_qss(tokens, alphas)

    def test_output_is_complete_and_substituted(self):
        """No unreplaced ``{placeholder}`` and balanced braces for every theme."""
        for label, qss in self._all_qss():
            with self.subTest(case=label):
                self.assertIsNone(
                    LEFTOVER_PLACEHOLDER_RE.search(qss),
                    f'{label}: unreplaced placeholder token leaked into the QSS',
                )
                self.assertEqual(
                    qss.count('{'), qss.count('}'),
                    f'{label}: braces are not balanced',
                )

    def test_no_bare_widget_rules(self):
        """Every QPushButton/QSlider/QListView/QLabel rule carries a scope.

        Two gates, so neither the class list nor the selector shape can be
        dodged: the line-anchored regex over the four scoped-needing classes
        (pseudo-states and comma-list members included), and the compound-wise
        selector parse that additionally rejects *any* bare class outside the
        named ``EXEMPT_CHROME_CLASSES`` -- including ``*``.
        """
        for label, qss in self._all_qss():
            with self.subTest(case=label):
                match = BARE_WIDGET_RE.search(qss)
                self.assertIsNone(
                    match,
                    f'{label}: bare widget rule escaped the scope gate: '
                    f'{match.group(0).strip() if match else ""}',
                )
                self.assertEqual(
                    [], _unexempted_bare_selectors(qss),
                    f'{label}: rule styles a class globally; scope it by '
                    f'objectName, dynamic property or ancestor (or exempt it '
                    f'in EXEMPT_CHROME_CLASSES as a reviewed decision)',
                )

    def test_scope_gate_catches_the_realistic_leaks(self):
        """The gate itself is tested, so it cannot silently narrow again."""
        for label, qss in self._all_qss():
            with self.subTest(case=label):
                bare = {member for member, _cls in _bare_class_selectors(qss)}
                for leak in (
                    'QPushButton {\n', 'QPushButton:disabled {\n',
                    'QLabel:hover {\n', 'QSlider::groove:horizontal {\n',
                    'QListView::item:selected {\n', '*:focus {\n',
                    'QLabel, #timeLabel {\n', '#timeLabel, QLabel {\n',
                ):
                    mutated = qss + leak + '    color: #1976d2;\n}\n'
                    self.assertTrue(
                        _unexempted_bare_selectors(mutated),
                        f'{label}: gate missed the leak {leak!r}',
                    )

    def test_exempt_chrome_classes_are_the_whole_exemption(self):
        """The bare chrome rules are a recorded list, not an accident.

        Pins three things: exactly the six exempt classes appear bare in the
        sheet, each of them at least once (a dead exemption would hide a dropped
        rule), and none of the scoped-needing classes can ever be exempted.
        """
        from core.theme import LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        qss = build_qss(LIGHT, AlphaSettings())
        bare_classes = {cls for _member, cls in _bare_class_selectors(qss)}
        self.assertEqual(set(EXEMPT_CHROME_CLASSES), bare_classes)
        self.assertEqual(
            set(), bare_classes & set(SCOPED_NEEDING_CLASSES),
            'a per-instance class was added to the chrome exemption',
        )

    def test_dialog_family_is_ancestor_scoped(self):
        """Finding 5: dialog buttons and the library list keep their styling.

        ``library_dialog.py`` / ``appearance_dialog.py`` build plain
        ``QPushButton`` and ``QListWidget`` children with no objectName and no
        dynamic property, and Task 5's mandate does not reach them. The old
        global ``QPushButton`` (``styles.qss:91-111``) and the whole
        ``QListView`` family -- base *and* the ``::item`` / ``::item:selected`` /
        ``::item:hover`` states (``styles.qss:114-132``) -- therefore survive as
        a ``QDialog``-scoped family. The item states matter specifically here:
        unlike ``#playlistView``, this list carries no delegate to paint them.
        """
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        for theme_name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            qss = build_qss(tokens, AlphaSettings())
            for selector in DIALOG_SELECTORS:
                with self.subTest(theme=theme_name, selector=selector):
                    self.assertIn(
                        f'\n{selector} {{', qss,
                        f'{selector} is missing; the dialog widgets fall back '
                        f'to raw Fusion metrics once styles.qss is deleted',
                    )

            base = _rule_block(qss, 'QDialog QPushButton')
            self.assertIn(f'background-color: {tokens.button_bg};', base)
            self.assertIn(f'1px solid {tokens.border}', base)
            hover = _rule_block(qss, 'QDialog QPushButton:hover')
            self.assertIn(f'background-color: {tokens.button_hover};', hover)
            self.assertIn(f'border-color: {tokens.border_strong};', hover)
            pressed = _rule_block(qss, 'QDialog QPushButton:pressed')
            self.assertIn(f'background-color: {tokens.button_pressed};', pressed)
            disabled = _rule_block(qss, 'QDialog QPushButton:disabled')
            self.assertIn(f'background-color: {tokens.button_disabled_bg};', disabled)
            self.assertIn(f'color: {tokens.button_disabled_text};', disabled)
            listing = _rule_block(qss, 'QDialog QListWidget')
            self.assertIn(f'background-color: {tokens.surface};', listing)

            # Item-level states: the base-list migration left styles.qss:120-132
            # with no successor. This QListWidget has no delegate, so row
            # padding, dividers and selection/hover colours must survive here or
            # the two-line rows (library_dialog.py:113) lose them.
            item = _rule_block(qss, 'QDialog QListWidget::item')
            self.assertIn('padding: 6px 8px;', item)
            self.assertIn(f'1px solid {tokens.divider}', item)
            item_selected = _rule_block(qss, 'QDialog QListWidget::item:selected')
            self.assertIn(f'background-color: {tokens.accent_soft};', item_selected)
            self.assertIn(f'color: {tokens.text_primary};', item_selected)
            item_hover = _rule_block(qss, 'QDialog QListWidget::item:hover')
            self.assertIn(f'background-color: {tokens.hover_bg};', item_hover)

            # The family must stay scoped by its ancestor: drop `QDialog ` and
            # these rules become the exact global leak the sheet exists to close
            # (which `test_no_bare_widget_rules` would then also catch).
            self.assertEqual(
                set(), set(DIALOG_SELECTORS) & {
                    member for member, _cls in _bare_class_selectors(qss)},
                'the dialog family lost its ancestor scope',
            )

    def test_declares_every_required_selector(self):
        """The selector inventory is the Task 5 contract, one for one."""
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import (
            REQUIRED_DYN_PROPERTIES,
            REQUIRED_OBJECT_NAMES,
            build_qss,
        )

        qss = build_qss(LIGHT, AlphaSettings())
        dark_qss = build_qss(DARK, AlphaSettings())

        for name in REQUIRED_OBJECT_NAMES:
            self.assertIn(f'#{name}', qss, f'#{name} is not styled')
            self.assertIn(f'#{name}', dark_qss, f'#{name} missing in DARK')
        for prop, value in REQUIRED_DYN_PROPERTIES:
            scoped = f'[{prop}="{value}"]'
            self.assertIn(scoped, qss, f'{scoped} is not styled')
            self.assertIn(scoped, dark_qss, f'{scoped} missing in DARK')

    def test_alpha_is_applied(self):
        """playlist/controls alphas land in their own panel's rule block."""
        from core.theme import LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        qss = build_qss(LIGHT, AlphaSettings(overlay=0.47, playlist=0.5, controls=0.25))

        playlist_block = _rule_block(qss, '#playlistView')
        self.assertIn('rgba(', playlist_block)
        self.assertIn(', 0.5)', playlist_block)

        controls_block = _rule_block(qss, '#bottomPanel')
        self.assertIn('rgba(', controls_block)
        self.assertIn(', 0.25)', controls_block)

    def test_alpha_is_clamped(self):
        """Out-of-range alphas clamp to 0.0/1.0 instead of raising."""
        from core.theme import LIGHT, AlphaSettings
        from core.theme_qss import build_qss, hex_to_rgba

        qss = build_qss(
            LIGHT, AlphaSettings(overlay=-1, playlist=2, controls=0.5)
        )

        # playlist=2 -> 1.0, controls=0.5 stays 0.5.
        self.assertIn(', 1.0)', _rule_block(qss, '#playlistView'))
        self.assertIn(', 0.5)', _rule_block(qss, '#bottomPanel'))
        for raw in RGBA_ALPHA_RE.findall(qss):
            self.assertGreaterEqual(float(raw), 0.0)
            self.assertLessEqual(float(raw), 1.0)

        # The overlay alpha is consumed by the paintEvent scrim, not the QSS,
        # so the clamping itself is pinned through the shared helper.
        self.assertEqual(hex_to_rgba('#ffffff', -1), 'rgba(255, 255, 255, 0.0)')
        self.assertEqual(hex_to_rgba('#ffffff', 2), 'rgba(255, 255, 255, 1.0)')

    def test_hex_to_rgba(self):
        from core.theme_qss import hex_to_rgba

        self.assertEqual(hex_to_rgba('#1976d2', 0.5), 'rgba(25, 118, 210, 0.5)')
        self.assertEqual(hex_to_rgba('#0d47a1', 0.47), 'rgba(13, 71, 161, 0.47)')
        self.assertEqual(hex_to_rgba('#000000', 1.0), 'rgba(0, 0, 0, 1.0)')


class PaletteOnlyColoursTest(unittest.TestCase):
    """The "no colour literal" invariant, tested instead of eyeballed once.

    ``core/theme.py`` is the contrast-checked source of truth, so every colour
    in the generated sheet has to be a token value *of the same theme* --
    ``transparent`` and ``none`` are the only named values allowed, and a
    border-style keyword may only ride along with a ``1px``. Tasks 5 and 6 edit
    this generator, and without this test a stray ``border-color: #bbb`` would
    pass the whole suite and put an unmeasured colour on screen.
    """

    def _themes(self):
        """Yield ``(name, qss, palette)`` for LIGHT and DARK."""
        from core.theme import DARK, LIGHT, TOKEN_FIELDS, AlphaSettings
        from core.theme_qss import build_qss

        for name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            palette = {getattr(tokens, field).lower() for field in TOKEN_FIELDS}
            yield name, build_qss(tokens, AlphaSettings()), palette

    def test_every_hex_is_a_token_value(self):
        for name, qss, palette in self._themes():
            with self.subTest(theme=name):
                offenders = sorted(
                    hex_color for hex_color in set(HEX_COLOR_RE.findall(qss))
                    if hex_color.lower() not in palette
                )
                self.assertEqual(
                    [], offenders,
                    f'{name}: colour literal foreign to this theme\'s tokens: '
                    f'{offenders}',
                )

    def test_every_rgba_is_a_token_at_an_alpha(self):
        """The alpha-composited surfaces count too: same triple, any alpha."""
        for name, qss, palette in self._themes():
            with self.subTest(theme=name):
                token_triples = {_hex_to_rgb(hex_color) for hex_color in palette}
                offenders = [
                    match.group(0) for match in RGBA_TRIPLE_RE.finditer(qss)
                    if (int(match.group(1)), int(match.group(2)),
                        int(match.group(3))) not in token_triples
                ]
                self.assertEqual(
                    [], offenders,
                    f'{name}: rgba() built from a colour that is not a token: '
                    f'{offenders}',
                )

    def test_no_named_colour_beyond_transparent_and_none(self):
        for name, qss, _palette in self._themes():
            with self.subTest(theme=name):
                offenders = []
                for prop, value in _colour_declarations(qss):
                    remainder = RGBA_COLOR_RE.sub(' ', HEX_COLOR_RE.sub(' ', value))
                    for word in re.split(r'[\s,]+', remainder):
                        if not word or not word.replace('-', '').isalpha():
                            continue        # lengths (``1px``) and empty slots
                        if word not in PERMITTED_COLOUR_WORDS:
                            offenders.append(f'{prop}: {word}')
                self.assertEqual(
                    [], offenders,
                    f'{name}: named colour (or unknown colour word) in a colour '
                    f'declaration: {offenders}',
                )

    def test_colour_scan_is_not_a_no_op(self):
        """A parse that matched nothing would make the three guards vacuous."""
        from core.theme import LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        qss = build_qss(LIGHT, AlphaSettings())
        declarations = list(_colour_declarations(qss))
        self.assertGreaterEqual(
            len(declarations), 40,
            'the colour scan matched almost nothing; the guards above prove '
            'nothing (fix COLOUR_PROPERTIES / DECLARATION_RE first)',
        )
        self.assertEqual(
            {'background-color', 'color', 'border', 'border-top', 'border-bottom',
             'border-color'},
            {prop for prop, _value in declarations},
        )
        self.assertTrue(
            any('rgba(' in value for _prop, value in declarations),
            'the alpha-composited surfaces vanished from the sheet',
        )


if __name__ == '__main__':
    unittest.main()
