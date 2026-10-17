#!/usr/bin/env python3
"""Tests for the SVG icon set and its token-colouring pipeline (Task 8).

Three layers are pinned here, because each can break on its own:

1. **The resources** -- twelve ``resource/icons/*.svg`` files: present,
   parseable, and following the authoring conventions (``viewBox="0 0 24 24"``,
   ``fill="currentColor"``, no external references). Those two properties are
   what the colouring pipeline and the rasteriser depend on, so they are
   asserted from the file text rather than inferred from a render.
2. **The geometry** -- the set has to look like one set: same ink extent, same
   rhythm, the play triangle optically (not geometrically) centred, and
   ``prev``/``next`` exact mirror images. Measured from rasterised masks, not
   from path text, because relative path commands make source coordinates a
   meaningless proxy for ink extent.
3. **The pipeline and its consumer** -- :func:`view.icons.icon` (rasterising,
   the ``dpr`` argument, the cache, the missing-file degradation) and
   ``BottomPanel``, which must take every glyph from the pipeline and put each
   one on the background the contrast guards in ``tests/test_theme.py`` measure.

Qt is imported only inside test bodies (or behind the module's ``QT_AVAILABLE``
guard), so a machine without PyQt6 skips this module instead of failing to
collect it.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_icons -v
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

# The 12 names the brief pins, transcribed verbatim as a literal -- not derived
# from ``view.icons.ICON_NAMES``. Deriving it would make the comparison true by
# construction, so a rename or a dropped glyph could never fail here (the same
# reasoning ``tests/test_theme.py`` gives for ``EXPECTED_TOKEN_FIELDS``).
ICON_NAMES = (
    'play', 'pause', 'prev', 'next', 'stop',
    'loop_off', 'loop_all', 'loop_one',
    'volume_mute', 'volume_low', 'volume_mid', 'volume_high',
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = PROJECT_ROOT / 'resource' / 'icons'

# Anything that pulls in another file, a second colour source, or executable
# content (brief: 「无外部引用」).
FORBIDDEN_ELEMENTS = ('image', 'script', 'style', 'use', 'foreignObject', 'filter')

# The one URL every authored SVG legitimately carries.
SVG_NAMESPACE = 'http://www.w3.org/2000/svg'


def _local_name(tag: str) -> str:
    """``{http://www.w3.org/2000/svg}path`` -> ``path``."""
    return tag.rsplit('}', 1)[-1]


def _token(hex_color: str) -> str:
    """A ``#rrggbb`` token in the exact spelling ``QColor.name()`` reports."""
    from PyQt6.QtGui import QColor

    return QColor(hex_color).name().lower()


class IconResourceTest(unittest.TestCase):
    """The twelve SVGs exist and keep the authoring conventions."""

    def test_all_icons_present_and_well_formed(self):
        self.assertEqual(
            12, len(ICON_NAMES),
            'the brief pins exactly 12 icons; a shorter list would let this '
            'test pass on a partial set',
        )
        for name in ICON_NAMES:
            path = ICONS_DIR / f'{name}.svg'
            with self.subTest(icon=name):
                self.assertTrue(path.is_file(), f'{path} is missing')

                text = path.read_text(encoding='utf-8')
                root = ET.fromstring(text)          # malformed SVG raises here
                self.assertEqual('svg', _local_name(root.tag))
                self.assertEqual(
                    '0 0 24 24', root.get('viewBox'),
                    'the pipeline scales the 24-unit box onto size*dpr, so a '
                    'different viewBox silently rescales the glyph',
                )
                self.assertIn(
                    'currentColor', text,
                    'fill="currentColor" is the placeholder view.icons '
                    'substitutes; a hardcoded hex would ignore the tokens',
                )

                for element in root.iter():
                    tag = _local_name(element.tag)
                    self.assertNotIn(
                        tag, FORBIDDEN_ELEMENTS,
                        f'<{tag}> is an external or executable reference',
                    )
                    for attr in ('fill', 'stroke'):
                        value = element.get(attr)
                        if value is None:
                            continue
                        self.assertIn(
                            value, ('currentColor', 'none'),
                            f'<{tag}> {attr}="{value}" is an off-token colour; '
                            'only currentColor (and none) may be authored in',
                        )

                # No fetch of any kind. The SVG namespace URI is the one URL an
                # SVG must carry, so it is removed before the scan.
                scannable = text.replace(SVG_NAMESPACE, '')
                for needle in ('xlink:href', 'http://', 'https://', 'url(',
                               '<![CDATA', '<!ENTITY', '@import'):
                    self.assertNotIn(
                        needle, scannable, f'{needle} reaches outside the file')

    def test_icon_names_are_the_twelve_shipped_files(self):
        """No fifthteenth file, no typo'd name sitting next to the real set."""
        on_disk = sorted(path.stem for path in ICONS_DIR.glob('*.svg'))
        self.assertEqual(sorted(ICON_NAMES), on_disk)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class IconGeometryTest(unittest.TestCase):
    """The set hangs together optically.

    Every measurement here comes from a rasterised 1-bit mask of the glyph,
    because the properties under test (ink extent, optical centring, mirroring)
    are about pixels, not about path text.
    """

    SAMPLE = 48        # device px for a 24-unit box: 2 px per unit

    def setUp(self):
        self.app = make_app()

    def _mask(self, name: str):
        """``{(x, y): True}`` ink set for one glyph at 2 px per unit."""
        from PyQt6.QtCore import QByteArray, QRectF, Qt
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer

        text = (ICONS_DIR / f'{name}.svg').read_text(encoding='utf-8')
        renderer = QSvgRenderer(QByteArray(text.replace(
            'currentColor', '#000000').encode('utf-8')))
        self.assertTrue(renderer.isValid(), f'{name}: QSvgRenderer rejected it')

        image = QImage(self.SAMPLE, self.SAMPLE,
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # ``render``'s return value is dropped by PyQt6 (always None on
            # Qt 6.11), so it may not be asserted here nor in view/icons.py --
            # and asserting it *while the painter is active* aborts the process
            # on the way out, which is how this was discovered.
            renderer.render(painter, QRectF(0, 0, self.SAMPLE, self.SAMPLE))
        finally:
            painter.end()

        ink = {(x, y)
               for y in range(self.SAMPLE)
               for x in range(self.SAMPLE)
               if image.pixelColor(x, y).alpha() > 128}
        self.assertTrue(ink, f'{name} rasterised to an empty glyph')
        return ink

    def _extent(self, ink):
        """Ink bbox in 24-unit coordinates: ``(x0, y0, x1, y1)``."""
        scale = self.SAMPLE / 24.0
        xs = [x for x, _y in ink]
        ys = [y for _x, y in ink]
        return (min(xs) / scale, min(ys) / scale,
                max(xs) / scale, max(ys) / scale)

    def test_every_glyph_keeps_the_same_optical_box(self):
        """Ink stays inside the 24 grid with a margin, and fills enough of it.

        A glyph whose ink only spans 10 units renders visibly smaller beside
        one that spans 18 at 20 px -- which is precisely how the five
        hand-drawn polygons this task replaces disagreed with each other.

        The floors sit half a unit under the authored values because the mask
        counts pixels at alpha > 128, and antialiasing trims the half-covered
        edge pixel on each side (measured: ``volume_mute`` is authored 10 units
        wide and inks 9.5).
        """
        for name in ICON_NAMES:
            with self.subTest(icon=name):
                x0, y0, x1, y1 = self._extent(self._mask(name))
                self.assertGreaterEqual(x0, 1.0, f'{name}: ink leaves the box left')
                self.assertGreaterEqual(y0, 1.0, f'{name}: ink leaves the box top')
                self.assertLessEqual(x1, 23.0, f'{name}: ink leaves the box right')
                self.assertLessEqual(y1, 23.0, f'{name}: ink leaves the box bottom')
                self.assertGreaterEqual(
                    x1 - x0, 9.0, f'{name} is too narrow for the set')
                self.assertGreaterEqual(
                    y1 - y0, 7.5, f'{name} is too short for the set')

    def test_transport_glyphs_share_one_height_rhythm(self):
        """play / pause / prev / next stand 14 units tall; stop stands 12.

        The square is deliberately inset (an equal-bbox square reads larger
        than a triangle of the same height), but that is the *only* allowed
        deviation -- which is exactly how the five hand-drawn polygons this task
        replaces disagreed with each other.
        """
        heights = {'play': 14.0, 'pause': 14.0, 'prev': 14.0, 'next': 14.0,
                   'stop': 12.0}
        for name, expected in heights.items():
            with self.subTest(icon=name):
                _x0, y0, _x1, y1 = self._extent(self._mask(name))
                self.assertAlmostEqual(
                    expected, y1 - y0, delta=0.8,
                    msg=f'{name} is {y1 - y0:.1f} units tall, expected '
                        f'{expected}; the transport row is authored on one '
                        'rhythm and one stray glyph reads as another size class',
                )

    def test_play_triangle_is_optically_not_geometrically_centred(self):
        """A right-pointing triangle looks left-heavy on its bbox centre.

        The ink bbox must sit right of 12, and the true area centroid (where
        the eye reads the middle) must land within a hair of 12. Both halves
        matter: shifting the whole triangle right would satisfy one and still
        look off.
        """
        from PyQt6.QtCore import QSize
        from view.icons import icon

        ink = self._mask('play')
        x0, _y0, x1, _y1 = self._extent(ink)
        self.assertGreater(
            (x0 + x1) / 2, 12.0,
            f'play spans {x0:.1f}..{x1:.1f}, bbox centre {(x0 + x1) / 2:.2f}: '
            'a triangle centred on its bounding box looks left-heavy',
        )
        centroid_x = sum(x for x, _y in ink) / len(ink) / (self.SAMPLE / 24.0)
        self.assertAlmostEqual(
            12.0, centroid_x, delta=1.2,
            msg=f'the area centroid of the play triangle sits at '
                f'{centroid_x:.2f}; the eye reads that as the middle',
        )
        self.assertFalse(icon('play', '#1976d2', 24).pixmap(QSize(24, 24)).isNull())

    def test_prev_and_next_are_mirror_images(self):
        """One glyph flipped, so the pair cannot drift apart in weight."""
        prev = self._mask('prev')
        nxt = self._mask('next')
        width = self.SAMPLE
        mirrored = {(width - 1 - x, y) for x, y in prev}
        union = len(mirrored | nxt)
        agreement = len(mirrored & nxt) / union
        self.assertGreaterEqual(
            agreement, 0.95,
            f'prev/next agree on only {agreement * 100:.1f}% of their ink; '
            'the pair is meant to be one shape seen from both sides',
        )

    def test_volume_levels_add_arcs_and_keep_the_speaker(self):
        """0/1/2/3 arcs: the cone is shared, the ink grows to the right."""
        extents = {name: self._extent(self._mask(name))
                   for name in ('volume_mute', 'volume_low', 'volume_mid',
                                'volume_high')}
        mute = extents['volume_mute']
        for name in ('volume_low', 'volume_mid', 'volume_high'):
            other = extents[name]
            with self.subTest(icon=name):
                self.assertAlmostEqual(
                    mute[0], other[0], delta=0.6,
                    msg=f'{name} moved the cone; only the arcs are supposed to '
                        'come and go')
                self.assertGreater(
                    other[2], mute[2] + 0.5,
                    f'{name} added no arc: the ink does not reach further right')

        self.assertLess(
            extents['volume_low'][2], extents['volume_mid'][2],
            'the arcs must step outward one level at a time')
        self.assertLess(
            extents['volume_mid'][2], extents['volume_high'][2])

    def test_loop_family_shares_the_ring_and_differs_in_the_middle(self):
        """loop_off / loop_all / loop_one: same loop, plus slash or digit."""
        all_ink = self._mask('loop_all')
        off_ink = self._mask('loop_off')
        one_ink = self._mask('loop_one')

        for name, ink in (('loop_off', off_ink), ('loop_one', one_ink)):
            with self.subTest(icon=name):
                extra = ink - all_ink
                self.assertGreater(
                    len(extra), 20,
                    f'{name} adds no distinguishable mark (slash / 1)')

        # The ring is the same ring in all three states.
        for name, ink in (('loop_off', off_ink), ('loop_one', one_ink)):
            with self.subTest(ring=name):
                shared = ink & all_ink
                self.assertGreater(
                    len(shared) / len(all_ink), 0.8,
                    f'{name} redrew the loop instead of annotating it')

        # ...and loop_one's mark is inside the ring, loop_off's crosses it.
        centre = {(x, y) for x, y in one_ink - all_ink
                  if 8 < x / (self.SAMPLE / 24.0) < 16
                  and 8 < y / (self.SAMPLE / 24.0) < 16}
        self.assertGreater(
            len(centre), 15,
            'loop_one must carry its "1" inside the loop, not beside it')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class IconPipelineTest(unittest.TestCase):
    """:func:`view.icons.icon`: recolour, rasterise, cache, degrade."""

    def setUp(self):
        from view.icons import clear_cache

        self.app = make_app()
        clear_cache()
        self.addCleanup(clear_cache)

    def test_icon_renders_at_1x_and_2x(self):
        from PyQt6.QtCore import QSize
        from view.icons import icon

        for dpr in (1.0, 2.0):
            with self.subTest(dpr=dpr):
                ic = icon('play', '#1976d2', 24, dpr)
                self.assertFalse(
                    ic.pixmap(QSize(24, 24)).isNull(),
                    f'a dpr-{dpr} play icon must paint something')
                # The sheet is registered at ``size * dpr`` device pixels and
                # tagged with the DPR. Qt denominates ``availableSizes()`` in
                # device pixels for such a sheet (verified: dpr=2 lists
                # QSize(48, 48)), so at dpr 1 this is the brief's "contains 24"
                # and at dpr 2 it is the proof the hi-dpi ask really rasterised
                # a 48 px sheet rather than reusing the 24 px one.
                sheet = QSize(int(24 * dpr), int(24 * dpr))
                self.assertIn(sheet, ic.availableSizes())
                self.assertEqual(
                    24, ic.pixmap(QSize(24, 24)).width(),
                    'a logical 24 px request must return a 24 px pixmap')

    def test_icon_is_recoloured_from_the_requested_colour(self):
        """``currentColor`` is substituted, so two asks give two glyphs."""
        from PyQt6.QtCore import QSize
        from view.icons import icon

        for colour in ('#1976d2', '#d0d0d0'):
            with self.subTest(colour=colour):
                pixmap = icon('play', colour, 24, 1.0).pixmap(QSize(24, 24))
                self.assertEqual(
                    _token(colour),
                    pixmap.toImage().pixelColor(12, 12).name().lower(),
                    'the triangle body must carry the requested colour')

    def test_cache_returns_same_object(self):
        from view.icons import icon

        first = icon('pause', '#444444', 20, 1.0)
        self.assertIs(first, icon('pause', '#444444', 20, 1.0),
                      'same key must return the cached QIcon')
        self.assertIsNot(first, icon('pause', '#444444', 20, 2.0),
                         'dpr is part of the key')
        self.assertIsNot(first, icon('pause', '#d0d0d0', 20, 1.0),
                         'colour is part of the key or a theme flip hands back '
                         'the old glyph')
        self.assertIsNot(first, icon('play', '#444444', 20, 1.0),
                         'name is part of the key')

    def test_clear_cache_forces_a_rerender(self):
        from view.icons import clear_cache, icon

        before = icon('stop', '#444444', 20, 1.0)
        clear_cache()
        self.assertIsNot(before, icon('stop', '#444444', 20, 1.0))

    def test_missing_icon_degrades_to_null_icon(self):
        """Review Focus 3: a missing resource is a warning, never a crash."""
        from io import StringIO
        from contextlib import redirect_stdout

        from view.icons import icon

        buffer = StringIO()
        with redirect_stdout(buffer):
            ic = icon('does_not_exist', '#000000', 24)

        self.assertTrue(ic.isNull(), 'a missing SVG must degrade to a null QIcon')
        self.assertIn(
            'does_not_exist', buffer.getvalue(),
            'the failure has to be reported, not swallowed: an icon set that '
            'silently stops drawing is invisible in the UI',
        )

    def test_frozen_resource_path_resolves_the_icons_subdirectory(self):
        """Packaging: a bundled tree resolves ``resource/icons/`` like ``resource/``.

        ``.build/pyplayer.spec`` ships the whole ``resource`` directory, so a
        frozen app finds the SVGs under ``sys._MEIPASS``. ``get_resource_path``
        must resolve the new subdirectory exactly as it already resolves
        ``resource/default_cover.png`` (``view/widgets/now_playing_panel.py:22``).
        """
        import tempfile
        from unittest import mock

        from core.resource_utils import get_resource_path

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sys, 'frozen', True, create=True), \
                    mock.patch.object(sys, '_MEIPASS', tmp, create=True):
                icons = get_resource_path('resource/icons/play.svg')
                cover = get_resource_path('resource/default_cover.png')

            self.assertEqual(Path(tmp) / 'resource' / 'icons' / 'play.svg', icons)
            self.assertEqual(Path('resource/icons'), icons.parent.relative_to(Path(tmp)))
            # Same ``resource`` root the existing cover resolves from, plus the
            # new subdirectory: that is what "ships the same way" means.
            self.assertEqual(cover.parent / 'icons', icons.parent)

    def test_broken_svg_degrades_too(self):
        """A file that exists but is not valid SVG follows the same path.

        ``QSvgRenderer.isValid()`` is False on truncated markup, and rendering
        it anyway yields an empty pixmap -- the failure mode a user would see
        as a blank button with no clue why.
        """
        import tempfile
        from io import StringIO
        from contextlib import redirect_stdout
        from unittest import mock

        from PyQt6.QtCore import QSize
        from view.icons import icon
        import view.icons as icons_module

        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'icons'
            broken.mkdir()
            (broken / 'play.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                '<path d="M0 0"/', encoding='utf-8')
            buffer = StringIO()
            with mock.patch.object(
                    icons_module, 'get_resource_path',
                    side_effect=lambda name: broken / f'{name}.svg'):
                with redirect_stdout(buffer):
                    ic = icon('play', '#1976d2', 24)

        self.assertTrue(ic.isNull(), 'unparseable markup must give a null QIcon')
        self.assertTrue(ic.pixmap(QSize(24, 24)).isNull())
        self.assertIn('play', buffer.getvalue(), 'and say so, once')


class BundledResourceTest(unittest.TestCase):
    """The spec bundles the directory, so a new resource subtree needs no spec edit."""

    def test_resource_directory_is_bundled_wholesale(self):
        spec = (PROJECT_ROOT / '.build' / 'pyplayer.spec').read_text(encoding='utf-8')
        self.assertIn(
            "datas.append((str(resource_dir), 'resource'))", spec,
            'the spec must keep bundling resource/ as a directory; the moment '
            'it enumerates files, resource/icons/*.svg stops shipping',
        )
        self.assertNotIn(
            'default_cover.png', spec,
            'a per-file resource entry is exactly the pattern that would leave '
            'the new icons out of the bundle',
        )


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class BottomPanelIconTest(unittest.TestCase):
    """``BottomPanel`` draws every glyph from the SVG set, on the right ground."""

    def setUp(self):
        from view.icons import clear_cache

        self.app = make_app()
        clear_cache()
        self.addCleanup(clear_cache)

    def _panel(self, mode='light'):
        """A bottom panel on a manager that has actually been applied."""
        from view.widgets.bottom_panel import BottomPanel

        manager = make_manager(mode)
        manager.apply_to(self.app)
        panel = BottomPanel(manager)
        self.addCleanup(panel.deleteLater)
        return panel, manager

    @staticmethod
    def _dominant_colour(pixmap):
        """The modal opaque colour of a rasterised glyph (AA edges excluded)."""
        from collections import Counter

        if pixmap is None or pixmap.isNull():
            return None
        image = pixmap.toImage()
        counts = Counter(
            image.pixelColor(x, y).name().lower()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 200
        )
        return counts.most_common(1)[0][0] if counts else None

    def _button_colour(self, button):
        from PyQt6.QtCore import QSize

        return self._dominant_colour(
            button.icon().pixmap(QSize(button.iconSize())))

    def _label_colour(self, label):
        return self._dominant_colour(label.pixmap())

    def test_hand_drawn_icon_code_is_gone(self):
        """Brief Step 5: the polygons, the rasteriser and the text glyphs left."""
        from view.widgets import bottom_panel

        source = Path(bottom_panel.__file__).read_text(encoding='utf-8')
        for gone in ('create_vector_icon', 'create_colored_icon',
                     'draw_play_icon', 'draw_pause_icon', 'draw_stop_icon',
                     'draw_prev_icon', 'draw_next_icon',
                     '\u21ba', '\u266a'):      # the loop and volume characters
            self.assertNotIn(
                gone, source, f'{gone} still lives in bottom_panel.py')
        for symbol in ('create_vector_icon', 'create_colored_icon',
                       'draw_play_icon', 'draw_pause_icon', 'draw_stop_icon',
                       'draw_prev_icon', 'draw_next_icon'):
            self.assertFalse(
                hasattr(bottom_panel, symbol),
                f'{symbol} must be deleted, not merely unreferenced')
        self.assertIn('from view.icons import icon', source)

    def test_transport_icons_are_svg_and_follow_the_icon_token(self):
        from core.theme import DARK, LIGHT

        panel, manager = self._panel('light')
        for button, name in ((panel._prev_btn, 'prev'), (panel._stop_btn, 'stop'),
                             (panel._next_btn, 'next')):
            with self.subTest(icon=name):
                self.assertFalse(button.icon().isNull(), f'{name} drew nothing')
                self.assertEqual(
                    _token(LIGHT.icon), self._button_colour(button),
                    f'{name} must be painted with tokens.icon '
                    f'({LIGHT.icon}), not a local literal')
            self.assertEqual(
                _token(LIGHT.icon_on_accent), self._button_colour(panel._play_btn),
                'play/pause sit on the accent disc, so they use icon_on_accent')

        # ``MainWindow.recolor`` is the ``theme_changed`` subscriber (Task 6's
        # fan-out), so a bare panel has to be recoloured the way the window
        # does it. The loop and volume glyphs read ``self._theme.tokens`` when
        # their state changes and need no such call -- which is why they are
        # checked without one below.
        manager.set_mode('dark')
        panel.recolor(manager.tokens)
        self.assertEqual(_token(DARK.icon), self._button_colour(panel._prev_btn),
                         'recolor() must regenerate the SVG glyphs from the new tokens')
        self.assertEqual(_token(DARK.icon_on_accent),
                         self._button_colour(panel._play_btn))

    def test_loop_button_carries_icons_on_its_own_three_states(self):
        """``icon_muted``'s contrast guard is only honest if the glyph sits here.

        ``tests/test_theme.py`` pins ``icon_muted`` at 3:1 against
        ``button_bg`` / ``button_hover`` / ``button_pressed`` / ``surface``,
        because the loop-off glyph was measured on ``#loopButton``. So the loop
        icon has to be that button's *icon* -- not a transparent label beside it
        -- or the guard protects a surface the icon never appears on.
        """
        from core.theme import DARK, LIGHT
        from core.theme_qss import build_qss
        from tests.test_theme_qss import _rule_block

        panel, manager = self._panel('light')
        tips, glyphs = [], []
        for mode in ('OFF', 'ONE', 'ALL'):
            with self.subTest(mode=mode):
                panel.set_loop_mode(mode)
                self.assertEqual(
                    '', panel._loop_btn.text(),
                    'the loop glyph is an icon now, not a character in the '
                    'button\'s text (whose colour the palette, not the token, decides)')
                self.assertFalse(panel._loop_btn.icon().isNull())
                expected = LIGHT.icon_muted if mode == 'OFF' else LIGHT.accent
                self.assertEqual(
                    _token(expected), self._button_colour(panel._loop_btn),
                    f'{mode} must be drawn with {expected}')
                tip = panel._loop_btn.toolTip()
                self.assertIn(mode, tip)
                tips.append(tip)
                glyphs.append(panel._loop_btn.icon().pixmap(
                    panel._loop_btn.iconSize()).toImage().copy())

        self.assertEqual(3, len(set(tips)), 'each mode needs its own tooltip')
        self.assertEqual(
            3, len({self._fingerprint(image) for image in glyphs}),
            'OFF / ONE / ALL are three distinct glyphs; one shared loop would '
            'make the modes distinguishable only by hover text',
        )

        # The button really does carry the three backgrounds the guard measures.
        sheet = build_qss(LIGHT, manager.alphas)
        self.assertIn(f'background-color: {LIGHT.button_bg};',
                      _rule_block(sheet, '#loopButton'))
        self.assertIn(f'background-color: {LIGHT.button_hover};',
                      _rule_block(sheet, '#loopButton:hover'))
        self.assertIn(f'background-color: {LIGHT.button_pressed};',
                      _rule_block(sheet, '#loopButton:pressed'))

        manager.set_mode('dark')
        panel.set_loop_mode('OFF')
        self.assertEqual(_token(DARK.icon_muted),
                         self._button_colour(panel._loop_btn))

    @staticmethod
    def _fingerprint(image):
        return bytes(1 if image.pixelColor(x, y).alpha() > 128 else 0
                     for y in range(image.height()) for x in range(image.width()))

    def test_volume_switches_four_glyphs_and_keeps_the_icon_on_the_panel(self):
        """Volume levels are icons; the percentage stays text."""
        from core.theme import DARK, LIGHT

        panel, manager = self._panel('light')
        fingerprints = set()
        for volume in (0.0, 0.2, 0.5, 0.9):
            with self.subTest(volume=volume):
                panel.set_volume(volume)
                self.assertEqual(
                    '', panel._volume_icon.text(),
                    'no text character may survive the swap')
                pixmap = panel._volume_icon.pixmap()
                self.assertIsNotNone(pixmap, 'the volume label lost its pixmap')
                self.assertFalse(pixmap.isNull(), 'the volume glyph drew nothing')
                self.assertEqual(_token(LIGHT.icon), self._label_colour(panel._volume_icon),
                                 'the volume glyph is an ordinary icon: tokens.icon')
                self.assertIn(f'{int(volume * 100)}%', panel._volume_label.text())
                fingerprints.add(self._fingerprint(pixmap.toImage()))

        self.assertEqual(
            4, len(fingerprints),
            '0/1/2/3 arcs are four different glyphs, not three plus a relabel',
        )

        manager.set_mode('dark')
        panel.set_volume(0.5)
        self.assertEqual(_token(DARK.icon), self._label_colour(panel._volume_icon),
                         'recolor() must redraw the volume glyph too')

    def test_play_pause_glyph_tracks_the_playing_state(self):
        panel, _manager = self._panel('light')
        resting = panel._play_btn.icon().pixmap(panel._play_btn.iconSize())
        panel.set_playing_state(True)
        playing = panel._play_btn.icon().pixmap(panel._play_btn.iconSize())
        self.assertNotEqual(self._fingerprint(resting.toImage()),
                            self._fingerprint(playing.toImage()),
                            'pause must be a different glyph from play')
        panel.set_playing_state(False)

    def test_volume_label_has_a_style_scope_and_the_icon_needs_none(self):
        """Task 6's two unscoped labels.

        ``#volumeLabel`` is text, so it needs the sheet's reach: an objectName,
        a rule in ``core/theme_qss.py`` and membership of
        ``REQUIRED_OBJECT_NAMES`` (the tuple is the styling contract).
        ``#volumeIcon`` gets an objectName for testability only: it displays a
        pixmap already painted from ``tokens.icon``, and the sole reason it ever
        wanted a scope was that it carried a *character*, whose colour came from
        the palette.
        """
        from core.theme import LIGHT
        from core.theme_qss import REQUIRED_OBJECT_NAMES, build_qss
        from tests.test_theme_qss import _rule_block

        panel, manager = self._panel('light')

        self.assertEqual('volumeLabel', panel._volume_label.objectName())
        self.assertIn('volumeLabel', REQUIRED_OBJECT_NAMES)
        sheet = build_qss(LIGHT, manager.alphas)
        block = _rule_block(sheet, '#volumeLabel')
        self.assertIn(f'color: {LIGHT.text_secondary};', block,
                      'the percentage must read as a companion to #timeLabel')
        self.assertIn('font-size:', block)

        self.assertEqual('volumeIcon', panel._volume_icon.objectName())
        self.assertNotIn(
            'volumeIcon', REQUIRED_OBJECT_NAMES,
            'an objectName the sheet does not select must not be claimed as a '
            'styling contract',
        )
        self.assertNotIn('#volumeIcon', sheet)

    def test_panel_is_still_unstyled_at_widget_level(self):
        """Task 6's end state must survive: no widget-level stylesheet anywhere."""
        from PyQt6.QtWidgets import QWidget

        from core.theme_qss import REQUIRED_OBJECT_NAMES, build_qss

        panel, manager = self._panel('light')
        styled = [
            f'{type(child).__name__}#{child.objectName()}'
            for child in panel.findChildren(QWidget)
            if child.styleSheet()
        ]
        self.assertEqual([], styled, 'bottom_panel reintroduced an inline sheet')
        self.assertEqual('', panel.styleSheet())
        sheet = build_qss(manager.tokens, manager.alphas)
        for name in REQUIRED_OBJECT_NAMES:
            self.assertIn(f'#{name}', sheet)

    def test_orphan_set_bg_alpha_alias_is_gone(self):
        """Nothing has called it since Task 6; an unexplained alias is dead code."""
        from view.widgets.bottom_panel import BottomPanel

        self.assertFalse(
            hasattr(BottomPanel, 'set_bg_alpha'),
            'MainWindow.set_controls_alpha talks to the manager directly, so '
            'this alias had no caller left',
        )

    def test_icon_sizes_come_from_the_geometry_tokens(self):
        from core.theme import PLAY_SIZE, TRANSPORT_SIZE

        panel, _manager = self._panel('light')
        self.assertEqual(TRANSPORT_SIZE, panel._prev_btn.width())
        self.assertEqual(TRANSPORT_SIZE, panel._stop_btn.width())
        self.assertEqual(TRANSPORT_SIZE, panel._loop_btn.width())
        self.assertEqual(PLAY_SIZE, panel._play_btn.width())
        self.assertEqual(TRANSPORT_SIZE // 2, panel._prev_btn.iconSize().width())
        from PyQt6.QtCore import QSize

        sheet = panel._prev_btn.icon().pixmap(QSize(panel._prev_btn.iconSize()))
        self.assertEqual(panel._prev_btn.iconSize().width(), sheet.width(),
                         'the glyph must be displayed at the size it was rasterised for')

    def test_bottom_panel_paints_icons_in_a_real_window(self):
        """End to end through ``MainWindow``: the glyphs survive the layout."""
        from view.main_window import MainWindow

        manager = make_manager('dark')
        manager.apply_to(self.app)
        window = MainWindow(manager)
        try:
            window.resize(900, 600)
            window.show()
            self.app.processEvents()
            panel = window._bottom_panel
            panel.set_loop_mode('ALL')
            panel.set_volume(0.2)
            grabbed = panel.grab().toImage()
            colours = {grabbed.pixelColor(x, y).name().lower()
                       for y in range(grabbed.height())
                       for x in range(grabbed.width())}
            from core.theme import DARK

            self.assertIn(
                _token(DARK.icon), colours,
                'a dark panel must show icon-coloured glyphs; a palette-derived '
                'grey would be this test blind spot',
            )
            self.assertEqual(_token(DARK.icon), self._button_colour(panel._stop_btn))
        finally:
            window.close()
            window.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
