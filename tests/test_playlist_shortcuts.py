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
  所以留给列表；`Delete`/`Enter`/`Ctrl+A`/小键盘 `Enter` 的原生行为也一并记录，免得
  后来人以为「快捷键本来不会和列表抢」。该探针还对照 `QListWidget` 与
  `QListView`+`PlaylistModel` 的 `Delete`（见
  :class:`NativeDeleteModelProbeTest`）：R11 把 Delete 交给视图，靠的正是
  「`PlaylistModel` 不实现 `removeRows`，所以列表不吃这个键」。
* **裁定 R11（修复回合 1）**：`Delete`/`Enter` 由 `PlaylistView.keyPressEvent` 承接，
  窗口只剩 `Ctrl+Space`/`Ctrl+↑`/`Ctrl+↓`/`Ctrl+Q`。原先那两个窗口 `QAction` 用「槽里
  判断焦点再早退」冒充范围控制——快捷键一旦匹配，按键已经被消费，早退不会把它还给焦点
  控件，于是整扇窗口的 Enter/Delete 全死（实测见 `OutsideTheListTest` 的计数与探针）。
  因此这个文件现在必须**两头**都测：列表内按键仍然走批量路线，列表外按键必须**回到焦点
  控件**。回到焦点控件这一半只能用「接收方 KeyPress 计数器」证明：本机 offscreen 下
  `QPushButton` 对合成 Enter **永远不会**给出 `pressed`/`clicked`（裸窗口、无任何绑定的
  对照同样为 0），而同一个按钮对 `Space` 给出 1/1——所以断言 `clicked` 会测出一个不存在
  的观测，阳性对照必须用 `Space`。

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
    from PyQt6.QtCore import PYQT_VERSION_STR, QEvent, QObject, QItemSelection, \
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

#: The key bindings **`MainWindow`** owns, as the literals they are written with in
#: production. A dict rather than constants because both the key-injection tests and
#: the ownership test need the same table, and the ownership test needs to say "exactly
#: these, no more". Ruling R11 took ``Delete``/``Enter`` out of this table: they are the
#: list's own keys now, and a window binding for them is the defect this file's
#: ``OutsideTheListTest`` exists to catch.
WINDOW_SHORTCUTS = {
    'Ctrl+Space': (Qt.Key.Key_Space, CTRL),
    'Ctrl+Up': (Qt.Key.Key_Up, CTRL),
    'Ctrl+Down': (Qt.Key.Key_Down, CTRL),
}

#: The keys ruling R11 answers in ``PlaylistView.keyPressEvent``, both spellings of
#: ``Enter`` included: Qt gives the main row ``Key_Return`` and the numeric keypad
#: ``Key_Enter``, and spec §5's row says ``Enter``.
LIST_KEYS = {
    'Delete': (Qt.Key.Key_Delete, NO_MODS),
    'Return': (Qt.Key.Key_Return, NO_MODS),
    'Enter': (Qt.Key.Key_Enter, NO_MODS),
}

#: Everything this file injects, for the tests that press a key and read the effect.
SHORTCUTS = {**WINDOW_SHORTCUTS, **LIST_KEYS}


TRACKED_SIGNALS = ('play_pause_requested', 'prev_track_requested',
                   'next_track_requested', 'play_tracks_requested',
                   'remove_tracks_requested', 'clear_playlist_requested')


class KeyPressCounter(QObject):
    """Counts the ``KeyPress`` events a widget is actually *delivered*.

    This is the only observable the "the key got back to the focused widget" half of
    ruling R11 can be asserted on here. A shortcut that matches consumes the press
    inside ``QApplication::notify``, before the receiver's own ``keyPressEvent`` (and
    before this filter) ever runs, so the count is 0 when the key was swallowed and 1
    when it was not -- and unlike ``event.isAccepted()`` it cannot lie (Task 6 measured
    that a press eaten by a window ``QAction`` still reports ``isAccepted() == False``).

    ``clicked`` is deliberately **not** used. Measured on this host in a bare window
    with no shortcut registered anywhere, a synthesized ``Key_Return``/``Key_Enter`` on
    a focused ``QPushButton`` produces ``pressed=0 clicked=0`` on every synthesis route
    (``QTest.keyClick``, ``QTest.keyPress``+``keyRelease``, raw ``sendEvent``), while
    ``Key_Space`` on that same button produces ``pressed=1 clicked=1``. So asserting
    ``clicked`` would assert something offscreen cannot show; the counter is paired with
    a bare-``Space`` positive control instead.
    """

    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            self.count += 1
        return False


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

    def _focus_off_list(self, widget) -> None:
        """Move the keyboard focus to ``widget`` and prove it landed.

        Same refusal as :meth:`_focus_list`: a press sent to a widget that is not the
        focus widget is not the route ruling R11 is about.
        """
        widget.setFocus()
        self.app.processEvents()
        self.assertIs(
            self.app.focusWidget(), widget,
            'the harness lost focus: this test is about the widget that HAS the '
            'keyboard, so a number read off another one proves nothing',
        )

    def _press_at(self, widget, key: int, mods=NO_MODS) -> int:
        """Press and release ``key`` on ``widget``; return what ``widget`` was handed.

        Release rides along because that is what a key press is in Qt: a button
        activates on the release, and ``QLineEdit`` only finishes some operations then.
        The return value is the receiver-side count -- 1 means the event reached the
        widget's own handling, 0 means something upstream consumed it first.
        """
        counter = KeyPressCounter()
        widget.installEventFilter(counter)
        self.addCleanup(widget.removeEventFilter, counter)
        for event_type, is_press in ((QEvent.Type.KeyPress, True),
                                     (QEvent.Type.KeyRelease, False)):
            event = QKeyEvent(event_type, key, mods)
            event.setAccepted(False)
            self.app.sendEvent(widget, event)
            self.app.processEvents()
        return counter.count

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

    Since ruling R11 these two keys are answered by ``PlaylistView.keyPressEvent``
    rather than a window ``QAction``, and **what this class asserts did not change** --
    that is the point of moving them. Both still go through the **view's** signals and
    MainWindow's forwards, not through a second index-computation path bolted onto the
    window: the selection's meaning is ``PlaylistView``'s to decide (plan Architecture:
    选择与索引解析留在 PlaylistView), and one route means the context menu and the
    keyboard cannot drift apart. The practical consequence a reviewer should notice is
    that deleting the view -> window forward breaks these tests, which is the point.

    The press is injected at the inner ``QListView`` because that is where the keyboard
    is: the list ignores both keys (Task 6's probe, and
    :class:`NativeDeleteModelProbeTest` for the model half), so Qt walks the press up to
    the outer widget. A key that arrives there is by construction a key the list was not
    using, which is what makes the outside-the-list half of ``OutsideTheListTest``
    provable without any focus bookkeeping.
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

    def test_numpad_enter_plays_selection(self):
        """The keypad ``Enter`` (``Key_Enter``) means the same row as ``Key_Return``.

        spec §5 spells the key ``Enter``, and Qt hands the two physical keys two
        different codes. Binding only the main-row one leaves the numeric keypad dead:
        measured with the code as shipped at ``3356222``, ``Key_Enter`` produced neither
        an action nor an effect anywhere in the window, which is exactly the shape this
        test now fails on if a refactor keeps only ``'Return'``.
        """
        self._load(5)
        self._select([1, 3, 4])
        self._forget_calls()

        recorded = self._record()
        self._press(*SHORTCUTS['Enter'])

        self.assertEqual([[1]], recorded['play_tracks_requested'],
                         'keypad Enter must reach play_tracks_requested with the '
                         'lowest selected display index, like the main-row key')
        self.playback.play.assert_called_once_with(_index_path(1))
        self.assertEqual(1, self.queue.get_current_position().display_index)

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
        """Each key reaches its window signal once, moves the real queue, **and** does
        not touch the list.

        Asserted on the engine call, not on a connect: with five flat rows and row
        2 playing, prev is T1 and next is T2 -- a signal that fired into nothing
        would leave ``play()`` uncalled (the batch 2 defect shape).

        The third half is ruling R10 applied to this pair (fix round 1, Minor 1). The
        task's own probe (:class:`NativeKeyBehaviourProbeTest`) measures ``Ctrl+Up``
        and ``Ctrl+Down`` **natively moving the cursor** on the unconstrained list
        (``row 1 -> 0`` and ``row 0 -> 1``), so a window binding that fires without
        eating the key would show up as a cursor that shifted under the transport
        request. Until now nothing in this file could see that: the signal count and
        the queue position both stay correct while the list silently walks. Asserted
        after *each* press, so a failure names the key that did it.
        """
        self._load(5)
        self._play(2)
        self._select([2])
        self._forget_calls()

        before_row = self._current_row()
        before_selection = self.playlist.selected_display_indices()
        self.assertEqual(2, before_row, 'fixture: row 2 is current')
        self.assertEqual([2], before_selection, 'fixture: row 2 is the selection')

        recorded = self._record()
        self._press(*SHORTCUTS['Ctrl+Up'])
        self.assertEqual(1, len(recorded['prev_track_requested']),
                         'Ctrl+Up must reach prev_track_requested exactly once')
        self.assertEqual([], recorded['next_track_requested'])
        self.assertEqual(
            before_row, self._current_row(),
            'Ctrl+Up moved the list cursor, so the press was not consumed by the '
            'shortcut -- transport and navigation both answered one key (R10; see the '
            'probe for what the native Ctrl+Up does)')
        self.assertEqual(
            before_selection, self.playlist.selected_display_indices(),
            'Ctrl+Up changed the selection, so the list saw the press too')
        self.assertEqual(1, self.queue.get_current_position().display_index,
                         'the queue position did not move back')

        self._press(*SHORTCUTS['Ctrl+Down'])
        self.assertEqual(1, len(recorded['next_track_requested']),
                         'Ctrl+Down must reach next_track_requested exactly once')
        self.assertEqual(1, len(recorded['prev_track_requested']),
                         'Ctrl+Down must not answer as prev')
        self.assertEqual(
            before_row, self._current_row(),
            'Ctrl+Down moved the list cursor, so the press was not consumed by the '
            'shortcut (R10)')
        self.assertEqual(
            before_selection, self.playlist.selected_display_indices(),
            'Ctrl+Down changed the selection, so the list saw the press too')
        self.assertEqual(2, self.queue.get_current_position().display_index,
                         'the queue position did not move forward')
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

    def test_ctrl_a_is_left_to_qt_native_select_all(self):
        """``Ctrl+A`` is Qt's own; this only confirms the native route still works.

        The name says what is true (fix round 1, Minor 3): the app implements **no**
        ``Ctrl+A`` -- the old ``test_ctrl_a_selects_all`` read as though it did, which
        is how a binding that nobody wrote gets "confirmed" by a passing test.

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
        """Each transport key is carried by exactly one action, parented and added to
        the window.

        ``addAction`` is what keeps a shortcut alive with no menu bar (batch 2 §6,
        and the reason ``Ctrl+Q`` already lives on the window here): an action that
        is only constructed and never added to a widget is reachable by nothing.
        The count is ``== 1`` per sequence, so a second widget binding the same key
        -- the "归属再次分散" risk spec §10 names -- fails instead of passing twice.

        Three keys, not five: ruling R11 moved ``Delete``/``Enter`` out of this table
        and into the view, and
        :meth:`test_no_window_binding_steals_delete_or_enter` is the other half --
        it is what turns red if a window ``QAction`` for those two comes back.
        """
        holders = {}
        for action in self.view.findChildren(QAction):
            for sequence in action.shortcuts():
                holders.setdefault(QKeySequence(sequence), []).append(action)

        window_actions = list(self.view.actions())
        for literal in WINDOW_SHORTCUTS:
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

    def test_no_window_binding_steals_delete_or_enter(self):
        """Ruling R11's guard: nothing in this window binds ``Delete``/``Enter``.

        This is the half that makes the swallowed-key defect *fail loudly* instead of
        silently re-appearing: an action for either key, anywhere in the window's
        subtree, matches before the focused widget sees the press and consumes it
        there -- and no slot can hand it back. So the assertion is on the absence of
        the binding, and it holds whether or not the key still works inside the list
        (the tests in ``BatchActionShortcutTest`` cover that half).

        ``QShortcut`` is included because that is the other way a key binding can
        appear at this level, and it consumes identically.
        """
        self._load(5)
        self._select([2])

        for literal in LIST_KEYS:
            with self.subTest(shortcut=literal):
                sequence = QKeySequence(literal)
                actions = [action for action in self.view.findChildren(QAction)
                           if sequence in [QKeySequence(candidate)
                                           for candidate in action.shortcuts()]]
                self.assertEqual([], actions,
                                 f'{literal} is bound as a window QAction again: that '
                                 f'binding consumes the key for every widget in this '
                                 f'window and no slot can give it back (R11)')
                stolen = [shortcut for shortcut in self.view.findChildren(QShortcut)
                          if QKeySequence(shortcut.key()) == sequence]
                self.assertEqual([], stolen,
                                 f'{literal} is bound as a QShortcut on the window')
        # and the list still answers both keys -- the guard above must not be bought
        # with a dead Delete/Enter
        recorded = self._record()
        self._press(*LIST_KEYS['Delete'])
        self.assertEqual([[2]], recorded['remove_tracks_requested'],
                         'Delete stopped reaching the batch route: the absence asserted '
                         'above has to be R11 moving the key, not losing it')

    def test_the_widgets_bind_no_shortcuts_of_their_own(self):
        """``PlaylistView`` and ``BottomPanel`` must not carry key *bindings*.

        The rail is exempt on purpose: ``ActionRail`` owns its ``Ctrl+O`` and
        ``tests/test_action_rail.py`` pins it there (batch 2's design). This guard
        is about the two widgets this task touched, and about ``QShortcut`` objects,
        the other way a binding can appear inside a widget.

        Ruling R11 does not weaken it. ``PlaylistView`` answers ``Delete``/``Enter`` in
        :meth:`keyPressEvent`, which is not a binding: it registers no sequence, claims
        no shortcut, and only ever sees a press the inner ``QListView`` already let
        go -- which is why the two keys cannot reach ``BottomPanel``'s buttons through
        it. Anything that *does* carry a sequence, on either widget, still fails here.
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
    """A key pressed **outside** the playlist must reach the widget that had focus.

    What this class asserted before the fix round was the defect wearing its intended
    clothes: ``test_delete_outside_the_playlist_does_not_remove`` pressed ``Delete`` on
    the volume slider and required that *nothing happen*. Nothing happening was exactly
    the bug -- a window-level ``QAction`` had already consumed the press, so the slider
    got nothing either. Ruling R11 removed those two bindings, and the expectation here
    is now the one that actually matters: **the focused widget gets its key back**.

    Three targets, because the three shapes fail differently:

    * ``#playButton`` -- a real ``QPushButton`` in the shipped shell. ``QAbstractButton``
      answers ``Enter``/``Space``, so this is where the swallow cost the user a function
      that used to work. Read with the receiver-side counter; ``clicked`` may not be
      asserted here (see :class:`KeyPressCounter` for the control numbers), so bare
      ``Space`` rides along as the positive control that the button and the counter are
      both alive.
    * a ``QLineEdit`` in this window -- batch 6's search box. ``returnPressed`` is a
      signal, so this is the strongest statement of the same fact, and the one the
      finding names. It is a fixture, not new UI: ``view/`` still has no line edit.
    * a ``QLineEdit`` in a ``QDialog`` parented to the window -- kept from before,
      because that is the half ``WidgetWithChildrenShortcut`` really did deliver.
    """

    def test_delete_outside_the_playlist_reaches_the_focused_widget(self):
        """``Delete`` on the volume slider is the slider's, not the list's.

        The slider keeps the honest-role properties the old version of this test needed:
        it takes focus, it is in the window, it is not in the playlist's subtree. What
        changes is the second half. Asserting only "no removal" would pass on the
        swallowing code too -- that is how the defect stayed green -- so the press must
        additionally be **delivered**: 1 for R11, 0 for the window ``QAction`` that used
        to answer from here.
        """
        from PyQt6.QtWidgets import QSlider

        self._load(5)
        self._select([0, 1])
        self._forget_calls()

        slider = self.view.findChild(QSlider, 'volumeSlider')
        self.assertIsNotNone(slider, '#volumeSlider must be in the shell')
        self._focus_off_list(slider)

        recorded = self._record()
        delivered = self._press_at(slider, *LIST_KEYS['Delete'])

        self.assertEqual(1, delivered,
                         'Delete never reached the widget that had focus: something '
                         'upstream consumed it (this is Important 1 -- a window-level '
                         'binding eats the key before the focus widget sees it)')
        self.assertEqual([], recorded['remove_tracks_requested'],
                          'Delete outside the playlist still reached the batch route')
        self.assertEqual([], self.queue.calls)
        self.assertEqual([0, 1], self.playlist.selected_display_indices(),
                         'the batch the key would have acted on changed anyway')

    def test_enter_outside_the_playlist_reaches_the_focused_button(self):
        """``Enter`` on the play/pause button activates nothing if it is swallowed.

        The control bar's five ``QPushButton``s and every ``LibraryRow`` are default
        ``StrongFocus`` with no ``setFocusPolicy`` call, so before R11 they held focus
        and could not be pressed by ``Enter`` -- the key died in a window action whose
        slot then returned early and did nothing with it.

        Read as a pair with the ``Space`` control below it: a button activated by
        keyboard is provable here with ``Space`` only, because a synthesized ``Enter``
        produces no ``pressed``/``clicked`` even in a bare window with no bindings at
        all. ``Space`` is not bound to anything in this window either (spec §4.4 leaves
        it to the list), so the control half also proves the two keys this round moved
        did not take it.
        """
        from PyQt6.QtWidgets import QPushButton

        self._load(5)
        self._select([0, 1])
        self._forget_calls()

        button = None
        for candidate in self.view._bottom_panel.findChildren(QPushButton):
            if candidate.objectName() == 'playButton':
                button = candidate
        self.assertIsNotNone(button, '#playButton must be in the shell')
        self._focus_off_list(button)

        recorded = self._record()
        delivered = self._press_at(button, *LIST_KEYS['Return'])

        self.assertEqual(1, delivered,
                         'Enter never reached the focused button: the window consumed '
                         'it (Important 1)')
        self.assertEqual([], recorded['play_tracks_requested'],
                         'Enter outside the playlist still reached the batch route')
        self.assertEqual([], self.queue.calls)

        # positive control: the same button, the same counter, a key a button really
        # does activate on. Without this line the assertion above could be reading a
        # dead counter instead of a live delivery.
        activations = []
        button.clicked.connect(lambda: activations.append(True))
        self.assertEqual(1, self._press_at(button, Qt.Key.Key_Space),
                         'the control lost the plot: Space no longer reaches the button')
        self.assertEqual([True], activations,
                         'Space no longer activates #playButton, so this test\'s '
                         'control has stopped proving anything')
        # ...and the activation has a landing, so the control cannot be satisfied by a
        # button wired to nothing. Bare Space is not bound at the window level (spec
        # §4.4 leaves it to the focused widget), which is what lets it arrive here.
        self.assertEqual(1, len(recorded['play_pause_requested']),
                         'Space activated the button but the click reached '
                         'play_pause_requested %d times: the control is counting a '
                         'widget with no route' % len(recorded['play_pause_requested']))
        self.assertEqual([], recorded['play_tracks_requested'],
                         'the Space control leaked into the playlist batch route')

    def test_enter_outside_the_playlist_submits_a_line_edit(self):
        """The batch 6 search box: ``Enter`` must be the line edit's to emit.

        ``view/`` has no ``QLineEdit`` yet, so this is the latent half of Important 1
        made observable today -- a fixture line edit parented to the bottom panel, the
        same subtree the real search box will live in. ``returnPressed`` is a Qt signal
        the widget emits from its own key handling, so it is the one outside-the-list
        assertion that does not need a counter: if the press had been consumed by a
        window action, it cannot fire (measured: 0 with the binding, 1 without).
        """
        from PyQt6.QtWidgets import QLineEdit

        self._load(5)
        self._select([0, 1])
        self._forget_calls()

        editor = QLineEdit(self.view._bottom_panel)
        self.addCleanup(editor.deleteLater)
        editor.setObjectName('probeSearchBox')
        editor.setGeometry(10, 10, 140, 20)
        editor.show()
        self.app.processEvents()
        self._focus_off_list(editor)

        submitted = []
        editor.returnPressed.connect(lambda: submitted.append(True))
        recorded = self._record()
        delivered = self._press_at(editor, *LIST_KEYS['Return'])

        self.assertEqual([True], submitted,
                         'Enter did not submit the line edit: something in this window '
                         'consumed it before the focused widget (R11)')
        self.assertEqual(1, delivered)
        self.assertEqual([], recorded['play_tracks_requested'],
                         'Enter outside the playlist still reached the batch route')
        self.assertEqual([0, 1], self.playlist.selected_display_indices(),
                         'the batch the dialog keys would have acted on moved')

    def test_enter_inside_a_child_dialog_is_not_eaten(self):
        """A dialog parented to the window keeps its own Enter and Delete.

        Kept from before the fix round, with the delivery half added. The dialog is a
        *separate window* in the object tree, so ``isAncestorOf`` stops at its edge
        (measured in batch 2) -- which is why the old window-level
        ``WidgetWithChildrenShortcut`` really did protect it, and the one part of
        Step 2's mechanism claim that held up. Under ruling R11 there is no window
        binding for these keys at all, so the protection no longer depends on a
        context: the keys are typed into the dialog and stay there. Asserted as
        delivery now (1 press received per key), because "nothing happened" is the
        assertion that let the swallow hide.
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
        self._focus_off_list(editor)

        recorded = self._record()
        delivered = {}
        for name, key in (('Enter', Qt.Key.Key_Return),
                          ('Delete', Qt.Key.Key_Delete)):
            delivered[name] = self._press_at(editor, key)

        self.assertEqual({'Enter': 1, 'Delete': 1}, delivered,
                         'the main window consumed a key typed into the dialog; both '
                         'belong to the widget holding the keyboard')
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
class NativeDeleteModelProbeTest(unittest.TestCase):
    """A probe: what a list view really does with ``Delete`` (ruling R11's foundation).

    R11 hands ``Delete``/``Enter`` to ``PlaylistView.keyPressEvent`` on the strength of
    one claim: the inner ``QListView`` does not consume those keys, so the press walks
    up to the outer widget. The review round asked for this to be checked against
    ``QListWidget``, on the reading that ``QAbstractItemView`` answers ``Delete`` when
    its model can remove rows -- which would make ``QListWidget`` the "model that can"
    side of the comparison.

    Measured on this host, that contrast **does not exist**, and the probe now says so
    rather than pretending to a difference (numbers printed below, PyQt 6.11 offscreen):

    * ``QListWidget`` with three items and row 1 selected: ``Delete`` gives
      ``accepted=False`` and ``count 3 -> 3``, and it carries **no** ``QAction`` with a
      shortcut at all (``widget.actions()`` filtered on ``shortcuts()`` is empty).
    * Its model -- the same class name PyQt reports for a plain
      ``QAbstractListModel`` -- answers ``removeRows(1, 0)`` with **False** and leaves
      three rows standing.
    * ``PlaylistModel`` answers ``removeRows(1, 0)`` with **False** too, and does not
      override the method at all (``'removeRows' in type(model).__dict__`` is False).

    So neither list view consumes the key and neither model can remove rows: the free
    ``Delete`` R11 relies on is a property of **the view**, not of this project's model.
    That is the stronger of the two possible findings -- the route cannot be broken by
    ``PlaylistModel`` growing ``removeRows`` later, because that method is not what
    makes ``QListView`` eat the key -- and it is why the assertions below are written
    against the *observed consumption* of the key rather than against a model
    difference that is not real. Bare ``Space`` and the bare arrows are asserted as the
    contrast case: those the list *does* accept, and they therefore never reach
    :meth:`PlaylistView.keyPressEvent`.

    Printed first, asserted second: ruling R4's discipline is that a probe whose
    numbers nobody prints is worth nothing on a Qt upgrade.
    """

    def setUp(self):
        self.app = make_app()
        self.manager = make_manager()

    def _list_widget(self):
        from PyQt6.QtWidgets import QListWidget

        widget = QListWidget()
        widget.addItems(['a', 'b', 'c'])
        widget.resize(240, 160)
        widget.show()
        self.app.processEvents()
        widget.setCurrentRow(1)
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), widget,
                      'probe fixture lost focus: an unfocused item view ignores the '
                      'navigation keys this probe reads as "consumed by the list"')
        self.addCleanup(widget.deleteLater)
        return widget

    def test_probe_native_delete_is_not_the_view_or_the_model_to_answer(self):
        """``Delete`` is free at both list views and neither model removes rows.

        Two independent reads per widget, because "the rows did not change" alone
        cannot tell "the view ignored the key" from "the view asked and the model
        refused": the press, then a direct ``removeRows`` call on the model.
        """
        from view.widgets.playlist_view import PlaylistView

        widget = self._list_widget()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, NO_MODS)
        event.setAccepted(False)
        self.app.sendEvent(widget, event)
        self.app.processEvents()
        list_widget_result = {
            'accepted': event.isAccepted(),
            'rows': f'{widget.count()} after',
            'bound_actions': [action.text() for action in widget.actions()
                              if action.shortcuts()],
            'model_remove_rows': widget.model().removeRows(1, 0),
            'model_rows': widget.model().rowCount(),
        }

        class ReachingPlaylistView(PlaylistView):
            """Counts the presses that arrive at the widget R11 answers on."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.seen = []

            def keyPressEvent(self, event):
                self.seen.append(int(event.key()))
                super().keyPressEvent(event)

        view = ReachingPlaylistView(self.manager)
        view.resize(240, 160)
        view.set_entries(_entries(3))
        view.show()
        self.app.processEvents()
        view._list_view.setCurrentIndex(view._model.index(1))
        view._list_view.setFocus(Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(), view._list_view,
                      'probe fixture lost focus: this probe reads which keys the '
                      'focused QListView keeps, so a view that does not hold the '
                      'keyboard hands everything upstairs (Task 6\'s R10 lesson)')
        self.addCleanup(view.deleteLater)
        model = view._model
        calls = []
        original = model.removeRows

        def recording(row, count, parent=None):
            calls.append((row, count))
            return original(row, count, parent)

        model.removeRows = recording
        before = model.rowCount()

        # Pressing into the inner QListView must land in PlaylistView.keyPressEvent,
        # because that is the only reason R11's override runs at all. The accept flag
        # cannot answer this: an ignored press walks up the parent chain and is marked
        # accepted by whoever finally handles it -- which after R11 is our own override,
        # so ``accepted == True`` here is the *success* shape, not a failure. Counting
        # what the outer widget is handed is the honest read.
        keys = []
        for key in (Qt.Key.Key_Delete, Qt.Key.Key_Return, Qt.Key.Key_Enter,
                    Qt.Key.Key_Space, Qt.Key.Key_Down):
            view.seen = []
            # Re-park the cursor mid-list before every key. Without this the loop is
            # order-dependent and reads a Qt boundary as a bug: the first key leaves the
            # cursor somewhere, and ``Down`` on the *last* row has nowhere to go, so the
            # list leaves it unclaimed and it walks upstairs. Measured that way once.
            view._list_view.setCurrentIndex(model.index(1))
            self.app.processEvents()
            row_before = view._list_view.currentIndex().row()
            press = QKeyEvent(QEvent.Type.KeyPress, key, NO_MODS)
            press.setAccepted(False)
            self.app.sendEvent(view._list_view, press)
            self.app.processEvents()
            keys.append((Qt.Key(key).name, list(view.seen), press.isAccepted(),
                         f'{row_before} -> '
                         f'{view._list_view.currentIndex().row()}'))
        playlist_result = {
            'rows': f'{before} -> {model.rowCount()}',
            'removeRows_calls': calls,
            'reached': keys,
            'model_remove_rows': original(1, 0),
            'model_rows_after_direct_call': model.rowCount(),
        }

        print(f'\n[Native Delete] PyQt {PYQT_VERSION_STR}, offscreen, row 1 of 3 '
              f'selected:')
        print(f'[Native Delete]   QListWidget      Delete accepted='
              f'{list_widget_result["accepted"]} rows={list_widget_result["rows"]} '
              f'bound_actions={list_widget_result["bound_actions"]} '
              f'model.removeRows(1,0)={list_widget_result["model_remove_rows"]} '
              f'model_rows={list_widget_result["model_rows"]}')
        print(f'[Native Delete]   PlaylistModel    rows={playlist_result["rows"]} '
              f'asked_by_the_view={playlist_result["removeRows_calls"]} '
              f'model.removeRows(1,0)={playlist_result["model_remove_rows"]} '
              f'model_rows_after_direct_call='
              f'{playlist_result["model_rows_after_direct_call"]}')
        print(f'[Native Delete]   reached PlaylistView.keyPressEvent '
              f'(name, seen, accepted, current row): {playlist_result["reached"]}')
        sys.stdout.flush()

        # neither list view eats Delete, and neither model can remove rows
        self.assertFalse(list_widget_result['accepted'],
                         'QListWidget now consumes Delete: the "the view ignores it, '
                         'so it walks up" premise behind ruling R11 needs re-reading')
        self.assertEqual([], list_widget_result['bound_actions'],
                         'QListWidget grew key-bound actions; Delete may no longer be '
                         'free at a list view')
        self.assertFalse(list_widget_result['model_remove_rows'],
                         "QListWidget's model started answering removeRows: re-check "
                         'whether the view now consumes Delete')
        self.assertFalse(playlist_result['model_remove_rows'],
                         'PlaylistModel started answering removeRows -- the row space '
                         'and the queue would both need re-reading (Task 5/6 contract)')
        self.assertEqual(3, model.rowCount(),
                         'the direct removeRows call changed the row count while the '
                         'method is supposed to be unsupported')

        # the list asked nothing of the model, and the rows survived Delete
        self.assertEqual([], calls,
                         'the inner QListView asked the model to remove rows: it is no '
                         'longer leaving Delete to the outer widget')
        self.assertEqual(3, model.rowCount(),
                         'the playlist rows did change on Delete: the inner QListView '
                         'is consuming the key, so PlaylistView.keyPressEvent stops '
                         'being reached -- re-read ruling R11 before trusting the route')

        by_name = {name: (seen, accepted) for name, seen, accepted, _row in keys}
        for name in ('Key_Delete', 'Key_Return', 'Key_Enter'):
            seen, _accepted = by_name[name]
            self.assertEqual([getattr(Qt.Key, name)], seen,
                             f'{name}: R11 reads this key in PlaylistView.keyPressEvent, '
                             f'and it is not being handed to it -- the batch route is '
                             f'dead (see BatchActionShortcutTest)')
        for name in ('Key_Space', 'Key_Down'):
            seen, accepted = by_name[name]
            self.assertEqual([], seen,
                             f'{name} now reaches PlaylistView.keyPressEvent: the inner '
                             f'QListView stopped consuming its own navigation keys, so '
                             f'an override here could start stealing them -- re-read '
                             f'ruling R11 and spec §5 (不劫持)')
            self.assertTrue(accepted,
                            f'{name} was not handled by the list at all: the keys R11 '
                            f'leaves alone are no longer the list\'s')


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
