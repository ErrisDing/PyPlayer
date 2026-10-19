#!/usr/bin/env python3
"""批次 3 Task 6：主窗口的快捷键与三条转发路线。

这个文件钉的是**效果**，不是接线。批次 2 抓到过一条同形状的缺陷：rail 的动作带着一串
可用的 `Ctrl+O` 字符串、测试全绿，而实际按键什么也不做（发射端连的是 `clicked`，快捷键
激活的是 `triggered`）。所以这里的每一条断言都落在「presenter 的槽跑了 / 队列变了 /
NowPlayingStrip 复位了」上，没有一条是「存在一次 connect 调用」。

四条判据值得单独说明：

* **裁定 R10**（``test_shortcut_beats_the_focused_widget_to_the_key``）：按键投给
  **焦点控件**（`PlaylistView` 里的 `QListView`），既不投给 MainWindow，也不直接调
  QAction。Task 1 的探针测的是 `QListView.keyPressEvent` 本身，绕开了窗口级 shortcut
  派发，对这里绑什么键、是否消费按键**毫无约束力**。断言两半：① 播放/暂停恰好 emit
  一次，② `selected_display_indices()` 与当前行**一字未动**。少了 ②，「快捷键与列表
  导航双触发」这个形状（R4 当初要避免的事）在本仓测不出来。②的可失败性另由
  ``test_bare_space_is_left_to_the_list`` 做阳性对照：裸 `Space` 确实会改动选区，说明
  列表自带的 handler 是活的，只要窗口不消费按键就一定会看见它。
* **裁定 R9**（``test_clear_playlist_requested_empties_the_queue_and_reset``）：
  `clear_playlist_requested` 自 Task 3 起真的会发射，而 Task 5 的 Produces 里并没有它的
  presenter 落点——照原计划接完线，点「清空播放列表」会一路发信号然后什么也不发生。
  这条测试从 **View** 发射，要求末端是队列空 + 播放态与 `NowPlayingStrip` 复位。
* **键的字面量**：`QKeySequence('Ctrl+Space')` 这种写法而不是 `StandardKey`。本机
  offscreen 实测 `StandardKey.Quit` 解析成字符串 `"Exit"`（批次 2），走 StandardKey 的
  测试根本注不进 `QKeyEvent(Key_Q, ControlModifier)`。字面量才能让注入的按键确定性命中。
* **播放/暂停只能绑 `Ctrl+Space`**：`NativeKeyBehaviourProbeTest` 是探针（Task 1 的
  写法），打印列表在**没有任何窗口绑定**时对这些键做了什么。裸 `Space` 已被占用，
  所以留给列表；`Delete`/`Enter`/`Ctrl+A` 的原生行为也一并记录，免得后来人以为
  「快捷键本来不会和列表抢」。

装配沿用 `tests/test_playlist_actions.py`：真 `MainWindow` + 真 `QueueService`（子类只
记录调用）+ 假播放服务，服务信号经 presenter 登记的连接发出。

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_shortcuts -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PyQt6.QtCore import PYQT_VERSION_STR, QEvent, QItemSelection, \
        QItemSelectionModel, Qt
    from PyQt6.QtGui import QAction, QKeyEvent, QKeySequence, QShortcut
    from PyQt6.QtWidgets import QWidget
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from core import i18n
from service.queue_service import DisplayEntry
from tests.test_playlist_actions import RecordingQueueService, _index_path, _tracks
from tests.test_view_smoke import make_app, make_manager

CTRL = Qt.KeyboardModifier.ControlModifier
NO_MODS = Qt.KeyboardModifier.NoModifier

#: The five bindings this task installs, as the literals they are written with in
#: production. A dict rather than five constants because both the key-injection
#: tests and the ownership test need the same table, and the ownership test needs
#: to say "exactly these, no more".
SHORTCUTS = {
    'Ctrl+Space': (Qt.Key.Key_Space, CTRL),
    'Delete': (Qt.Key.Key_Delete, NO_MODS),
    'Return': (Qt.Key.Key_Return, NO_MODS),
    'Ctrl+Up': (Qt.Key.Key_Up, CTRL),
    'Ctrl+Down': (Qt.Key.Key_Down, CTRL),
}

TRACKED_SIGNALS = ('play_pause_requested', 'prev_track_requested',
                   'next_track_requested', 'play_tracks_requested',
                   'remove_tracks_requested', 'clear_playlist_requested')


def _entries(count: int) -> list:
    """``count`` flat display entries, named by row.

    Same shape as ``tests.test_playlist_selection.make_entries``: ``node_idx`` is
    offset from the display row so a helper that handed back the wrong index space
    could not pass by luck. The queue-built fixtures below keep the two spaces
    together on purpose (the removal route must be addressed in *display* rows),
    so this is only used by the standalone-view probe, where no queue is involved.
    """
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


class ShortcutHarness:
    """Real window + real presenter + real queue + fake playback, shown and focused.

    Mixed into the ``TestCase`` classes below (the reason ``test_playlist_actions``
    does it that way applies here too: each class wants a different set of cases on
    top of the same assembly). The window is *shown* and the inner ``QListView``
    holds focus, because that is the only situation in which a key press reaches a
    ``WindowShortcut`` at all -- a hidden window is not in the shortcut map's active
    window, and a test that pressed keys into ``MainWindow`` itself would prove
    nothing about routing.
    """

    def setUp(self):
        from presenter.main_presenter import MainPresenter
        from view.main_window import MainWindow

        self._previous_locale = i18n.get_current_locale()
        i18n.set_locale('zh_CN')
        self.app = make_app()

        self.view = MainWindow(make_manager())
        self.addCleanup(self.view.deleteLater)
        self.playlist = self.view._playlist_view
        self.list_view = self.playlist._list_view
        self.model = self.playlist._model
        self.strip = self.view.findChild(QWidget, 'nowPlayingStrip')
        self.assertIsNotNone(self.strip, '#nowPlayingStrip must be in the shell')

        self.queue = RecordingQueueService()
        self.playback = mock.MagicMock(name='playback_service')
        self.playback.get_volume.return_value = 0.5
        self.playback.current_track = None
        self.library = mock.MagicMock(name='library_service')
        self.metadata = mock.MagicMock(name='metadata_service')
        self.config = mock.MagicMock(name='config_service')
        self.config.get_libraries.return_value = []
        self.config.get_background_image.return_value = None
        self.config.get_theme.return_value = 'light'
        self.config.get_overlay_alpha.return_value = 0.3
        self.config.get_playlist_alpha.return_value = 0.5
        self.config.get_controls_alpha.return_value = 0.6

        self.presenter = MainPresenter(
            view=self.view,
            playback_service=self.playback,
            queue_service=self.queue,
            library_service=self.library,
            metadata_service=self.metadata,
            config_service=self.config,
        )

        self.view.resize(900, 600)
        self.view.show()
        self.view.activateWindow()
        self.app.processEvents()
        self._focus_list()

    def tearDown(self):
        self.view.close()
        self.app.processEvents()
        i18n.set_locale(self._previous_locale)

    # === driving keys the way the keyboard does ===

    def _focus_list(self) -> None:
        """Put focus where the user has it -- the list -- and prove it landed."""
        self.list_view.setFocus()
        self.app.processEvents()
        self.assertIs(
            self.app.focusWidget(), self.list_view,
            'the harness lost focus: a key posted to a widget that is not the '
            'focus widget is not the route this task is about (ruling R10)',
        )

    def _press(self, key: int, mods=NO_MODS) -> bool:
        """Send one key press to the **focused widget**; return ``isAccepted()``.

        Deliberately ``app.sendEvent`` to ``self.list_view`` and not to the window:
        ``QApplication::notify`` runs shortcut dispatch for a key press before it
        hands the event to the receiver, which is exactly the race ruling R10 says
        must be decided in the shortcut's favour.

        The returned flag is **not** proof of consumption on this host, measured: a
        press eaten by a window ``QAction`` still reports ``isAccepted() == False``
        here (Qt resolves shortcuts against the window's own state and never marks
        the injected event), while a press the view itself handled reports ``True``.
        So no test below asserts on it; consumption is proved by the observable
        consequence -- the selection and the current row coming back unchanged.
        """
        event = QKeyEvent(QEvent.Type.KeyPress, key, mods)
        event.setAccepted(False)
        self.app.sendEvent(self.list_view, event)
        self.app.processEvents()
        return event.isAccepted()

    # === driving data the way the services do ===

    def _load(self, count: int) -> None:
        """Build a flat queue of ``count`` tracks and prove the view followed."""
        self.queue.build_from_tracks(_tracks(count))
        self.assertEqual(count, len(self.queue.get_display_entries()))
        self.assertEqual(count, self.model.rowCount(),
                         'the queue never reached the visible list')

    def _select(self, rows: list) -> None:
        """Make ``rows`` the selection, with the middle of them current.

        Through the selection model rather than synthetic clicks: Task 1 pinned the
        mouse/modifier semantics over in ``test_playlist_selection``, and this file
        is about what a *key* does to a selection that already exists.

        The current row is set **before** the batch: measured here, and the reason
        the order is load-bearing, is that ``QAbstractItemView::setCurrentIndex``
        runs ``selectionCommand()`` without an event, which answers
        ``ClearAndSelect`` -- so setting it afterwards collapses whatever batch was
        just made. ``select()`` never touches the current index, so the two steps
        survive each other in this order only.
        """
        if rows:
            self.list_view.setCurrentIndex(self.model.index(rows[len(rows) // 2]))
        selection = QItemSelection()
        for row in rows:
            selection.select(self.model.index(row), self.model.index(row))
        self.list_view.selectionModel().select(
            selection,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows)
        self.app.processEvents()
        self.assertEqual(sorted(rows), self.playlist.selected_display_indices(),
                         'the fixture lost the selection')

    def _play(self, display_idx: int):
        """Start row ``display_idx``: position, then the strip via the presenter."""
        track = self.queue.set_position_by_display_index(display_idx)
        self.assertIsNotNone(track, f'row {display_idx} is not playable')
        signal = self.playback.track_changed
        receivers = [call.args[0] for call in signal.connect.call_args_list]
        self.assertTrue(receivers, 'nothing is connected to track_changed')
        for receiver in receivers:
            receiver(track)
        return track

    def _forget_calls(self) -> None:
        self.queue.calls.clear()

    # === reading the window's side of the route ===

    def _record(self) -> dict:
        """Attach one recorder per View API signal, after the presenter's connect.

        Connected *after* ``MainPresenter.__init__`` on purpose: the presenter's slot
        runs first, so a recorder that saw nothing can only mean the emit never
        happened -- not that a slot swallowed it.
        """
        recorded = {name: [] for name in TRACKED_SIGNALS}
        for name, sink in recorded.items():
            signal = getattr(self.view, name, None)
            self.assertIsNotNone(
                signal, f'MainWindow has no {name}: the View API is missing')
            signal.connect(self._recorder(sink))
        return recorded

    @staticmethod
    def _recorder(sink):
        """Append the single payload for a value signal, ``True`` for a bare one.

        The recorder keeps the *arguments*, not the tuple around them, so an
        assertion reads as ``[[0, 2, 4]]`` -- the batch the View API is supposed to
        carry -- instead of a tuple-wrapped copy of it.
        """
        def record(*args):
            sink.append(args[0] if len(args) == 1 else True)
        return record

    # === reading state back ===

    def _queue_paths(self) -> list:
        return [entry.full_path for entry in self.queue.get_display_entries()]

    def _current_row(self) -> int:
        """The view's current row, or ``-1`` when nothing is current.

        ``QListView`` has no ``currentRow()`` -- that is a ``QListWidget``
        convenience -- so the row comes off ``currentIndex()`` (Task 1's note).
        """
        return self.list_view.currentIndex().row()

    def _playing_row_path(self):
        row = self.model.get_playing_index()
        if row < 0:
            return None
        entry = self.playlist.get_entry_at(row)
        return None if entry is None else entry.full_path


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PlayPauseShortcutTest(ShortcutHarness, unittest.TestCase):
    """Ruling R10: the window's binding answers the key, and the list never sees it."""

    def test_play_pause_shortcut(self):
        """``Ctrl+Space`` -> ``play_pause_requested`` exactly once.

        ``Ctrl+Space`` and not ``Space`` because Task 1 measured the bare key as
        already taken by the view (spec §4.4), and this host still says so --
        :class:`NativeKeyBehaviourProbeTest` re-measures it. The effect half is the
        presenter's: with the engine playing and not paused, the honest outcome of
        a play/pause request is ``pause()``, so this checks the slot ran rather
        than that a signal exists.
        """
        self._load(5)
        self.playback.is_playing = True
        self.playback.is_paused = False
        self._select([2])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Ctrl+Space'])

        self.assertEqual(1, len(recorded['play_pause_requested']),
                         'Ctrl+Space must reach play_pause_requested exactly once; '
                         'twice means the view and the window both answered (R4)')
        self.assertTrue(self.playback.pause.called,
                        'the signal fired but no presenter slot ran -- batch 2\'s '
                        'inert-shortcut shape')
        self.assertFalse(self.playback.play.called)

    def test_shortcut_beats_the_focused_widget_to_the_key(self):
        """Ruling R10, both halves, at the focused widget.

        ① the play/pause signal fires once, and ② the selection and the current row
        come back **byte for byte unchanged**. ② is the half that pins consumption:
        the view's own handler for ``Ctrl+Space`` is the same one Task 1 measured for
        bare ``Space`` (it walks the cursor and replaces the selection with that row),
        so a binding that fires without eating the key would show up here as a moved
        cursor -- a shape no other test in this repo can see.
        """
        self._load(5)
        self._select([0, 2, 4])
        before_selection = self.playlist.selected_display_indices()
        before_row = self._current_row()
        self.assertEqual([0, 2, 4], before_selection)
        self.assertEqual(2, before_row, 'fixture: the middle of the batch is current')

        recorded = self._record()
        self._press(*SHORTCUTS['Ctrl+Space'])

        # The consumption half is asserted **first**, on purpose: a binding that fires
        # without eating the key -- the shape ruling R4 exists to prevent -- then fails
        # here, on the half that names it, instead of behind the emission count.
        self.assertEqual(
            before_selection, self.playlist.selected_display_indices(),
            'the list moved, so the press was not consumed by the shortcut -- both '
            'the window and QListView answered one key (see also '
            'test_bare_space_is_left_to_the_list for the positive control)',
        )
        self.assertEqual(
            before_row, self._current_row(),
            'the current row moved, so the press still reached QListView after the '
            'shortcut ran')
        self.assertEqual(1, len(recorded['play_pause_requested']),
                         'Ctrl+Space must reach play_pause_requested exactly once')
        for name in TRACKED_SIGNALS:
            if name != 'play_pause_requested':
                self.assertEqual([], recorded[name],
                                 f'{name} must not answer Ctrl+Space')

    def test_bare_space_is_left_to_the_list(self):
        """The other half of R4: the bare key stays the list's.

        Positive control for the test above. Nothing is bound to bare ``Space``, so
        the view's own handler must run and must visibly change the selection -- if
        this ever goes green while the test above also passes, the "unchanged"
        assertion has stopped measuring anything.
        """
        self._load(5)
        self._select([0, 1, 2])
        before = self.playlist.selected_display_indices()

        recorded = self._record()
        self._press(Qt.Key.Key_Space)

        self.assertEqual([], recorded['play_pause_requested'],
                         'bare Space was bound: spec §4.4 gives it to list navigation')
        self.assertNotEqual(
            before, self.playlist.selected_display_indices(),
            'the list stopped reacting to Space -- the positive control below the '
            '"selection unchanged" assertion is gone (see spec §4.4)',
        )


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not available')
class BatchActionShortcutTest(ShortcutHarness, unittest.TestCase):
    """``Delete`` and ``Enter``: the keyboard route must reach the queue.

    Both go through the **view's** signals and MainWindow's forwards, not through a
    second index-computation path bolted onto the window: the selection's meaning is
    ``PlaylistView``'s to decide (plan Architecture: 选择与索引解析留在 PlaylistView),
    and one route means the context menu and the keyboard cannot drift apart. The
    practical consequence a reviewer should notice is that deleting the
    view -> window forward breaks these tests, which is the point.
    """

    def test_delete_removes_selection(self):
        """Multi-select, press Delete: payload ascending, and the queue shrank.

        The payload is the whole batch (spec §4.2 hands the sorting to the removal
        loop) and the effect is the interleaved removal of Task 5 -- rows 0/2/4 out
        of five leave 1/3, reached in descending order.
        """
        self._load(5)
        self._select([0, 2, 4])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Delete'])

        self.assertEqual([[0, 2, 4]], recorded['remove_tracks_requested'],
                         'Delete must hand remove_tracks_requested the ascending '
                         'selection (spec §5)')
        self.assertEqual([_index_path(1), _index_path(3)], self._queue_paths(),
                         'the signal fired but the queue never changed')
        self.assertEqual([4, 2, 0], self.queue.removals(),
                         'descending into remove_at_display_index (spec §4.2)')
        self.assertEqual(2, self.model.rowCount(),
                         'the visible list did not follow the queue')

    def test_delete_with_an_empty_selection_does_nothing(self):
        """spec §7: 选区为空时不产生调用——空列表不得进 presenter 再靠循环兜底."""
        self._load(5)
        self._select([])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Delete'])

        self.assertEqual([], recorded['remove_tracks_requested'])
        self.assertEqual([], self.queue.calls,
                         'an empty selection reached the queue')
        self.assertEqual(5, self.model.rowCount())

    def test_enter_plays_selection(self):
        """``Enter`` plays the **smallest** selected display index, not the last click.

        The View API payload is ``[min]`` (the brief fixes it): ``Enter`` names one
        row to start from. ``playback.play`` receiving that row's path is the proof
        the request landed on Task 5's handler and on the double-click route.
        """
        self._load(5)
        self._select([1, 2, 4])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Return'])

        self.assertEqual([[1]], recorded['play_tracks_requested'],
                         'Enter must hand play_tracks_requested the lowest selected '
                         'display index (spec §5)')
        self.playback.play.assert_called_once_with(_index_path(1))
        self.assertEqual(1, self.queue.get_current_position().display_index)
        self.assertEqual(_index_path(1), self._playing_row_path())

    def test_enter_with_an_empty_selection_does_nothing(self):
        """Same rule as Delete: no rows, no request, and no accidental play."""
        self._load(5)
        self._select([])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Return'])

        self.assertEqual([], recorded['play_tracks_requested'])
        self.playback.play.assert_not_called()
        self.assertEqual([], self.queue.calls)

    def test_the_forwards_carry_the_view_signals(self):
        """The right-click route uses the same two forwards as the keys.

        Emitted from the ``PlaylistView`` itself, the way ``contextMenuEvent`` does
        after a menu entry is clicked, with a batch that is *not* what the view's
        own ``Enter`` would produce (three rows for play, so the payload must reach
        the presenter whole and be reduced there).
        """
        self._load(5)
        self._select([1, 2, 4])
        self._forget_calls()

        recorded = self._record()
        self.playlist.play_requested.emit([1, 2, 4])

        self.assertEqual([[1, 2, 4]], recorded['play_tracks_requested'],
                         'PlaylistView.play_requested is not forwarded')
        self.playback.play.assert_called_once_with(_index_path(1))

        self._forget_calls()
        self.playlist.remove_requested.emit([0, 3])
        self.assertEqual([[0, 3]], recorded['remove_tracks_requested'],
                         'PlaylistView.remove_requested is not forwarded')
        self.assertEqual([_index_path(1), _index_path(2), _index_path(4)],
                         self._queue_paths())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not available')
class NavigationShortcutTest(ShortcutHarness, unittest.TestCase):
    """``Ctrl+Up``/``Ctrl+Down`` and the untouched ``Ctrl+A`` / bare arrows."""

    def test_ctrl_up_down_trigger_prev_next(self):
        """Each key reaches its window signal once *and* moves the real queue.

        Asserted on the engine call, not on a connect: with five flat rows and row
        2 playing, prev is T1 and next is T2 -- a signal that fired into nothing
        would leave ``play()`` uncalled (the batch 2 defect shape).
        """
        self._load(5)
        self._play(2)
        self._select([2])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Ctrl+Up'])
        self.assertEqual(1, len(recorded['prev_track_requested']),
                         'Ctrl+Up must reach prev_track_requested exactly once')
        self.assertEqual([], recorded['next_track_requested'])
        self.assertEqual(1, self.queue.get_current_position().display_index,
                         'the queue position did not move back')

        self._press(*SHORTCUTS['Ctrl+Down'])
        self.assertEqual(1, len(recorded['next_track_requested']),
                         'Ctrl+Down must reach next_track_requested exactly once')
        self.assertEqual(1, len(recorded['prev_track_requested']),
                         'Ctrl+Down must not answer as prev')
        played = [call.args[0] for call in self.playback.play.call_args_list]
        self.assertEqual([_index_path(1), _index_path(2)], played,
                         'prev/next must reach the engine with the right tracks')

    def test_plain_up_down_still_navigates_the_list(self):
        """Review Focus 5 / spec §5: the bare arrows stay the list's.

        The current row must move and prev/next must stay silent. This is the
        judgement criterion the plan names, not a bonus: a window binding that
        swallows the bare arrows would leave the list unusable by keyboard.
        """
        self._load(5)
        self._select([2])
        before = self._current_row()

        recorded = self._record()
        self._press(Qt.Key.Key_Down)
        after_down = self._current_row()
        self.assertEqual(before + 1, after_down,
                         'bare Down stopped navigating the list')
        self._press(Qt.Key.Key_Up)
        self.assertEqual(before, self._current_row(),
                         'bare Up stopped navigating the list')

        self.assertEqual([], recorded['prev_track_requested'])
        self.assertEqual([], recorded['next_track_requested'],
                         'the bare arrows were hijacked (spec §5: 不劫持)')

    def test_ctrl_a_selects_all(self):
        """``Ctrl+A`` is Qt's own; this only confirms the native route still works.

        Deliberately *no* QAction for it: spec §5 says 原生, and a window binding on
        the same key would consume the press before the view's ``selectAll()``.
        Asserted together with "no batch signal fired", because a stray binding on
        Ctrl+A that only selected rows would otherwise pass unnoticed.
        """
        self._load(5)
        self._select([1])
        self._forget_calls()

        recorded = self._record()
        self._press(Qt.Key.Key_A, CTRL)

        self.assertEqual([0, 1, 2, 3, 4], self.playlist.selected_display_indices(),
                         'Ctrl+A no longer selects every row')
        self.assertEqual([], recorded['remove_tracks_requested'])
        self.assertEqual([], recorded['play_tracks_requested'])
        self.assertEqual([], self.queue.calls)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not available')
class ClearPlaylistRouteTest(ShortcutHarness, unittest.TestCase):
    """Ruling R9: ``clear_playlist_requested`` must have a presenter landing."""

    def test_clear_playlist_requested_empties_the_queue_and_reset(self):
        """Emit from the View -> queue empty -> playback and strip reset.

        Every assertion is on the far end of the route: the entries are gone from
        the service *and* the visible model, no row keeps the playing highlight,
        the strip is back to its empty-state copy, the engine was stopped, and the
        queue's own position is -1 rather than a node index into an empty list
        (``clear()`` is the only existing API that resets it -- R8).
        """
        self._load(3)
        playing = self._play(1)
        self.assertEqual(playing.title, self.strip._title_text)
        self._forget_calls()

        recorded = self._record()
        self.playlist.clear_playlist_requested.emit()

        self.assertEqual(1, len(recorded['clear_playlist_requested']),
                         'MainWindow does not forward the view signal (R9)')
        self.assertEqual([], self._queue_paths(), 'the queue is not empty')
        self.assertEqual(0, self.model.rowCount(),
                         'the visible list did not follow the cleared queue')
        self.assertEqual(-1, self.model.get_playing_index(),
                         'a row still carries the playing highlight')
        self.assertEqual(i18n.get('metadata.no_track'), self.strip._title_text,
                         'NowPlayingStrip was not reset')
        self.assertTrue(self.playback.stop.called,
                        'the engine is still playing a queue that no longer exists')
        self.assertEqual(-1, self.queue.get_current_position().node_index,
                         'R8: only clear() resets the position; a stale index into '
                         'an emptied node list is one advance_to_next() from trouble')
        self.assertIn(('clear',), self.queue.calls,
                      'the landing must reuse the existing _queue.clear() path')
        self.assertFalse(self.playback.play.called)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not available')
class ShortcutOwnershipTest(ShortcutHarness, unittest.TestCase):
    """spec §5 / 判据: the bindings live on ``MainWindow``, nowhere else."""

    def test_shortcuts_are_owned_by_the_main_window(self):
        """Each key is carried by exactly one action, parented and added to the window.

        ``addAction`` is what keeps a shortcut alive with no menu bar (batch 2 §6,
        and the reason ``Ctrl+Q`` already lives on the window here): an action that
        is only constructed and never added to a widget is reachable by nothing.
        The count is ``== 1`` per sequence, so a second widget binding the same key
        -- the "归属再次分散" risk spec §10 names -- fails instead of passing twice.
        """
        holders = {}
        for action in self.view.findChildren(QAction):
            for sequence in action.shortcuts():
                holders.setdefault(QKeySequence(sequence), []).append(action)

        window_actions = list(self.view.actions())
        for literal in SHORTCUTS:
            with self.subTest(shortcut=literal):
                found = holders.get(QKeySequence(literal), [])
                self.assertEqual(1, len(found),
                                 f'{literal} must be bound exactly once, on the '
                                 f'window: found {len(found)}')
                action = found[0]
                self.assertIs(self.view, action.parent(),
                              f'the {literal} binding is not parented to MainWindow '
                              f'(owned by {action.parent()!r})')
                self.assertIn(action, window_actions,
                              f'{literal} was never added to the window, so it is '
                              'alive only as long as something else holds it')
                self.assertTrue(action.isEnabled(),
                                f'{literal} is disabled, so the press is not consumed')

    def test_the_widgets_bind_no_shortcuts_of_their_own(self):
        """``PlaylistView`` and ``BottomPanel`` must not carry key bindings.

        The rail is exempt on purpose: ``ActionRail`` owns its ``Ctrl+O`` and
        ``tests/test_action_rail.py`` pins it there (batch 2's design). This guard
        is about the two widgets this task touched, and about ``QShortcut`` objects,
        the other way a binding can appear inside a widget.
        """
        for widget, name in ((self.playlist, 'PlaylistView'),
                             (self.view._bottom_panel, 'BottomPanel')):
            with self.subTest(widget=name):
                self.assertEqual(
                    [], [action.objectName() for action in widget.actions()
                         if action.shortcuts()],
                    f'{name} carries its own key binding; spec §5 puts every '
                    f'shortcut in MainWindow._setup_shortcuts()')
                self.assertEqual(
                    [], widget.findChildren(QShortcut),
                    f'{name} installs a QShortcut')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not available')
class OutsideTheListTest(ShortcutHarness, unittest.TestCase):
    """The plan's stated intent for the ``Delete``/``Enter`` context.

    Step 2 asks for ``WidgetWithChildrenShortcut`` on those two "避免在列表外误触发".
    These tests measure whether that intent actually holds on this host, and pin it
    either way: focus on a control-bar slider, and focus in a ``QLineEdit`` inside a
    dialog parented to the window -- the shape that would eat the keys a user types
    into the library or appearance dialogs.
    """

    def test_delete_outside_the_playlist_does_not_remove(self):
        """Delete with focus on the control bar's volume slider must do nothing.

        The slider is the honest probe: it takes focus, it is in the window, and it
        is not in the playlist's subtree -- which is what Step 2's
        ``WidgetWithChildrenShortcut`` is supposed to mean. If the binding turns out
        to answer from anywhere in the window, this test says so and the scope is
        fixed rather than reworded.
        """
        from PyQt6.QtWidgets import QSlider

        self._load(5)
        self._select([0, 1])
        self._forget_calls()

        slider = self.view.findChild(QSlider, 'volumeSlider')
        self.assertIsNotNone(slider, '#volumeSlider must be in the shell')
        slider.setFocus()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), slider,
                      'fixture: focus is off the list')

        recorded = self._record()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, NO_MODS)
        event.setAccepted(False)
        self.app.sendEvent(slider, event)
        self.app.processEvents()

        self.assertEqual([], recorded['remove_tracks_requested'],
                         'Delete outside the playlist still reached the batch route')
        self.assertEqual([], self.queue.calls)
        self.assertEqual([0, 1], self.playlist.selected_display_indices(),
                         'the batch the key would have acted on changed anyway')

    def test_enter_inside_a_child_dialog_is_not_eaten(self):
        """A dialog parented to the window keeps its own Enter.

        The dialog is a *separate window* in the object tree, so ``isAncestorOf``
        stops at its edge (measured in batch 2) -- which is precisely why a
        window-level ``WidgetWithChildrenShortcut`` must not steal keys from it. If
        it ever does, typing Enter in a dialog would play the playlist instead of
        accepting the dialog.
        """
        from PyQt6.QtWidgets import QDialog, QLineEdit

        self._load(5)
        self._select([0, 1])
        self._forget_calls()

        dialog = QDialog(self.view)
        self.addCleanup(dialog.deleteLater)
        editor = QLineEdit(dialog)
        editor.setText('C:/media')
        dialog.show()
        editor.setFocus()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), editor,
                      'fixture: the dialog line edit does not hold focus')

        recorded = self._record()
        for key, mods in ((Qt.Key.Key_Return, NO_MODS), (Qt.Key.Key_Delete, NO_MODS)):
            event = QKeyEvent(QEvent.Type.KeyPress, key, mods)
            event.setAccepted(False)
            self.app.sendEvent(editor, event)
            self.app.processEvents()

        self.assertEqual([], recorded['play_tracks_requested'],
                         'Enter typed in a dialog reached the playlist')
        self.assertEqual([], recorded['remove_tracks_requested'],
                         'Delete typed in a dialog reached the playlist')
        self.assertEqual([0, 1], self.playlist.selected_display_indices(),
                         'the selection the dialog keys would have acted on moved')
        self.assertTrue(dialog.isVisible(),
                        'the dialog lost its window to a window-level shortcut')
        dialog.close()


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class NativeKeyBehaviourProbeTest(unittest.TestCase):
    """A probe, not a guard: what the list does with **no window binding** at all.

    Same role as Task 1's ``test_space_default_behaviour_probe``. Nothing here is
    bound, so every line is the bare ``QListView`` answer -- the facts that make the
    bindings above necessary rather than a matter of taste. Spec §4.4 forbids
    assuming the ``Space`` answer; this file refuses to assume the others either,
    and records them for the report.
    """

    def setUp(self):
        self.app = make_app()
        self.manager = make_manager()

    def _view(self, count: int = 3, current_row: int = 0,
              pre_select=(0, 1, 2)):
        from view.widgets.playlist_view import PlaylistView

        view = PlaylistView(self.manager)
        view.resize(400, 300)
        view.set_entries(_entries(count))
        view.show()
        self.app.processEvents()
        view._list_view.setFocus()
        view._list_view.setCurrentIndex(view._model.index(current_row))
        selection = QItemSelection()
        for row in pre_select:
            selection.select(view._model.index(row), view._model.index(row))
        view._list_view.selectionModel().select(
            selection,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows)
        self.app.processEvents()
        self.addCleanup(view.deleteLater)
        return view

    def _one_press(self, view, key, mods):
        removed = []
        original = view._model.removeRows

        def counting(count, row, parent=None):
            removed.append((count, row))
            return original(count, row, parent)

        view._model.removeRows = counting
        activated = []
        view._list_view.doubleClicked.connect(
            lambda index: activated.append(index.row()))
        event = QKeyEvent(QEvent.Type.KeyPress, key, mods)
        event.setAccepted(False)
        self.app.sendEvent(view._list_view, event)
        self.app.processEvents()
        return event.isAccepted(), removed, activated

    def test_probe_native_key_behaviour(self):
        """Print, then pin: Space (both forms), Delete, Enter, Ctrl+A, Ctrl+arrows.

        ``QListView`` has no ``removeRows`` support in ``PlaylistModel`` (a
        ``QAbstractListModel`` that never implements it), so the native Delete must
        leave the rows standing -- the reason the window has to bind the key to do
        the removal itself, and not assume Qt will do it.

        Two pre-conditions, not one: the arrow cases start on row 1 with row 1
        alone selected, because from row 0 ``Up`` has nowhere to go and from an
        all-selected list ``Ctrl+A`` cannot show anything. A probe that cannot fail
        is not a measurement.
        """
        cases = (
            # name, key, mods, current row, pre-selection
            ('Space', Qt.Key.Key_Space, NO_MODS, 0, (0, 1, 2)),
            ('Ctrl+Space', Qt.Key.Key_Space, CTRL, 0, (0, 1, 2)),
            ('Delete', Qt.Key.Key_Delete, NO_MODS, 0, (0, 1, 2)),
            ('Enter', Qt.Key.Key_Return, NO_MODS, 0, (0, 1, 2)),
            ('Ctrl+A', Qt.Key.Key_A, CTRL, 1, (1,)),
            ('Ctrl+Up', Qt.Key.Key_Up, CTRL, 1, (1,)),
            ('Ctrl+Down', Qt.Key.Key_Down, CTRL, 0, (0,)),
            ('Up', Qt.Key.Key_Up, NO_MODS, 1, (1,)),
        )
        observations = []
        for name, key, mods, current_row, pre_select in cases:
            view = self._view(current_row=current_row, pre_select=pre_select)
            before = (view.selected_display_indices(),
                      view._list_view.currentIndex().row(), view._model.rowCount())
            self.assertEqual([*pre_select], before[0], f'{name}: fixture drifted')
            self.assertEqual(current_row, before[1], f'{name}: fixture drifted')
            accepted, removed, activated = self._one_press(view, key, mods)
            after = (view.selected_display_indices(),
                     view._list_view.currentIndex().row(), view._model.rowCount())
            observations.append({
                'case': name, 'accepted': accepted, 'before': before,
                'after': after, 'removeRows': removed, 'doubleClicked': activated,
            })
            view.close()

        print(f'\n[Native keys] PyQt {PYQT_VERSION_STR}, standalone PlaylistView, 3 '
              f'rows, press sent to the focused QListView (no MainWindow, so no '
              f'binding):')
        for obs in observations:
            print(f"[Native keys]   {obs['case']:10s} accepted={obs['accepted']} "
                  f"sel {obs['before'][0]} -> {obs['after'][0]} "
                  f"row {obs['before'][1]} -> {obs['after'][1]} "
                  f"rows {obs['before'][2]} -> {obs['after'][2]} "
                  f"removeRows={obs['removeRows']} "
                  f"doubleClicked={obs['doubleClicked']}")
        sys.stdout.flush()

        self.assertEqual(len(cases), len(observations))
        by_case = {obs['case']: obs for obs in observations}

        # Measured, and pinned so an upgrade that changes any of them is a signal to
        # re-read this file rather than a silent drift. Both Space forms are taken by
        # the view (spec §4.4): bare Space walks the cursor 0 -> 1 and collapses the
        # batch to [1]; Ctrl+Space walks it the same way and collapses to [2] (the
        # Ctrl half changes the selection command, not the handler). Either way the
        # press is consumed and the selection moves -- which is why the window's
        # Ctrl+Space binding has to eat the key before the view sees it (ruling R10).
        space = by_case['Space']
        self.assertEqual([1], space['after'][0], 'spec §4.4 records [..] -> [1]')
        self.assertEqual(1, space['after'][1], 'spec §4.4 records current row 0 -> 1')
        self.assertTrue(space['accepted'], 'Space is not free')
        ctrl_space = by_case['Ctrl+Space']
        self.assertEqual(1, ctrl_space['after'][1],
                         'Ctrl+Space still walks the cursor, so it is the *same* '
                         'built-in handler spec §4.4 measured (1 row down)')
        self.assertNotEqual(ctrl_space['before'][0], ctrl_space['after'][0],
                            'Ctrl+Space no longer touches the selection: re-read '
                            'spec §4.4 before keeping the binding')
        self.assertTrue(ctrl_space['accepted'], 'Ctrl+Space is consumed by the view')

        delete = by_case['Delete']
        self.assertEqual(3, delete['after'][2],
                         'the native Delete does not remove rows (the model does not '
                         'implement removeRows), so the window has to bind the key')
        self.assertEqual([], delete['removeRows'],
                         'PlaylistModel suddenly answers removeRows: re-read this '
                         'probe before trusting the batch route')

        enter = by_case['Enter']
        self.assertEqual([], enter['doubleClicked'],
                         'Enter did not activate the row natively: if it ever does, '
                         'the window binding and the double-click route would both '
                         'run -- see the Task 6 report')

        self.assertEqual([0, 1, 2], by_case['Ctrl+A']['after'][0],
                         'Ctrl+A is Qt native here: the reason no QAction is bound '
                         'to it')

        for name in ('Ctrl+Up', 'Ctrl+Down', 'Up'):
            obs = by_case[name]
            self.assertNotEqual(
                obs['before'][1], obs['after'][1],
                f"{name}: the view's own cursor stopped moving -- if the arrow pair "
                f'is no longer the view\'s business, the window binding of '
                f'Ctrl+Up/Ctrl+Down is no longer an override and ruling R10 must be '
                f're-read')


if __name__ == '__main__':
    unittest.main(verbosity=2)
