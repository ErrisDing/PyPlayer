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

# The 34 token names, transcribed from spec §4.1's field-group table in
# declaration order (表面 → 文字 → 强调 → 列表状态 → 线 → 控件 → 浮层).
#
# This literal is the module's contract with Task 4's QSS generator and the
# delegate painters. It must NOT be derived from ``core.theme`` (e.g. via
# ``dataclasses.fields``): deriving it makes the comparison true by
# construction, so renaming or reordering a token could never fail.
EXPECTED_TOKEN_FIELDS = (
    # 表面 / surfaces
    'window_bg', 'surface', 'surface_alt', 'surface_header', 'scrim',
    # 文字 / text
    'text_primary', 'text_secondary', 'text_muted', 'text_on_accent',
    # 强调 / accent
    'accent', 'accent_hover', 'accent_pressed', 'accent_soft',
    # 列表状态 / list states
    'selection_bg', 'playing_bg', 'playing_text', 'playing_bar', 'hover_bg',
    # 线 / lines
    'border', 'border_strong', 'divider',
    # 控件 / controls
    'button_bg', 'button_hover', 'button_pressed', 'button_disabled_bg',
    'button_disabled_text', 'icon', 'icon_muted', 'icon_on_accent',
    'focus_ring',
    # 浮层 / overlays
    'tooltip_bg', 'tooltip_text', 'scrollbar_thumb', 'scrollbar_thumb_hover',
)


def _fields(tokens) -> set[str]:
    """Return the token names declared on ``tokens``' dataclass."""
    return {f.name for f in fields(tokens)}


class ThemeTokensTest(unittest.TestCase):
    """LIGHT / DARK must define the same complete set of colour tokens."""

    def test_token_field_names_match_spec_4_1(self):
        """The 34 token names, in declaration order, are pinned to spec 4.1.

        ``EXPECTED_TOKEN_FIELDS`` is a literal transcribed from the spec's
        field-group table, never derived from ``ThemeTokens``, so this fails
        on a rename, a reorder, an addition or a removal. Those names are the
        contract with ``core.theme_qss`` (Task 4) and the delegate painters.
        """
        from core.theme import TOKEN_FIELDS

        self.assertEqual(len(EXPECTED_TOKEN_FIELDS), TOKEN_COUNT)
        self.assertEqual(TOKEN_FIELDS, EXPECTED_TOKEN_FIELDS)

    def test_light_and_dark_define_identical_fields(self):
        from core.theme import DARK, LIGHT, TOKEN_FIELDS

        expected = set(EXPECTED_TOKEN_FIELDS)
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
        # icon_muted is a non-text UI component (the loop-off glyph), so its
        # bar is 3:1 (WCAG 1.4.11), NOT the 4.5:1 that text_muted must clear
        # (1.4.3) — see spec §4.6 D1. The two greys differ per theme on
        # purpose; do not "fix" icon_muted by mirroring text_muted.
        # Backgrounds are the surfaces the glyph actually renders on: the
        # #loopButton states (button_bg / button_hover / button_pressed) and
        # the panel surface it sits in.
        ('icon_muted', 'button_bg', 3.0),
        ('icon_muted', 'button_hover', 3.0),
        ('icon_muted', 'button_pressed', 3.0),
        ('icon_muted', 'surface', 3.0),
        # Task 8 made the six pairs below real rather than hypothetical. An SVG
        # glyph is rasterised with a token *before* it is painted, so QSS can no
        # longer be trusted to keep it legible the way it keeps text legible:
        # the pairing has to be pinned here, on the same 3:1 non-text-component
        # bar (WCAG 1.4.11).
        #   * prev / stop / next carry ``icon`` and sit on the three
        #     ``QPushButton[role="transport"]`` backgrounds the sheet emits.
        #   * the volume speaker carries ``icon`` too, but on the panel itself,
        #     whose ``rgba(surface, controls)`` is the ``icon``/``surface`` pair
        #     above (measured: ``icon`` on the composited LIGHT panel is 9.66:1,
        #     within 0.1 of the 9.74:1 that pin reports).
        #   * loop_one / loop_all carry ``accent`` on the loop button's three
        #     states -- the tightest margin in the set, 3.49:1 on LIGHT
        #     button_pressed, so it is listed rather than folded into
        #     accent-on-surface.
        ('icon', 'button_bg', 3.0),
        ('icon', 'button_hover', 3.0),
        ('icon', 'button_pressed', 3.0),
        ('accent', 'button_bg', 3.0),
        ('accent', 'button_hover', 3.0),
        ('accent', 'button_pressed', 3.0),
        # Batch 2 Task 3's icon rail: seven 20 px glyphs rasterised from
        # ``tokens.icon`` over the four ``#railButton`` fills the sheet emits.
        # Same rule as the transport row above -- QSS paints the background and
        # the pipeline paints the glyph, so nothing but this tuple keeps the two
        # on speaking terms.
        #   * resting: the button is transparent, so the glyph lands on
        #     ``#actionRail``'s ``surface_alt`` fill;
        #   * hover: ``hover_bg``;
        #   * blocked: ``button_disabled_bg``, the fill a running action's
        #     partner wears;
        #   * running: ``accent_soft``, the progress fill under the spinner.
        # ``:pressed`` is deliberately not repeated: it emits ``button_pressed``,
        # already pinned three lines up for the transport buttons.
        # Measured at authoring: LIGHT 8.53-9.09, DARK 7.63-9.29, so this pin
        # records pairings that hold rather than ones that need a colour change.
        ('icon', 'surface_alt', 3.0),
        ('icon', 'hover_bg', 3.0),
        ('icon', 'button_disabled_bg', 3.0),
        ('icon', 'accent_soft', 3.0),
        # Batch 2 Task 4's library rows: the ``folder`` glyph is rasterised from
        # ``tokens.icon`` and the row it sits on can be the current library, whose
        # fill ``#libraryRow[current="true"]`` emits as ``selection_bg``. For the
        # glyph alone, the other three grounds the row can wear -- ``surface``
        # (the panel), ``hover_bg`` and ``button_pressed`` -- are pinned above.
        ('icon', 'selection_bg', 3.0),
        # The text and the marker of those same four grounds were *not* covered,
        # because the block above is a glyph set and ``TEXT_PAIRS`` only lists
        # ``surface``/``surface_alt``/``selection_bg``/``playing_bg``: the two
        # fills ``#libraryRow:hover`` and ``#libraryRow:pressed`` emit under
        # ``text_primary`` had no text pin, and the 2 px ``accent`` current-marker
        # on the selection fill had none at all. Measured at authoring --
        # ``text_primary``/``hover_bg`` 14.46 LIGHT, 10.91 DARK;
        # ``text_primary``/``button_pressed`` 12.49, 6.94 (both the 4.5 text bar,
        # WCAG 1.4.3); ``accent``/``selection_bg`` 3.98, 5.67 (the 3.0 non-text
        # bar, WCAG 1.4.11 -- a 2 px marker is a UI component, not text, so it is
        # not held to 4.5). All six pass: these three tuples close a coverage
        # hole, they do not change a colour.
        ('text_primary', 'hover_bg', 4.5),
        ('text_primary', 'button_pressed', 4.5),
        ('accent', 'selection_bg', 3.0),
        # The ``icon_muted`` / ``surface`` pair above is a deliberate superset:
        # the loop-off glyph paints on the button, never on the panel. It stays
        # because #loopButton's fill is one QSS edit away from transparent (the
        # sheet already emits ``transparent`` for #railButton and
        # #nowPlayingStrip), and a guard must not be the thing that notices such
        # a change.
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


class Batch2GeometryTest(unittest.TestCase):
    """Batch 2's size tokens: the rail, the strip and the floating panel.

    ``core/theme.py`` is the only place a geometry value may be written down, so
    the three new constants are pinned by *value* here (a widget that invents its
    own 56 would not fail any other test) and the retired one is pinned by
    absence: ``ART_SIZE`` sized the left panel's cover box, and the left panel is
    what batch 2 deletes, so the constant must not survive into a theme that no
    longer has a consumer for it.
    """

    def test_batch2_sizes_are_the_planned_values(self):
        from core.theme import RAIL_WIDTH, SIDEBAR_WIDTH, STRIP_ART_SIZE

        self.assertEqual(48, STRIP_ART_SIZE)
        self.assertEqual(56, RAIL_WIDTH)
        self.assertEqual(240, SIDEBAR_WIDTH)

    def test_art_size_is_gone(self):
        """``ART_SIZE`` must not come back as a re-export or a renamed alias.

        Its one remaining reader was the left panel, which held a literal 200
        while batch 2 replaced the token with ``STRIP_ART_SIZE``; Task 9 deleted
        that widget, so nothing may reach back to this module for the value.
        """
        import core.theme as theme

        self.assertFalse(
            hasattr(theme, 'ART_SIZE'),
            'ART_SIZE still lives in core.theme; batch 2 replaced it with '
            'STRIP_ART_SIZE / RAIL_WIDTH / SIDEBAR_WIDTH',
        )


if __name__ == '__main__':
    unittest.main()
