#!/usr/bin/env python3
"""Playlist multi-selection and right-click tests (batch 3, Tasks 1 and 3).

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

Task 3 adds :class:`ContextMenuTargetTest`, which wires those helpers to the
menu: the target rules of spec §4.3, the menu entry -> signal mapping, and the
per-click menu disposal ruling R7 asks for. Its own two harness decisions
(``QTest`` sends no context-menu event on this platform, and the popup goes
through a seam because ``QMenu.exec()`` is a nested event loop) are recorded in
that class's docstring.

The first test in this file is different in kind: it is a *probe*, not a guard.
Spec §4.4 refuses to assume whether ``QListView`` already consumes ``Space``
(the shell could bind it to play/pause) and asks for a measurement instead. It
prints what a Space press does to the selection and to the current row, in both
selection modes, and the answer recorded under spec §4.4 is what Task 6 binds.
The measurement came first; the assertions below it now pin that measurement, so
a Qt upgrade that frees the key fails loudly instead of leaving Task 6 holding a
binding that quietly double-fires.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_selection -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PyQt6.QtWidgets import QAbstractItemView, QLabel
    from PyQt6.QtCore import PYQT_VERSION_STR, QEvent, QPoint, Qt
    from PyQt6.QtTest import QTest
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from tests.test_view_smoke import make_app, make_manager


def make_entries(count: int) -> list:
    """``count`` flat (non-folder) display entries, named by row.

    ``node_idx`` is deliberately ``i + 100`` and never ``i``. Real queue data
    keeps the two index spaces apart -- ``queue_service`` reads
    ``_display_entries[display_idx]`` and then deletes ``_queue_nodes[node_idx]``
    (service/queue_service.py:486-502), and a folder entry makes them diverge --
    so a fixture where they coincide cannot tell which space a helper returned.
    With this offset, an implementation that handed back ``node_idx`` instead of
    the display row would fail every assertion below, and the batch removal path
    (spec §4.2, Task 5) would delete the wrong tracks.
    """
    from service.queue_service import DisplayEntry

    return [
        DisplayEntry(
            display_text=f'track {i}.flac',
            node_idx=i + 100,
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
        facts on the Qt of this host: bare ``Space`` is already taken by the view, and so is
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
        range_obs['case'] = ('ExtendedSelection + Space, rows 0..2 selected '
                             'programmatically (ClearAndSelect, not Ctrl/Shift clicks)')
        observations.append(range_obs)
        view.close()
        view.deleteLater()

        print(f'\n[Space probe] spec 4.4 -- PyQt {PYQT_VERSION_STR}, focused QListView '
              'with 3 rows, current row 0, one key press delivered via app.sendEvent:')
        for obs in observations:
            print(f"[Space probe]   {obs['case']}: "
                  f"receiver accepted={obs['accepted']}; "
                  f"selection model changed={obs['selection_changed']} "
                  f"({obs['before_rows']} -> {obs['after_rows']}); "
                  f"currentRow changed={obs['current_row_changed']} "
                  f"({obs['before_current_row']} -> {obs['after_current_row']})")
        sys.stdout.flush()

        self.assertEqual(len(observations), 5, 'four key cases plus the range case')
        for obs in observations:
            self.assertEqual(obs['before_current_row'], 0,
                             f"{obs['case']}: probe setup lost the current row")

        # Measured: every case walks the cursor 0 -> 1 and leaves row 1 as the
        # whole selection, in both selection modes and under Ctrl. These are the
        # numbers spec §4.4 records, pinned exactly -- Space is NOT free for
        # play/pause. They subsume the weaker "something changed" and
        # "the range survived" forms the first fix round carried.
        for obs in observations:
            self.assertEqual([1], obs['after_rows'],
                             f"{obs['case']}: spec §4.4 records [..] -> [1]")
            self.assertEqual(1, obs['after_current_row'],
                             f"{obs['case']}: spec §4.4 records current row 0 -> 1")

        # Two further facts spec §4.4 records as prose: the view *consumes* the
        # key (the original claim, and the reason a window-level binding has to
        # eat it before the focused view sees it), and Ctrl+Space is
        # indistinguishable from bare Space (so neither one is free either).
        for obs in observations:
            self.assertTrue(
                obs['accepted'],
                f"{obs['case']}: the view stopped consuming the press, so the key "
                f"may be free for play/pause -- re-read spec §4.4",
            )
        fields = ('accepted', 'before_rows', 'after_rows',
                  'before_current_row', 'after_current_row',
                  'selection_changed', 'current_row_changed')
        by_case = {obs['case']: obs for obs in observations}
        for mode in ('SingleSelection', 'ExtendedSelection'):
            space_obs = by_case[f'{mode} + Space']
            ctrl_obs = by_case[f'{mode} + Ctrl+Space']
            self.assertEqual(
                [space_obs[name] for name in fields],
                [ctrl_obs[name] for name in fields],
                'Ctrl+Space no longer behaves exactly like bare Space -- spec §4.4 '
                'binds Ctrl+Space on the strength of that identity',
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
        """Click order must not decide the answer (spec §4.2's consumer).

        Pins the ascending half against the live widget. The dedup half is not
        reachable this way -- a row is never listed twice by the selection model --
        and is pinned separately in
        :meth:`test_selection_normalisation_survives_a_scrambled_collaborator`.
        """
        for row in (4, 1, 3, 0, 2):
            self._ctrl_click(row)

        indices = self.view.selected_display_indices()
        self.assertEqual([0, 1, 2, 3, 4], indices,
                         'display rows, not the node_idx=100..104 the fixture carries')
        self.assertIsInstance(indices, list)

    def test_no_selection_returns_an_empty_list(self):
        """Spec §7: an empty selection is ``[]`` for the caller to act on.

        ``None`` here would reach the presenter as a missing target instead of a
        no-op, so the empty case is pinned before any click happens.
        """
        self.assertEqual([], self.view.selected_display_indices())

    def test_selection_normalisation_survives_a_scrambled_collaborator(self):
        """Deduplication pinned at its own seam, which no click can reach.

        ``QItemSelectionModel::selectedRows()`` leaves its order unspecified in
        Qt's own docs, and on this host it returns *click* order -- measured: with
        the ``sorted(...)`` removed, the click-order test above fails as
        ``[4, 1, 3, 0, 2]``. So sorting has a live pin, and it is portable only
        as long as Qt keeps handing rows back in click order.

        Deduplication has no such pin, because a row is never listed twice by the
        selection model whatever the user did. This replaces the collaborator with
        the shape the normalisation exists to absorb, so ``set(...)`` is tested
        rather than assumed.
        """
        from unittest import mock

        model = self.view._model

        class ScrambledSelectionModel:
            def selectedRows(self, column=0):
                return [model.index(row) for row in (3, 1, 3, 0, 1)]

        with mock.patch.object(self.view._list_view, 'selectionModel',
                               return_value=ScrambledSelectionModel()):
            self.assertEqual([0, 1, 3], self.view.selected_display_indices(),
                             'rows must come back ascending and deduplicated '
                             'whatever order the selection model handed them over')

    def test_display_index_at_returns_minus_one_on_empty_area(self):
        """The strip under the last row is not a row: -1, so no context menu (spec §4.3)."""
        list_view = self.view._list_view
        viewport = list_view.viewport()
        last_bottom = list_view.visualRect(
            self.view._model.index(self.ROW_COUNT - 1)).bottom()

        self.assertEqual(
            -1, self.view.display_index_at(QPoint(50, last_bottom + 200), viewport),
            'a point 200px below the last row must resolve to no row')
        blank_in_viewport = QPoint(50, last_bottom + 20)
        self.assertTrue(
            viewport.rect().contains(blank_in_viewport),
            'this point must still be inside the viewport, or the assertion below '
            'silently degrades into the out-of-bounds branch it exists to distinguish')
        self.assertEqual(
            -1, self.view.display_index_at(blank_in_viewport, viewport),
            'the blank strip that is still inside the viewport must also resolve '
            'to no row -- that is the area a right-click actually lands in')

        row_two = QPoint(list_view.visualRect(self.view._model.index(2)).center())
        self.assertEqual(2, self.view.display_index_at(row_two, viewport))

    def test_display_index_at_maps_from_the_widget_it_is_told(self):
        """``pos`` is read in the coordinate space of the ``widget`` argument.

        The list sits below a header inside this widget, so the outer widget's
        space is the viewport's shifted down by the header. An implementation
        that assumed one space for both would answer row 1 for a point over row
        2, and would report the header as a real row -- opening the menu the
        spec §4.3 target rule is built on top of.
        """
        list_view = self.view._list_view
        viewport = list_view.viewport()

        # The same physical pixels, expressed in the outer widget's space.
        # ``viewport.mapTo(view, p)`` is the direction that round-trips against
        # the mapping this method performs. Measured on this host, the inverted
        # call ``view.mapFrom(viewport, p)`` answers a *different* point -- off by
        # (-3, -2) -- so it cannot stand in for it here. Why Qt answers that way
        # is not established; that it does is.
        #
        # One pixel above each row's bottom edge, not its centre: an unmapped
        # read adds the header offset, and 13px of slack still lands a centre on
        # its own row, so a centre-only probe passes the bug it exists to catch.
        for row in range(self.ROW_COUNT):
            rect = list_view.visualRect(self.view._model.index(row))
            outer_point = viewport.mapTo(
                self.view, QPoint(rect.center().x(), rect.bottom() - 1))
            self.assertEqual(
                row, self.view.display_index_at(outer_point, self.view),
                f'row {row}: a header-height offset must be taken off the outer space')

        # A point over the header is over nothing in the viewport: without the
        # mapping it lands on row 0 and pops the menu for a row the user did not
        # click. ``header.geometry()`` is already in this widget's space -- the
        # header is a child of ``self.view`` -- so the centre needs no conversion.
        header = self.view.findChild(QLabel, 'playlistHeader')
        header_point = header.geometry().center()
        self.assertTrue(header.geometry().contains(header_point),
                        'the probe point must sit in the header strip')
        self.assertEqual(-1, self.view.display_index_at(header_point, self.view),
                         'the header strip is not a row')

    def test_display_index_at_on_an_empty_model(self):
        """No rows at all: every point is blank, including one the list covers."""
        self.view.set_entries([])
        self.app.processEvents()

        self.assertEqual(
            -1, self.view.display_index_at(QPoint(50, 50),
                                           self.view._list_view.viewport()),
            'an empty playlist has no row for any point to resolve to')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ContextMenuTargetTest(unittest.TestCase):
    """Task 3: the right-click wiring -- resolve a target, adjust the selection,
    show the menu, turn the clicked entry into a view signal (spec §4.3).

    Two harness decisions come from probes run on this host rather than from
    assumption:

    * ``QTest.mouseClick(viewport, RightButton, ...)`` delivers mouse press and
      release and **no** ``QContextMenuEvent`` at all (measured: only the two
      mouse events reach any handler, on the offscreen platform). So the click
      here is a real ``QContextMenuEvent`` sent through ``app.sendEvent`` -- the
      same object the platform would deliver on Windows.
    * The event is aimed at the **inner** list viewport, the widget a physical
      right-click actually lands on. ``QAbstractItemView::contextMenuEvent``
      ignores it, and Qt then propagates it up to ``PlaylistView``, re-expressing
      ``pos()`` in each receiver's space (measured: viewport ``(198, 69)`` arrives
      at the outer widget as ``(199, 82)`` -- the +13 viewport offset). That is
      why the handler exists on ``PlaylistView`` and why it may hand
      ``event.pos()`` to ``display_index_at`` together with ``self``. It also
      means these tests break loudly if a Qt upgrade ever makes the inner view
      accept the event: the wiring would then have to move to the inner view.

    ``QMenu.exec()`` is a nested event loop and can never run in an automated
    test, so the popup goes through the ``PlaylistView._popup_menu`` seam and the
    tests patch that on the class (which also pins the call signature: two
    positional arguments, no ``self``). The menu itself is still really built --
    :meth:`test_repeated_right_clicks_leave_no_menu_behind` depends on it.
    """

    ROW_COUNT = 6

    ACTION_SIGNALS = ('play_requested', 'remove_requested')

    def setUp(self):
        from view.widgets.playlist_view import PlaylistView

        self.app = make_app()
        self.manager = make_manager()
        self.view = PlaylistView(self.manager)
        # 6 rows x 28px = 168px of content in a 300px tall view: the blank strip
        # under the last row exists and is reachable by a right-click.
        self.view.resize(400, 300)
        self.view.set_entries(make_entries(self.ROW_COUNT))
        self.view.show()
        self.app.processEvents()

        # Every emission of every action signal, in order, as (name, payload).
        self.emitted = []
        for name in self.ACTION_SIGNALS:
            getattr(self.view, name).connect(
                lambda rows, name=name: self.emitted.append((name, list(rows))))
        self.view.clear_playlist_requested.connect(
            lambda: self.emitted.append(('clear_playlist_requested', None)))
        self.view.context_menu_requested.connect(
            lambda index, event: self.emitted.append(('context_menu_requested', index)))

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    # -- fixtures ---------------------------------------------------------

    def _ctrl_click(self, row: int) -> None:
        """Add ``row`` to the selection the way a user does (see SelectionTest)."""
        list_view = self.view._list_view
        QTest.mouseClick(list_view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier,
                         list_view.visualRect(self.view._model.index(row)).center())
        self.app.processEvents()

    def _select(self, *rows: int) -> None:
        for row in rows:
            self._ctrl_click(row)

    def _set_playing(self, row: int) -> None:
        """Make ``row`` the playing row through the view's own API."""
        self.view.set_current_playing(row)
        self.app.processEvents()

    def _right_click_row(self, row: int, choose: str = None) -> dict:
        """Right-click one pixel above ``row``'s bottom edge; see :meth:`_right_click`.

        One pixel above the bottom edge and not the centre: the mapping this
        routes through is off by the 13px viewport offset when it is wrong, and a
        centre point still lands on its own row, so only a near-boundary point
        can tell the two apart (the same reason SelectionTest maps rows there).
        """
        rect = self.view._list_view.visualRect(self.view._model.index(row))
        return self._right_click(self.view._list_view.viewport(),
                                 QPoint(rect.center().x(), rect.bottom() - 1),
                                 choose=choose)

    def _right_click(self, widget, point: QPoint, choose: str = None) -> dict:
        """Deliver a real context-menu event and report what the popup was shown with.

        ``point`` is in ``widget``'s coordinate space -- the widget a spontaneous
        right-click would have landed on. ``choose`` is a ``MENU_*`` id: the entry
        the fake popup pretends the user clicked, or ``None`` for a cancelled menu.

        The returned snapshot is what the assertions read, and it is filled in by
        the patched seam, i.e. *while the menu is open*:

        * ``shown`` -- how many times a menu was actually popped;
        * ``targets`` -- ``self.view.selected_display_indices()`` at that moment,
          so the menu's target is read off the live selection rather than off the
          dispatch that happens afterwards (the window-level test below reads only
          ``shown``, since ``targets`` always comes off this test's own view);
        * ``ids`` -- each entry's ``action.data()``, separators dropped;
        * ``labels`` -- the same entries' text, for the play/pause copy;
        * ``parent`` -- the widget the menu was parented to (``None`` when nothing
          was built), which is what makes the residue test non-vacuous;
        * ``global_pos`` -- the point the menu was told to open at.
        """
        from unittest import mock

        from PyQt6.QtGui import QContextMenuEvent

        from view.widgets.playlist_view import PlaylistView

        snapshot = {'shown': 0, 'targets': None, 'ids': (), 'labels': (),
                    'parent': None, 'global_pos': None}

        def fake_popup(*args):
            # Exactly (menu, global_pos): the seam must not receive ``self``, or
            # the signature the handler calls it with has drifted.
            menu, global_pos = args
            entries = [action for action in menu.actions() if not action.isSeparator()]
            snapshot['shown'] += 1
            snapshot['targets'] = self.view.selected_display_indices()
            snapshot['ids'] = tuple(action.data() for action in entries)
            snapshot['labels'] = tuple(action.text() for action in entries)
            snapshot['parent'] = menu.parent()
            snapshot['global_pos'] = global_pos
            snapshot['point'] = point
            snapshot['widget'] = widget
            if choose is None:
                return None
            return next(action for action in entries if action.data() == choose)

        event = QContextMenuEvent(QContextMenuEvent.Reason.Other, QPoint(point),
                                  QPoint(widget.mapToGlobal(point)))
        with mock.patch.object(PlaylistView, '_popup_menu', side_effect=fake_popup):
            self.app.sendEvent(widget, event)
            self.app.processEvents()
        return snapshot

    def _blank_point_in_viewport(self) -> QPoint:
        """A point below the last row that is still inside the viewport."""
        list_view = self.view._list_view
        viewport = list_view.viewport()
        last_bottom = list_view.visualRect(
            self.view._model.index(self.ROW_COUNT - 1)).bottom()
        point = QPoint(50, last_bottom + 40)
        self.assertTrue(viewport.rect().contains(point),
                        'the blank strip must be reachable inside the viewport, '
                        'or this probes the out-of-bounds branch instead')
        return point

    def _names(self) -> list:
        return [name for name, _payload in self.emitted]

    # -- target rules (spec §4.3) ----------------------------------------

    def test_right_click_on_unselected_row_narrows_selection_to_it(self):
        """Cursor row outside the selection: the selection becomes exactly that row."""
        from view.widgets.playlist_context_menu import MENU_CLEAR, MENU_PLAY, MENU_REMOVE

        self._select(0, 1, 2)
        snapshot = self._right_click_row(5)

        self.assertEqual([5], snapshot['targets'],
                         'a menu opened over an unselected row acts on that row alone')
        self.assertEqual([5], self.view.selected_display_indices(),
                         'and the selection really was replaced, not left as [0, 1, 2]')
        self.assertEqual(1, snapshot['shown'])
        self.assertEqual((MENU_PLAY, MENU_REMOVE, MENU_CLEAR), snapshot['ids'],
                         'the three entries, in the builder\'s order')
        self.assertIs(self.view, snapshot['parent'],
                      'the menu is parented to this view, so its disposal is this '
                      "view's business (ruling R7)")

    def test_menu_opens_at_the_cursor_not_at_local_coordinates(self):
        """The point handed to the popup is the event's global position.

        A wrong value here is invisible to every other assertion in this class --
        the seam is patched, so nothing else looks at where the menu would have
        appeared -- and the user would see the popup open offset from the cursor.
        """
        snapshot = self._right_click_row(2)

        self.assertIsNotNone(snapshot['global_pos'], 'the seam must be given a point')
        self.assertEqual(
            snapshot['widget'].mapToGlobal(snapshot['point']), snapshot['global_pos'],
            'the popup must be told the cursor position in global coordinates')
        self.assertNotEqual(
            snapshot['point'], snapshot['global_pos'],
            'on a host where the widget-local point equals the global point this '
            'assertion compares a value with itself and proves nothing')

    def test_right_click_inside_selection_keeps_the_batch(self):
        """Cursor row already selected: selection untouched, menu acts on all of it."""
        self._select(0, 1, 2)
        snapshot = self._right_click_row(1)

        self.assertEqual([0, 1, 2], snapshot['targets'],
                         'right-clicking inside the selection must not shrink it')
        self.assertEqual([0, 1, 2], self.view.selected_display_indices())

    def test_right_click_on_empty_area_does_not_open_menu(self):
        """Review Focus 5 / spec §7: blank space means no menu, no signal, no change.

        Three blank areas, all of them ``-1`` for ``display_index_at``: the strip
        under the last row, the header strip (only reachable in this widget's own
        space, which is why it is aimed at the outer widget), and -- in
        :meth:`test_right_click_on_an_empty_playlist_does_not_open_menu` -- the
        empty model.
        """
        self._select(0, 2)
        snapshot = self._right_click(self.view._list_view.viewport(),
                                     self._blank_point_in_viewport())

        self.assertEqual(0, snapshot['shown'], 'no menu over the blank strip')
        self.assertIsNone(snapshot['parent'])
        self.assertEqual([], self.emitted,
                         'and no signal at all -- not even context_menu_requested')
        self.assertEqual([0, 2], self.view.selected_display_indices(),
                         'the selection must survive a stray right-click untouched')

    def test_right_click_on_the_header_strip_does_not_open_menu(self):
        """The header is blank space too (spec §4.3), in the outer widget's space."""
        from PyQt6.QtWidgets import QLabel

        header = self.view.findChild(QLabel, 'playlistHeader')
        point = header.geometry().center()
        self.assertTrue(header.geometry().contains(point),
                        'the probe point must sit in the header strip')
        self._select(0, 2)

        snapshot = self._right_click(header, point)

        self.assertEqual(0, snapshot['shown'],
                         'a point over the header resolves to no row, so the menu '
                         'stays closed -- that is what display_index_at(pos, self) '
                         'mapping is for')
        self.assertEqual([], self.emitted)
        self.assertEqual([0, 2], self.view.selected_display_indices(),
                         'and the batch that was there must still be there')

    def test_right_click_on_an_empty_playlist_does_not_open_menu(self):
        """Empty model: every point is blank, so nothing pops and nothing emits."""
        self.view.set_entries([])
        self.app.processEvents()

        rect = self.view._list_view.rect()
        snapshot = self._right_click(self.view._list_view.viewport(),
                                     QPoint(rect.center().x(), rect.center().y()))

        self.assertEqual(0, snapshot['shown'],
                         'an empty playlist has no menu for any point')
        self.assertEqual([], self.emitted)
        self.assertEqual([], self.view.selected_display_indices())

    def test_right_click_targets_the_row_under_the_cursor_not_one_above_it(self):
        """Every row resolves through the mapping, for every row at once.

        The handler receives ``event.pos()`` in *this* widget's space (Qt re-maps
        it while propagating from the viewport) and must pass ``self`` as the
        coordinate source. Pass the wrong widget and each target shifts: the
        near-boundary points :meth:`_right_click_row` uses are what expose that.
        """
        for row in range(self.ROW_COUNT):
            with self.subTest(row=row):
                snapshot = self._right_click_row(row)
                self.assertEqual([row], snapshot['targets'])

    # -- menu action -> signal -------------------------------------------

    def test_menu_play_emits_play_requested(self):
        self._select(0, 1, 2)
        self._right_click_row(1, choose='play')

        self.assertEqual(['context_menu_requested', 'play_requested'], self._names())
        self.assertEqual([0, 1, 2], dict(self.emitted)['play_requested'],
                         'the whole batch, in ascending display-row order')

    def test_menu_remove_emits_remove_requested(self):
        self._select(0, 1, 2)
        self._right_click_row(1, choose='remove')

        self.assertEqual([0, 1, 2], dict(self.emitted)['remove_requested'])

    def test_menu_clear_emits_clear_playlist_requested(self):
        """Clear is not target-scoped: no payload, just the request.

        ``targets`` must not ride along on this one -- a batch right-click that
        happens to land on row 4 still means "empty the playlist", and forwarding
        ``[4]`` would read as "remove row 4" to the presenter (Task 5).
        """
        self._select(0, 1, 2)
        self._right_click_row(1, choose='clear')

        self.assertEqual(['context_menu_requested', 'clear_playlist_requested'],
                         self._names())
        self.assertEqual([('clear_playlist_requested', None)], self.emitted[-1:])

    def test_menu_play_after_narrowing_emits_only_the_cursor_row(self):
        """The two halves compose: a narrowed target is what gets emitted."""
        self._select(0, 1, 2)
        self._right_click_row(4, choose='play')

        self.assertEqual([4], dict(self.emitted)['play_requested'])

    def test_cancelled_menu_emits_no_action_signal(self):
        """``exec()`` returning ``None`` (Escape, or a click outside) acts on nothing.

        Only the request is reported. Dispatching the first entry here would make
        a dismissed menu perform an action, and an unguarded ``action.data()``
        would raise.
        """
        self._select(0, 1)
        self._right_click_row(0, choose=None)

        self.assertEqual(['context_menu_requested'], self._names())

    def test_context_menu_requested_emitted(self):
        """The signal batch 1 declared and nobody ever emitted now has a producer.

        Payload is ``targets[0]`` plus the live event. With a one-row selection the
        two coincide, so this test only pins that one popup reports one request; what
        ``targets[0]`` means for a batch is
        :meth:`test_context_menu_requested_payload_is_the_batch_minimum`, and who may
        listen at all is :meth:`test_context_menu_requested_has_no_production_consumer`.
        """
        self._select(2)
        snapshot = self._right_click_row(2)

        self.assertEqual(['context_menu_requested'], self._names())
        self.assertEqual(2, dict(self.emitted)['context_menu_requested'])
        self.assertEqual(1, snapshot['shown'], 'one popup, one request')

    def test_context_menu_requested_payload_is_the_batch_minimum(self):
        """The payload names the batch, not the cursor (spec §4.3's inside rule).

        A cursor that is already inside the selection keeps the selection, so
        ``targets`` is the whole batch and ``targets[0]`` is its **smallest display
        index**. Here the press is on row 4 of the batch [1, 3, 4]: an implementation
        that emitted the row the user pointed at would report ``4`` here and the
        comment at ``PlaylistView.contextMenuEvent`` would be the only thing saying
        otherwise. ``tests/tools/render_matrix.py`` pins the same shape independently.
        """
        self._select(1, 3, 4)

        self._right_click_row(4)

        self.assertEqual(['context_menu_requested'], self._names())
        self.assertEqual(1, dict(self.emitted)['context_menu_requested'],
                         'a right-click inside a batch reports the batch minimum, '
                         'not the cursor row')
        self.assertEqual([1, 3, 4], self.view.selected_display_indices(),
                         'and the batch itself must be the one the menu was built for')

    def test_context_menu_requested_has_no_production_consumer(self):
        """The hook is observation-only, and that is now a checked claim (ruling R9).

        R9's defect shape is a signal that is "emitted and connected, landing
        nowhere, all green". ``PlaylistView`` now says in its own comment that this
        one is a deliberate observation hook with no production slot -- so the two
        ways it could rot are both machine-checked here:

        * a production slot appears and the comment goes stale (or a second,
          undocumented consumer starts acting on a payload whose shape this class
          pins for observers only);
        * the automated listeners stop connecting, and the signal becomes emitted
          for nobody -- the shape ``tests/test_dead_code_removed.py`` pins its
          survival against.

        Scanned as text because the consumers are in another package: an import-time
        graph walk would need every module imported, and a ``getattr``-style indirect
        connect is already covered -- the scan looks for the signal *name* anywhere
        in a production file and reports what it finds.
        """
        root = Path(__file__).resolve().parent.parent
        production_dirs = ('core', 'presenter', 'service', 'view', 'tui')
        production_files = [root / 'main.py']
        for name in production_dirs:
            production_files.extend(sorted((root / name).rglob('*.py')))

        # The two lines that may *execute* on the signal in production are its
        # declaration and its emit; a comment may name it (that is the record), but
        # anything else -- above all a ``connect`` -- is a new consumer.
        allowed = ('context_menu_requested = pyqtSignal',
                   'self.context_menu_requested.emit(')
        unexpected = []
        for path in production_files:
            text = path.read_text(encoding='utf-8', errors='replace')
            for number, line in enumerate(text.splitlines(), 1):
                if 'context_menu_requested' not in line:
                    continue
                if line.lstrip().startswith('#'):
                    continue
                if not any(marker in line for marker in allowed):
                    unexpected.append(
                        f'{path.relative_to(root)}:{number}: {line.strip()}')

        self.assertEqual([], unexpected,
                         'a production file consumes context_menu_requested: the '
                         '"observation hook, no slot" record in PlaylistView and in '
                         'tests/test_dead_code_removed.py must be rewritten first')

        # And the recorded listeners really are listening, or the hook observes nothing.
        for listener in (Path(__file__).resolve(),
                         root / 'tests' / 'tools' / 'render_matrix.py'):
            self.assertIn('context_menu_requested.connect',
                          listener.read_text(encoding='utf-8', errors='replace'),
                          f'{listener.name} no longer connects to the hook, so the '
                          'right-click routing it exists to witness is unmeasured')

    def test_play_and_pause_share_the_play_id(self):
        """The toggle reads Pause over the playing row but stays ``MENU_PLAY``.

        Labels and ids are read off the menu *while it is open*, from the seam, so
        ``PlaylistView._is_playing_index_in`` cannot quietly always answer False
        (the menu would keep saying Play over the playing track) and a Pause item
        cannot invent a fourth signal Task 5 would have to guess at.
        """
        from core import i18n

        self._select(2)
        stopped = self._right_click_row(2)
        self._set_playing(2)
        playing = self._right_click_row(2)

        self.assertEqual('play', stopped['ids'][0])
        self.assertEqual('play', playing['ids'][0],
                         'pause is the same action in another state, not a new id')
        self.assertEqual(i18n.get('ctx.play'), stopped['labels'][0])
        self.assertEqual(i18n.get('ctx.pause'), playing['labels'][0],
                         'the playing row must be offered Pause')

    # -- lifecycle (ruling R7) -------------------------------------------

    def _live_menus(self) -> list:
        from PyQt6.QtWidgets import QMenu

        return self.view.findChildren(QMenu)

    def test_repeated_right_clicks_leave_no_menu_behind(self):
        """Ruling R7: a menu is built per right-click, so it must also die per
        right-click. Nothing else in the suite can see this leak --
        ``tests/test_view_structure.py:414`` builds a fresh ``MainWindow`` and never
        right-clicks, so a view that grew one ``QMenu`` per click stayed green.

        Asserts zero rather than "count does not grow" because the *live tree* is
        what batch 2's structure contract walks: a menu built once and reused
        forever also stops the counter growing, but it keeps a ``QMenu`` in the
        window tree between clicks and would turn ``:414`` red the moment a test
        right-clicks inside a ``MainWindow``.
        """
        self.assertEqual([], self._live_menus(), 'no menu before any click')

        first = self._right_click_row(1)
        after_first = len(self._live_menus())
        second = self._right_click_row(2)
        after_second = len(self._live_menus())

        # ``deleteLater()`` defers to the event loop, and -- measured on this host
        # -- ``QApplication.processEvents()`` does NOT run deferred deletes: only
        # the targeted flush ``QEventLoop::exec()`` performs when it unwinds does.
        # This line stands in for "control returned to the event loop".
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

        live = self._live_menus()
        self.assertEqual(0, len(live),
                         f'{len(live)} QMenu(s) still parented to the view after two '
                         'open/close cycles: every right-click leaks one menu '
                         '(ruling R7). Pending counts were '
                         f'{after_first} then {after_second}.')

    def test_a_right_click_inside_the_main_window_leaves_no_menu_in_its_tree(self):
        """The other half of ruling R7: batch 2's structure guard must stay true.

        ``tests/test_view_structure.py:414`` asserts the live ``MainWindow`` tree
        holds no ``QMenu``, but it builds a fresh window and never right-clicks, so
        it cannot see a per-click leak. Here the same assertion runs *after* a right
        click: a menu that survived the popup would trip the contract the next
        batch's structure census depends on.
        """
        from PyQt6.QtWidgets import QMenu

        from view.main_window import MainWindow
        from view.widgets.playlist_view import PlaylistView

        window = MainWindow(self.manager)
        try:
            window.resize(900, 600)
            window.show()
            self.app.processEvents()

            hosted = window.findChild(PlaylistView)
            hosted.set_entries(make_entries(3))
            self.app.processEvents()

            rect = hosted._list_view.visualRect(hosted._model.index(1))
            snapshot = self._right_click(
                hosted._list_view.viewport(),
                QPoint(rect.center().x(), rect.bottom() - 1))
            self.assertEqual(1, snapshot['shown'],
                             'the wiring must work inside a real window too')
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

            self.assertEqual([], window.findChildren(QMenu),
                              'the window tree must be menu-free again')
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_the_menu_is_rebuilt_for_the_new_target(self):
        """The disposal must not cost correctness: each click shows its own menu."""
        from view.widgets.playlist_context_menu import MENU_REMOVE

        self._select(0, 1, 2)
        batch = self._right_click_row(1)
        single = self._right_click_row(4)

        self.assertEqual(2, batch['shown'] + single['shown'])
        self.assertEqual([0, 1, 2], batch['targets'])
        self.assertEqual([4], single['targets'])
        self.assertIn(MENU_REMOVE, single['ids'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
