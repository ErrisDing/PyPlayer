#!/usr/bin/env python3
"""Playlist right-click menu builder tests (batch 3, Task 2).

:func:`view.widgets.playlist_context_menu.build_playlist_menu` is a pure
function: it turns a resolved target (the display indices Task 3 worked out
from the cursor and the selection) plus a "is the target playing" flag into a
``QMenu``. Splitting it out of ``PlaylistView`` is what lets this file build
menus with no window at all -- spec §3's rationale for the new module is
exactly that the menu is unit-testable away from the shell.

What is pinned here, in the order the plan's Task 2 Step 1 lists it:

* an empty target produces **no menu** (``None``, not an empty ``QMenu``): the
  blank-area rule of spec §4.3 and Review Focus 5 is "do not pop a menu", and a
  zero-action menu is a menu.
* the action order and the copy -- play, remove, clear, each label straight
  from ``i18n`` under *both* locales, so a key added only to ``zh_CN`` fails
  now rather than rendering ``[MISSING: ...]`` in front of an English user.
* a playing target shows pause in the play slot (same action id, because the
  slot is one toggle whose label depends on state).
* a multi-row target shows the count in the remove label -- the batch case
  Task 5 will act on, and the reason ``ctx.remove_count`` is a separate key.
* every action carries its menu id in ``data()`` (Task 3 routes on it, so the
  set must be exactly ``MENU_IDS`` -- one action missing its id, or an
  unregistered id, fails) and ``objectName('menuItem')``.
* a source scan for the old hardcoded English literals, the same guard shape
  ``tests/test_i18n_coverage.py`` uses: it needs no QApplication, so it runs
  even where PyQt6 does not exist.

Assertions read real ``QMenu``/``QAction`` objects rather than mocks, because a
mock would pass on a menu that never renders. The parent is a plain ``QWidget``,
never a ``MainWindow``: ``tests/test_view_structure.py`` asserts the live
main-window tree contains no ``QMenu`` (the retired menu bar's shape), and this
module must not become the reason that guard gets weakened.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_context_menu -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PyQt6.QtWidgets import QWidget
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from core import i18n
from tests.test_view_smoke import make_app

SOURCE_PATH = ROOT / 'view' / 'widgets' / 'playlist_context_menu.py'

# The English labels the pre-i18n version of this widget used, in both quote
# styles -- a scan that watched only double quotes would miss ``addAction('Play')``.
# A docstring is not a quoted literal, so prose about the copy does not trip this,
# and this is a list of known labels, not a detector for arbitrary English.
FORBIDDEN_LITERALS = ('"Play"', '"Remove"', '"Clear"',
                      "'Play'", "'Remove'", "'Clear'")


def _labels(menu) -> list:
    """Non-separator action texts, in menu order."""
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _real_actions(menu) -> list:
    """Non-separator actions, in menu order."""
    return [action for action in menu.actions() if not action.isSeparator()]


def _action_by_id(menu, menu_id: str):
    """The action carrying ``menu_id`` in its ``data()``, or ``None``."""
    for action in _real_actions(menu):
        if action.data() == menu_id:
            return action
    return None


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PlaylistMenuBuildTest(unittest.TestCase):
    """The six contracts of ``build_playlist_menu``."""

    def setUp(self):
        self.app = make_app()
        self._previous_locale = i18n.get_current_locale()
        # A plain QWidget parent: a MainWindow would put a QMenu in the live
        # window tree that test_view_structure guards (see module docstring).
        self.parent = QWidget()

    def tearDown(self):
        i18n.set_locale(self._previous_locale)
        self.parent.deleteLater()
        self.app.processEvents()

    def _menu(self, target_indices, target_is_playing=False, locale=None):
        from view.widgets.playlist_context_menu import build_playlist_menu

        if locale is not None:
            i18n.set_locale(locale)
        return build_playlist_menu(target_indices, target_is_playing, self.parent)

    def test_returns_none_for_no_target(self):
        """No resolved target means no menu at all (spec §4.3 blank area)."""
        for is_playing in (False, True):
            with self.subTest(target_is_playing=is_playing):
                self.assertIsNone(
                    self._menu([], is_playing),
                    'an empty target must return None -- an empty QMenu is '
                    'still a menu popping over the blank area',
                )

    def test_menu_actions_and_labels(self):
        """Target [3], not playing: play / remove / clear, all i18n'd, both locales."""
        for locale in ('zh_CN', 'en_US'):
            with self.subTest(locale=locale):
                menu = self._menu([3], locale=locale)
                self.assertIsNotNone(menu, 'a real target must produce a menu')
                self.assertEqual(
                    _labels(menu),
                    [i18n.get('ctx.play'), i18n.get('ctx.remove'),
                     i18n.get('ctx.clear_playlist')],
                    f'the action order/labels under {locale} are wrong',
                )
                for label in _labels(menu):
                    self.assertNotIn('MISSING', label,
                                     f'unresolved copy under {locale}: {label!r}')
                    self.assertNotIn('{', label,
                                     f'unsubstituted placeholder under '
                                     f'{locale}: {label!r}')

                # Exactly one separator, and it sits between the target
                # actions and the destructive global entry (Task 2 Step 3).
                separators = [index for index, action in enumerate(menu.actions())
                              if action.isSeparator()]
                self.assertEqual(
                    separators, [2],
                    'clear_playlist must be split from the target actions by '
                    'exactly one separator placed after them',
                )

    def test_playing_target_shows_pause_instead_of_play(self):
        """The first entry is the play/pause toggle; state picks the label."""
        from view.widgets.playlist_context_menu import MENU_PLAY

        for locale in ('zh_CN', 'en_US'):
            with self.subTest(locale=locale):
                menu = self._menu([0], target_is_playing=True, locale=locale)
                first = _real_actions(menu)[0]
                self.assertEqual(first.text(), i18n.get('ctx.pause'))
                self.assertNotEqual(
                    first.text(), i18n.get('ctx.play'),
                    'pause and play resolved to the same copy -- a key is '
                    'doing the other one\'s job',
                )
                self.assertEqual(
                    first.data(), MENU_PLAY,
                    'the pause label lives on the play slot: one toggle, two '
                    'states, one menu id',
                )

    def test_batch_labels_show_count(self):
        """A three-row target says how many rows it removes."""
        menu = self._menu([1, 2, 3])
        remove = _action_by_id(menu, 'remove')
        self.assertIsNotNone(remove, 'the remove entry lost its menu id')
        self.assertEqual(
            remove.text(), i18n.get('ctx.remove_count', count=3),
            'a multi-row target must use the parameterised ctx.remove_count',
        )
        self.assertIn('3', remove.text(),
                      f'the count is not in the label: {remove.text()!r}')
        self.assertNotIn('{', remove.text())

    def test_every_action_carries_its_menu_id(self):
        """data() is exactly MENU_IDS, in order; each is #menuItem; the menu has
        the parent it was handed."""
        from view.widgets.playlist_context_menu import (
            MENU_CLEAR, MENU_IDS, MENU_PLAY, MENU_REMOVE,
        )

        menu = self._menu([1, 2])
        actions = _real_actions(menu)
        self.assertEqual(
            {action.data() for action in actions}, set(MENU_IDS),
            'every action must carry a registered menu id and every id must '
            'have an action',
        )
        self.assertEqual(
            len(actions), len(MENU_IDS),
            'the action count and MENU_IDS disagree: an id is duplicated or '
            'an action is unregistered',
        )
        # Position, not just membership. Swapping the remove and clear ids leaves
        # both the set and the count unchanged, and would have Task 3 batch-remove
        # rows when the user asked to empty the playlist.
        self.assertEqual(
            [MENU_PLAY, MENU_REMOVE, MENU_CLEAR],
            [action.data() for action in actions],
            'each id must sit at its own position, not merely somewhere in the menu',
        )

        # Ownership, pinned rather than left to prose. This is what the lifecycle
        # warning depends on: a parentless menu nobody keeps a reference to is gone
        # after exec(), while a parented one survives until the parent dies and has
        # to be deleted by whoever built it.
        self.assertIs(menu.parent(), self.parent,
                      'the menu must belong to the caller-supplied parent')

        for action in actions:
            self.assertEqual(
                action.objectName(), 'menuItem',
                f'{action.text()!r} must carry objectName menuItem',
            )


class HardcodedLiteralScanTest(unittest.TestCase):
    """Source scan, no QApplication: the copy has to come from i18n."""

    def test_no_hardcoded_english_labels(self):
        """The copy comes from i18n, never from one of the pre-i18n English labels."""
        source = SOURCE_PATH.read_text(encoding='utf-8')
        for literal in FORBIDDEN_LITERALS:
            hits = [
                f'{SOURCE_PATH.name}:{line_number}'
                for line_number, line in enumerate(source.splitlines(), 1)
                if literal in line
            ]
            self.assertFalse(
                hits,
                f'playlist_context_menu.py contains the hardcoded literal '
                f'{literal} at {", ".join(hits)}',
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
