#!/usr/bin/env python3
"""Playlist multi-selection tests (batch 3, Task 1).

Task 1 gives ``PlaylistView`` Windows-Explorer selection semantics and the two
index helpers the rest of the batch builds on. Two things are pinned here:

* ``ExtendedSelection`` -- Ctrl+click toggles a row, Shift+click extends a
  range. This is asserted with real mouse clicks on the viewport
  (``QTest.mouseClick``), not by calling the selection model, because the
  modifier handling and the Shift anchor live in
  ``QAbstractItemView``'s mouse press/release handlers; driving ``select()``
  directly would pass even if the view were still ``SingleSelection``.
* :meth:`PlaylistView.selected_display_indices` /
  :meth:`PlaylistView.display_index_at` -- the only two ways Task 2..6 address
  rows, so the sorted-and-deduplicated contract and the ``-1`` blank-area
  contract are the interfaces the later tasks depend on.

The first test in this file is different in kind: it is a *probe*, not a guard.
Spec §4.4 refuses to assume whether ``QListView`` already consumes ``Space``
(the shell could bind it to play/pause) and asks for a measurement instead. It
prints what a Space press does to the selection and to the current row, in both
selection modes, and the answer recorded under spec §4.4 is what Task 6 binds.
It asserts only the measurement's shape -- a probe that asserted a guessed
expectation would be circular.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_selection -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PyQt6.QtWidgets import QAbstractItemView
    from PyQt6.QtCore import QEvent, QPoint, Qt
    from PyQt6.QtTest import QTest
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from tests.test_view_smoke import make_app, make_manager


def make_entries(count: int) -> list:
    """``count`` flat (non-folder) display entries, named by row."""
    from service.queue_service import DisplayEntry

    return [
        DisplayEntry(
            display_text=f'track {i}.flac',
            node_idx=i,
            is_folder=False,
            path=f'/tmp/music/track{i}.flac',
            full_path=f'/tmp/music/track{i}.flac',
        )
        for i in range(count)
    ]


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class SpaceProbeTest(unittest.TestCase):
    """Spec §4.4: measure what Space does before deciding what binds it."""

    def setUp(self):
        self.app = make_app()
        self.manager = make_manager()

    def _view(self, count: int = 3, focus_row: int = 0):
        """A shown, focused view of ``count`` rows with row ``focus_row`` current."""
        from view.widgets.playlist_view import PlaylistView

        view = PlaylistView(self.manager)
        view.resize(400, 300)
        view.set_entries(make_entries(count))
        view.show()
        self.app.processEvents()

        view._list_view.setFocus()
        self.app.processEvents()
        view._list_view.setCurrentIndex(view._model.index(focus_row))
        self.app.processEvents()
        return view

    def _press_space(self, widget, modifiers=Qt.KeyboardModifier.NoModifier):
        """Send a real Space press to ``widget``; return whether the receiver accepted it.

        ``setAccepted(False)`` first: a hand-built ``QKeyEvent`` starts out
        accepted, so the returned flag says what the *receiver* did with the
        event rather than what the constructor defaulted to.
        """
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, modifiers)
        event.setAccepted(False)
        self.app.sendEvent(widget, event)
        self.app.processEvents()
        return event.isAccepted()

    @staticmethod
    def _selected_rows(view) -> list:
        """Selected rows straight from the selection model.

        Deliberately *not* ``selected_display_indices()``: this probe was run
        before that method existed (Step 1 of the plan precedes Step 4), and it
        must keep measuring raw Qt behaviour rather than the wrapper under test.
        """
        return sorted(index.row() for index in
                      view._list_view.selectionModel().selectedRows())

    @staticmethod
    def _current_row(view) -> int:
        """The view's current row, or ``-1`` when nothing is current.

        ``QListView`` has no ``currentRow()`` -- that is a ``QListWidget``
        convenience -- so the row comes off ``currentIndex()``.
        """
        return view._list_view.currentIndex().row()

    def _measure(self, view, modifiers, pre_select=None):
        """Snapshot selection + current row around one Space press."""
        from PyQt6.QtCore import QItemSelection, QItemSelectionModel

        if pre_select is not None:
            model = view._list_view.selectionModel()
            selection = QItemSelection(view._model.index(pre_select[0]),
                                       view._model.index(pre_select[1]))
            model.select(selection,
                         QItemSelectionModel.SelectionFlag.ClearAndSelect
                         | QItemSelectionModel.SelectionFlag.Rows)
            self.app.processEvents()

        before_rows = self._selected_rows(view)
        before_row = self._current_row(view)
        accepted = self._press_space(view._list_view, modifiers)
        return {
            'accepted': accepted,
            'before_rows': before_rows,
            'after_rows': self._selected_rows(view),
            'before_current_row': before_row,
            'after_current_row': self._current_row(view),
            'selection_changed': before_rows != self._selected_rows(view),
            'current_row_changed': before_row != self._current_row(view),
        }

    def test_space_default_behaviour_probe(self):
        """Print what a Space press does to the selection and to the current row.

        Not a guard: spec §4.4 forbids assuming the answer, so the deltas are
        printed for every case and the conclusion they force is recorded under
        spec §4.4 for Task 6 to read. The assertions below re-pin the *measured*
        facts (Qt 6.11): bare ``Space`` is already taken by the view, and so is
        ``Ctrl+Space``, so play/pause has to be bound by something that consumes
        the key before the view sees it. If a Qt upgrade ever frees the key,
        these assertions fail loudly instead of Task 6 silently keeping a binding
        that now double-fires.
        """
        modes = (
            ('SingleSelection', QAbstractItemView.SelectionMode.SingleSelection),
            ('ExtendedSelection', QAbstractItemView.SelectionMode.ExtendedSelection),
        )
        modifiers = (
            ('Space', Qt.KeyboardModifier.NoModifier),
            ('Ctrl+Space', Qt.KeyboardModifier.ControlModifier),
        )

        observations = []
        for mode_name, mode in modes:
            for mod_name, mods in modifiers:
                view = self._view()
                view._list_view.setSelectionMode(mode)
                obs = self._measure(view, mods)
                obs['case'] = f'{mode_name} + {mod_name}'
                observations.append(obs)
                view.close()
                view.deleteLater()

        # The case Task 6 actually cares about: does a bare Space destroy a
        # range the user just built with Ctrl/Shift+click?
        view = self._view()
        view._list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        range_obs = self._measure(view, Qt.KeyboardModifier.NoModifier, pre_select=(0, 2))
        range_obs['case'] = 'ExtendedSelection + Space, rows 0..2 pre-selected'
        observations.append(range_obs)
        view.close()
        view.deleteLater()

        print('\n[Space probe] spec 4.4 -- Qt 6.11, focused QListView with 3 rows, '
              'current row 0, one key press delivered via app.sendEvent:')
        for obs in observations:
            print(f"[Space probe]   {obs['case']}: "
                  f"receiver accepted={obs['accepted']}; "
                  f"selected_display_indices changed={obs['selection_changed']} "
                  f"({obs['before_rows']} -> {obs['after_rows']}); "
                  f"currentRow changed={obs['current_row_changed']} "
                  f"({obs['before_current_row']} -> {obs['after_current_row']})")
        sys.stdout.flush()

        self.assertEqual(len(observations), 5, 'four key cases plus the range case')
        for obs in observations:
            self.assertIsInstance(obs['selection_changed'], bool)
            self.assertIsInstance(obs['current_row_changed'], bool)
            self.assertEqual(obs['before_current_row'], 0,
                             f"{obs['case']}: probe setup lost the current row")

        # Measured: every case moves the cursor, and bare Space in the shipped
        # mode replaces the whole selection -- Space is NOT free for play/pause.
        for obs in observations:
            self.assertTrue(
                obs['selection_changed'] or obs['current_row_changed'],
                f"{obs['case']}: Space looks free -- spec §4.4's recorded "
                f"decision (bind Ctrl+Space) needs re-measuring",
            )
        self.assertNotEqual(
            range_obs['after_rows'], [0, 1, 2],
            'a bare Space used to collapse a 3-row range; if it no longer does, '
            're-read spec §4.4 before re-binding plain Space',
        )


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class SelectionTest(unittest.TestCase):
    """Explorer-style selection and the two display-index helpers."""

    ROW_COUNT = 5

    def setUp(self):
        from view.widgets.playlist_view import PlaylistView

        self.app = make_app()
        self.manager = make_manager()
        self.view = PlaylistView(self.manager)
        # 5 rows x ROW_HEIGHT (28px) = 140px of content inside a 300px tall
        # view, so the area below the last row exists and is reachable: that
        # blank strip is what ``display_index_at`` must report as -1.
        self.view.resize(400, 300)
        self.view.set_entries(make_entries(self.ROW_COUNT))
        self.view.show()
        self.app.processEvents()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def _click(self, row: int, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        """Click the centre of ``row`` in the viewport.

        ``QTest.mouseClick`` and not a hand-built ``QMouseEvent`` sent through
        ``app.sendEvent``: Qt records the *anchor* that Shift extends from only
        while handling a **spontaneous** release event
        (``QAbstractItemView::mouseReleaseEvent``), so a synthetic pair selects
        row 4 and silently reports ``[4]`` for a Shift+click -- a harness bug
        that would read as an implementation bug. Verified on this host: the
        synthetic pair never extends a range, the QTest pair gives
        ``[1, 2, 3, 4]``.
        """
        list_view = self.view._list_view
        QTest.mouseClick(list_view.viewport(), Qt.MouseButton.LeftButton,
                         modifiers, list_view.visualRect(self.view._model.index(row)).center())
        self.app.processEvents()

    def _ctrl_click(self, row: int) -> None:
        self._click(row, Qt.KeyboardModifier.ControlModifier)

    def _shift_click(self, row: int) -> None:
        self._click(row, Qt.KeyboardModifier.ShiftModifier)

    def test_selection_mode_is_extended(self):
        """Task 1's headline switch: the list is no longer single-select."""
        self.assertEqual(
            self.view._list_view.selectionMode(),
            QAbstractItemView.SelectionMode.ExtendedSelection,
            'the playlist must be ExtendedSelection for Ctrl/Shift+click to work',
        )

    def test_ctrl_click_toggles_individual_rows(self):
        """Ctrl+click adds a row to the selection; on a selected row it removes it."""
        self._ctrl_click(0)
        self._ctrl_click(2)
        self.assertEqual([0, 2], self.view.selected_display_indices())

        self._ctrl_click(2)
        self.assertEqual([0], self.view.selected_display_indices())

    def test_shift_click_selects_a_contiguous_range(self):
        """Shift+click extends from the last plain-clicked row, endpoints included."""
        self._click(1)
        self._shift_click(4)
        self.assertEqual([1, 2, 3, 4], self.view.selected_display_indices())

    def test_selected_display_indices_is_sorted_and_deduplicated(self):
        """Ascending and unique whatever the click order was (spec §4.2 consumer)."""
        for row in (4, 1, 3, 0, 2):
            self._ctrl_click(row)

        indices = self.view.selected_display_indices()
        self.assertEqual([0, 1, 2, 3, 4], indices)
        self.assertEqual(sorted(indices), indices, 'indices must come back ascending')
        self.assertEqual(len(set(indices)), len(indices),
                         'indices must come back deduplicated')
        self.assertIsInstance(indices, list)

    def test_display_index_at_returns_minus_one_on_empty_area(self):
        """The strip under the last row is not a row: -1, so no context menu (spec §4.3)."""
        list_view = self.view._list_view
        last_bottom = list_view.visualRect(
            self.view._model.index(self.ROW_COUNT - 1)).bottom()

        self.assertEqual(
            -1, self.view.display_index_at(QPoint(50, last_bottom + 200)),
            'a point 200px below the last row must resolve to no row')
        self.assertEqual(
            -1, self.view.display_index_at(QPoint(50, last_bottom + 20)),
            'the blank strip that is still inside the viewport must also resolve '
            'to no row -- that is the area a right-click actually lands in')

        row_two = QPoint(list_view.visualRect(self.view._model.index(2)).center())
        self.assertEqual(2, self.view.display_index_at(row_two))


if __name__ == '__main__':
    unittest.main(verbosity=2)
