#!/usr/bin/env python3
"""i18n coverage tests for the view layer (Task 9).

Three guards, one per failure mode the audit found (§4.6 A6/A7):

* ``test_view_keys_exist_in_both_locales`` -- the 8 keys Task 9 introduces
  must resolve in *both* properties files; a key shipped only in zh_CN would
  render ``[MISSING: ...]`` the moment the app ran under en_US.
* ``test_no_missing_keys_in_empty_state`` (Review Focus 5) -- a freshly built
  ``MainWindow`` (no ``update_*`` call ever) must not show a missing key or
  one of the old hardcoded English literals in any ``QLabel``. This is the
  first-launch contract: nothing is loaded yet, the copy still has to be
  complete.
* ``test_no_hardcoded_english_literals_left`` -- a source scan of the five
  files Task 9 touched, so a literal cannot sneak back in through a re-edit
  even if every runtime path happens to be covered.

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

MODIFIED_VIEW_FILES = (
    'view/widgets/now_playing_panel.py',
    'view/widgets/playlist_view.py',
    'view/widgets/bottom_panel.py',
    'view/widgets/library_selector.py',
    'view/delegates/playlist_delegate.py',
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
        for rel_path in MODIFIED_VIEW_FILES:
            source = (ROOT / rel_path).read_text(encoding='utf-8')
            for literal in FORBIDDEN_LITERALS:
                self.assertNotIn(
                    literal, source,
                    f'{rel_path} still contains the hardcoded literal {literal}',
                )


if __name__ == '__main__':
    unittest.main(verbosity=2)
