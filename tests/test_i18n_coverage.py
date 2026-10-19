#!/usr/bin/env python3
"""i18n coverage and delegate-state tests for the view layer (Task 9).

Four guards, one per failure mode the audit found (§4.6 A5/A6/A7/D1):

* ``test_view_keys_exist_in_both_locales`` -- the 8 keys Task 9 introduces
  must resolve in *both* properties files; a key shipped only in zh_CN would
  render ``[MISSING: ...]`` the moment the app ran under en_US.
* ``test_no_missing_keys_in_empty_state`` (Review Focus 5) -- a freshly built
  ``MainWindow`` (no ``update_*`` call ever) must not show a missing key or
  one of the old hardcoded English literals in any ``QLabel``. This is the
  first-launch contract: nothing is loaded yet, the copy still has to be
  complete.
* ``test_no_hardcoded_english_literals_left`` -- a source scan of the files
  Task 9 touched, so a literal cannot sneak back in through a re-edit even if
  every runtime path happens to be covered. ``presenter/main_presenter.py`` is
  in that list because the review found the task's own headline string still
  reaching users through the presenter, one layer above the view the original
  scan watched.
* ``DelegateStatePixelsTest`` (A5/D1) -- the three delegate layers Task 9 adds
  (the 3px ``playing_bar``, the playing row's ``playing_text``, the
  ``text_muted`` position) and the elide reservation that keeps the name off
  it are asserted on rendered pixels in a narrow viewport, where the
  un-reserved name would collide with the position.

The empty-state assertion runs under ``zh_CN`` deliberately: the en_US copy
for ``now_playing.no_art`` is ``No Artwork``, which contains the ``'No Art'``
substring the test forbids in the *pre-i18n* sense. Cross-locale existence is
the first test's job; this one checks the Chinese UI is literal-free.

Run with an offscreen Qt platform for the window test:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_i18n_coverage -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n
from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

# The 8 keys Task 9 produces (2 are existing keys checked by the widgets
# themselves; these are the new ones declared by the plan's Interfaces list).
VIEW_KEYS = (
    'metadata.unknown_title',
    'now_playing.no_art',
    'playlist.header',
    'loop.mode_off',
    'loop.mode_one',
    'loop.mode_all',
    'button.stop_track',
    'library.tooltip',
)

MODIFIED_SOURCE_FILES = (
    # Batch 1 Task 9 scanned the left panel and the chip row. Both were deleted
    # by batch 2 Task 9, and the two widgets that took over their copy are
    # substituted here so the scan keeps the same reach instead of quietly
    # losing a file.
    'view/widgets/now_playing_strip.py',
    'view/widgets/library_sidebar.py',
    'view/widgets/playlist_view.py',
    'view/widgets/bottom_panel.py',
    'view/delegates/playlist_delegate.py',
    # Review finding 1: this class of leak survived the original scan because
    # the scan only watched ``view/``. The presenter sits one layer up and can
    # pre-fill the very copy the view is supposed to own, so it is scanned too.
    'presenter/main_presenter.py',
)

# Quoted string literals (and the open-quote prefix for the loop family, whose
# suffix varies per mode). A docstring is not a quoted literal, so prose that
# mentions the old copy does not trip this.
FORBIDDEN_LITERALS = (
    '"No Track Playing"',
    '"Unknown Title"',
    '"No Art"',
    '"Playlist"',
    '"Loop: ',
)


def _missing(key: str) -> str:
    return f'[MISSING: {key}]'


class I18nKeyCoverageTest(unittest.TestCase):
    """The new keys must exist in both locales (no QApplication needed)."""

    def setUp(self):
        self._previous_locale = i18n.get_current_locale()

    def tearDown(self):
        i18n.set_locale(self._previous_locale)

    def test_view_keys_exist_in_both_locales(self):
        for locale_str in ('zh_CN', 'en_US'):
            i18n.set_locale(locale_str)
            for key in VIEW_KEYS:
                value = i18n.get(key)
                self.assertNotEqual(
                    value, _missing(key),
                    f'key {key!r} missing from main.{locale_str}.properties',
                )
                self.assertNotIn('[MISSING', value)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class EmptyStateCopyTest(unittest.TestCase):
    """First launch, no data: no missing keys, no English literals."""

    def setUp(self):
        self._previous_locale = i18n.get_current_locale()
        i18n.set_locale('zh_CN')

    def tearDown(self):
        i18n.set_locale(self._previous_locale)

    def test_no_missing_keys_in_empty_state(self):
        from PyQt6.QtWidgets import QLabel

        from view.main_window import MainWindow

        app = make_app()
        window = MainWindow(make_manager('light'))
        try:
            window.resize(900, 600)
            window.show()
            app.processEvents()

            texts = [label.text() for label in window.findChildren(QLabel)]
            self.assertTrue(texts, 'a fresh MainWindow must have labels')
            for text in texts:
                self.assertNotIn('[MISSING', text)
                for literal in ('No Track', 'No Art', 'Unknown Title'):
                    self.assertNotIn(literal, text)
        finally:
            window.close()
            window.deleteLater()


class HardcodedLiteralScanTest(unittest.TestCase):
    """The old literals must be gone from the Task 9 sources."""

    def test_no_hardcoded_english_literals_left(self):
        for rel_path in MODIFIED_SOURCE_FILES:
            source = (ROOT / rel_path).read_text(encoding='utf-8')
            for literal in FORBIDDEN_LITERALS:
                hits = [
                    f'{rel_path}:{line_number}'
                    for line_number, line in enumerate(source.splitlines(), 1)
                    if literal in line
                ]
                self.assertFalse(
                    hits,
                    f'{rel_path} still contains the hardcoded literal '
                    f'{literal} at {", ".join(hits)}',
                )


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class DelegateStatePixelsTest(unittest.TestCase):
    """A5/D1: the delegate's playing-state layers are provable on pixels.

    Task 9 Step 5 added three paint layers -- a 3px ``playing_bar`` down the
    left of the playing row, ``playing_text`` for that row's title, and
    ``text_muted`` (replacing ``QColor(136, 136, 136, 160)``) for the
    right-aligned ``[relative_position]`` -- plus an elide rule that reserves
    ``position_width + SPACE_2`` for the name. Before this test the only pixel
    evidence in the suite was the ``playing_bg`` / ``selection_bg`` census in
    ``tests/test_theme_manager.py``, so reverting any of the four left every
    test green -- including the narrow-window title/position collision the
    reservation exists to prevent.

    The viewport is deliberately ~120px wide: that is the only geometry where
    the reservation matters. ``POSITION`` is short so ``[Rock]`` itself still
    fits and paints inside its band (a position wider than the row gets
    clipped by Qt and would leave no muted ink to measure), while ``NAME`` is
    long enough that the un-reserved full-width elide reaches into the
    position's band.

    Every assertion reads exact token colours. Offscreen Qt renders Latin
    glyphs with antialiased edges, so only interior coverage lands on the pure
    token value -- that is enough (measured: 16 name columns and 48 position
    columns per row), and it is why the copy here is ASCII rather than CJK,
    which offscreen draws as hollow boxes and would give a false negative.
    """

    VIEW_WIDTH = 120        # px, narrow on purpose (see the class docstring)
    NAME = 'NeverGonnaGiveYouUpLongName.mp3'
    POSITION = 'Rock'       # renders as "[Rock]"
    BAR_WIDTH = 3           # px, the audited A5 marker width

    def setUp(self):
        self.app = make_app()
        # Same convention as tests/test_theme_manager.py: the application sheet
        # is left as the last theme applied (only the palette is restored),
        # because each assertion reads the pixels its own apply_to produced.
        self._saved_palette = self.app.palette()

    def tearDown(self):
        self.app.setPalette(self._saved_palette)

    def _paint_rows(self, mode: str):
        """Return ``(image, row_rects, tokens)`` for a 2-row playlist.

        Row 0 is the playing row; both rows carry a position so both take the
        name/position layout path.
        """
        from core.theme import THEMES
        from service.queue_service import DisplayEntry
        from view.theme_manager import ThemeManager
        from view.widgets.playlist_view import PlaylistView

        tokens = THEMES[mode]
        manager = ThemeManager(mode=mode)
        manager.apply_to(self.app)

        view = PlaylistView(manager)
        view.set_entries([
            DisplayEntry(display_text=self.NAME, node_idx=0, is_folder=False,
                         path='/lib/playing.mp3', sub_index=0,
                         full_path='/lib/playing.mp3', is_playing=True,
                         relative_position=self.POSITION),
            DisplayEntry(display_text=self.NAME, node_idx=1, is_folder=False,
                         path='/lib/other.mp3', sub_index=0,
                         full_path='/lib/other.mp3',
                         relative_position=self.POSITION),
        ])
        list_view = view._list_view
        view.resize(self.VIEW_WIDTH, 90)
        view.show()
        self.app.processEvents()

        image = list_view.viewport().grab().toImage()
        rects = [list_view.visualRect(list_view.model().index(row))
                 for row in (0, 1)]
        view.close()
        view.deleteLater()
        return image, rects, tokens

    @staticmethod
    def _ink_columns(image, rect, colour: str) -> list:
        """Columns of ``rect`` holding at least one exact ``colour`` pixel."""
        target = colour.lower()
        columns = []
        for x in range(rect.left(), rect.right() + 1):
            for y in range(rect.top(), rect.bottom() + 1):
                if image.pixelColor(x, y).name().lower() == target:
                    columns.append(x)
                    break
        return columns

    def test_playing_row_paints_bar_and_title_without_reaching_the_position(self):
        from core.theme import SPACE_2

        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, (playing, other), tokens = self._paint_rows(mode)

                # 1. A5: the left 3px of the playing row is the playing_bar
                # marker, exactly 3 columns wide, and the same columns of a
                # non-playing row carry none of it.
                self.assertEqual(
                    self._ink_columns(image, playing, tokens.playing_bar),
                    list(range(playing.left(), playing.left() + self.BAR_WIDTH)),
                    'the playing row must carry a 3px playing_bar on its left '
                    'edge and nothing else may use that colour',
                )
                self.assertEqual(
                    self._ink_columns(image, other, tokens.playing_bar), [],
                    'a non-playing row must not paint the playing_bar marker',
                )

                # 2. D1: the right-hand position is text_muted, on both rows
                # (the old QColor(136,136,136,160) matched no token).
                muted = [self._ink_columns(image, rect, tokens.text_muted)
                         for rect in (playing, other)]
                for rect, position_columns in zip((playing, other), muted):
                    self.assertTrue(
                        position_columns,
                        'the [relative_position] column must be painted in '
                        'the text_muted token',
                    )
                    self.assertGreater(
                        position_columns[-1], rect.center().x(),
                        'the muted position text belongs on the right half '
                        'of the row',
                    )

                # 3. A5: the playing row's title is playing_text and the row
                # holds no text_primary; the other row is the mirror image.
                name = self._ink_columns(image, playing, tokens.playing_text)
                self.assertTrue(
                    name,
                    'the playing row must draw its title in playing_text',
                )
                self.assertEqual(
                    self._ink_columns(image, playing, tokens.text_primary), [],
                    'the playing row must not fall back to text_primary',
                )
                other_name = self._ink_columns(image, other, tokens.text_primary)
                self.assertTrue(
                    other_name,
                    'a normal row keeps drawing its title in text_primary',
                )
                self.assertEqual(
                    self._ink_columns(image, other, tokens.playing_text), [],
                    'only the playing row may take the playing_text colour',
                )

                # 4. The elide reservation, measured in pixels. The reservation
                # makes the title's ink stop at least SPACE_2 before the
                # position's ink (measured here: title x5..24, position x41..108
                # in both themes). Draw the name un-reserved at this width and
                # it is elided against the whole row and painted *under* the
                # position text, so the muted glyphs overwrite it: the title's
                # exact-colour ink then survives out to x=36, inside the reserved
                # gap, and the gap assertion fires. The strict non-overlap
                # assertion below is the harder form of the same contract -- the
                # title may never put ink in the position's columns at all.
                rows = (('playing row', name), ('normal row', other_name))
                for row_index, (label, name_columns) in enumerate(rows):
                    position_columns = muted[row_index]
                    self.assertLess(
                        name_columns[-1], position_columns[0],
                        f'the {label} title overlaps the [relative_position] '
                        f'text: title ink runs to x={name_columns[-1]}, '
                        f'position ink starts at x={position_columns[0]}',
                    )
                    self.assertGreaterEqual(
                        position_columns[0] - name_columns[-1], SPACE_2,
                        f'the {label} title must leave the reserved SPACE_2 '
                        f'gap before the position text',
                    )


if __name__ == '__main__':
    unittest.main(verbosity=2)
