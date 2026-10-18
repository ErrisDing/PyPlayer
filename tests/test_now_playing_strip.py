#!/usr/bin/env python3
"""Tests for ``view.widgets.now_playing_strip.NowPlayingStrip`` (batch 2, Task 5).

The strip replaces the batch-1 left panel's cover box and track read-outs at the
left end of the control bar (spec §2: 取消左栏, 封面缩到 48 px). Three things are
pinned here, in order of how easily they regress:

* **The cover pipeline is a move, not a rewrite.** The PIL-first path, the
  RGBA/RGB ``QImage`` construction, the Qt-only fallback and the
  exception-returns-default-cover behaviour all came straight out of the batch-1
  left panel, whose file batch 2 Task 9 deleted. A rewrite of that block silently
  loses the ``devicePixelRatio`` and colour-mode handling the batch-1 tests
  already cover, so
  the assertions below are about *pixels* -- the batch-1 Task 9 technique -- not
  about which method was called. :meth:`test_initial_state_shows_default_cover_not_text`
  compares the rendered cover with the reference scaled default cover, and
  :meth:`test_album_art_replaces_default` checks the colour that came back is the
  one that went in.
* **Empty artist stays empty.** Batch 1 ruled that a missing artist renders
  nothing rather than ``metadata.unknown_artist``; a placeholder is new behaviour
  nobody asked for (that ruling is restated in the widget, not silently dropped).
* **One line, two texts.** A bottom bar is ~64 px tall, so the album name has no
  room -- it stays in the signature for the presenter's sake and gets a column in
  batch 4. Eliding is therefore the widget's job: an 80-character title in a 320 px
  bar must show an ellipsis and must not push the bar wider, because a ``QLabel``
  that refuses to shrink would take the whole window's minimum width with it.

``#nowPlayingStrip`` / ``#stripArt`` / ``#stripTitle`` / ``#stripArtist`` are styled
in ``core/theme_qss.py`` but deliberately *not* registered in
``REQUIRED_OBJECT_NAMES`` in this task: that tuple is asserted against the live
``MainWindow`` tree, and the strip enters it in Task 7 (Task 3's ruling). The names
and the "no widget-level stylesheet" invariant are asserted here instead.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_now_playing_strip -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

# The English copy batch 1 replaced with i18n keys. A literal here, in the strip,
# would be a regression of spec §4.6's "no hardcoded interface text" ruling.
FORBIDDEN_LITERALS = ('"No Track Playing"', '"No Art"', '"Unknown Title"',
                      "'No Track Playing'", "'No Art'", "'Unknown Title'")


def _token(hex_color: str) -> str:
    """A ``#rrggbb`` colour in the exact spelling ``QColor.name()`` reports."""
    from PyQt6.QtGui import QColor

    return QColor(hex_color).name().lower()


def _dominant_colour(pixmap):
    """The modal opaque colour of a pixmap (batch 1 Task 9's pixel technique)."""
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


def _png_bytes(hex_color, size=64):
    """Raw PNG bytes of a solid-colour rectangle, without PIL.

    ``size`` is either a side length or a ``(width, height)`` pair -- the pair form
    is what pins the aspect-ratio handling of the Qt-only fallback.

    Written with ``QPixmap.save`` rather than PIL because this repo's GUI
    interpreter (conda ``dev_313``) has no Pillow: the PIL branch of the moved
    conversion code is exercised by batch 1's tests, and this task must be able to
    prove the Qt-only fallback paints the right pixels on its own.
    """
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QColor, QPixmap

    width, height = (size, size) if isinstance(size, int) else size
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(hex_color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, 'PNG')
    return bytes(buffer.data())


def _reference_default_cover(art_size):
    """What the panel should show when there is no art: the batch-1 reference.

    Same expression as the moved ``_clear_art`` body -- the cached cover scaled to
    the art box with ``KeepAspectRatio`` + ``SmoothTransformation`` -- so an equal
    image is evidence the moved path is intact, and a different one says the strip
    stopped showing the default cover.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

    from view.widgets.now_playing_strip import DEFAULT_COVER_PATH

    cover = QPixmap(str(DEFAULT_COVER_PATH))
    if cover.isNull():
        return None
    return cover.scaled(art_size, art_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class NowPlayingStripTest(unittest.TestCase):
    """Cover pixels, two lines of text, and the absence of placeholder copy."""

    def setUp(self):
        from core import i18n

        self.app = make_app()
        self._previous_locale = i18n.get_current_locale()
        i18n.set_locale('zh_CN')
        self.addCleanup(i18n.set_locale, self._previous_locale)

    def _strip(self, width=320):
        """A strip inside a shown parent of ``width``, with the sheet applied.

        The parent matters twice: a child widget's ``isVisible()`` answer is its
        parent's, and the elision arithmetic only runs once the layout has given
        the labels a width.
        """
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        from view.widgets.now_playing_strip import NowPlayingStrip

        manager = make_manager('light')
        manager.apply_to(self.app)
        self.addCleanup(manager.deleteLater)

        parent = QWidget()
        parent.resize(width, 64)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        strip = NowPlayingStrip(parent)
        layout.addWidget(strip)
        parent.show()
        self.app.processEvents()
        self.addCleanup(parent.deleteLater)
        self.addCleanup(strip.deleteLater)
        self.assertTrue(strip.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
                        '#nowPlayingStrip can only paint its fill with the attribute')
        return strip, manager

    @staticmethod
    def _art(strip):
        from PyQt6.QtWidgets import QLabel

        label = strip.findChild(QLabel, 'stripArt')
        assert label is not None, '#stripArt is missing'
        return label

    @staticmethod
    def _title(strip):
        from PyQt6.QtWidgets import QLabel

        label = strip.findChild(QLabel, 'stripTitle')
        assert label is not None, '#stripTitle is missing'
        return label

    @staticmethod
    def _artist(strip):
        from PyQt6.QtWidgets import QLabel

        label = strip.findChild(QLabel, 'stripArtist')
        assert label is not None, '#stripArtist is missing'
        return label

    # === Step 1 tests ===

    def test_initial_state_shows_default_cover_not_text(self):
        """No track yet: the 48 px box holds the default cover, not the 暂无封面 copy."""
        from core.theme import STRIP_ART_SIZE

        strip, _manager = self._strip()
        art = self._art(strip)

        self.assertEqual((STRIP_ART_SIZE, STRIP_ART_SIZE),
                         (art.width(), art.height()),
                         'the art box is a STRIP_ART_SIZE square')
        self.assertIsNotNone(art.pixmap(),
                             'the initial state shows text, not the default cover')
        self.assertFalse(art.pixmap().isNull())
        self.assertEqual('', art.text(),
                         'the cover box fell back to the no-art label')
        reference = _reference_default_cover(STRIP_ART_SIZE)
        if reference is not None:
            self.assertEqual(reference.toImage(), art.pixmap().toImage(),
                             'the initial cover is not the scaled default cover')
            self.assertEqual(_dominant_colour(reference),
                             _dominant_colour(art.pixmap()))

        # The sheet owns every colour here; nothing in the widget carries one.
        from PyQt6.QtWidgets import QWidget

        self.assertEqual('', strip.styleSheet())
        for child in strip.findChildren(QWidget):
            self.assertEqual('', child.styleSheet(),
                             f'{type(child).__name__}#{child.objectName()} has an '
                             'inline stylesheet; the app sheet is the only source')

    def test_the_strip_names_are_styled_by_the_sheet(self):
        """``#nowPlayingStrip``/``#stripArt``/``#stripTitle``/``#stripArtist`` exist.

        The pair Task 5 could not close through ``REQUIRED_OBJECT_NAMES`` (Task 7
        registers the names), so it is closed here: a name the widget carries and
        the sheet does not select would take its colour from the palette, which is
        how the progress and volume sliders ended up looking different in batch 1.
        """
        import re

        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        def block(qss, selector):
            match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', qss)
            self.assertIsNotNone(match, f'no rule block for {selector!r}')
            return match.group(1)

        for theme_name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            qss = build_qss(tokens, AlphaSettings())
            with self.subTest(theme=theme_name):
                for selector in ('#nowPlayingStrip', '#stripArt', '#stripTitle',
                                 '#stripArtist'):
                    self.assertIn(f'\n{selector} {{', qss,
                                  f'{selector} is missing; that widget falls back to '
                                  'palette colours')
                # The strip is a plate *inside* #bottomPanel: any opaque fill here
                # would cover the controls-alpha composite the panel paints.
                self.assertIn('background-color: transparent;',
                              block(qss, '#nowPlayingStrip'))
                self.assertIn(f'background-color: {tokens.surface_alt};',
                              block(qss, '#stripArt'))
                self.assertIn(f'color: {tokens.text_primary};', block(qss, '#stripTitle'))
                self.assertIn(f'color: {tokens.text_secondary};',
                              block(qss, '#stripArtist'))

    def test_album_art_replaces_default(self):
        """Bytes in, same colour out -- and it is not the default cover any more."""
        from core.theme import STRIP_ART_SIZE

        pink = '#e91e63'
        strip, _manager = self._strip()
        art = self._art(strip)
        before = _dominant_colour(art.pixmap())

        strip.update_album_art(_png_bytes(pink))

        self.assertEqual(_token(pink), _dominant_colour(art.pixmap()),
                         'the fed cover did not reach the box intact')
        self.assertNotEqual(before, _dominant_colour(art.pixmap()),
                            'the default cover was never replaced')
        self.assertNotEqual(
            _dominant_colour(_reference_default_cover(STRIP_ART_SIZE)),
            _dominant_colour(art.pixmap()),
            'the art is still the default cover')
        self.assertLessEqual(art.pixmap().width(), STRIP_ART_SIZE)
        self.assertLessEqual(art.pixmap().height(), STRIP_ART_SIZE)

        # ``KeepAspectRatio`` on the Qt-only path: a 120x60 cover lands as 48x24, not
        # as a 48x48 smear. A solid square cannot show a stretched edge, which is why
        # this case is a rectangle -- measured: flipping the mode to
        # ``IgnoreAspectRatio`` leaves every colour assertion above green.
        strip.update_album_art(_png_bytes(pink, (120, 60)))
        self.assertEqual((STRIP_ART_SIZE, STRIP_ART_SIZE // 2),
                         (art.pixmap().width(), art.pixmap().height()),
                         'the fed cover was stretched into the square instead of '
                         'scaled inside it')

        # Junk bytes take the exception path and come back as the default cover,
        # never as a blank box or a crash.
        strip.update_album_art(b'not an image at all')
        self.assertEqual(before, _dominant_colour(art.pixmap()),
                         'undecodable art left the box empty instead of falling back')

        # The PIL branch, measured rather than asserted. This repo's GUI interpreter
        # has no Pillow, so the three colour-mode paths the moved code branches on
        # would otherwise be a claim -- and a rewrite that flattened them into one
        # ``QImage`` call is exactly what the "move it verbatim" instruction exists to
        # prevent. A stub answers the four calls the branch makes (``open``,
        # ``thumbnail``, ``convert``, ``tobytes``) and the pixels are checked.
        import contextlib
        from types import SimpleNamespace
        from unittest import mock

        import view.widgets.now_playing_strip as strip_module

        for mode, expect_convert in (('RGBA', False), ('RGB', False), ('L', True)):
            with self.subTest(pil_mode=mode):
                calls = []

                class StubImage:
                    """``PIL.Image.Image`` stand-in emitting one solid colour."""

                    Resampling = SimpleNamespace(LANCZOS='LANCZOS')

                    def __init__(self, source_mode, width, height):
                        self.mode = source_mode
                        self.width, self.height = width, height

                    @classmethod
                    def open(cls, fp):
                        fp.read()
                        calls.append('open')
                        return cls(mode, 120, 90)

                    def thumbnail(self, box, resample):
                        calls.append(('thumbnail', box, resample))
                        # A real thumbnail preserves aspect ratio inside the box;
                        # 120x90 inside a square box lands on 48x36, so the stub
                        # keeps the ratio too -- the size that reaches ``QImage`` is
                        # part of what is being tested.
                        scale = min(box[0] / self.width, box[1] / self.height)
                        self.width = int(self.width * scale)
                        self.height = int(self.height * scale)

                    def convert(self, target):
                        calls.append(f'convert:{target}')
                        return StubImage(target, self.width, self.height)

                    def tobytes(self, fmt, want_mode):
                        calls.append(f'tobytes:{want_mode}')
                        assert fmt == 'raw' and want_mode == self.mode, calls
                        # 48 * 3 and 48 * 4 are both 4-byte-aligned scanlines -- the
                        # exact condition Qt's stride-less ``QImage`` constructor
                        # needs. A rewrite that skipped the aspect-ratio handling
                        # would hand Qt an unpadded buffer here and paint nothing.
                        pixel = (bytes([233, 30, 99, 255]) if want_mode == 'RGBA'
                                 else bytes([233, 30, 99]))
                        return pixel * (self.width * self.height)

                with contextlib.ExitStack() as stack:
                    stack.enter_context(mock.patch.object(strip_module, 'PIL_AVAILABLE', True))
                    # ``create=True`` because the name only exists when Pillow is
                    # importable -- and this repo's GUI interpreter has no Pillow,
                    # which is why the Qt-only fallback above is the path that ran.
                    stack.enter_context(mock.patch.object(strip_module, 'Image', StubImage,
                                                          create=True))
                    strip.update_album_art(b'fake bytes')

                thumbnails = [entry for entry in calls if isinstance(entry, tuple)]
                self.assertEqual(1, len(thumbnails),
                                 f'the PIL branch must thumbnail once, got {calls}')
                _tag, box, resample = thumbnails[0]
                self.assertEqual((STRIP_ART_SIZE, STRIP_ART_SIZE), box,
                                 'the thumbnail box must be the strip art size, not '
                                 "the panel's 200")
                self.assertEqual('LANCZOS', resample,
                                 'the moved code asks PIL for a LANCZOS thumbnail')
                self.assertEqual(expect_convert,
                                 any(str(c).startswith('convert') for c in calls),
                                 f'the {mode} branch took the wrong path')
                self.assertIn(f'tobytes:{"RGB" if expect_convert else mode}', calls,
                              'the QImage was built from the wrong raw encoding')
                # Aspect ratio is preserved inside the square box (120x90 -> 48x36),
                # so the box's height is a ceiling rather than the pixmap's size.
                self.assertEqual(STRIP_ART_SIZE, art.pixmap().width())
                self.assertGreater(art.pixmap().height(), 0)
                self.assertLessEqual(art.pixmap().height(), STRIP_ART_SIZE)
                self.assertEqual(
                    _token(pink), _dominant_colour(art.pixmap()),
                    f'the {mode} path produced a QPixmap whose pixels are not what '
                    'was fed in -- the RGBA8888/RGB888 stride handling regressed')

        # The exception branch, which junk bytes alone cannot reach: the Qt-only
        # path answers them with a null pixmap, so it is the *PIL* path that has to
        # prove ``except`` lands on the default cover instead of a blank box.
        class RaisingImage:
            Resampling = SimpleNamespace(LANCZOS='LANCZOS')

            @staticmethod
            def open(fp):
                raise ValueError('truncated image data')

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(strip_module, 'PIL_AVAILABLE', True))
            stack.enter_context(mock.patch.object(strip_module, 'Image', RaisingImage,
                                                  create=True))
            strip.update_album_art(_png_bytes(pink))
        self.assertEqual(
            before, _dominant_colour(art.pixmap()),
            'a PIL failure left the box empty instead of falling back to the '
            'default cover -- the exception branch of the moved code is its own '
            'safety net and has to stay one')

    def test_clear_falls_back_to_default_cover(self):
        """Same path as the initial state (batch 1 ruling A7), and recolor survives it."""
        from core.theme import STRIP_ART_SIZE, DARK

        from core import i18n

        strip, _manager = self._strip()
        art = self._art(strip)
        default = _dominant_colour(_reference_default_cover(STRIP_ART_SIZE))

        strip.update_track_info('Song', 'Singer', 'Album')
        strip.update_album_art(_png_bytes('#3f51b5'))
        self.assertNotEqual(default, _dominant_colour(art.pixmap()))

        strip.clear()
        self.assertEqual(default, _dominant_colour(art.pixmap()),
                         'clear() did not return to the default cover')
        self.assertEqual(i18n.get('metadata.no_track'), self._title(strip).text())
        self.assertEqual('', self._artist(strip).text())
        self.assertEqual('', art.text(), 'the cover is gone and only the words are left')

        # Task 7 forwards ``theme_changed`` into ``recolor``; it may not blank the
        # cover it did not draw.
        strip.recolor(DARK)
        self.assertFalse(art.pixmap() is None or art.pixmap().isNull(),
                         'recolor() cleared the cover')

    def test_title_and_artist_render_and_elide(self):
        """An 80-character title elides inside 320 px; the artist line survives."""
        from PyQt6.QtGui import QFontMetrics

        title = 'U' * 80
        strip, _manager = self._strip(width=320)
        label, artist = self._title(strip), self._artist(strip)

        strip.update_track_info(title, 'Some Artist', 'Some Album')
        self.app.processEvents()

        self.assertIn('…', label.text(),
                      'a long title is clipped, not elided: the user cannot tell '
                      'two similar titles apart')
        self.assertNotEqual(title, label.text())
        self.assertEqual(title, label.toolTip(),
                         'elision must leave the whole title reachable')
        self.assertLessEqual(QFontMetrics(label.font()).horizontalAdvance(label.text()),
                             label.width(),
                             'the elided title still runs past its own control')
        self.assertLessEqual(label.width(), strip.width(),
                             'the label escaped the strip; a QLabel that refuses to '
                             'shrink takes the window minimum width with it')

        self.assertTrue(artist.isVisible())
        self.assertEqual('Some Artist', artist.text(),
                         'the artist line lost its text or was pushed out')
        self.assertLessEqual(QFontMetrics(artist.font()).horizontalAdvance(artist.text()),
                             artist.width())

        # A bottom bar may never widen the window. ``BottomPanel`` lays its children
        # out honouring their minimum size hints, so if these labels reported theirs
        # the 80-character title would push the whole shell open (measured: 312 px of
        # strip minimum with the labels' default policy against 72 px with the one
        # the widget sets). The claim is about the number, not the policy name: a
        # mutation that renames the policy but keeps the behaviour stays green, and one
        # that keeps the name but loses the behaviour fails.
        from core.theme import STRIP_ART_SIZE

        strip.update_track_info('Title', 'Artist', '')
        self.app.processEvents()
        short_minimum = strip.minimumSizeHint().width()
        strip.update_track_info(title, 'A' * 40, '')
        self.app.processEvents()
        self.assertEqual(short_minimum, strip.minimumSizeHint().width(),
                         'the title length changed the bar\'s minimum width: the '
                         'window can no longer be resized smaller than the text')
        self.assertLess(short_minimum, STRIP_ART_SIZE * 2,
                        'the bar demands more than the cover box and two short lines')

    def test_empty_artist_stays_empty(self):
        """Batch 1 R3, still in force: no artist means no text, not a placeholder."""
        from core import i18n

        strip, _manager = self._strip()
        strip.update_track_info('T', '', '')
        self.assertEqual('', self._artist(strip).text(),
                         'a placeholder appeared for a missing artist; the sheet '
                         'has an empty line by design')
        self.assertEqual('', self._artist(strip).toolTip())
        self.assertEqual('T', self._title(strip).text())

        # An empty title is the one case that does get copy -- it is the batch-1
        # behaviour, and it is i18n'd, not a literal.
        strip.update_track_info('', 'Singer', '')
        self.assertEqual(i18n.get('metadata.unknown_title'), self._title(strip).text())
        self.assertNotIn('[MISSING', self._title(strip).text())

    def test_no_english_literals(self):
        """The strip sources its copy from i18n, like the panel it replaces."""
        from view.widgets.now_playing_strip import NowPlayingStrip

        source = Path(NowPlayingStrip.__module__.replace('.', '/') + '.py')
        text = source.read_text(encoding='utf-8')
        for literal in FORBIDDEN_LITERALS:
            self.assertNotIn(literal, text,
                             f'{literal} is hardcoded English in the strip')

        # Both locales resolve; nothing ships as ``[MISSING: ...]``.
        from core import i18n

        for locale in ('zh_CN', 'en_US'):
            i18n.set_locale(locale)
            for key in ('metadata.no_track', 'metadata.unknown_title',
                        'now_playing.no_art'):
                with self.subTest(locale=locale, key=key):
                    value = i18n.get(key)
                    self.assertNotIn('[MISSING', value)
                    self.assertTrue(value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
