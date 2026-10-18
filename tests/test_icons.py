#!/usr/bin/env python3
"""Tests for the SVG icon set and its token-colouring pipeline (Task 8).

Three layers are pinned here, because each can break on its own:

1. **The resources** -- twelve ``resource/icons/*.svg`` files: present,
   parseable, and following the authoring conventions (``viewBox="0 0 24 24"``,
   ``fill="currentColor"``, no external references, and no colour literal
   *anywhere* -- not in a ``fill`` attribute, not in a ``style`` attribute, not
   in an inline value, because the tint is a plain string replace of
   ``currentColor`` and anything else is permanently off-palette). Those
   properties are what the colouring pipeline and the rasteriser depend on, so
   they are asserted from the file text rather than inferred from a render.
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
import re
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

# Batch 2 Task 3's seven, added to this file because the two enumeration tests
# below assert "the set on disk is exactly the set named here": seven new files
# in ``resource/icons`` that this list does not know about are, by this suite's
# own logic, an unexplained fifteenth glyph. Literal for the same reason as
# above, and the geometry floors apply to them too -- a rail glyph that inks
# half the box would otherwise render as a lighter button beside its neighbours.
RAIL_ICON_NAMES = (
    'file', 'folder', 'refresh', 'refresh_all', 'settings', 'info', 'add',
)

ALL_ICON_NAMES = ICON_NAMES + RAIL_ICON_NAMES

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = PROJECT_ROOT / 'resource' / 'icons'

# Anything that pulls in another file, a second colour source, or executable
# content (brief: 「无外部引用」).
FORBIDDEN_ELEMENTS = ('image', 'script', 'style', 'use', 'foreignObject', 'filter')

# The one URL every authored SVG legitimately carries.
SVG_NAMESPACE = 'http://www.w3.org/2000/svg'

# ``view.icons._render``'s two degradation branches, by the wording each one
# prints. Finding 1: the tests have to say *which* branch a fixture reached, or a
# stub that points at a non-existent path turns the malformed-SVG test into a
# second copy of the missing-file test -- which is exactly what happened here.
# Checked in this order, and the two markers are mutually exclusive by wording.
_DEGRADATION_BRANCHES = (
    ('malformed', 'is not valid SVG'),
    ('missing', 'not found'),
)

# Every spelling of a colour a hand-edit can hide in these files' vocabulary.
# The pipeline's only colour source is the ``currentColor`` placeholder --
# ``view.icons`` does a plain ``str.replace`` on it -- so a literal anywhere
# else in the markup (a ``style`` attribute, ``stop-color``, an inline value)
# is a colour no token can ever reach: it passes "contains currentColor", it
# renders, and it stays off-palette permanently. ElementTree drops comments when
# it parses, so scanning the tree (not the raw text) skips the prose.
NAMED_COLOURS = (
    'aliceblue', 'antiquewhite', 'aqua', 'aquamarine', 'azure', 'beige',
    'bisque', 'black', 'blanchedalmond', 'blue', 'blueviolet', 'brown',
    'burlywood', 'cadetblue', 'chartreuse', 'chocolate', 'coral',
    'cornflowerblue', 'crimson', 'cyan', 'darkblue', 'darkcyan', 'darkgoldenrod',
    'darkgray', 'darkgrey', 'darkgreen', 'darkkhaki', 'darkmagenta',
    'darkolivegreen', 'darkorange', 'darkorchid', 'darkred', 'darksalmon',
    'darkslateblue', 'darkslategray', 'darkturquoise', 'darkviolet', 'deeppink',
    'deepskyblue', 'dimgray', 'dodgerblue', 'firebrick', 'floralwhite',
    'forestgreen', 'fuchsia', 'gainsboro', 'ghostwhite', 'gold', 'goldenrod',
    'gray', 'green', 'greenyellow', 'honeydew', 'hotpink', 'indianred', 'indigo',
    'ivory', 'khaki', 'lavender', 'lavenderblush', 'lawngreen', 'lemonchiffon',
    'lightblue', 'lightcoral', 'lightcyan', 'lightgoldenrodyellow', 'lightgray',
    'lightgreen', 'lightpink', 'lightsalmon', 'lightseagreen', 'lightskyblue',
    'lightslategray', 'lightsteelblue', 'lightyellow', 'lime', 'limegreen',
    'linen', 'magenta', 'maroon', 'mediumaquamarine', 'mediumblue',
    'mediumorchid', 'mediumpurple', 'mediumseagreen', 'mediumslateblue',
    'mediumspringgreen', 'mediumturquoise', 'mediumvioletred', 'midnightblue',
    'mintcream', 'mistyrose', 'moccasin', 'navajowhite', 'navy', 'oldlace',
    'olive', 'olivedrab', 'orange', 'orangered', 'orchid', 'palegoldenrod',
    'palegreen', 'paleturquoise', 'palevioletred', 'papayawhip', 'peachpuff',
    'peru', 'pink', 'plum', 'powderblue', 'purple', 'red', 'rosybrown',
    'royalblue', 'saddlebrown', 'salmon', 'sandybrown', 'seagreen', 'seashell',
    'sienna', 'silver', 'skyblue', 'slateblue', 'slategray', 'snow',
    'springgreen', 'steelblue', 'tan', 'teal', 'thistle', 'tomato',
    'turquoise', 'violet', 'wheat', 'white', 'whitesmoke', 'yellow',
    'yellowgreen',
)

# ``currentColor`` is the placeholder, not a colour; ``none`` and the geometry
# keywords are not colours either. They are excluded so the pattern can be run
# over every attribute value without special-casing the ones the set uses.
COLOUR_PATTERN = re.compile(
    r'#[0-9a-fA-F]{3,8}\b'                      # #rgb .. #rrggbbaa
    r'|\b(?:rgb|rgba|hsl|hsla|color|device-cmyk)\s*\('
    r'|\b(?:' + '|'.join(sorted(NAMED_COLOURS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE)


def _local_name(tag: str) -> str:
    """``{http://www.w3.org/2000/svg}path`` -> ``path``."""
    return tag.rsplit('}', 1)[-1]


def _token(hex_color: str) -> str:
    """A ``#rrggbb`` token in the exact spelling ``QColor.name()`` reports."""
    from PyQt6.QtGui import QColor

    return QColor(hex_color).name().lower()


class IconResourceTest(unittest.TestCase):
    """The nineteen SVGs exist and keep the authoring conventions."""

    def test_all_icons_present_and_well_formed(self):
        self.assertEqual(
            12, len(ICON_NAMES),
            'batch 1 pins exactly 12 transport/volume icons; a shorter list '
            'would let this test pass on a partial set',
        )
        self.assertEqual(
            7, len(RAIL_ICON_NAMES),
            'batch 2 Task 3 pins exactly 7 rail icons (add included, spinner '
            'reused), so an eighth file cannot slip in under this test',
        )
        self.assertEqual(19, len(ALL_ICON_NAMES))
        for name in ALL_ICON_NAMES:
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

                    # ...and the same rule for the places the attribute check
                    # cannot see. ``style="fill:#e53935"`` next to a legal
                    # ``fill="currentColor"`` keeps both checks above happy, and
                    # the inline declaration wins at render time: a permanently
                    # off-palette glyph that no token flip can ever recolour.
                    for attr, value in sorted(element.attrib.items()):
                        hidden = COLOUR_PATTERN.findall(value)
                        self.assertEqual(
                            [], hidden,
                            f'<{tag}> {attr}="{value}" hardcodes {hidden}: only '
                            'the currentColor placeholder may carry a colour, '
                            'wherever it is spelled (attribute, style, inline '
                            'value) -- view.icons substitutes currentColor alone',
                        )
                    for text in (element.text, element.tail):
                        hidden = COLOUR_PATTERN.findall(text or '')
                        self.assertEqual(
                            [], hidden,
                            f'<{tag}> has character data carrying {hidden}',
                        )

                # No fetch of any kind. The SVG namespace URI is the one URL an
                # SVG must carry, so it is removed before the scan.
                scannable = text.replace(SVG_NAMESPACE, '')
                for needle in ('xlink:href', 'http://', 'https://', 'url(',
                               '<![CDATA', '<!ENTITY', '@import'):
                    self.assertNotIn(
                        needle, scannable, f'{needle} reaches outside the file')

    def test_icon_names_are_the_shipped_files(self):
        """No fifteenth file, no typo'd name sitting next to the real set.

        Renamed from ``test_icon_names_are_the_twelve_shipped_files`` when batch
        2 Task 3 added seven files: the claim was always "the set on disk is the
        set named here", and keeping the old name would make it lie about its own
        count.
        """
        on_disk = sorted(path.stem for path in ICONS_DIR.glob('*.svg'))
        self.assertEqual(sorted(ALL_ICON_NAMES), on_disk)


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
        for name in ALL_ICON_NAMES:
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

    def test_loop_glyph_stays_in_the_transport_row_size_class(self):
        """The loop button is the fifth member of a row of equal 40px buttons.

        Found by the Task 10 render matrix, not by any earlier check: Material's
        own ``repeat`` path reaches x 3 and x 21 and y 2 and y 22, so the loop
        ring inked 19.2 x 19.2 units against the transport family's 12 x 14.4.
        Measured, that is 1.6x the linear size of prev / stop / next, and in the
        rendered row the loop mark read as a different size class rather than as
        the fifth button. The ring was redrawn onto a 14 x 16 box (stroke weight
        kept at 2 units -- scaling the whole path down would have thinned it and
        made the glyph lighter as well as smaller).

        The bar is deliberately generous: this guards the *class*, not the exact
        box, so a future re-author may retune the ring without touching this
        test, and only a return to the "one glyph shouts" shape fails it.
        """
        transport = {name: self._extent(self._mask(name))
                     for name in ('play', 'pause', 'prev', 'next')}
        widest = max(x1 - x0 for x0, _y0, x1, _y1 in transport.values())
        tallest = max(y1 - y0 for _x0, y0, _x1, y1 in transport.values())
        for name in ('loop_off', 'loop_all', 'loop_one'):
            with self.subTest(icon=name):
                x0, y0, x1, y1 = self._extent(self._mask(name))
                self.assertLessEqual(
                    x1 - x0, widest * 1.30,
                    msg=f'{name} inks {x1 - x0:.1f} units wide against the '
                        f'transport family\'s {widest:.1f}; beside four 40px '
                        'buttons it reads as a different size class',
                )
                self.assertLessEqual(
                    y1 - y0, tallest * 1.30,
                    msg=f'{name} inks {y1 - y0:.1f} units tall against the '
                        f'transport family\'s {tallest:.1f}; beside four 40px '
                        'buttons it reads as a different size class',
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

    def _ink_box(self, pixmap):
        """Ink extent of a rasterised sheet, in ``viewBox`` units, + ink pixel count.

        Returns ``(x0, y0, x1, y1, count)`` with the coordinates normalised by
        the *sheet width*, so a 24 px and a 48 px sheet are directly comparable
        and the numbers are the same 24-unit geometry
        :class:`IconGeometryTest` measures. Normalising is what gives this teeth:
        a sheet that only inks the top-left quadrant of its canvas, or gets
        clipped against its edge, has a bbox that disagrees with the 1x one even
        though a pixmap exists and is non-null.
        """
        image = pixmap.toImage()
        scale = 24.0 / image.width()
        points = [(x, y)
                  for y in range(image.height())
                  for x in range(image.width())
                  if image.pixelColor(x, y).alpha() > 128]
        self.assertTrue(points,
                        f'a {image.width()} px sheet rasterised to no ink at all')
        xs = [x for x, _y in points]
        ys = [y for _x, y in points]
        return (min(xs) * scale, min(ys) * scale,
                max(xs) * scale, max(ys) * scale, len(points))

    def test_icon_renders_at_1x_and_2x(self):
        """The hi-dpi ask really rasterised -- and filled -- a 48 px sheet.

        Two things have to be pinned, and neither is pinned by "a pixmap exists":

        * the sheet is requested **with** the ratio. ``icon.pixmap(QSize(24,24))``
          answers at the caller's default ratio and hands back a 24x24,
          ``devicePixelRatio == 1.0`` *downscale* of whatever is cached (verified
          on Qt 6.11), so it cannot distinguish a filled 48 px canvas from a
          corner-painted one;
        * the ink inside that canvas has the 1x glyph's extent and 4x the pixel
          count, i.e. the high-resolution box is actually painted.

        That is the regression surface of ``view.icons._render``: a target rect
        that loses the device scale paints the glyph into the top-left quarter of
        the sheet, and a ``setDevicePixelRatio`` moved before the paint makes the
        painter work in logical coordinates and clips the glyph against the edge.
        Both leave a non-null, correctly sized, half-empty sheet -- and both were
        invisible to a test that only looked at ``availableSizes()``.
        """
        from PyQt6.QtCore import QSize
        from view.icons import icon

        measured = {}
        for dpr in (1.0, 2.0):
            with self.subTest(dpr=dpr):
                ic = icon('play', '#1976d2', 24, dpr)

                # The sheet is registered at ``size * dpr`` device pixels and
                # tagged with the DPR, so Qt denominates ``availableSizes()`` in
                # device pixels for it (verified: dpr=2 lists QSize(48, 48)).
                # Necessary, not sufficient: it says a sheet exists, not that
                # anything was painted into it.
                sheet = QSize(int(24 * dpr), int(24 * dpr))
                self.assertIn(sheet, ic.availableSizes())

                pixmap = ic.pixmap(QSize(24, 24), dpr)
                self.assertFalse(
                    pixmap.isNull(), f'a dpr-{dpr} play icon must paint something')
                self.assertEqual(sheet.width(), pixmap.width())
                self.assertEqual(sheet.height(), pixmap.height())
                self.assertAlmostEqual(dpr, pixmap.devicePixelRatio(), places=3,
                                       msg='the sheet must carry the ratio it was '
                                           'rasterised for, or Qt scales it again')

                box = self._ink_box(pixmap)
                measured[dpr] = box
                x0, y0, x1, y1, _count = box
                # The set's authored ink margin, at both ratios: the glyph must
                # sit inside 1..23 units of its own sheet. A pre-tagged DPR pushes
                # the ink to 23.5 (clipped by the canvas edge); a logical-size
                # target rect instead leaves the far half of the box empty, which
                # the extent floors below catch.
                self.assertGreaterEqual(x0, 1.0,
                                        f'dpr {dpr}: ink starts at {x0:.2f} units, '
                                        'the glyph does not fill its sheet')
                self.assertGreaterEqual(y0, 1.0,
                                        f'dpr {dpr}: ink starts at {y0:.2f} units, '
                                        'the glyph does not fill its sheet')
                self.assertLessEqual(x1, 23.0,
                                     f'dpr {dpr}: ink reaches {x1:.2f} units, i.e. '
                                     'it is clipped by the sheet edge')
                self.assertLessEqual(y1, 23.0,
                                     f'dpr {dpr}: ink reaches {y1:.2f} units, i.e. '
                                     'it is clipped by the sheet edge')
                # play is authored 11 x 14 units (the transport rhythm); the mask
                # loses the antialiased tip pixel, so 1x measures 9.0 x 13.0 and
                # 2x 10.0 x 13.5. A logical-size target rect measures 4.5 x 6.5
                # (half the box, in the corner) and a pre-tagged DPR 7.5 x 13.5
                # pushed against the edge, so these floors bite.
                self.assertGreaterEqual(
                    x1 - x0, 8.5,
                    f'dpr {dpr}: ink spans {x1 - x0:.2f} units wide; a glyph '
                    'painted into part of the sheet measures about half that')
                self.assertGreaterEqual(
                    y1 - y0, 12.5,
                    f'dpr {dpr}: ink spans {y1 - y0:.2f} units tall')

        # A logical 24 px request without a ratio answers at 24 px. That is Qt
        # downscaling the cached sheet, not evidence about the hi-dpi render --
        # kept only to pin the caller-visible contract, and deliberately not the
        # one labelled "the proof" (see the docstring).
        with self.subTest('plain logical ask'):
            plain = icon('play', '#1976d2', 24, 2.0).pixmap(QSize(24, 24))
            self.assertEqual(24, plain.width())
            self.assertEqual(1.0, plain.devicePixelRatio())

        if len(measured) == 2:
            one_x, two_x = measured[1.0], measured[2.0]
            for i, edge in enumerate(('left', 'top', 'right', 'bottom')):
                self.assertAlmostEqual(
                    one_x[i], two_x[i], delta=1.5,
                    msg=f'the 2x sheet\'s {edge} ink edge sits at {two_x[i]:.2f} '
                        f'units but the 1x sheet\'s at {one_x[i]:.2f}: the two '
                        'ratios rasterised different glyphs, so one of them is '
                        'not filling its canvas',
                )
            # Same shape, four times the pixels -- an upscale of the 1x sheet or
            # a corner-paint cannot satisfy this and a correct 2x paint does
            # (measured 306 vs 4 x 76 = 304, the slack is antialiasing).
            self.assertAlmostEqual(
                two_x[4], 4 * one_x[4], delta=0.15 * 4 * one_x[4],
                msg=f'the 48 px sheet holds {two_x[4]} ink pixels against the '
                    f'24 px sheet\'s {one_x[4]}: a hi-dpi sheet must hold ~4x, '
                    'not the same count (corner-painted) or a clipped surplus',
            )

        # And the spelling that Qt 6.11 makes pixel-identical to the correct call
        # -- ``QSvgRenderer.render(painter)`` scales to the painter's viewport,
        # measured 0 px of difference against the explicit rect -- still has to
        # pass its target rect, because the device-pixel scale of that rect is
        # the whole contract and the rendering gives no signal about it.
        with self.subTest('the render call keeps an explicit device-pixel rect'):
            import view.icons as icons_module

            code = '\n'.join(
                line for line in Path(icons_module.__file__).read_text(
                    encoding='utf-8').splitlines()
                if not line.strip().startswith('#'))
            calls = [line.strip() for line in code.splitlines()
                     if 'renderer.render(' in line]
            self.assertEqual(1, len(calls),
                             'exactly one rasterisation call is expected')
            for call in calls:
                self.assertRegex(
                    call, r'renderer\.render\(painter,\s*QRectF\([^)]*(?:sheet|dpr)',
                    f'{call} drops the device-pixel target rect: the sheet is '
                    'size * dpr, so a rect in logical pixels (or none at all) '
                    'paints the glyph into part of the canvas',
                )

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
        warning = buffer.getvalue()
        self.assertIn(
            'does_not_exist', warning,
            'the failure has to be reported, not swallowed: an icon set that '
            'silently stops drawing is invisible in the UI',
        )
        # Finding 1: which of the two downgrade branches was taken is part of the
        # contract. ``not found`` is the not-found branch; if the invalid-SVG
        # wording ever appears here, the fixture stopped being a missing file and
        # this test silently became a duplicate of the malformed one below.
        self.assertIn('not found', warning, f'wrong branch: {warning!r}')
        self.assertNotIn('is not valid SVG', warning, f'wrong branch: {warning!r}')

    def test_frozen_resource_path_resolves_the_icons_subdirectory(self):
        """Packaging: a bundled tree resolves ``resource/icons/`` like ``resource/``.

        ``.build/pyplayer.spec`` ships the whole ``resource`` directory, so a
        frozen app finds the SVGs under ``sys._MEIPASS``. ``get_resource_path``
        must resolve the new subdirectory exactly as it already resolves
        ``resource/default_cover.png`` (``view/widgets/now_playing_strip.py:53``).
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

    def _render_from_temp_dir(self, name, svg_text=None):
        """``icon(name)`` against a stand-in ``resource/icons`` directory.

        ``svg_text=None`` leaves the file absent; a string writes it as
        ``<name>.svg``. Returns ``(qicon, captured_warning)``.

        The patch maps the *basename* of the resource path, and that is the whole
        point: ``view.icons._icon_path`` asks for
        ``get_resource_path('resource/icons/<name>.svg')``, so a stub that appends
        ``.svg`` to what it was handed answers a path with a doubled extension,
        which does not exist, and the malformed-SVG branch is never taken -- the
        bug this helper exists to make impossible (whole-branch review finding 1).
        """
        import shutil
        import tempfile
        from io import StringIO
        from contextlib import redirect_stdout
        from unittest import mock

        import view.icons as icons_module
        from view.icons import clear_cache, icon

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        icons = tmp / 'icons'
        icons.mkdir()
        if svg_text is not None:
            (icons / f'{name}.svg').write_text(svg_text, encoding='utf-8')

        clear_cache()
        buffer = StringIO()
        with mock.patch.object(
                icons_module, 'get_resource_path',
                side_effect=lambda requested: icons / Path(requested).name):
            with redirect_stdout(buffer):
                rendered = icon(name, '#1976d2', 24)
        return rendered, buffer.getvalue()

    def test_broken_svg_degrades_too(self):
        """Finding 1: the *malformed* branch, not the missing-file one.

        ``QSvgRenderer.isValid()`` is False on truncated markup, and rendering it
        anyway yields an empty pixmap -- the failure mode a user would see as a
        blank button with no clue why. The fixture is asserted present *and*
        invalid before the call, so this test cannot quietly slide back into the
        not-found path the way the old ``lambda name: broken / f'{name}.svg'``
        stub did (that doubled the extension and the file was never found).
        """
        from PyQt6.QtCore import QByteArray, QSize
        from PyQt6.QtSvg import QSvgRenderer
        from view.icons import icon

        malformed = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path fill="currentColor" d="M0 0"/'      # truncated mid-attribute
        )

        # The fixture is what it claims: parseable-as-bytes, present, invalid.
        self.assertFalse(
            QSvgRenderer(QByteArray(
                malformed.replace('currentColor', '#1976d2').encode('utf-8'))
            ).isValid(),
            'the "malformed" fixture is valid SVG, so the branch under test '
            'would not be the malformed one',
        )

        ic, warning = self._render_from_temp_dir('play', malformed)

        self.assertTrue(ic.isNull(), 'unparseable markup must give a null QIcon')
        self.assertTrue(ic.pixmap(QSize(24, 24)).isNull())
        self.assertIn('is not valid SVG', warning, f'wrong branch: {warning!r}')
        self.assertNotIn('not found', warning, f'wrong branch: {warning!r}')
        self.assertEqual(
            ['Warning: icon play is not valid SVG'],
            [line.split(' (')[0] for line in warning.splitlines() if line],
            'the malformed file must report exactly the invalid-SVG line: a '
            'second warning means the fixture also lost its currentColor '
            'placeholder (a different contract, covered by the authored-set '
            'tests), and spec §6 promises one warning line per failure',
        )

    def test_missing_and_malformed_svg_degrade_on_distinguishable_branches(self):
        """Finding 1: the two downgrade paths say different things.

        ``_render`` has one degradation contract and two branches (file absent,
        file present but not valid SVG). Asserting only "``isNull()`` and one
        warning" cannot tell them apart, which is how the malformed half of the
        contract ended up with zero coverage: both tests were running the
        not-found branch. This pins which branch each fixture reaches, and that
        neither warning quotes both reasons.
        """
        def branch(warning):
            """The ``_render`` branch the captured warning came from."""
            hits = [name for name, needle in _DEGRADATION_BRANCHES if needle in warning]
            self.assertEqual(
                1, len(hits),
                f'expected exactly one branch marker, got {hits} for {warning!r}',
            )
            return hits[0]

        missing_icon, missing_warning = self._render_from_temp_dir('play')
        broken_icon, broken_warning = self._render_from_temp_dir(
            'play', '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M0 0"/')

        self.assertTrue(missing_icon.isNull() and broken_icon.isNull())
        self.assertEqual('missing', branch(missing_warning))
        self.assertEqual('malformed', branch(broken_warning))
        self.assertNotEqual(
            branch(missing_warning), branch(broken_warning),
            'the two degradations are indistinguishable, so one of the branches '
            'is not being taken (they differ by "not found" vs "is not valid SVG")',
        )


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

    def test_every_glyph_name_lands_on_the_button_that_owns_it(self):
        """Finding 3: the name→button wiring, pinned at the call site.

        ``prev`` and ``next`` are authored as exact mirrors of equal extent and
        equal colour, and ``play``/``pause`` share a size and a colour, so swapping
        either pair keeps every non-null-and-colour assertion in this file green --
        including the mirror test, which measures the *rasterised set* and so
        cannot tell a swapped call site from a swapped resource file. This pins the
        name instead of its pixels: ``view.widgets.bottom_panel.icon`` is replaced
        for the duration of the test by a factory that records the ordered sequence
        of names the panel asks for and tags each name onto the ``QIcon`` it
        returns, while per-widget ``setIcon``/``setPixmap`` spies report which name
        actually landed on which widget. A name swap fails here, and so does wiring
        a glyph to the wrong state (pause while resting, ``loop_all`` on ONE, an
        off-by-one step).

        Chosen over pixel-differencing the mirrors because the defect lives in the
        wiring, not in the artwork: an ink-mask comparison would only re-test
        ``IconGeometryTest``'s mirror claim, would break on any redraw of the SVGs,
        and would still not name the glyph the call site asked for. Reading the name
        back *through pixels* -- the first attempt here, one stamped colour per glyph
        recovered with ``_dominant_colour`` -- is rejected for the same reason: it
        puts ``QColor`` round-tripping and the modal-colour step on the critical
        path, so it re-tests the renderer instead of the wiring and reports any
        raster artefact (a stale ``__pycache__`` did exactly this, showing
        ``next`` on ``_prev_btn``) as a swapped button. Asserting the requested
        sequence and its landing point depends on neither.
        """
        from unittest import mock

        from PyQt6.QtGui import QIcon

        import view.widgets.bottom_panel as bottom_panel_module
        from core.theme import DARK, LIGHT
        from view.widgets.bottom_panel import BottomPanel

        # ``_generate_icons`` asks for the resting-state glyphs in this order:
        # the three transport buttons, then the play disc, then the loop and
        # volume indicators. The names are the contract; the pixels are not.
        RESTING = ['prev', 'stop', 'next', 'play', 'loop_off', 'volume_high']

        requested = []
        landed = []

        class TaggedIcon(QIcon):
            """A ``QIcon`` that carries the glyph name it was asked for.

            ``pixmap`` is overridden because one call site -- ``_set_volume_icon``
            -- never hands the icon to a widget: it rasterises first and puts the
            resulting *pixmap* on the label, so the tag has to travel through that
            call too. The icon itself stays empty: this test is about names, and an
            empty ``QIcon`` cannot fail for a rendering reason.
            """

            def __init__(self, name):
                super().__init__()
                self.requested_name = name

            def pixmap(self, *args, **kwargs):
                sheet = super().pixmap(*args, **kwargs)
                sheet.requested_name = self.requested_name
                return sheet

        def tagging_icon(name, color, size, dpr=1.0):
            self.assertIn(
                name, ICON_NAMES,
                f'{name!r} is not in the authored set; a call site that invents a '
                f'glyph name silently degrades to a null icon in production')
            requested.append(name)
            return TaggedIcon(name)

        def spy(widget, label, setter):
            """Record the tag of whatever ``widget`` is handed by ``setter``."""
            original = getattr(widget, setter)

            def record(tagged):
                landed.append((label, getattr(tagged, 'requested_name', None)))
                return original(tagged)

            setattr(widget, setter, record)

        def landing(action, description):
            """Run ``action``, which must put exactly one glyph on one widget."""
            landed.clear()
            action()
            self.assertEqual(
                1, len(landed),
                f'{description} must set one glyph, observed {landed}')
            return landed[0]

        manager = make_manager('light')
        manager.apply_to(self.app)
        with mock.patch.object(bottom_panel_module, 'icon', tagging_icon):
            panel = BottomPanel(manager)
            self.addCleanup(panel.deleteLater)

            # Construction: every resting glyph asked for, by name, once.
            self.assertEqual(
                RESTING, requested,
                'constructing the panel must request exactly the resting glyphs')

            for widget, label in ((panel._prev_btn, '_prev_btn'),
                                  (panel._play_btn, '_play_btn'),
                                  (panel._stop_btn, '_stop_btn'),
                                  (panel._next_btn, '_next_btn'),
                                  (panel._loop_btn, '_loop_btn'),
                                  (panel._volume_icon, '_volume_icon')):
                spy(widget, label,
                    'setPixmap' if label == '_volume_icon' else 'setIcon')

            # Resting state: one glyph per widget, and each mirror on its own
            # side. Re-running ``_generate_icons`` (the same path ``recolor``
            # takes) is what feeds the spies; the tokens are the live ones, so
            # nothing but the name is under test here.
            landed.clear()
            panel.recolor(LIGHT)
            self.assertEqual(
                6, len(landed), f'one glyph per widget, observed {landed}')
            self.assertEqual(
                {'_prev_btn': 'prev', '_play_btn': 'play', '_stop_btn': 'stop',
                 '_next_btn': 'next', '_loop_btn': 'loop_off',
                 '_volume_icon': 'volume_high'},
                dict(landed),
                'a glyph name landed on the wrong widget')

            self.assertEqual(
                ('_play_btn', 'pause'),
                landing(lambda: panel.set_playing_state(True), 'playing'),
                'a playing player must show pause, not play')
            self.assertEqual(
                ('_play_btn', 'play'),
                landing(lambda: panel.set_playing_state(False), 'stopped'),
                'the pause glyph must leave when playback stops')

            for mode, glyph in (('OFF', 'loop_off'), ('ONE', 'loop_one'),
                                ('ALL', 'loop_all')):
                self.assertEqual(
                    ('_loop_btn', glyph),
                    landing(lambda mode=mode: panel.set_loop_mode(mode),
                            f'loop mode {mode}'),
                    f'loop mode {mode} must show {glyph}')

            for volume, glyph in ((0.0, 'volume_mute'), (0.2, 'volume_low'),
                                  (0.5, 'volume_mid'), (0.9, 'volume_high')):
                self.assertEqual(
                    ('_volume_icon', glyph),
                    landing(lambda volume=volume: panel.set_volume(volume),
                            f'volume {volume}'),
                    f'volume {volume} must show {glyph}')

            # A theme flip re-asks for the same names, not a subset of them.
            panel.set_playing_state(False)
            panel.set_loop_mode('OFF')
            panel.set_volume(0.5)
            requested.clear()
            panel.recolor(DARK)
            self.assertEqual(
                ['prev', 'stop', 'next', 'play', 'loop_off', 'volume_mid'],
                requested,
                'recolor() must regenerate every glyph by name for the state the '
                'panel is in; a dropped or renamed request on the recolor path is '
                'invisible to the colour tests above because they all read the '
                'same warm cache')

    def test_loop_button_carries_icons_on_its_own_three_states(self):
        """``icon_muted``'s contrast guard is only honest if the glyph sits here.

        ``tests/test_theme.py`` pins ``icon_muted`` at 3:1 against
        ``button_bg`` / ``button_hover`` / ``button_pressed`` / ``surface``,
        because the loop-off glyph was measured on ``#loopButton``. So the loop
        icon has to be that button's *icon* -- not a transparent label beside it
        -- or the guard protects a surface the icon never appears on.
        """
        from core import i18n
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
                # Task 9 (A6/D3): the per-mode tooltips are i18n keys now
                # (loop.mode_off / mode_one / mode_all), so this pins "the tip
                # is the key's value" rather than the old English literal --
                # locale-independent by construction, and the distinctness
                # assertions below still prove one tooltip per mode.
                self.assertEqual(tip, i18n.get(f'loop.mode_{mode.lower()}'))
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
