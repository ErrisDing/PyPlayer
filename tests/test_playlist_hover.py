#!/usr/bin/env python3
"""Playlist row hover feedback (batch 3, Task 4 -- audit C2, spec §4.1).

Spec §4.1 pins *where* hover lives: ``PlaylistItemDelegate`` paints it, and the
sheet gets no ``#playlistView::item`` rule. Batch 2's final review caught a
``::item`` rule that could never render, because this delegate overrides
``paint()`` and never asks the style to draw the item sub-control -- a QSS hover
rule would be a second dead rule with zero wearers.
``test_no_item_qss_rule_was_added`` guards that from the generator side; the
three pixel tests guard the real path.

The mechanism was measured before this file was written, because no code in this
repo set ``Qt.WidgetAttribute.WA_Hover`` before this task (a grep across all
``*.py`` returned zero hits) and the hover branch is unreachable without it --
i.e. the branch would have shipped as dead code, the exact defect class this
batch was warned about. Facts this file relies on, all measured on this host
(Qt 6.11.0 / PyQt 6.11.0, offscreen):

* ``QListView`` puts ``QStyle.State_MouseOver`` on exactly one item option -- the
  row under the cursor -- **only** when the list view's *viewport* carries
  ``WA_Hover``. The bit is absent with the attribute left off (default), and
  absent when it is set on the ``QListView`` itself instead of the viewport. So
  the attribute, not the branch, is what feeds this delegate, and that is why
  ``PlaylistView`` sets it.
* ``QTest.mouseMove`` is enough: under offscreen it moves the platform cursor,
  the view repaints, and ``grab()`` afterwards reproduces the same option state.
  No synthetic ``QHoverEvent`` is needed -- hand-posting one also flips the bit,
  but that is the path a test would have to invent, not the one production uses.
* On real hardware the same two ingredients are what make hover work: the
  spontaneous mouse moves Qt delivers to the viewport, and ``WA_Hover``, which
  is exactly the attribute QSS's own ``::item:hover`` rule would have set during
  polish. Nothing here is test-only scaffolding.
* One harness fact is *not* a product fact: the offscreen platform positions
  every top-level window at the same origin, so a visible window left behind by
  another test file covers this one and ``QTest.mouseMove`` never reaches it.
  ``_view`` stands this window clear of that stack; see the comment there.

Hover is asserted as *pixels* off a real ``PlaylistView``, and each pixel claim
is paired with the recorded ``option.state`` of that same paint: a colour alone
cannot tell "hover painted the row" from "the row was never hovered", and that
distinction is the whole content of the priority test.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_hover -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PyQt6.QtCore import QPoint, QEvent, Qt
    from PyQt6.QtWidgets import QStyle
    from PyQt6.QtTest import QTest
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from tests.test_playlist_selection import make_entries
from tests.test_view_smoke import make_app, make_manager

# The recorded option states are plain ints (a ``QStyle.StateFlag`` is an enum,
# and mixing the two in a bitmask read is exactly the kind of thing a future Qt
# enum change gets wrong silently), so the two masks are taken as ints once.
MOUSE_OVER = int(QStyle.StateFlag.State_MouseOver.value)
SELECTED = int(QStyle.StateFlag.State_Selected.value)

# Sampled columns of a row, as offsets from its left/right edges. ``+12`` clears
# both the ``SPACE_2`` gutter and the 3px ``playing_bar``; ``-12`` clears the
# right-hand position read-out; the middle is the row's own centre. Every column
# is read one row-top pixel down, above the text band and off the bottom divider,
# so a hit here is background and never ink.
BAND_TOP_OFFSET = 3
BAND_INSET = 12


def _hover_rules(qss: str) -> list:
    """``(selector, body)`` for every ``#playlistView::item`` rule in a sheet.

    Deliberately a scan of generated *output*, not of ``core/theme_qss.py``'s
    source: that file carries a comment naming ``#playlistView::item`` to explain
    why the rule is absent, so a source grep matches text that emits no pixels.
    """
    found = []
    for chunk in qss.split('}'):
        selector, brace, body = chunk.partition('{')
        if not brace:
            continue
        selector = ' '.join(selector.split())
        # Spacing-insensitive, so ``QListView#playlistView ::item:hover`` counts.
        if '#playlistView::item' in selector.replace(' ', ''):
            found.append((selector, body))
    return found


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PlaylistHoverTest(unittest.TestCase):
    """The hovered row paints ``tokens.hover_bg``, and nothing above it moves."""

    ROW_COUNT = 5

    def setUp(self):
        self.app = make_app()
        self.views = []

    def tearDown(self):
        for view in self.views:
            view.close()
            view.deleteLater()
        # ``deleteLater`` is not honoured by ``processEvents`` on this host; the
        # targeted flush below is what actually reclaims the widgets (measured in
        # batch 3, Task 3), so the suite does not accumulate visible windows.
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    # -- fixtures ----------------------------------------------------------

    def _view(self, mode: str = 'light'):
        """A shown ``PlaylistView`` of ``ROW_COUNT`` flat rows, plus its manager.

        ``ThemeManager(mode=...)`` with an explicit mode, never ``auto``: on the
        offscreen platform ``QStyleHints.colorScheme()`` reports ``Unknown`` and
        ``auto`` therefore always resolves to light, which would make the dark
        half of ``test_hover_applies_in_both_themes`` a light test.
        """
        from view.widgets.playlist_view import PlaylistView

        # One window is the cursor's window at a time: hide whatever this test
        # already opened, or the second view lands on the same spot as the first
        # and shadows its hover. Measured during a mutation run, where a failing
        # first subTest left its view visible and the next subTest reported the
        # ``underMouse`` guard below instead of the colour it was checking.
        for previous in self.views:
            previous.hide()

        manager = make_manager(mode)
        view = PlaylistView(manager)
        view.resize(400, 300)
        view.set_entries(make_entries(self.ROW_COUNT))
        view.show()
        # Move this window out from under other tests' residue before hovering.
        # Every top-level window the offscreen platform gives a position lands at
        # the same origin, and a test file that finishes without hiding its window
        # leaves one covering this one -- measured in the full run, where
        # ``tests/test_library_sidebar`` residue (820x600 at (2,2)) kept
        # ``viewport.underMouse()`` False through a ``QTest.mouseMove``, so no row
        # ever reached the delegate with State_MouseOver and the first hover test
        # failed for a reason that has nothing to do with hover. ``raise_()`` and
        # ``activateWindow()`` alone did not fix it (measured, same residue);
        # standing the window clear of the stack does. Production has one main
        # window, so nothing here is a claim about how hover works.
        view.move(1200, 900)
        view.raise_()
        view.activateWindow()
        self.app.processEvents()
        self.views.append(view)
        return view, manager

    def _rect(self, view, row: int):
        return view._list_view.visualRect(view._model.index(row))

    def _band(self, image, rect) -> list:
        """The row's background colour, sampled across three clear columns."""
        y = rect.top() + BAND_TOP_OFFSET
        xs = (rect.left() + BAND_INSET,
              (rect.left() + rect.right()) // 2,
              rect.right() - BAND_INSET)
        return [image.pixelColor(x, y).name().lower() for x in xs]

    def _hover(self, view, row: int) -> None:
        """Put the cursor on ``row`` the way a user does.

        The ``underMouse`` guard is the harness check, not the product check: if
        the move did not land on this viewport, every pixel claim downstream
        would fail while the delegate was behaving perfectly, so the failure is
        named here instead.
        """
        viewport = view._list_view.viewport()
        rect = self._rect(view, row)
        QTest.mouseMove(viewport, QPoint(rect.center().x(), rect.center().y()))
        self.app.processEvents()
        self.assertTrue(
            viewport.underMouse(),
            'the synthesized mouse move did not land on this view\'s viewport: a '
            'visible top-level window is stacked over it, so no row can be '
            'hovered (see the move() in _view)')

    def _unhover(self, view) -> None:
        """Park the cursor in the blank strip below the last row (no row hovered).

        Needed because the platform cursor position survives between tests: a
        fresh view at the same geometry would otherwise open already hovered.
        """
        viewport = view._list_view.viewport()
        last_bottom = self._rect(view, self.ROW_COUNT - 1).bottom()
        point = QPoint(50, last_bottom + 40)
        self.assertTrue(viewport.rect().contains(point),
                        'the blank strip must be reachable inside the viewport, '
                        'or the baseline grab is taken with a row still hovered')
        QTest.mouseMove(viewport, point)
        self.app.processEvents()

    def _grab_with_states(self, view):
        """Grab the viewport while recording each row's ``option.state``.

        Wraps the real ``paint`` rather than replacing it: the pixels asserted
        downstream come from the delegate under test, and the recorded states say
        which branch that paint was entitled to take. Without the states, a
        "hover must not override selection" test would pass just as happily on a
        row that was never hovered at all.
        """
        from unittest import mock

        from view.delegates.playlist_delegate import PlaylistItemDelegate

        states = {}
        original = PlaylistItemDelegate.paint

        def recording(delegate, painter, option, index):
            states[index.row()] = int(option.state.value)
            return original(delegate, painter, option, index)

        with mock.patch.object(PlaylistItemDelegate, 'paint', recording):
            image = view._list_view.viewport().grab().toImage()
        return image, states

    # -- the three pixel claims -------------------------------------------

    def test_hovered_plain_row_paints_hover_bg(self):
        """C2: the row under the cursor takes ``tokens.hover_bg`` -- and only it."""
        view, manager = self._view()
        tokens = manager.tokens
        row = 1

        self._unhover(view)
        before, before_states = self._grab_with_states(view)
        baseline = self._band(before, self._rect(view, row))
        self.assertNotIn(tokens.hover_bg, baseline,
                         'the row already reads as hovered before any mouse move, '
                         'so the pixel claim below would prove nothing')
        self.assertFalse(any(state & MOUSE_OVER for state in before_states.values()),
                         'no row may carry State_MouseOver while the cursor sits in '
                         'the blank strip -- hover is one row, not the whole view')

        self._hover(view, row)
        after, after_states = self._grab_with_states(view)

        self.assertIn(row, after_states, 'the hovered row was not painted at all')
        self.assertTrue(after_states[row] & MOUSE_OVER,
                        'State_MouseOver never reached the delegate for the row under '
                        'the cursor: QListView only sets that bit when the list view '
                        'viewport carries Qt.WidgetAttribute.WA_Hover, so without the '
                        'attribute the delegate\'s hover branch never runs')
        band = self._band(after, self._rect(view, row))
        self.assertEqual([tokens.hover_bg] * 3, band,
                         f'the hovered row must be filled with hover_bg across its '
                         f'whole width, got {band}')
        self.assertNotEqual(baseline, band,
                            'hovering the row changed no pixel: the assertion above '
                            'is comparing hover_bg with itself')

        for neighbour in (0, 2):
            neighbour_band = self._band(after, self._rect(view, neighbour))
            self.assertNotIn(tokens.hover_bg, neighbour_band,
                             f'row {neighbour} took the hover fill while only row '
                             f'{row} is under the cursor')
            self.assertEqual(self._band(before, self._rect(view, neighbour)),
                             neighbour_band,
                             f'row {neighbour} changed colour while only row {row} '
                             'was hovered')

        self.assertTrue(
            view._list_view.viewport().testAttribute(Qt.WidgetAttribute.WA_Hover),
            'the viewport must keep carrying WA_Hover: it is the only thing that '
            'makes QListView hand State_MouseOver to this delegate (measured -- the '
            'attribute on the QListView itself does not do it)')

    def test_hover_never_overrides_playing_or_selected(self):
        """Review Focus 3 / spec §4.1: the chain is playing > selection > hover.

        Both states are read off the same paint as the pixel, so a row cannot
        pass by being un-hovered: the hover bit is required to be present while
        the colour is required not to be ``hover_bg``.
        """
        view, manager = self._view()
        tokens = manager.tokens

        # -- the playing row: playing_bg survives a hover on top of it.
        view.set_current_playing(2)
        self.app.processEvents()
        self._hover(view, 2)
        image, states = self._grab_with_states(view)
        self.assertTrue(states[2] & MOUSE_OVER,
                        'the playing row was hovered but QStyle.State_MouseOver was '
                        'not set for it, so this test proves nothing about priority')
        self.assertEqual([tokens.playing_bg] * 3,
                         self._band(image, self._rect(view, 2)),
                         'a hovered playing row must stay playing_bg -- hover sits '
                         'below playing in the chain, not above it')

        # -- a selected row: selection_bg survives.
        QTest.mouseClick(view._list_view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(self._rect(view, 4).center().x(),
                                self._rect(view, 4).center().y()))
        self.app.processEvents()
        self._hover(view, 4)
        image, states = self._grab_with_states(view)
        self.assertTrue(states[4] & MOUSE_OVER,
                        'the selected row was not hovered; see the playing case above')
        self.assertTrue(states[4] & SELECTED,
                        'row 4 is not State_Selected, so the colour claim below tests '
                        'a plain row and not the selection/hover priority')
        self.assertEqual([tokens.selection_bg] * 3,
                         self._band(image, self._rect(view, 4)),
                         'a hovered selected row must stay selection_bg')

        # -- and hover is still live in the same frame, so the two claims above
        #    cannot both be explained by "hover never fires here".
        self._hover(view, 0)
        image, states = self._grab_with_states(view)
        self.assertTrue(states[0] & MOUSE_OVER)
        self.assertEqual([tokens.hover_bg] * 3, self._band(image, self._rect(view, 0)),
                         'with nothing above it in the chain, the hovered row must '
                         'still take hover_bg -- otherwise the two assertions above '
                         'pass because hover is dead, which is the defect this '
                         'batch was warned about')

    def test_hover_applies_in_both_themes(self):
        """Spec §1.4: hover is visible in light *and* dark, from the tokens."""
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                view, manager = self._view(mode)
                tokens = manager.tokens
                row = 1

                self._unhover(view)
                before, _states = self._grab_with_states(view)
                self.assertNotIn(tokens.hover_bg,
                                 self._band(before, self._rect(view, row)))

                self._hover(view, row)
                image, states = self._grab_with_states(view)
                self.assertTrue(states[row] & MOUSE_OVER,
                                f'{mode}: no State_MouseOver for the hovered row')
                self.assertEqual([tokens.hover_bg] * 3,
                                 self._band(image, self._rect(view, row)),
                                 f'{mode}: the hovered row must take that theme\'s '
                                 f'hover_bg ({tokens.hover_bg})')

                # The live flip the manager is built for: set_mode repaints the
                # rows from the new token set, hover included.
                manager.set_mode('dark' if mode == 'light' else 'light')
                image, states = self._grab_with_states(view)
                self.assertTrue(states[row] & MOUSE_OVER,
                                f'{mode}: a theme flip must not drop the hover state')
                self.assertEqual([manager.tokens.hover_bg] * 3,
                                 self._band(image, self._rect(view, row)),
                                 f'{mode}: after flipping to '
                                 f'{manager.tokens.hover_bg} the hovered row must '
                                 f'read the new token, not the old one')
                view.close()
                self.views.remove(view)

    def test_no_item_qss_rule_was_added(self):
        """Spec §4.1: hover must not arrive as QSS, which never renders here.

        Reads the output of ``build_qss``, not that module's source -- the source
        carries the literal text ``#playlistView::item`` inside the comment that
        explains why no such rule is emitted, so grepping it finds a match that
        paints zero pixels.
        """
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        for name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            qss = build_qss(tokens, AlphaSettings())
            with self.subTest(theme=name):
                self.assertEqual([], _hover_rules(qss),
                                 f'{name}: a #playlistView::item rule exists. This '
                                 f'view\'s delegate overrides paint() and never asks '
                                 f'the style for the item sub-control, so such a rule '
                                 f'is parsed and discarded -- hover belongs in '
                                 f'PlaylistItemDelegate (spec §4.1).')
                # The scan has to be able to see the forbidden shape at all, or
                # the assertion above is vacuous on any Qt that drops the rule.
                fake = (f'#playlistView::item:hover {{ background-color: '
                        f'{tokens.hover_bg}; }}')
                rules = _hover_rules(fake)
                self.assertEqual(1, len(rules),
                                 'the scanner does not recognise the rule shape it '
                                 'is supposed to forbid; the guard above proves nothing')
                self.assertIn(tokens.hover_bg, rules[0][1],
                              'the scanner cannot read a rule body, so it cannot '
                              'tell where hover_bg is being painted from')
                # And the token is in the sheet -- elsewhere. Without this the
                # "no playlist rule" claim would also pass on a sheet that lost
                # hover_bg entirely, i.e. on a regression of a different kind.
                self.assertIn(tokens.hover_bg.lower(), qss.lower(),
                              f'{name}: hover_bg is gone from the stylesheet, so the '
                              f'rule census above has nothing to be about')


if __name__ == '__main__':
    unittest.main(verbosity=2)
