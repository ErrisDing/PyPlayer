#!/usr/bin/env python3
"""批次 4 Task 6：播放列表模型的四个 role 与**定向**行更新入口。

Task 5 把元数据送到了 ``DisplayEntry`` 上，Task 7 会把 sweep 的迟到结果一行一行喂进
视图。这一步的全部风险都在"一行"两个字上：逐行填充最容易被顺手做成整表重建
（``beginResetModel`` 一行代码就能"刷好"），而整表 reset 会抖掉选中、滚动与视图自己的
状态 —— spec §6 的"标题不许因补元数据而闪"在模型这一侧的同一条款就是它。

所以本文件的计数器全部**连信号**，不去 patch 实例方法。这是本机 PyQt 的实测事实：Qt
只在「类型」上查找 Python 覆写，往实例上挂补丁（``model.removeRows = recorder``）C++
侧永远不会回头问它，记录器恒空、读它的断言恒绿。连接 ``layoutChanged`` / ``modelReset``
/ ``modelAboutToBeReset`` / ``rowsAboutToBe(Removed|Inserted)`` / ``rows(Removed|Inserted)``
记次数，连接 ``dataChanged`` 记 ``(top, bottom, roles)``，"不发 reset" 才是可证伪的
（变异取证 ① 就是把实现换成 reset 跑一次，红在 ``modelReset`` 计数上）。

两层薄转发按仓里既有形状：``MainWindow.update_row_metadata`` →
``PlaylistView.update_row_metadata`` → ``PlaylistModel.update_row_metadata``，对齐
``set_playlist_entries``→``set_entries``（``view/main_window.py:687-689``）与
``highlight_current_track``→``set_current_playing``（``:683-685``）——presenter 只认
MainWindow。越界行号一律 no-op：sweep 的迟到结果撞上"表已经变短"是正常路况，不是错误。

``MetadataStateRole`` 返回的是 ``str``，取值就是 ``service.metadata_store`` 导出的那三个
常量（裁定 B4-R5）：不另造枚举、不用 int，视图层与仓库侧共用同一份拼写。搬运的三个状态
都必须有形状，包括 ``(md=None, state='unknown')`` —— "sweep 答不上来"那一格到视图层就是
它，与 ``(None, 'pending')`` 的"还没试过"共用一份空值（裁定 B4-R17）。

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_playlist_metadata_model -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PyQt6.QtCore import QModelIndex, QItemSelection, QItemSelectionModel, Qt
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from core.library_manager import Track
from service.metadata_store import (
    RowMetadata,
    STATE_KNOWN,
    STATE_PENDING,
    STATE_UNKNOWN,
)
from service.queue_service import QueueService
from tests.test_view_smoke import make_app, make_manager
from view.models.playlist_model import PlaylistModel

LIB = '/media/rock'
KNOWN = RowMetadata(artist='The Trio', album='Blue Notes', duration=227.0)
EMPTY = RowMetadata(artist=None, album=None, duration=None)
#: The four roles ``update_row_metadata`` is allowed to announce, as a set: a fifth
#: role (or a swap of two of them) cannot slip past an order-insensitive comparison.
#: Read through the function rather than a module constant so this file imports (and
#: each test fails on its own assertion) before Task 6 lands.
def _four_roles() -> set:
    return {PlaylistModel.DurationRole, PlaylistModel.ArtistRole,
            PlaylistModel.AlbumRole, PlaylistModel.MetadataStateRole}


def _path(n: int) -> str:
    return f'{LIB}/track{n}.mp3'


def _entries(count: int = 3):
    """``count`` file rows from a real ``QueueService``, states cycling known/unknown/pending.

    Fed through Task 5's ``set_metadata`` rather than hand-built, so this file
    cannot pass against entry objects the queue would never produce -- and so the
    row numbers here are display rows of a live table.
    """
    queue = QueueService()
    queue.build_from_tracks([Track(path=_path(n), title=f'Track {n}')
                             for n in range(count)])
    queue.set_metadata({_path(n): [KNOWN, EMPTY, None][n % 3]
                        for n in range(count)})
    return queue.get_display_entries()


def _states(model: PlaylistModel) -> list:
    """The state word of every row -- the cheapest whole-table snapshot."""
    return [model.data(model.index(row), PlaylistModel.MetadataStateRole)
            for row in range(model.rowCount())]


class ModelSignals:
    """Every signal a targeted row update must not touch, counted.

    Connected, never patched: an attribute assigned onto a Qt *instance* is
    invisible to the C++ side, so a patched "recorder" reports zero of everything
    and turns the assertions below true by construction.
    """

    def __init__(self, model: PlaylistModel):
        self.data_changed: list = []
        self.counts = {'layoutChanged': 0, 'modelAboutToBeReset': 0,
                       'modelReset': 0, 'rowsAboutToBeInserted': 0,
                       'rowsInserted': 0, 'rowsAboutToBeRemoved': 0,
                       'rowsRemoved': 0}
        model.layoutChanged.connect(self._counter('layoutChanged'))
        model.modelAboutToBeReset.connect(self._counter('modelAboutToBeReset'))
        model.modelReset.connect(self._counter('modelReset'))
        model.rowsAboutToBeInserted.connect(self._counter('rowsAboutToBeInserted'))
        model.rowsInserted.connect(self._counter('rowsInserted'))
        model.rowsAboutToBeRemoved.connect(self._counter('rowsAboutToBeRemoved'))
        model.rowsRemoved.connect(self._counter('rowsRemoved'))
        model.dataChanged.connect(self._data_changed)

    def _counter(self, name: str):
        def bump(*_args):
            self.counts[name] += 1
        return bump

    def _data_changed(self, top, bottom, roles):
        self.data_changed.append((top.row(), bottom.row(), frozenset(roles)))

    @property
    def rebuild_count(self) -> int:
        """Anything that resets, relayouts or inserts/removes rows."""
        return sum(self.counts.values())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class RoleContractTest(unittest.TestCase):
    """The four roles sit after ``UserRole + 1..6`` and answer one row per state."""

    def setUp(self):
        self.model = PlaylistModel()
        self.model.set_entries(_entries(3))

    def test_role_numbers_follow_the_existing_six(self):
        numbers = sorted([PlaylistModel.DurationRole, PlaylistModel.ArtistRole,
                          PlaylistModel.AlbumRole,
                          PlaylistModel.MetadataStateRole])
        self.assertEqual(
            [Qt.ItemDataRole.UserRole + n for n in (7, 8, 9, 10)], numbers)
        taken = {PlaylistModel.IsPlayingRole, PlaylistModel.IsFolderRole,
                 PlaylistModel.NodeIndexRole, PlaylistModel.SubIndexRole,
                 PlaylistModel.FullPathRole, PlaylistModel.RelativePositionRole}
        self.assertEqual(set(), taken & set(numbers),
                         'a new role collides with an existing one')

    def test_known_row_answers_the_three_values_and_the_state_word(self):
        row = self.model.index(0)
        self.assertEqual(227.0, self.model.data(row, PlaylistModel.DurationRole))
        self.assertEqual('The Trio',
                         self.model.data(row, PlaylistModel.ArtistRole))
        self.assertEqual('Blue Notes',
                         self.model.data(row, PlaylistModel.AlbumRole))
        state = self.model.data(row, PlaylistModel.MetadataStateRole)
        self.assertIsInstance(state, str)
        self.assertEqual(STATE_KNOWN, state)

    def test_unknown_row_answers_empty_values_with_the_unknown_word(self):
        """B4-R8 across the model boundary: three ``None`` values are *present*."""
        row = self.model.index(1)
        self.assertIsNone(self.model.data(row, PlaylistModel.DurationRole))
        self.assertIsNone(self.model.data(row, PlaylistModel.ArtistRole))
        self.assertIsNone(self.model.data(row, PlaylistModel.AlbumRole))
        self.assertEqual(STATE_UNKNOWN,
                         self.model.data(row, PlaylistModel.MetadataStateRole))

    def test_pending_row_answers_the_pending_word(self):
        row = self.model.index(2)
        self.assertIsNone(self.model.data(row, PlaylistModel.DurationRole))
        self.assertEqual(STATE_PENDING,
                         self.model.data(row, PlaylistModel.MetadataStateRole))

    def test_invalid_index_answers_nothing_for_every_new_role(self):
        for role in sorted(_four_roles()):
            with self.subTest(role=role):
                variant = self.model.data(QModelIndex(), role)
                self.assertTrue(variant.isNull(),
                                f'role {role} invented a value for an invalid index')

    def test_existing_roles_still_answer(self):
        """The new roles must not disturb what the delegate already reads."""
        row = self.model.index(0)
        self.assertEqual('Track 0',
                         self.model.data(row, Qt.ItemDataRole.DisplayRole))
        self.assertEqual(_path(0),
                         self.model.data(row, PlaylistModel.FullPathRole))


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class UpdateRowMetadataTest(unittest.TestCase):
    """``update_row_metadata`` = one ``dataChanged`` for four roles, nothing else."""

    def setUp(self):
        self.app = make_app()
        self.model = PlaylistModel()
        self.model.set_entries(_entries(3))
        self.signals = ModelSignals(self.model)

    def test_update_emits_exactly_one_datachange_for_the_four_roles(self):
        self.model.update_row_metadata(1, KNOWN, STATE_KNOWN)

        self.assertEqual(1, len(self.signals.data_changed),
                         f'a targeted row update emitted {self.signals.data_changed}')
        top, bottom, roles = self.signals.data_changed[0]
        self.assertEqual((1, 1), (top, bottom),
                         'the update announced a range instead of one row')
        self.assertEqual(_four_roles(), set(roles))

    def test_update_emits_no_layout_change_and_no_reset(self):
        self.model.update_row_metadata(0, KNOWN, STATE_KNOWN)

        self.assertEqual(0, self.signals.counts['layoutChanged'])
        self.assertEqual(0, self.signals.counts['modelReset'])
        self.assertEqual(0, self.signals.rebuild_count)

    def test_the_updated_row_reads_the_new_values(self):
        self.model.update_row_metadata(2, KNOWN, STATE_KNOWN)

        row = self.model.index(2)
        self.assertEqual(227.0, self.model.data(row, PlaylistModel.DurationRole))
        self.assertEqual('The Trio',
                         self.model.data(row, PlaylistModel.ArtistRole))
        self.assertEqual('Blue Notes',
                         self.model.data(row, PlaylistModel.AlbumRole))
        self.assertEqual(STATE_KNOWN,
                         self.model.data(row, PlaylistModel.MetadataStateRole))

    def test_a_none_payload_clears_the_columns_and_marks_pending(self):
        """The wipe shape: values gone *and* the state word back to pending, in one call."""
        self.model.update_row_metadata(0, None, STATE_PENDING)

        row = self.model.index(0)
        self.assertIsNone(self.model.data(row, PlaylistModel.DurationRole))
        self.assertIsNone(self.model.data(row, PlaylistModel.ArtistRole))
        self.assertIsNone(self.model.data(row, PlaylistModel.AlbumRole))
        self.assertEqual(STATE_PENDING,
                         self.model.data(row, PlaylistModel.MetadataStateRole))

    def test_a_none_payload_with_the_unknown_word_stays_unknown(self):
        """M2: ``(md=None, state='unknown')`` 是"sweep 答不上来"那一格的形状。

        上面那条只覆盖 ``(None, 'pending')``，于是"值全空 + 状态词在场"这一形状在模型
        边界上没有任何用例。它必须是 ``unknown`` 而**不是** ``pending``：裁定 B4-R17 的
        理由在这里同样成立 —— 一格"没有值"可以有两种来历，delegate（Task 8）靠这个词决定
        画加载记号还是画"取不到"的记号。若哪天有人让 ``update_row_metadata`` 从值反推词
        （``state = state_for_values(md)``），这条会红而上面那条不会。
        """
        self.model.update_row_metadata(0, None, STATE_UNKNOWN)

        row = self.model.index(0)
        self.assertIsNone(self.model.data(row, PlaylistModel.DurationRole))
        self.assertIsNone(self.model.data(row, PlaylistModel.ArtistRole))
        self.assertIsNone(self.model.data(row, PlaylistModel.AlbumRole))
        state = self.model.data(row, PlaylistModel.MetadataStateRole)
        self.assertIsInstance(state, str)
        self.assertEqual(STATE_UNKNOWN, state)
        self.assertNotEqual(STATE_PENDING, state,
                            'the word was re-derived from the empty values')
        self.assertEqual([(0, 0, _four_roles())],
                         [(t, b, set(r)) for t, b, r in self.signals.data_changed],
                         'the unknown shape must still announce exactly one row')

    def test_other_rows_keep_their_own_columns_and_states(self):
        self.model.update_row_metadata(1, KNOWN, STATE_KNOWN)

        self.assertEqual('The Trio',
                         self.model.data(self.model.index(0),
                                         PlaylistModel.ArtistRole))
        self.assertEqual(227.0,
                         self.model.data(self.model.index(0),
                                         PlaylistModel.DurationRole))
        self.assertEqual(STATE_PENDING,
                         self.model.data(self.model.index(2),
                                         PlaylistModel.MetadataStateRole))
        self.assertIsNone(self.model.data(self.model.index(2),
                                          PlaylistModel.DurationRole))

    def test_row_count_and_states_of_the_other_rows_are_untouched(self):
        before = _states(self.model)
        self.model.update_row_metadata(0, EMPTY, STATE_UNKNOWN)

        self.assertEqual(3, self.model.rowCount())
        self.assertEqual([STATE_UNKNOWN, STATE_UNKNOWN, STATE_PENDING],
                         _states(self.model))
        self.assertNotEqual(before, _states(self.model),
                            'the targeted row did not actually change')

    def test_updating_a_row_does_not_move_the_playing_highlight(self):
        model = PlaylistModel()
        model.set_entries(_entries(3))
        model.set_current_playing(2)
        signals = ModelSignals(model)

        model.update_row_metadata(0, KNOWN, STATE_KNOWN)

        self.assertEqual(2, model.get_playing_index())
        self.assertTrue(model.data(model.index(2), PlaylistModel.IsPlayingRole))
        self.assertEqual([(0, 0, _four_roles())],
                         [(t, b, set(r)) for t, b, r in signals.data_changed])

    def test_out_of_range_rows_are_no_ops(self):
        states_before = _states(self.model)

        for row in (-1, 3, 99):
            with self.subTest(row=row):
                self.model.update_row_metadata(row, KNOWN, STATE_KNOWN)

        self.assertEqual([], self.signals.data_changed)
        self.assertEqual(0, self.signals.rebuild_count)
        self.assertEqual(3, self.model.rowCount())
        self.assertEqual(states_before, _states(self.model))
        self.assertEqual([STATE_KNOWN, STATE_UNKNOWN, STATE_PENDING], states_before)
        self.assertIsNone(self.model.data(self.model.index(2),
                                          PlaylistModel.DurationRole))


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ViewEntryPointTest(unittest.TestCase):
    """``PlaylistView.update_row_metadata`` forwards; rows and selection stay put."""

    def setUp(self):
        self.app = make_app()
        from view.widgets.playlist_view import PlaylistView

        self.view = PlaylistView(make_manager())
        self.view.resize(400, 300)
        self.view.show()
        self.app.processEvents()
        self.view.set_entries(_entries(5))
        self.app.processEvents()
        self.model = self.view._list_view.model()
        self.signals = ModelSignals(self.model)

    def tearDown(self):
        self.view.close()

    def _select(self, *rows):
        selection = QItemSelection()
        for row in rows:
            selection.select(self.model.index(row), self.model.index(row))
        self.view._list_view.selectionModel().select(
            selection,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows)
        self.app.processEvents()

    def test_view_forward_updates_the_model_row(self):
        self.view.update_row_metadata(1, KNOWN, STATE_KNOWN)

        self.assertEqual(227.0, self.model.data(self.model.index(1),
                                                PlaylistModel.DurationRole))
        self.assertEqual([(1, 1)],
                         [(t, b) for t, b, _roles in self.signals.data_changed])
        self.assertEqual(0, self.signals.rebuild_count)

    def test_view_forward_keeps_the_rows_and_the_selection(self):
        self._select(0, 2)
        rows_before = self.model.rowCount()
        selection_before = self.view.selected_display_indices()

        self.view.update_row_metadata(1, KNOWN, STATE_KNOWN)
        self.app.processEvents()

        self.assertEqual([0, 2], selection_before,
                         'the fixture lost the selection it is meant to protect')
        self.assertEqual(selection_before, self.view.selected_display_indices(),
                         'a per-row metadata update moved the user\'s selection')
        self.assertEqual(rows_before, self.model.rowCount())

    def test_view_forward_rejects_out_of_range_rows_without_touching_anything(self):
        self._select(3)
        selection_before = self.view.selected_display_indices()
        states_before = _states(self.model)
        last_row = self.model.rowCount() - 1

        for row in (-1, self.model.rowCount(), 10 ** 4):
            with self.subTest(row=row):
                self.view.update_row_metadata(row, KNOWN, STATE_KNOWN)

        self.assertEqual([], self.signals.data_changed)
        self.assertEqual(0, self.signals.rebuild_count)
        self.assertEqual(states_before, _states(self.model))
        self.assertEqual(selection_before, self.view.selected_display_indices())
        self.assertNotEqual(STATE_KNOWN,
                            self.model.data(self.model.index(last_row),
                                            PlaylistModel.MetadataStateRole),
                            'an out-of-range update wrote a live row')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class WholeListRouteCarriesNoRepaintTest(unittest.TestCase):
    """Why Task 7 may not refresh a row through ``set_entries`` (characterization).

    ``PlaylistView.set_entries`` → ``PlaylistModel.update_entries`` compares only
    ``display_text`` and ``is_playing`` (``view/models/playlist_model.py:151-154``),
    and the entries it is handed are the *same objects* the queue holds
    (``get_display_entries`` copies the list, not the rows). So after
    ``QueueService.apply_metadata`` the model's rows already *read* the new values
    and yet nothing is announced: no ``dataChanged``, no repaint. That asymmetry is
    the whole reason ``update_row_metadata`` is a separate entry point instead of a
    convenience, and Task 7's sweep callback is the consumer this pin speaks to.
    """

    def setUp(self):
        self.app = make_app()
        self.queue = QueueService()
        self.queue.build_from_tracks([Track(path=_path(n), title=f'Track {n}')
                                      for n in range(3)])
        self.model = PlaylistModel()
        self.model.set_entries(self.queue.get_display_entries())
        self.signals = ModelSignals(self.model)

    def test_a_queue_side_update_reaches_the_model_data_but_announces_nothing(self):
        self.queue.apply_metadata(_path(1), KNOWN, STATE_KNOWN)
        self.model.update_entries(self.queue.get_display_entries())

        row = self.model.index(1)
        self.assertEqual(227.0, self.model.data(row, PlaylistModel.DurationRole),
                         'the entries are no longer shared objects; re-check this '
                         'file: the values arriving by aliasing is half of the pin')
        self.assertEqual(STATE_KNOWN,
                         self.model.data(row, PlaylistModel.MetadataStateRole))
        self.assertEqual([], self.signals.data_changed,
                         'update_entries grew a metadata comparison; Task 7 can now '
                         'refresh rows through the whole-list route and this pin, '
                         'not the other way round')
        self.assertEqual(0, self.signals.rebuild_count)

    def test_the_targeted_entry_point_is_the_one_that_announces(self):
        """The same change, made through ``update_row_metadata``, is repaintable."""
        self.queue.apply_metadata(_path(1), KNOWN, STATE_KNOWN)
        self.signals.data_changed.clear()

        self.model.update_row_metadata(1, KNOWN, STATE_KNOWN)

        self.assertEqual(1, len(self.signals.data_changed))


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MainWindowForwardingTest(unittest.TestCase):
    """The presenter only knows ``MainWindow``: one forward down, no side effects."""

    def setUp(self):
        self.app = make_app()
        from view.main_window import MainWindow

        self.window = MainWindow(make_manager())
        self.window.set_playlist_entries(_entries(3))
        self.app.processEvents()
        self.model = self.window._playlist_view._list_view.model()

    def tearDown(self):
        self.window.close()

    def test_main_window_forwards_to_the_playlist_model(self):
        signals = ModelSignals(self.model)

        self.window.update_row_metadata(1, KNOWN, STATE_KNOWN)

        self.assertEqual(STATE_KNOWN,
                         self.model.data(self.model.index(1),
                                         PlaylistModel.MetadataStateRole))
        self.assertEqual([(1, 1, _four_roles())],
                         [(t, b, set(r)) for t, b, r in signals.data_changed])
        self.assertEqual(0, signals.rebuild_count)

    def test_main_window_out_of_range_is_a_no_op(self):
        signals = ModelSignals(self.model)
        states_before = _states(self.model)

        self.window.update_row_metadata(7, KNOWN, STATE_KNOWN)

        self.assertEqual([], signals.data_changed)
        self.assertEqual(0, signals.rebuild_count)
        self.assertEqual(states_before, _states(self.model))


if __name__ == '__main__':
    unittest.main(verbosity=2)
