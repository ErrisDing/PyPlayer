#!/usr/bin/env python3
"""Unit tests for the theme token layer.

`core/theme.py` is pure Python (no Qt import), so these tests need neither a
display nor PyQt6:

    python -m unittest tests.test_theme -v
"""
import re
import sys
import unittest
from dataclasses import fields
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEX_COLOR_RE = re.compile(r'^#[0-9a-f]{6}$')

# Number of semantic colour tokens defined by spec §4.1.
TOKEN_COUNT = 34


def _fields(tokens) -> set[str]:
    """Return the token names declared on ``tokens``' dataclass."""
    return {f.name for f in fields(tokens)}


class ThemeTokensTest(unittest.TestCase):
    """LIGHT / DARK must define the same complete set of colour tokens."""

    def test_light_and_dark_define_identical_fields(self):
        from core.theme import DARK, LIGHT, TOKEN_FIELDS

        expected = set(TOKEN_FIELDS)
        self.assertEqual(_fields(LIGHT), _fields(DARK))
        self.assertEqual(_fields(LIGHT), expected)
        self.assertEqual(len(TOKEN_FIELDS), TOKEN_COUNT)
        self.assertEqual(len(expected), TOKEN_COUNT)

        for name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            for field_name in TOKEN_FIELDS:
                value = getattr(tokens, field_name)
                self.assertIsInstance(
                    value, str,
                    f'{name}.{field_name} must be a str, got {type(value).__name__}',
                )
                self.assertRegex(
                    value, HEX_COLOR_RE,
                    f'{name}.{field_name} must be lowercase #rrggbb, got {value!r}',
                )

    def test_resolve_truth_table(self):
        from core.theme import DARK, LIGHT, resolve

        cases = [
            ('auto', 'Dark', DARK),
            ('auto', 'Light', LIGHT),
            ('auto', 'Unknown', LIGHT),
            ('light', 'Dark', LIGHT),
            ('light', 'Light', LIGHT),
            ('light', 'Unknown', LIGHT),
            ('dark', 'Dark', DARK),
            ('dark', 'Light', DARK),
            ('dark', 'Unknown', DARK),
        ]
        self.assertEqual(len(cases), 9)

        for mode, system_scheme, expected in cases:
            with self.subTest(mode=mode, system_scheme=system_scheme):
                resolved = resolve(mode, system_scheme)
                self.assertIs(
                    resolved, expected,
                    f'resolve({mode!r}, {system_scheme!r}) must return the '
                    f'{"LIGHT" if expected is LIGHT else "DARK"} singleton',
                )

    def test_resolve_rejects_unknown_mode(self):
        from core.theme import resolve

        for mode in ('neon', '', 'AUTO', 'Light', 'system'):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    resolve(mode, 'Dark')


class ThemeContrastTest(unittest.TestCase):
    """WCAG 2.1 AA contrast invariants over the token pairs that actually meet.

    Thresholds are fixed by the spec (4.5 for body text, 3.0 for iconography)
    and must never be relaxed; when a pair fails, the colour changes instead.
    """

    # Text tokens against the backgrounds they are painted on in the playlist,
    # headers and cards (spec §4.6 D1).
    TEXT_PAIRS = ('surface', 'surface_alt', 'selection_bg', 'playing_bg')
    TEXT_TOKENS = ('text_primary', 'text_secondary', 'text_muted')

    # fg token, bg token, minimum ratio.
    EXTRA_PAIRS = (
        ('text_on_accent', 'accent', 4.5),
        ('playing_text', 'playing_bg', 4.5),
        ('icon', 'surface', 3.0),
        ('icon_on_accent', 'accent', 3.0),
        ('tooltip_text', 'tooltip_bg', 4.5),
    )

    @staticmethod
    def _rel_lum(hex_color: str) -> float:
        """WCAG 2.1 relative luminance of a ``#rrggbb`` colour."""
        channels = []
        for index in (1, 3, 5):
            c = int(hex_color[index:index + 2], 16) / 255
            c = c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            channels.append(c)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    @classmethod
    def contrast(cls, fg: str, bg: str) -> float:
        """WCAG 2.1 contrast ratio between two ``#rrggbb`` colours (1..21)."""
        lum_a, lum_b = cls._rel_lum(fg), cls._rel_lum(bg)
        lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
        return (lighter + 0.05) / (darker + 0.05)

    def test_contrast_requirements(self):
        from core.theme import DARK, LIGHT

        failures = []
        for name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            pairs = [
                (fg, bg, 4.5)
                for fg in self.TEXT_TOKENS
                for bg in self.TEXT_PAIRS
            ] + list(self.EXTRA_PAIRS)

            for fg_name, bg_name, minimum in pairs:
                fg = getattr(tokens, fg_name)
                bg = getattr(tokens, bg_name)
                ratio = self.contrast(fg, bg)
                if ratio < minimum:
                    failures.append(
                        f'{name}: {fg_name} {fg} on {bg_name} {bg} = '
                        f'{ratio:.2f}:1, needs {minimum}:1'
                    )

        self.assertEqual([], failures, '\n'.join(failures))


if __name__ == '__main__':
    unittest.main()
