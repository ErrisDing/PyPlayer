#!/usr/bin/env python3
"""Unit tests for the QSS generator (Task 4: ``core/theme_qss.py``).

The module is pure Python (no Qt import), so these tests need neither a
display nor PyQt6:

    python -m unittest tests.test_theme_qss -v

The generator is the single stylesheet source of the theme layer: every rule
must be scoped to an ``#objectName`` or a ``[prop="value"]`` dynamic property
(the bare-widget rules of ``view/resources/styles.qss`` are exactly what
produced the two different-looking sliders), and every colour must come from a
``core.theme`` token.
"""
import re
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Bare widget selectors that the old global stylesheet used and that must
# never come back: each one is now scoped behind an objectName or a
# dynamic-property selector.
BARE_WIDGET_RE = re.compile(r'^\s*(QPushButton|QSlider|QListView|QLabel)\s*\{', re.M)

# Any ``{placeholder}`` left in the output means a substitution silently
# failed and the raw template leaked into the stylesheet.
LEFTOVER_PLACEHOLDER_RE = re.compile(r'\{[a-z_]+\}')

# The alpha value of any ``rgba(r, g, b, a)`` produced by the generator.
RGBA_ALPHA_RE = re.compile(r'rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([0-9.]+)\s*\)')

# The selected media-library chip rule, pinned so the contrast guard below
# reads the exact rule the generator emits rather than a substring hit on the
# base ``QPushButton[chip="true"]`` rule.
CHIP_SELECTED_SELECTOR = 'QPushButton[chip="true"][selected="true"]'


def _rule_block(qss: str, selector_pattern: str) -> str:
    """Return the declaration body of the rule whose selector matches.

    ``selector_pattern`` is matched literally against the text preceding
    ``{``, so callers pin the exact rule (``#playlistView {``) instead of the
    first substring hit (``#playlistView::item {``).
    """
    match = re.search(re.escape(selector_pattern) + r'\s*\{([^}]*)\}', qss)
    assert match, f'no rule block found for {selector_pattern!r}'
    return match.group(1)


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
    WCAG helper that pairing is 4.03:1 in LIGHT, and no other ``accent_*``
    foreground clears 4.5:1 on ``accent_soft`` in BOTH themes -- DARK's accent
    family inverts its lightness ordering relative to LIGHT (``accent``
    5.31/4.03 vs ``accent_pressed`` 4.44/7.56). The ruling is therefore on the
    background: the selected chip is an outlined chip -- ``accent`` text and
    border on ``surface`` -- which is 4.60:1 LIGHT / 6.91:1 DARK.

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
        """Every QPushButton/QSlider/QListView/QLabel rule carries a scope."""
        for label, qss in self._all_qss():
            with self.subTest(case=label):
                match = BARE_WIDGET_RE.search(qss)
                self.assertIsNone(
                    match,
                    f'{label}: bare widget rule escaped the scope gate: '
                    f'{match.group(0).strip() if match else ""}',
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


if __name__ == '__main__':
    unittest.main()
