#!/usr/bin/env python3
"""批次 4 Task 5：行数据通路 —— ``DisplayEntry`` 携带元数据 + 定向行更新。

三列（时长/艺人/专辑）要上屏，先得有人把值**送到显示行上**。这一层的全部难点都不在
"能不能读到值"，而在"值活在哪儿"：

* **值活在队列的一份 path→行元数据 表上，不是只活在 ``DisplayEntry`` 上**（brief 的
  实测理由）。``_rebuild_display_entries()`` 在每次队列结构变化时**重新造一批**
  ``DisplayEntry``（``service/queue_service.py:138,161,167,523``）。若定向更新只写旧
  条目对象，"移除一首歌 → 其余行的三列全部退回 ``⋯``"这条会是**绿的**，而它是本任务
  存在的理由。因此 ``MetadataSurvivesRebuildTest`` 是本文件的中心，
  ``ApplyMetadataTest`` 只是它的前提。
* **查表发生在建表时，不是画一行时**（spec §4.9"不做第二次查找"）。
  ``_rebuild_display_entries`` 从那份表填新条目；``apply_metadata`` 同时写那份表和
  当前活着的条目，两者是同一份状态的两个写入点。
* **三态只有 ``service.metadata_store`` 的那三个字符串**（裁定 B4-R5），队列侧一律
  ``import`` 常量，不重打字面量。``MetadataStateRole``（Task 6）返回的就是这个值。
* **"有没有元数据"只许 ``is None``**（裁定 B4-R8）：三键全 ``None`` 的 ``RowMetadata``
  是**在场的载荷**（"取过了，啥也没有"→ ``unknown``），真值判断会把它塌回 ``pending``，
  正好把判据 6 要保护的"已试过"状态弄丢。``test_empty_row_is_unknown_not_pending`` 是
  这条的钉子；"假值**但在场**"（``duration=0.0``、``artist=''``）那半边的样本落在
  ``tests/test_metadata_store.py`` 的 ``SharedTriStateRuleTest`` —— 判据既然只有一个作者，
  钉子也只需要一处。
* **``Track`` 不改**（spec §4.9）：``Track.duration`` 的 ``0.0`` 与"未知"同源，不能当
  显示依据。``test_track_columns_are_not_the_display_source`` 把这条钉住——载荷给的是
  一个 ``duration=0.0`` 的 ``Track``，行上显示的仍是"未知"。

定向更新走**返回值**（``list[int]``），本任务**不新增信号**：早期草案的
``display_row_metadata_changed(int, str)`` 按批次 3 终审 R9（信号必须有落地站）删掉了，
Task 7 拿行号逐行走 Task 6 的视图入口。``SignalCensusTest`` 把这个裁定钉成一条断言，
免得后来人"顺手补一个信号"。

三态判据**只有一个作者**：``service.metadata_store.state_for_values``。审查发现 I1 打的
是队列曾经抄过一份（``_state_for_payload``），而"两边对账"的用例挡不住那份抄本被改成真值
判断（探针 A：23 条全绿）。所以 ``set_metadata`` 现在**调用** store 的那个纯函数，
``QueueCallsTheSharedRuleTest`` 把"必须同源"这件事本身钉成可红的两条：同一个函数对象 + 哨兵
替换后队列侧读出哨兵。裁定 B4-R6 只禁止 ``service/metadata_store.py`` import 队列，
反方向本来就有（本文件早就 import 该模块的常量与 ``RowMetadata``）。

那份表存的是 ``(值, 状态词)`` **一对**而不是 brief 字面的单个值（裁定 B4-R17）：
``md=None`` 同时是"没试过"和"试过、啥也没有"，单值表达不了 spec §4.1 要区分的两态。
``PairIsTheWholePointTest`` 钉的就是这件事：定向更新过的那一行**重建之后**仍拿着当时的
状态词，而 ``set_metadata({})``（切库）又把它收回 ``pending``。按 brief 字面"简化"回单值
表（探针 B）在 ``test_a_none_payload_carrying_the_unknown_word_stays_unknown`` 上必须红
—— 本轮变异 V5 实测正是这一条。

``store`` 在这里是被**读**的（裁定 B4-R6 允许的方向）：``QueueStateMatchesStoreStateTest``
拿 store 当参照系核对"整表换"的结果，``WarmReopenAsksForNothingTest`` 则把 store 与队列搭
成一份联合场景 —— 单看 ``store.validate()`` 永远不会因队列而红（审查发现 M4），所以那条
判据 5 的钉子改成"两侧的待办清单必须同时为空 / 同时非空"。

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_queue_metadata -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PyQt6.QtCore import QT_VERSION_STR, pyqtSignal  # noqa: F401 (presence probe)
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

from core.cache_manager import MD_KEYS, CachedFile
from core.library_manager import MediaFile, Track
from service import metadata_store, queue_service
from service.metadata_store import (
    LibraryMetadataStore,
    RowMetadata,
    STATE_KNOWN,
    STATE_PENDING,
    STATE_UNKNOWN,
)
from service.queue_service import QueueService

LIB = '/media/rock'


def _path(n: int) -> str:
    """The n-th library file, spelled the way the queue stores it."""
    return f'{LIB}/track{n}.mp3'


def _track(n: int) -> Track:
    """A queue track.

    ``artist``/``album``/``duration`` are deliberately **not** left empty: the point
    of Task 5 is that the row does not read them (spec §4.9), so a fixture that
    carries plausible values proves the display values come from the metadata
    table, not from the ``Track``.
    """
    return Track(path=_path(n), title=f'Track {n}',
                 artist='From Track', album='From Track', duration=1.0)


def _flat(*numbers: int) -> QueueService:
    """A ``QueueService`` of one ``FileNode`` per number (flat library shape)."""
    queue = QueueService()
    queue.build_from_tracks([_track(n) for n in numbers])
    return queue


def _folders() -> QueueService:
    """A folder queue where one path occupies **two** rows.

    Display layout: ``0`` is the folder header, ``1``/``2``/``3`` its tracks, and
    ``_path(0)`` appears twice (a real shape: the same file reached through two
    scan passes shows up twice inside one folder node). Row numbers therefore do
    **not** equal ``node_idx`` here, which is what the index-space mutation trips on.
    """
    queue = QueueService()
    queue.build_from_folders({f'{LIB}/Album': [_track(0), _track(1), _track(0)]})
    return queue


KNOWN = RowMetadata(artist='The Trio', album='Blue Notes', duration=227.0)
EMPTY = RowMetadata(artist=None, album=None, duration=None)


def _file_rows(queue: QueueService) -> list:
    """Non-folder entries, ascending by row -- the rows that carry the columns."""
    return [entry for entry in queue.get_display_entries() if not entry.is_folder]


class _CountingEntries(list):
    """The display list as an instrument: it journals how production consults it.

    Standing in for ``QueueService._display_entries`` (same ``DisplayEntry`` objects,
    same ``list`` semantics) turns "the sweep is quadratic in the library" into a
    *countable* claim -- ``iterations`` counts whole-table walks, ``item_reads``
    counts single-row lookups -- instead of a wall-clock assertion that would be the
    fragile shape this suite refuses.取证等级: test-side collaborator, swapped in and
    out around one call; the production mutation of the same variable is recorded
    separately in the report.
    """

    def __init__(self, items):
        super().__init__(items)
        self.iterations = 0
        self.item_reads = 0

    def reset(self) -> None:
        self.iterations = 0
        self.item_reads = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()

    def __getitem__(self, index):
        if isinstance(index, int):
            self.item_reads += 1
        return super().__getitem__(index)


def _values(entries) -> list:
    return [(e.duration, e.artist, e.album, e.metadata_state) for e in entries]


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class FreshRowsArePendingTest(unittest.TestCase):
    """A row nobody has fetched for yet is ``pending`` with three empty columns."""

    def test_new_entries_start_pending_with_no_values(self):
        queue = _flat(0, 1, 2)
        rows = _file_rows(queue)
        self.assertEqual(3, len(rows))
        for entry in rows:
            self.assertEqual(STATE_PENDING, entry.metadata_state)
            self.assertIsNone(entry.duration)
            self.assertIsNone(entry.artist)
            self.assertIsNone(entry.album)

    def test_track_columns_are_not_the_display_source(self):
        """spec §4.9: ``Track.duration == 0.0``/``artist`` must not leak into a row.

        ``_track()`` carries ``duration=1.0`` and both tags, and the row still
        reads ``None``/``pending`` -- so if a later change starts sourcing the
        columns from ``Track``, the row will say "0:00"/a value here instead.
        """
        queue = _flat(0)
        entry = _file_rows(queue)[0]
        self.assertEqual(1.0, queue._queue_nodes[0].track.duration,
                         'fixture lost the Track-side value it is meant to ignore')
        self.assertIsNone(entry.duration)
        self.assertIsNone(entry.artist)
        self.assertIsNone(entry.album)
        self.assertEqual(STATE_PENDING, entry.metadata_state)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class SetMetadataTest(unittest.TestCase):
    """``set_metadata`` is the whole-table fill: one call, every row, three states."""

    def test_set_metadata_fills_every_row_field_and_state(self):
        queue = _flat(0, 1, 2)
        queue.set_metadata({_path(0): KNOWN, _path(1): EMPTY, _path(2): None})

        first, second, third = _file_rows(queue)
        self.assertEqual((227.0, 'The Trio', 'Blue Notes', STATE_KNOWN),
                         (first.duration, first.artist, first.album,
                          first.metadata_state))
        # B4-R8: an all-None payload is *present*, so it is "tried, nothing".
        self.assertEqual((None, None, None, STATE_UNKNOWN),
                         (second.duration, second.artist, second.album,
                          second.metadata_state))
        self.assertEqual((None, None, None, STATE_PENDING),
                         (third.duration, third.artist, third.album,
                          third.metadata_state))

    def test_empty_row_is_unknown_not_pending(self):
        """The truthiness trap ruling B4-R8 names: ``if md:`` collapses this to pending."""
        queue = _flat(0)
        queue.set_metadata({_path(0): EMPTY})
        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_UNKNOWN, entry.metadata_state)
        self.assertIsNot(STATE_PENDING, entry.metadata_state)

    def test_partial_payload_is_known_and_keeps_its_none_fields(self):
        queue = _flat(0)
        queue.set_metadata({_path(0): RowMetadata(duration=12.5)})
        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_KNOWN, entry.metadata_state)
        self.assertEqual(12.5, entry.duration)
        self.assertIsNone(entry.artist)
        self.assertIsNone(entry.album)

    def test_folder_header_row_stays_pending(self):
        """Only file rows have a path to look up; the folder row owns no columns."""
        queue = _folders()
        queue.set_metadata({_path(0): KNOWN})
        header = queue.get_display_entries()[0]
        self.assertTrue(header.is_folder)
        self.assertEqual(STATE_PENDING, header.metadata_state)
        self.assertIsNone(header.artist)

    def test_mapping_is_a_replacement_not_a_merge(self):
        """The switch-library shape: a path missing from the new table is pending."""
        queue = _flat(0, 1)
        queue.set_metadata({_path(0): KNOWN, _path(1): KNOWN})
        queue.set_metadata({_path(0): KNOWN})
        first, second = _file_rows(queue)
        self.assertEqual(STATE_KNOWN, first.metadata_state)
        self.assertEqual(STATE_PENDING, second.metadata_state)
        self.assertIsNone(second.artist)

    def test_set_metadata_empty_mapping_returns_every_row_to_pending(self):
        """切库形状：``set_metadata({})`` 之后一切回 ``pending``。"""
        queue = _flat(0, 1, 2)
        queue.set_metadata({_path(0): KNOWN, _path(1): EMPTY})
        queue.apply_metadata(_path(2), KNOWN, STATE_KNOWN)

        queue.set_metadata({})

        for entry in _file_rows(queue):
            self.assertEqual(STATE_PENDING, entry.metadata_state,
                             f'{entry.full_path} survived the table wipe')
            self.assertIsNone(entry.duration)
            self.assertIsNone(entry.artist)
            self.assertIsNone(entry.album)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ApplyMetadataTest(unittest.TestCase):
    """``apply_metadata`` returns the **row numbers** it updated -- or ``[]``."""

    def test_hit_returns_the_row_and_updates_it(self):
        queue = _flat(0, 1, 2)
        rows = queue.apply_metadata(_path(1), KNOWN, STATE_KNOWN)

        self.assertEqual([1], rows)
        entry = queue.get_display_entries()[1]
        self.assertEqual(227.0, entry.duration)
        self.assertEqual('The Trio', entry.artist)
        self.assertEqual('Blue Notes', entry.album)
        self.assertEqual(STATE_KNOWN, entry.metadata_state)
        # Untouched neighbours stay pending: a targeted update is targeted.
        self.assertEqual(STATE_PENDING, queue.get_display_entries()[0].metadata_state)
        self.assertEqual(STATE_PENDING, queue.get_display_entries()[2].metadata_state)

    def test_miss_returns_no_rows_and_changes_nothing(self):
        queue = _flat(0, 1)
        rows = queue.apply_metadata(f'{LIB}/gone.flac', KNOWN, STATE_KNOWN)

        self.assertEqual([], rows)
        self.assertEqual([(None, None, None, STATE_PENDING)] * 2,
                         _values(_file_rows(queue)))

    def test_a_second_targeted_update_replaces_the_first(self):
        queue = _flat(0)
        queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)
        queue.apply_metadata(_path(0), EMPTY, STATE_UNKNOWN)

        self.assertEqual([0], queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN))
        entry = queue.get_display_entries()[0]
        self.assertEqual(227.0, entry.duration)
        self.assertEqual(STATE_KNOWN, entry.metadata_state)

    def test_one_path_on_two_rows_returns_and_updates_both_rows(self):
        """folder 队列里同一路径占两行时**两行都要返回并更新**。

        Otherwise the same song shows a length in one place and ``⋯`` in the other.
        The rows are ``1`` and ``3`` while both entries carry ``node_idx == 0`` --
        so a ``full_path``/``node_idx`` mix-up cannot produce this list.
        """
        queue = _folders()
        rows = queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)

        self.assertEqual([1, 3], rows)
        entries = queue.get_display_entries()
        for row in (1, 3):
            self.assertEqual(227.0, entries[row].duration, f'row {row} not updated')
            self.assertEqual('The Trio', entries[row].artist, f'row {row} not updated')
            self.assertEqual(STATE_KNOWN, entries[row].metadata_state)
        self.assertEqual(STATE_PENDING, entries[2].metadata_state,
                         'a sibling row of the same folder was updated too')
        self.assertEqual(STATE_PENDING, entries[0].metadata_state,
                         'the folder header row was updated; it owns no columns')

    def test_pending_payload_is_stored_as_pending(self):
        """``apply_metadata(path, None, STATE_PENDING)`` is the sweep's "still nothing"."""
        queue = _flat(0)
        queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)
        self.assertEqual([0], queue.apply_metadata(_path(0), None, STATE_PENDING))
        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_PENDING, entry.metadata_state)
        self.assertIsNone(entry.duration)

    def test_no_rows_no_work_and_nothing_remembered(self):
        """M6: the empty queue is the ``rows == []`` branch, in the open.

        A sweep result can legitimately arrive after the playlist was emptied but
        before ``set_metadata`` re-filled it. ``[]`` is then the whole answer -- and
        the values must not be quietly parked in the table either, or a file that
        no row ever asked about comes back filled when the queue is rebuilt (the
        same leak ``test_rebuild_for_a_path_the_table_never_saw_stays_pending``
        pins for a path that exists elsewhere in the table).
        """
        queue = QueueService()
        self.assertEqual([], queue.get_display_entries())
        self.assertEqual([], queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN))

        queue.build_from_tracks([_track(0)])
        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_PENDING, entry.metadata_state)
        self.assertIsNone(entry.duration)
        self.assertIsNone(entry.artist)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSurvivesRebuildTest(unittest.TestCase):
    """The reason this task exists: a rebuild must not wipe the columns.

    ``remove_at_display_index`` calls ``_rebuild_display_entries()``, which throws
    away every ``DisplayEntry`` object and constructs new ones (the four call sites
    in ``service/queue_service.py``). If a targeted update only wrote the entry it
    was holding, these assertions would be the only thing standing between the user
    and "remove a song, the whole playlist falls back to ``⋯``".
    """

    def test_targeted_update_survives_a_removal_rebuild(self):
        queue = _flat(0, 1, 2, 3)
        queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)
        queue.apply_metadata(_path(1), EMPTY, STATE_UNKNOWN)
        queue.apply_metadata(_path(2), KNOWN, STATE_KNOWN)

        self.assertTrue(queue.remove_at_display_index(3))

        rows = _file_rows(queue)
        self.assertEqual([_path(0), _path(1), _path(2)],
                         [e.full_path for e in rows])
        for entry in rows:
            self.assertNotEqual(STATE_PENDING, entry.metadata_state,
                                f'{entry.full_path} fell back to pending after a rebuild')
        self.assertEqual(227.0, rows[0].duration)
        self.assertEqual('The Trio', rows[0].artist)
        self.assertEqual(STATE_UNKNOWN, rows[1].metadata_state)
        self.assertIsNone(rows[1].duration)
        self.assertEqual(STATE_KNOWN, rows[2].metadata_state)

    def test_removed_row_leaves_the_other_rows_filled(self):
        """Removing the *updated* row must not shift the neighbours out of position.

        ``set_metadata`` replaces the table, so the applied row is re-declared here
        as well: what is being pinned is the state *after* the replacement rebuilds,
        not the lucky survival of a stale entry object.
        """
        queue = _flat(0, 1, 2)
        queue.apply_metadata(_path(1), KNOWN, STATE_KNOWN)
        queue.set_metadata({_path(0): EMPTY, _path(1): KNOWN, _path(2): EMPTY})

        self.assertTrue(queue.remove_at_display_index(0))
        rows = _file_rows(queue)
        self.assertEqual([_path(1), _path(2)], [e.full_path for e in rows])
        self.assertEqual(STATE_KNOWN, rows[0].metadata_state)
        self.assertEqual(227.0, rows[0].duration)
        self.assertEqual(STATE_UNKNOWN, rows[1].metadata_state)

        self.assertTrue(queue.remove_at_display_index(0))
        rows = _file_rows(queue)
        self.assertEqual(1, len(rows))
        self.assertEqual(_path(2), rows[0].full_path)
        self.assertEqual(STATE_UNKNOWN, rows[0].metadata_state)

    def test_folder_rebuild_after_removal_keeps_both_rows_of_one_path(self):
        queue = _folders()
        queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)

        # Drop the middle track; the duplicate path keeps occupying two rows.
        self.assertTrue(queue.remove_at_display_index(2))
        entries = queue.get_display_entries()
        self.assertTrue(entries[0].is_folder)
        filled = [e for e in entries if e.metadata_state == STATE_KNOWN]
        self.assertEqual(2, len(filled),
                         'the duplicated path lost one of its two rows on rebuild')
        self.assertEqual([_path(0), _path(0)], [e.full_path for e in filled])

    def test_set_metadata_fill_survives_a_rebuild(self):
        """The whole-table fill is stored the same way as the targeted one."""
        queue = _flat(0, 1)
        queue.set_metadata({_path(0): KNOWN, _path(1): KNOWN})
        self.assertTrue(queue.remove_at_display_index(1))
        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_KNOWN, entry.metadata_state)
        self.assertEqual(227.0, entry.duration)

    def test_rebuild_for_a_path_the_table_never_saw_stays_pending(self):
        """A miss is not remembered: the queue table mirrors the rows, the store is durable."""
        queue = _flat(0, 1)
        queue.apply_metadata(f'{LIB}/gone.flac', KNOWN, STATE_KNOWN)
        self.assertTrue(queue.remove_at_display_index(0))
        entry = _file_rows(queue)[0]
        self.assertEqual(_path(1), entry.full_path)
        self.assertEqual(STATE_PENDING, entry.metadata_state)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PairIsTheWholePointTest(unittest.TestCase):
    """裁定 B4-R17：那张表的值是 ``(RowMetadata, 状态词)`` **一对**，不是单个值。

    这一对不是审美选择。``md=None`` 同时是"没试过"（``pending``）与"试过、啥也没有"
    （``unknown``），单值表表达不了 spec §4.1 要区分的这两态，而生产默认就产出这个组合：
    提取抛异常时 ``metadata_service`` 交回 ``md=None``，store 那边落成一行的
    ``RowMetadata()``，``state_of`` 因此答 ``unknown``。表里若只存值，重建时按值重推，
    这一格就在**下一次结构变化之后**塌回 ``pending`` —— 审查者按 brief 字面模拟单值表
    （探针 B）时 23 条全绿、谁也没看见，症状是那一格永远显示"取到了吗？"。

    所以本类的三条都是**重建之后**才成立的断言：调用当场的值单值表也写对，差别只在重建。
    """

    def test_the_unknown_word_survives_a_rebuild(self):
        """三键全 ``None`` 的载荷（"试过、啥也没有"）经过重建仍是 ``unknown``。"""
        queue = _flat(0, 1, 2)
        queue.apply_metadata(_path(1), RowMetadata(), STATE_UNKNOWN)
        self.assertEqual(STATE_UNKNOWN,
                         _file_rows(queue)[1].metadata_state,
                         'fixture: the word is right before the rebuild')

        self.assertTrue(queue.remove_at_display_index(0))
        target = [e for e in _file_rows(queue) if e.full_path == _path(1)][0]
        self.assertEqual(STATE_UNKNOWN, target.metadata_state,
                         'a tried-but-empty row collapsed back to pending on rebuild')
        self.assertNotEqual(STATE_PENDING, target.metadata_state)
        self.assertIsNone(target.duration)
        self.assertIsNone(target.artist)
        self.assertIsNone(target.album)

    def test_a_none_payload_carrying_the_unknown_word_stays_unknown(self):
        """``(None, 'unknown')``：单值形状下 ``None`` 只能读成 ``pending``，所以塌了。

        This is the cell the single-value table cannot express at all: no values,
        and still "already tried". If a later change drops the pair, this is the
        assertion that goes red first.
        """
        queue = _flat(0, 1, 2)
        queue.apply_metadata(_path(1), None, STATE_UNKNOWN)

        self.assertTrue(queue.remove_at_display_index(0))
        target = [e for e in _file_rows(queue) if e.full_path == _path(1)][0]
        self.assertEqual(STATE_UNKNOWN, target.metadata_state,
                         'the pair was reduced to its value and the word was lost')
        self.assertIsNone(target.duration)

    def test_the_wipe_puts_the_same_path_back_to_pending(self):
        """反向：``set_metadata({})``（切库）之后同一路径必须是 ``pending``。

        The pair is not a ratchet -- the wipe has to overwrite the word, not merely
        the values, or the library being left would keep answering ``unknown`` for
        files the new library never fetched.
        """
        queue = _flat(0, 1, 2)
        queue.apply_metadata(_path(1), None, STATE_UNKNOWN)
        queue.apply_metadata(_path(2), RowMetadata(), STATE_UNKNOWN)

        queue.set_metadata({})

        by_path = {e.full_path: e for e in _file_rows(queue)}
        for path in (_path(1), _path(2)):
            self.assertEqual(STATE_PENDING, by_path[path].metadata_state,
                             f'{path} kept a tried-and-empty word across the wipe')
            self.assertIsNone(by_path[path].duration)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class QueueCallsTheSharedRuleTest(unittest.TestCase):
    """发现 I1：三态判据在仓库里**只许有一份**，而"只有一份"本身必须可红。

    修之前这里是两个作者（``queue_service._state_for_payload`` 与
    ``LibraryMetadataStore.state_of`` 的三段 ``if``），审查者把其中一份改成真值判断后
    全量 23 条仍绿（探针 A）——"事后对账"的用法挡不住抄本变质，因为两份实现对同一批
    样本可以永远同意。规则现在上移为 ``metadata_store.state_for_values``：``state_of``
    委托它（钉子见 ``tests/test_metadata_store.py`` 的 ``SharedTriStateRuleTest``），
    队列 import 它。本类钉的是"队列这份调用确实是同一个函数对象"这件事，
    把队列侧换回**任何**本地重复实现都必须在这里红。
    """

    def test_the_queue_holds_the_stores_function_object_itself(self):
        """同名也不行：必须是同一个对象，不是"看起来一样"的第二份实现。"""
        self.assertIs(metadata_store.state_for_values,
                      queue_service.state_for_values,
                      'queue_service re-authored the tri-state rule locally; '
                      'the store is its only author')

    def test_set_metadata_names_the_state_through_the_shared_rule(self):
        """行为半边：把共享规则换成哨兵，``set_metadata`` 的结果必须跟着变。

        两个名字都换：``queue_service`` 里 import 进来的那个绑定，和
        ``metadata_store`` 模块属性（以防调用写成 ``metadata_store.state_for_values``）。
        本地抄本用自己的名字或自己的代码，看不见哨兵，于是这里红。
        """
        sentinel = 'sentinel-from-the-shared-rule'
        seen: list = []
        queue_binding = queue_service.state_for_values
        store_binding = metadata_store.state_for_values
        try:
            def spy(md):
                seen.append(md)
                return sentinel

            queue_service.state_for_values = spy
            metadata_store.state_for_values = spy
            queue = _flat(0)
            queue.set_metadata({_path(0): KNOWN})
            entry = _file_rows(queue)[0]
            self.assertEqual(sentinel, entry.metadata_state,
                             'set_metadata named the state somewhere other than the '
                             'shared rule, so a second copy of it still exists')
        finally:
            queue_service.state_for_values = queue_binding
            metadata_store.state_for_values = store_binding
        self.assertIn(KNOWN, seen,
                      'the shared rule was never handed this payload')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class QueueStateMatchesStoreStateTest(unittest.TestCase):
    """``set_metadata`` 的结果等于 store 对同一条载荷的结论 —— 因为那是同一条规则。

    本类的定位自审查发现 I1 起改写：它**不是**"防两份实现分家"的钉子（分家已被
    ``QueueCallsTheSharedRuleTest`` 从源头堵掉，判据也只剩一个作者），而是把两处调用
    同一条规则的结果核对一遍，顺带覆盖 ``apply_metadata`` 把手递的那个词原样落地。
    载荷表里加了"假值但在场"的 ``artist=''``，但要说清楚：真值判断那种变质**不会**红在
    这里 —— 两边共用一个函数，输入一样输出自然一样（变异 V3 实测：本类全绿）。红的是
    ``tests/test_metadata_store.py`` 里判据自己的钉子，那才是"一个作者、一处钉子"的意思。
    """

    def test_queue_state_equals_store_state_for_the_same_payload(self):
        payloads = [KNOWN, EMPTY, RowMetadata(duration=4.0),
                    RowMetadata(artist=''), None]
        queue = _flat(0)
        path = _path(0)

        for md in payloads:
            store = LibraryMetadataStore()
            if md is not None:
                store.record(path, md, 1000, 100.0)
            expected = store.state_of(path)

            queue.set_metadata({path: md})
            entry = _file_rows(queue)[0]
            self.assertEqual(expected, entry.metadata_state,
                             f'payload {md}: queue and store disagree')

    def test_applied_state_is_handed_through_verbatim(self):
        """The sweep already knows the state; the queue must not re-derive it."""
        queue = _flat(0)
        queue.apply_metadata(_path(0), KNOWN, STATE_UNKNOWN)
        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_UNKNOWN, entry.metadata_state)
        self.assertEqual(227.0, entry.duration)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class WarmReopenAsksForNothingTest(unittest.TestCase):
    """判据 4 / Review Focus 5：全知库第二次打开**零提取** —— 两侧的待办必须同时为空。

    修之前这里只有一句 ``assertEqual([], store.validate(files))``，而它结构上不可能红
    （审查发现 M4）：队列根本不持 store 的引用，Task 5 的任何实现都无法让 ``validate``
    变长，那句断言测的是 Task 3 早已钉过的 store 契约。单独把它搬去 Task 7 的接线测试
    也不完整 —— "暖启动"是一个**联合**主张：store 认为无事可做 **且** 队列一行都不显示
    pending，缺任何一半，用户看到的都是一排永远转不完的省略号。

    所以本类把两半一起取，并断言两份清单相等；冷库作为对照保证这不是恒真 —— 同一条
    联合断言在冷库上必须是三行对三行。删掉 ``set_metadata`` 的表写入（M4 要求的那个变异）
    时，暖库那份的队列半边立刻非空，红在这里。
    """

    @staticmethod
    def _media(n: int) -> MediaFile:
        return MediaFile(path=_path(n), title=f'Track {n}', file_type='audio',
                         extension='.mp3', size_bytes=1000, modified_time=100.0)

    @staticmethod
    def _todo(queue: QueueService, store: LibraryMetadataStore,
              files: list) -> tuple:
        """两份待办：队列里读出 ``pending`` 的行，和 store 认为该提取的路径。"""
        rows = sorted(e.full_path for e in _file_rows(queue)
                      if e.metadata_state == STATE_PENDING)
        targets = sorted(full_path for full_path, _size, _mtime
                         in store.validate(files))
        return rows, targets

    def _warm(self, numbers):
        """Store loaded from a cache that answered every row, queue filled from it."""
        files = [self._media(n) for n in numbers]
        store = LibraryMetadataStore()
        store.load_cache_entries([
            CachedFile(path=_path(n), title=f'Track {n}', file_type='audio',
                       extension='.mp3', size_bytes=1000, modified_time=100.0,
                       md={key: getattr(KNOWN, key) for key in MD_KEYS})
            for n in numbers
        ])
        queue = _flat(*numbers)
        queue.set_metadata({f.path: store.get(f.path) for f in files})
        return queue, store, files

    def test_full_known_library_needs_no_extraction_after_set_metadata(self):
        numbers = (0, 1, 2)
        queue, store, files = self._warm(numbers)

        rows, targets = self._todo(queue, store, files)
        self.assertEqual([], targets,
                         'a warm table still asked the sweep for work')
        self.assertEqual([], rows,
                         'the store is done but the rows still say pending')
        self.assertEqual(rows, targets)
        for entry in _file_rows(queue):
            self.assertEqual(STATE_KNOWN, entry.metadata_state)
            self.assertEqual(227.0, entry.duration)

        # And the structure change that must not lose anything keeps it warm.
        queue.remove_at_display_index(0)
        rows, targets = self._todo(queue, store, files)
        self.assertEqual(([], []), (rows, targets),
                         'a rebuild re-opened work the cache had already answered')
        for entry in _file_rows(queue):
            self.assertEqual(STATE_KNOWN, entry.metadata_state)

    def test_cold_library_asks_for_every_row_the_store_still_wants(self):
        """对照组：同一条联合断言在冷库上是 ``3 == 3``，所以上一条不是恒真。"""
        numbers = (0, 1, 2)
        files = [self._media(n) for n in numbers]
        store = LibraryMetadataStore()
        store.load_cache_entries([
            CachedFile(path=_path(n), title=f'Track {n}', file_type='audio',
                       extension='.mp3', size_bytes=1000, modified_time=100.0)
            for n in numbers
        ])
        queue = _flat(*numbers)
        queue.set_metadata({f.path: store.get(f.path) for f in files})

        rows, targets = self._todo(queue, store, files)
        self.assertEqual([_path(n) for n in numbers], rows)
        self.assertEqual(rows, targets)
        self.assertEqual(3, len(targets),
                         'a cold library must still hand the sweep its whole row set')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ClearKeepsTheMetadataTableTest(unittest.TestCase):
    """裁定 B4-R18：``clear()`` **不清**那张表 —— 这是特征用例，不是许可。

    生产里 ``clear()`` 只服务"清空播放列表"（``presenter/main_presenter.py`` 的两个调用
    点），切库走的是 ``set_current_library`` → ``build_from_tracks``，**不经过**它；清空
    由 Task 7 的 ``set_metadata({})`` 负责。路径是绝对路径，值属于文件而不属于"这一份
    播放列表"，所以用户清空后又把同一批文件加回来时 spec §5 末句的"下次打开同库就是满的"
    应当同样成立 —— 顺手在 ``clear()`` 里加一句 ``self._row_metadata.clear()`` 看着无害，
    实际是把已提取的答案丢掉、把整库重新排一遍队。那条改动必须在这里红。
    """

    def test_the_answers_survive_an_emptied_playlist(self):
        queue = _flat(0, 1, 2)
        queue.set_metadata({_path(0): KNOWN, _path(1): RowMetadata(),
                            _path(2): None})

        queue.clear()

        self.assertEqual([], queue.get_display_entries())
        queue.build_from_tracks([_track(0), _track(1), _track(2)])
        by_path = {e.full_path: e for e in _file_rows(queue)}
        self.assertEqual(STATE_KNOWN, by_path[_path(0)].metadata_state)
        self.assertEqual(227.0, by_path[_path(0)].duration)
        self.assertEqual(STATE_UNKNOWN, by_path[_path(1)].metadata_state)
        self.assertEqual(STATE_PENDING, by_path[_path(2)].metadata_state,
                         'a row the table never held came back as something else')

    def test_the_wipe_is_still_the_way_to_lose_the_answers(self):
        """与 ``clear()`` 相反的那一半：``set_metadata({})``（切库）才该清掉它。"""
        queue = _flat(0)
        queue.set_metadata({_path(0): KNOWN})
        queue.clear()
        queue.set_metadata({})
        queue.build_from_tracks([_track(0)])

        entry = _file_rows(queue)[0]
        self.assertEqual(STATE_PENDING, entry.metadata_state)
        self.assertIsNone(entry.duration)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class DeliveryRowIndexTest(unittest.TestCase):
    """I4 / ruling B4-R32: one delivery consults **its own rows**, never the table.

    ``apply_metadata`` used to rebuild its row list with
    ``[idx for idx, entry in enumerate(self._display_entries) ...]`` -- once per
    answered row, so the sweep's own cost went quadratic in the library. Measured by
    the review on this host with a real ``QueueService`` and no mocks: **147 us per
    delivery, 441 ms cumulative at N=3000** of GUI-thread work, against the ~0.95 s of
    extraction the spec §8 probe recorded -- the write-back's whole budget again, for
    walking a list. §8's probe program measured extraction, the ``os.stat`` walk and
    the JSON dump, and *not* the row lookup, which is why the term survived the batch.

    The nail is a **countable quantity, not a timing test** (a wall-clock assertion
    here would be the fragile shape this suite refuses): a ``list`` subclass stands in
    for ``_display_entries`` and journals how it is consulted, so a delivery in a
    300-row queue must touch *its own* row and iterate nothing. That is what a
    "walk-and-filter" reimplementation cannot fake: the index has to both exist and be
    the thing that is read.

    The other half is freshness -- an index that lies is worse than a slow one, so
    every structural route (build, rebuild after a removal, the folder shape, ``clear``
    which empties the rows without rebuilding them) is compared against the ground
    truth read back off the entries themselves, and one behavioural test asserts the
    *row numbers* a delivery returns after a removal shifted them.
    """

    def _instrument(self, queue: QueueService) -> '_CountingEntries':
        counter = _CountingEntries(queue.get_display_entries())
        queue._display_entries = counter
        counter.reset()
        return counter

    def _ground_truth(self, queue: QueueService) -> dict:
        """What the rows themselves say, read by the *test* walking them."""
        truth: dict = {}
        for row, entry in enumerate(queue.get_display_entries()):
            if entry.is_folder or not entry.full_path:
                continue
            truth.setdefault(entry.full_path, []).append(row)
        return truth

    def test_a_delivery_in_a_long_queue_touches_only_its_own_rows(self):
        size = 300
        queue = _flat(*range(size))
        target = size - 1  # the worst row for a scan: everything precedes it

        counter = self._instrument(queue)
        rows = queue.apply_metadata(_path(target), KNOWN, STATE_KNOWN)

        self.assertEqual([target], rows, 'the update itself went wrong: fixture bug')
        self.assertEqual(
            0, counter.iterations,
            'a delivery walked the whole display list again: at one delivery per '
            'answered row that is the sweep\'s quadratic term (measured: 147 us per '
            'delivery, 441 ms cumulative at N=3000)')
        self.assertEqual(
            1, counter.item_reads,
            'a delivery read %d entries by index -- exactly one per row of its own '
            'path is the whole job' % counter.item_reads)

    def test_the_folder_shape_costs_one_read_per_row_of_the_path(self):
        """Two rows of one path cost two reads, not two walks of the table."""
        queue = _folders()
        counter = self._instrument(queue)

        rows = queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)

        self.assertEqual([1, 3], rows)
        self.assertEqual(0, counter.iterations, 'the multi-row case fell back to a scan')
        self.assertEqual(2, counter.item_reads,
                         'a path on two rows consulted %d entries, not 2'
                         % counter.item_reads)

    def test_the_index_holds_exactly_the_rows_of_each_path(self):
        queue = _folders()
        queue.apply_metadata(_path(1), KNOWN, STATE_KNOWN)
        entries = queue.get_display_entries()

        self.assertEqual(self._ground_truth(queue), dict(queue._rows_by_full_path),
                         'the row index and the rows themselves disagree: a delivery '
                         'would then repaint the wrong row (or none)')
        # Fixture guard with teeth: row 0 is the folder header, and the duplicated
        # path is the one that occupies 1 *and* 3 -- so ``[1, 3]`` below is index
        # space, not ``node_idx``/``sub_index`` space.
        self.assertTrue(entries[0].is_folder,
                        'the folder fixture lost its header row, so every row number '
                        'asserted here is measuring the wrong space')
        self.assertEqual(_path(0), entries[1].full_path)
        self.assertEqual(_path(1), entries[2].full_path)
        self.assertEqual(_path(0), entries[3].full_path)
        self.assertEqual([1, 3], queue._rows_by_full_path[_path(0)],
                         'the folder path that occupies two rows is indexed as one')
        self.assertEqual([2], queue._rows_by_full_path[_path(1)])
        self.assertNotIn(entries[0].path, queue._rows_by_full_path,
                         'a folder header entered the index: it owns no columns, and '
                         'a delivery would then paint its header row')

    def test_the_index_survives_a_removal_with_the_shifted_row_numbers(self):
        """Behavioural half: after a rebuild the delivery returns *new* rows.

        ``remove_at_display_index`` rebuilds the entries, so every row at or above the
        hole moves down by one. An index carried over from the old layout would still
        answer ``[1, 3]`` here and repaint a row that now holds a different file -- the
        one failure mode an index like this can have, and it is silent.
        """
        queue = _folders()
        queue.remove_at_display_index(1)   # removes the first copy of _path(0)

        self.assertEqual(self._ground_truth(queue), dict(queue._rows_by_full_path),
                         'the index did not follow the rebuild')
        self.assertEqual([2], queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN),
                         'the surviving row of the duplicated path is no longer at 2, '
                         'so a stale index is repainting the wrong row')
        self.assertEqual([1], queue.apply_metadata(_path(1), KNOWN, STATE_KNOWN),
                         '_path(1) shifted with it')
        entries = queue.get_display_entries()
        self.assertEqual(STATE_KNOWN, entries[2].metadata_state)
        self.assertEqual(STATE_KNOWN, entries[1].metadata_state)
        self.assertEqual(STATE_PENDING, entries[0].metadata_state,
                         'the folder header row owns no columns and must stay out of '
                         'the index')

    def test_clear_empties_the_index_along_with_the_rows(self):
        """``clear()`` drops the entries without rebuilding them (ruling B4-R18).

        The row-metadata *table* stays by design; the *index* is a view of the rows,
        so an index that outlives them is a delivery that paints nothing and reports
        rows that do not exist.
        """
        queue = _flat(0, 1)
        queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)
        queue.clear()

        self.assertEqual({}, dict(queue._rows_by_full_path),
                          'the index survived a clear() that emptied the rows')
        self.assertEqual([], queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN))
        queue.build_from_tracks([_track(0), _track(1)])
        self.assertEqual(self._ground_truth(queue), dict(queue._rows_by_full_path))

    def test_set_metadata_does_not_move_the_index(self):
        """The whole-table fill writes values, never rows."""
        queue = _flat(0, 1, 2)
        before = dict(queue._rows_by_full_path)
        queue.set_metadata({_path(0): KNOWN, _path(2): EMPTY})

        self.assertEqual(before, dict(queue._rows_by_full_path),
                         'a value-only fill changed the row layout it indexes')
        self.assertEqual(self._ground_truth(queue), dict(queue._rows_by_full_path))


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class SignalCensusTest(unittest.TestCase):
    """本任务不新增信号（裁定 R9）：定向更新的出口是返回值。"""

    def test_declared_signals_are_exactly_the_existing_three(self):
        """An exact census: a fourth signal on the queue is what this rules out.

        Deliberately a set equality, not ``assertFalse(hasattr(QueueService,
        'display_row_metadata_changed'))``: the latter is true by construction for
        any name nobody typed. The census goes red for *whatever* a later task calls
        its update signal, and the alternative it demands is the return value of
        ``apply_metadata`` (batch 3 ruling R9: a signal needs a landing slot, and
        this one's two arguments were already known to the caller).
        """
        declared = {name for name, value in vars(QueueService).items()
                    if isinstance(value, pyqtSignal)}
        self.assertEqual({'position_changed', 'queue_changed', 'display_changed'},
                         declared)

    def test_targeted_update_emits_nothing(self):
        """``apply_metadata`` must not re-emit the whole list; Task 6 refreshes rows."""
        queue = _flat(0, 1)
        seen: list = []
        queue.display_changed.connect(lambda entries: seen.append(list(entries)))
        queue.queue_changed.connect(lambda: seen.append('queue'))

        queue.apply_metadata(_path(0), KNOWN, STATE_KNOWN)

        self.assertEqual([], seen)


if __name__ == '__main__':
    unittest.main(verbosity=2)
