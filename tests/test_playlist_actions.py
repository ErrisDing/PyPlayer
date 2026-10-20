#!/usr/bin/env python3
"""批次 3 Task 5：presenter 的批量动作（批量移除 / 播放选中）。

spec §4.2 定了移除的顺序（`sorted(set(indices), reverse=True)`），§5 定了 `Enter`
取**显示索引最小**的那一行，§7 定了两条边界（空列表不得进循环、全删 == 清空）。这三条
本文件都有专测。

真正难的是**移除之后播放位置归谁**——裁定 R8（2026-10-20，控制器实测）：
`QueueService.remove_at_display_index()` 只 `_rebuild_display_entries()`，**从不维护
`PlaybackPosition`**（`service/queue_service.py:486-513`），而 `clear()` 会重置它
（`:478-484`）。这个不对称的后果是：删完之后

* `get_current_track()` 读的是**陈旧 node_index 在新节点表上的位置**，删掉播放行本身
  与删掉播放行**上方**一行都会指向**另一首歌**（实测都是 T2 在播 → 答 T3）；
* `_position.display_index` 同样停旧，于是播放高亮也会落在别的行上。

本批次范围线是「不改队列契约」，所以补偿只能落在 presenter：**以曲目身份**重解析——
删前先 `get_current_track()` 取路径，删完在 `get_display_entries()` 里按路径找它的**新**
显示索引，找到就 `set_position_by_display_index(new_idx)` 钉回去；找不到（播的那首被删
了）就把位置归零并复位播放态。presenter 里那段补偿逻辑的全部理由都在这里，
`QueuePositionAfterRemovalCharacterizationTest` 则把队列层现在这个行为**钉成事实**并
交给批次 5，免得后来人只看到一段解释不清的补偿。

装配沿用 `tests/test_presenter_status.py`：真 `MainWindow` + 真 `QueueService`（子类只
记录调用，删除语义全是真的）+ 假播放服务；服务信号通过 presenter 登记的连接发出
（`_emit`），不直接调槽，否则连接本身就没被测到。

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_actions -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n
from core.library_manager import Track
from service.queue_service import QueueService
from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

LIB = '/media/rock'


def _index_path(index: int) -> str:
    """``Track`` path for the flat fixture, spelled the way the queue stores it."""
    return f'{LIB}/track{index}.mp3'


def _tracks(count: int) -> list:
    """``count`` flat tracks, T0..T(count-1): path and title both carry the index."""
    return [Track(path=_index_path(index), title=f'Track {index}')
            for index in range(count)]


class RecordingQueueService(QueueService):
    """The real queue, plus a log of the mutations the presenter asked for.

    Only the four entry points the presenter may use are overridden, and every
    override delegates, so removal and
    position semantics stay the real ones -- this exists because spec §7's
    "empty selection must not reach the queue" and §4.2's descending order are
    claims about *which* calls the presenter makes, not about the resulting state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.calls: list = []

    def remove_at_display_index(self, display_idx: int) -> bool:
        self.calls.append(('remove', display_idx))
        return super().remove_at_display_index(display_idx)

    def set_position_by_display_index(self, display_idx: int):
        self.calls.append(('set_position', display_idx))
        return super().set_position_by_display_index(display_idx)

    def set_current_position(self, node_idx: int, sub_idx: int = -1) -> None:
        self.calls.append(('set_current_position', node_idx, sub_idx))
        return super().set_current_position(node_idx, sub_idx)

    def clear(self) -> None:
        self.calls.append(('clear',))
        return super().clear()

    def removals(self) -> list:
        """The indices handed to ``remove_at_display_index``, in call order."""
        return [call[1] for call in self.calls if call[0] == 'remove']


class PlaylistActionHarness:
    """Real window + real queue + fake playback, shaped like ``PresenterHarness``.

    Mixed into the ``unittest.TestCase`` classes below rather than subclassed, for
    the same reason `test_presenter_status` does it that way: the harness needs
    ``self.assert*`` and each test class wants a different set of cases on top.
    """

    def setUp(self):
        from PyQt6.QtWidgets import QWidget

        from presenter.main_presenter import MainPresenter
        from view.main_window import MainWindow

        self._previous_locale = i18n.get_current_locale()
        i18n.set_locale('zh_CN')
        self.app = make_app()

        self.view = MainWindow(make_manager())
        self.addCleanup(self.view.deleteLater)
        # Private members on purpose: the row count and the playing row are the
        # view's own state, and there is no public getter for either (batch 1/2
        # structure tests reach the tree the same way).
        self.playlist = self.view._playlist_view
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
        # No configured library: ``_load_config`` must not auto-scan one and build a
        # queue behind a test that already built its own.
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

    def tearDown(self):
        i18n.set_locale(self._previous_locale)

    # === driving the layers the way the application does ===

    def _emit(self, service, signal_name, *args):
        """Fire a service signal through the connection the presenter made."""
        signal = getattr(service, signal_name)
        receivers = [call.args[0] for call in signal.connect.call_args_list]
        self.assertTrue(
            receivers,
            f'nothing is connected to {signal_name}: the presenter lost the route',
        )
        for receiver in receivers:
            receiver(*args)

    def _load(self, count: int) -> None:
        """Build a flat queue of ``count`` tracks and prove the view followed."""
        self.queue.build_from_tracks(_tracks(count))
        self.assertEqual(count, len(self.queue.get_display_entries()))
        self.assertEqual(count, self.model.rowCount(),
                         'the queue never reached the visible list')

    def _play(self, display_idx: int):
        """Start row ``display_idx``: position, then the strip via the presenter."""
        track = self.queue.set_position_by_display_index(display_idx)
        self.assertIsNotNone(track, f'row {display_idx} is not playable')
        # The engine is a mock, so it will not announce the track itself; the
        # presenter's own ``track_changed`` route is what fills the strip.
        self._emit(self.playback, 'track_changed', track)
        return track

    def _forget_calls(self) -> None:
        """Drop the mutation log: setup plays through the queue too."""
        self.queue.calls.clear()

    # === reading state back ===

    def _path_of(self, index: int) -> str:
        return _index_path(index)

    def _queue_paths(self) -> list:
        return [entry.full_path for entry in self.queue.get_display_entries()]

    def _view_paths(self) -> list:
        return [self.playlist.get_entry_at(row).full_path
                for row in range(self.model.rowCount())]

    def _playing_row_path(self):
        """The path of the row the *view* highlights, or ``None`` for no row."""
        row = self.model.get_playing_index()
        if row < 0:
            return None
        entry = self.playlist.get_entry_at(row)
        return None if entry is None else entry.full_path


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class BatchRemovalTest(PlaylistActionHarness, unittest.TestCase):
    """``_on_remove_tracks``: order, boundaries, and what survives under R8."""

    def test_interleaved_batch_removal_leaves_exactly_the_complement(self):
        """Review Focus 2 / spec §4.2: deleting {1,3,5} leaves {0,2,4,6}.

        Interleaved on purpose -- two adjacent rows pass an ascending loop by
        accident, three spread rows cannot.
        """
        self._load(7)

        self.presenter._on_remove_tracks([1, 3, 5])

        expected = [self._path_of(i) for i in (0, 2, 4, 6)]
        self.assertEqual(expected, self._queue_paths(),
                         'an ascending loop deletes the wrong songs: removing row 3 '
                         'shifts row 5 up to 4 (spec §4.2)')
        self.assertEqual(expected, self._view_paths(),
                         'the queue shrank but the visible list did not follow')
        self.assertEqual(4, len(self.queue.get_display_entries()),
                         'spec §1 criterion 3: the queue length must be right')

    def test_removal_is_descending_order(self):
        """The loop itself, not just its outcome: strictly descending, deduplicated."""
        self._load(7)
        self._forget_calls()

        # Unsorted *and* with a duplicate: ``set()`` and ``reverse=True`` are the two
        # halves of the spec §4.2 rule, and an assertion on the final state alone
        # cannot tell a deduplicated descending loop from a lucky set of indices.
        self.presenter._on_remove_tracks([1, 5, 3, 3])

        removed = self.queue.removals()
        self.assertEqual([5, 3, 1], removed,
                         'the batch must reach remove_at_display_index in descending '
                         'order, with the duplicate collapsed to one deletion')
        self.assertEqual(sorted(removed, reverse=True), removed, removed)
        self.assertEqual([self._path_of(i) for i in (0, 2, 4, 6)],
                         self._queue_paths())

    def test_empty_selection_does_not_call_the_queue(self):
        """spec §7: 选区为空时不产生调用——不得传空列表给 presenter 再靠循环兜底."""
        self._load(7)
        self._play(2)
        self._forget_calls()

        self.presenter._on_remove_tracks([])

        self.assertEqual([], self.queue.calls,
                         'an empty selection reached the queue: spec §7 puts the '
                         '"no rows, no call" rule in the view *and* the presenter, '
                         'not in a loop that happens not to run')
        self.assertEqual(7, len(self.queue.get_display_entries()))
        self.assertEqual(7, self.model.rowCount())
        self.assertFalse(self.playback.stop.called,
                         'nothing was removed, so playback has nothing to reset')
        self.assertEqual(self._path_of(2), self._playing_row_path())

    def test_removing_the_playing_track_does_not_silently_point_at_another_song(self):
        """Review Focus 1 / R8, shape one: the playing row *itself* goes.

        Measured on this host without the identity re-resolution (R8, five rows
        playing T2): remove the playing row and ``get_current_track()`` answers
        **T3** -- the stale node index now names a different song. Silently. The
        same shape here is seven rows playing T3 and removing [2,3,4], and the
        honest outcome is a cleared strip and no playing row at all, never
        another song.
        """
        self._load(7)
        playing = self._play(3)
        self.assertEqual(playing.title, self.strip._title_text)
        self.assertEqual(self._path_of(3), self._playing_row_path())

        self.presenter._on_remove_tracks([2, 3, 4])

        self.assertEqual([self._path_of(i) for i in (0, 1, 5, 6)], self._queue_paths())
        # The queue's position, not merely the view's paint: R8 is about the service.
        self.assertIsNone(self.queue.get_current_track(),
                          'the playing row was removed, yet the queue still names a '
                          'track -- that track is whatever slid into the stale node '
                          'index (R8: measured as T3 where T2 was playing)')
        self.assertEqual(-1, self.queue.get_current_position().display_index,
                         'a stale display_index is what puts the highlight on the '
                         'wrong row once the rows below move up')
        self.assertEqual(-1, self.model.get_playing_index(),
                         'no row may carry the playing highlight once its song is gone')
        self.assertIsNone(self._playing_row_path())
        self.assertNotIn(True, [entry.is_playing
                                for entry in self.queue.get_display_entries()],
                         'a rebuilt entry kept the playing flag of a deleted song')
        self.assertEqual(i18n.get('metadata.no_track'), self.strip._title_text,
                         'the strip still headlines a track the queue no longer has')
        self.assertTrue(self.playback.stop.called,
                        'the removed song must not keep playing from the engine')
        self.assertFalse(self.playback.play.called,
                         'clearing after a removal must not start a substitute song')
        # The "nothing is current" write is this handler's use of a fourth queue
        # API (ruling R8 permits no others): pinning the exact arguments gives
        # batch 5 a target when it deletes the compensation.
        self.assertIn(('set_current_position', -1, -1), self.queue.calls,
                      'the reset of the current position is what keeps the stale '
                      'node index from naming another song')

    def test_removing_the_playing_copy_stops_even_when_another_copy_is_queued(self):
        """Two queued copies of one path: identity by path alone cannot say which went.

        The shape that makes the display index, not the path, the authority here.
        Removing the *playing* row while an identical path sits elsewhere in the
        list must stop: the row the user deleted was the one that was playing, and
        continuing would mean the strip and the highlight describe a row nobody
        asked to keep. R8's path re-pin, used alone, would read the surviving copy
        as "same song, new row" and keep playing.
        """
        from core.library_manager import Track

        dup = f'{LIB}/duplicate.mp3'
        self.queue.build_from_tracks([
            Track(path=f'{LIB}/a.mp3', title='A'),
            Track(path=dup, title='B first copy'),
            Track(path=dup, title='B second copy'),
            Track(path=f'{LIB}/c.mp3', title='C'),
        ])
        self.assertEqual(4, len(self.queue.get_display_entries()))
        self._play(1)
        self._forget_calls()

        self.presenter._on_remove_tracks([1])

        self.assertTrue(self.playback.stop.called,
                        'the row that was playing was deleted; a duplicate of the '
                        'same path elsewhere must not be read as its survivor')
        self.assertEqual(-1, self.model.get_playing_index(),
                         'no row may hold the highlight after its own row was deleted')
        self.assertNotIn(('set_position', 1), self.queue.calls,
                         'the handler re-pinned the duplicate copy instead of resetting')

    def test_removing_only_invalid_indices_changes_nothing(self):
        """A batch whose every index is out of range must not stop or re-pin.

        ``remove_at_display_index`` answers ``False`` for an out-of-range row and
        the queue is untouched, so the removal path must stop there. Before this
        guard the handler fell through to the reset branch on an empty result and
        silenced playback the user never asked to stop.
        """
        self._load(4)
        self._play(1)
        self._forget_calls()

        self.presenter._on_remove_tracks([9, 99])

        # The indices do reach the queue -- that is where out-of-range is decided,
        # and it answers False. What must not happen is any *consequence*.
        self.assertEqual([99, 9], self.queue.removals(),
                         'the handler sorts descending before asking the queue')
        self.assertEqual(4, len(self.queue.get_display_entries()),
                         'a no-op removal changed the list')
        self.assertFalse(self.playback.stop.called,
                         'nothing was deleted, so playback must not stop')
        self.assertNotIn(('set_current_position', -1, -1), self.queue.calls,
                         'the position was reset although the list did not change')

    def test_removing_a_row_above_the_playing_row_keeps_the_same_song_playing(self):
        """Review Focus 1 / R8, shape two: a row *above* the playing one goes.

        The other half of the measured pair: removing row 0 while T2 plays makes
        ``get_current_track()`` answer **T3** too -- the node at index 2 is now a
        different file. The song is still in the queue, so the answer here is the
        *same* track at its new, lower display index -- and no replay.
        """
        self._load(7)
        playing = self._play(3)

        self.presenter._on_remove_tracks([0, 1])

        self.assertEqual([self._path_of(i) for i in (2, 3, 4, 5, 6)],
                         self._queue_paths())
        current = self.queue.get_current_track()
        self.assertIsNotNone(current)
        self.assertEqual(playing.path, current.path,
                         'R8: the position must be re-resolved by track identity -- '
                         'reading get_current_track() after a removal reports the '
                         'song that slid into the stale node index')
        self.assertEqual(playing.title, self.strip._title_text,
                         'the headline song did not change, so the strip must not either')
        # Row 3 became row 1: the highlight follows the song, not the old number.
        self.assertEqual(1, self.queue.get_current_position().display_index)
        self.assertEqual(1, self.model.get_playing_index(),
                         'the removal reset the rebuilt entries, so the highlight has '
                         'to be re-pointed at the surviving row')
        self.assertEqual(playing.path, self._playing_row_path())
        self.assertFalse(self.playback.stop.called,
                         'the playing song survived: stopping it would be its own bug')
        self.assertFalse(self.playback.play.called,
                         're-pointing a position is not a request to replay from it')
        self.assertNotIn(('clear',), self.queue.calls,
                         'rows remain, so this is not the clear-everything shape')

    def test_removing_every_row_resets_playback_state(self):
        """spec §7: 移除全部行 == 清空，播放状态与 NowPlayingStrip 一并复位."""
        self._load(3)
        self._play(1)
        self._forget_calls()

        self.presenter._on_remove_tracks([0, 1, 2])

        self.assertEqual([], self._queue_paths())
        self.assertEqual(0, self.model.rowCount())
        self.assertEqual(-1, self.model.get_playing_index())
        self.assertEqual(i18n.get('metadata.no_track'), self.strip._title_text)
        self.assertTrue(self.playback.stop.called)
        self.assertEqual(-1, self.queue.get_current_position().node_index,
                         'an emptied queue must not keep a node index pointing at '
                         'nothing (R8: per-row removal never resets the position, '
                         'only clear() does)')
        self.assertIn(('clear',), self.queue.calls,
                      'removing every row is the clear path (spec §7), and clear() is '
                      'the only existing queue API that resets the position')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PlaySelectionTest(PlaylistActionHarness, unittest.TestCase):
    """``_on_play_tracks``: spec §5's ``Enter`` rule on the double-click path."""

    def test_play_tracks_uses_lowest_display_index(self):
        """[4,1,2] plays row 1 -- the smallest display index, not the last clicked.

        Reuses ``_on_track_double_clicked`` rather than duplicating the playback
        route: one way to start a row means the context menu, ``Enter`` and the
        double-click cannot drift apart.
        """
        self._load(7)
        self._forget_calls()

        self.presenter._on_play_tracks([4, 1, 2])

        self.playback.play.assert_called_once_with(self._path_of(1))
        self.assertEqual(1, self.queue.get_current_position().display_index)
        self.assertEqual(self._path_of(1), self._playing_row_path())
        self.assertEqual([('set_position', 1)],
                         [call for call in self.queue.calls if call[0] == 'set_position'],
                         'a batch play is one request, played from its lowest row')

        # And the empty shape, same rule as removal: nothing reaches the queue.
        self._forget_calls()
        self.playback.play.reset_mock()
        self.presenter._on_play_tracks([])
        self.assertEqual([], self.queue.calls,
                         'spec §7: an empty selection is not forwarded to be caught '
                         'by a loop')
        self.playback.play.assert_not_called()


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class FolderQueueRemovalTest(PlaylistActionHarness, unittest.TestCase):
    """The removal route addressed in **display rows**, on a queue where the two
    index spaces do not coincide.

    Every other presenter-route fixture in this file builds its queue with
    ``build_from_tracks``, which makes one ``FileNode`` per track -- so the visible
    row and ``DisplayEntry.node_idx`` are the same number and a call that passed the
    wrong space would still remove the right songs. That coincidence is why this
    class exists: ``QueueService.build_from_folders``
    (``service/queue_service.py:141``) produces the shape where they diverge, one
    folder row plus one row per track, all carrying the *same* ``node_idx``:

    ====  ================  ==========  ==================
    row   shows             ``node_idx``  ``sub_index``
    ====  ================  ==========  ==================
    0     folder Alpha      0           -1  (``is_folder``)
    1     track0            0           0
    2     track1            0           1
    3     folder Beta       1           -1  (``is_folder``)
    4     track2            1           0
    5     track3            1           1
    ====  ================  ==========  ==================

    Removing [1, 2] by node index would delete node 1 and node 2 -- i.e. all of
    folder Beta and nothing else -- while the display-row reading deletes exactly the
    two Alpha tracks. Both readings are green on a flat queue; only one of them is
    what the user selected here. The rows are asserted by **path**, never by index,
    because an index assertion is exactly what the two spaces make unreadable.
    """

    FOLDER_ROWS = 6  # 2 folders + 4 tracks

    def _folder_data(self) -> dict:
        """Two folders, two tracks each, paths from the flat fixture's own table."""
        return {
            f'{LIB}/Alpha': _tracks(2),
            f'{LIB}/Beta': [Track(path=_index_path(i), title=f'Track {i}')
                            for i in (2, 3)],
        }

    def _load_folders(self) -> None:
        """Build through ``build_from_folders`` and prove the index spaces diverged.

        The precondition is asserted, not assumed: without it every assertion below
        would also pass on a flat queue, which is the whole failure mode this class
        exists to close.
        """
        self.queue.build_from_folders(self._folder_data())
        entries = self.queue.get_display_entries()
        self.assertEqual(self.FOLDER_ROWS, len(entries),
                         'the folder fixture did not produce folder rows on top of '
                         'its tracks, so the two index spaces still coincide')
        node_column = [entry.node_idx for entry in entries]
        self.assertEqual([0, 0, 0, 1, 1, 1], node_column,
                         'display row == node_idx again: this queue is not a shape '
                         'that can tell the two spaces apart')
        self.assertEqual([True, False, False, True, False, False],
                         [entry.is_folder for entry in entries])
        self.assertEqual(self.FOLDER_ROWS, self.model.rowCount(),
                         'the queue shrank or grew before the view ever saw it')

    def _file_paths(self) -> list:
        """Surviving **track** paths, in display order, folder rows dropped.

        Deliberately not :meth:`_queue_paths`: a folder entry carries ``full_path ==
        ''``, so the flat-queue reader would mix empty strings into the comparison
        and an assertion about "which songs are left" would be reading folder rows as
        songs.
        """
        return [entry.full_path for entry in self.queue.get_display_entries()
                if not entry.is_folder]

    def _row_kinds(self) -> list:
        return [('folder' if entry.is_folder else 'track')
                for entry in self.queue.get_display_entries()]

    def test_batch_removal_deletes_the_selected_songs_not_their_nodes(self):
        """[1, 2] -- the two Alpha tracks -- leaves both Beta tracks intact.

        Covers spec §4.2's descending rule on the shape that makes it bite (rows 1
        and 2 are siblings of one folder: removing row 1 first renumbers row 2 under
        the ascending reading) and the emptied-folder branch of
        ``service/queue_service.py:506-509`` in the same step: once both Alpha tracks
        are gone the folder itself must stop being a row, or the list shows a folder
        that contains nothing.
        """
        self._load_folders()
        self._forget_calls()

        self.presenter._on_remove_tracks([1, 2])

        self.assertEqual([2, 1], self.queue.removals(),
                         'spec §4.2: descending, and in the display space the '
                         'selection was written in')
        self.assertEqual([self._path_of(2), self._path_of(3)], self._file_paths(),
                         'the wrong songs went: a node-index reading deletes Beta '
                         'whole and leaves Alpha alone')
        self.assertEqual(['folder', 'track', 'track'], self._row_kinds(),
                         'an emptied folder stayed as a row')
        self.assertEqual(3, self.model.rowCount(),
                         'the visible list did not follow the queue')
        self.assertEqual(self._file_paths(),
                         [path for path in (
                             self.playlist.get_entry_at(row).full_path
                             for row in range(self.model.rowCount()))
                          if path],
                         'the view shows different songs than the queue holds')

    def test_folder_row_removal_takes_the_whole_node(self):
        """The ``entry.is_folder`` branch: row 3 is folder Beta, so it is Beta's turn.

        One row in, two songs out, and the rows above it untouched -- the branch at
        ``queue_service.py:506-509`` deletes ``self._queue_nodes[entry.node_idx]``,
        which is only correct because the folder entry's ``node_idx`` is the node's
        position and its display row is not (row 3 vs node 1).
        """
        self._load_folders()
        self._forget_calls()

        self.presenter._on_remove_tracks([3])

        self.assertEqual([self._path_of(i) for i in (0, 1)], self._file_paths(),
                         'a folder row that removes a single track, or nothing, is '
                         'the same index-space confusion in the other direction')
        self.assertEqual(['folder', 'track', 'track'], self._row_kinds())
        self.assertEqual([3], self.queue.removals())

    def test_selection_spanning_two_folders_keeps_the_interleaved_songs(self):
        """[2, 4]: one track from each folder, adjacent in neither index space.

        Row 2 is sub-index 1 of node 0 (track1) and row 4 is sub-index 0 of node 1
        (track2), so the batch deletes the middle two songs and leaves the outer two.
        The shape that punishes an implementation that resolved the rows through the
        wrong field: as node indices, [2, 4] names two nodes that do not exist and
        nothing is deleted at all; as sub-indices, it deletes track0 and track1.
        """
        self._load_folders()

        self.presenter._on_remove_tracks([2, 4])

        self.assertEqual([self._path_of(0), self._path_of(3)], self._file_paths())
        self.assertEqual(self.FOLDER_ROWS - 2, len(self.queue.get_display_entries()),
                         'two rows in, two rows out -- no folder was collateral')

    def test_playing_track_is_re_pinned_to_a_track_row_after_removal(self):
        """R8's re-pin on a folder queue: the filter at ``main_presenter.py:346``.

        Track2 plays on row 4; deleting row 1 moves it to row 3, which is **not** its
        node index either. The presenter must re-find it by path *and* must not accept
        a folder row as the answer -- folder entries carry ``full_path == ''``, so a
        scan without the ``not entry.is_folder`` filter could only match one by an
        empty playing path, which the guard above already rejects. The filter is
        therefore a **defensive** clause here rather than a reachable branch, and the
        assertion below pins the observable it protects: the position lands on the
        row that actually holds the song.
        """
        self._load_folders()
        playing = self._play(4)
        self.assertEqual(self._path_of(2), playing.path)
        self.assertEqual(4, self.model.get_playing_index())
        self._forget_calls()

        self.presenter._on_remove_tracks([1])

        self.assertEqual([self._path_of(i) for i in (1, 2, 3)], self._file_paths())
        position = self.queue.get_current_position()
        self.assertEqual(3, position.display_index,
                         'the highlight did not follow the song to its new row')
        surviving = self.queue.get_display_entries()[position.display_index]
        self.assertFalse(surviving.is_folder,
                         'the re-pin landed on a folder row: the playing track is '
                         'not a folder, and main_presenter.py:346 exists for this')
        self.assertEqual(self._path_of(2), surviving.full_path)
        self.assertEqual(3, self.model.get_playing_index(),
                         'the view highlight and the queue position disagree')
        self.assertEqual(self._path_of(2), self.queue.get_current_track().path,
                         'R8: a stale node index reads another song after a deletion')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class QueuePositionAfterRemovalCharacterizationTest(unittest.TestCase):
    """R8 as a **fact about the queue**, not as endorsed behaviour.

    Characterization test: every assertion below describes what
    ``QueueService.remove_at_display_index`` does today, so that

    * the identity re-resolution in ``MainPresenter._on_remove_tracks`` is not read
      as unexplained paranoia by the next person;
    * the queue-layer debt has a red test to delete when batch 5 (队列变更契约) fixes
      it -- at that point these assertions should flip, and the presenter's
      compensation can be simplified.

    It is **not** a claim that answering T3 while T2 was removed is acceptable: it is
    the reason batch 3 may not trust that reading. ``clear()`` at
    ``service/queue_service.py:478-484`` resets ``_position``; the row-by-row path at
    ``:486-513`` only rebuilds the display entries. That asymmetry is the trap.

    Flat five-track queue, T2 playing, one shape per subTest -- the first two are the
    shapes that silently play the wrong song, the third is the one that gets lucky.
    """

    def _queue_playing_t2(self) -> QueueService:
        queue = QueueService()
        queue.build_from_tracks(_tracks(5))
        self.assertIsNotNone(queue.set_position_by_display_index(2))
        return queue

    def test_remove_at_display_index_does_not_maintain_the_playback_position(self):
        stale = (
            # what was removed, what the queue now *says* is playing
            ('playing row itself (index 2)', [2], 'Track 3'),
            ('a row above the playing one (index 0)', [0], 'Track 3'),
            ('a row below the playing one (index 4)', [4], 'Track 2'),
        )
        for case, indices, reported in stale:
            with self.subTest(case=case):
                queue = self._queue_playing_t2()
                for index in indices:
                    self.assertTrue(queue.remove_at_display_index(index))
                current = queue.get_current_track()
                self.assertIsNotNone(current, case)
                self.assertEqual(reported, current.title,
                                 f'{case}: the queue reads its own stale node index '
                                 f'against the shrunken node list. Removing a row at '
                                 f'or above the playing one names the *next* song; '
                                 f'only a row below leaves it alone. Batch 5 owns the '
                                 f'fix -- see this class docstring')
                self.assertEqual(2, queue.get_current_position().display_index,
                                 f'{case}: display_index is never recomputed either')

    def test_removing_the_tail_is_the_only_shape_that_fails_safe(self):
        """Why one test would have missed R8: an out-of-range node index answers None.

        Removing T2 *and* the tail leaves the stale index past the end, so
        ``get_current_track()`` returns ``None`` -- the safe answer. Every other
        shape stays in range and names the wrong song, which is exactly the case a
        single "remove the playing row and expect nothing" test would have gone green
        on.
        """
        queue = self._queue_playing_t2()
        for index in (4, 3, 2):
            self.assertTrue(queue.remove_at_display_index(index))

        self.assertEqual([_index_path(0), _index_path(1)],
                         [entry.full_path for entry in queue.get_display_entries()])
        self.assertIsNone(queue.get_current_track())
        self.assertEqual(2, queue.get_current_position().display_index,
                         'still stale: the safe reading comes from the position '
                         'being *wrong but out of range*, not from maintenance')


if __name__ == '__main__':
    unittest.main(verbosity=2)
