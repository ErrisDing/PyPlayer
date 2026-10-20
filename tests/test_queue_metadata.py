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
  这条的钉子。
* **``Track`` 不改**（spec §4.9）：``Track.duration`` 的 ``0.0`` 与"未知"同源，不能当
  显示依据。``test_track_columns_are_not_the_display_source`` 把这条钉住——载荷给的是
  一个 ``duration=0.0`` 的 ``Track``，行上显示的仍是"未知"。

定向更新走**返回值**（``list[int]``），本任务**不新增信号**：早期草案的
``display_row_metadata_changed(int, str)`` 按批次 3 终审 R9（信号必须有落地站）删掉了，
Task 7 拿行号逐行走 Task 6 的视图入口。``SignalCensusTest`` 把这个裁定钉成一条断言，
免得后来人"顺手补一个信号"。

同一份载荷在两个任务里的判断必须一致，所以 ``store`` 在这里是被**读**的（裁定 B4-R6：
队列测试可以读 store，``service/metadata_store.py`` 永不 import 队列）——
``QueueStateMatchesStoreStateTest`` 拿 store 当参照系，防止队列侧那份"整表换"的推导和
``state_of`` 静默分家。

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
        entry = queue.get_display_entries()[0]
        self.assertEqual(STATE_PENDING, entry.metadata_state)
        self.assertIsNone(entry.duration)


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
class QueueStateMatchesStoreStateTest(unittest.TestCase):
    """The queue's whole-table derivation is the store's, not a fourth opinion.

    ``set_metadata`` receives values only, so it has to name the state itself; the
    store owns that rule (``state_of``). This test reads the store as the reference
    (ruling B4-R6 allows exactly this direction) so the two cannot drift: a change
    to either side alone goes red here.
    """

    def test_queue_state_equals_store_state_for_the_same_payload(self):
        payloads = [KNOWN, EMPTY, RowMetadata(duration=4.0), None]
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
class WarmBuildNeedsNoExtractionTest(unittest.TestCase):
    """Review Focus 5: a fully known library reopens with **zero** extraction.

    The queue-side half of criterion 5: after the scan built the table, one
    ``set_metadata`` carries the cache's answers, and ``validate`` still has
    nothing to ask for -- neither before nor after a rebuild.
    """

    @staticmethod
    def _media(n: int) -> MediaFile:
        return MediaFile(path=_path(n), title=f'Track {n}', file_type='audio',
                         extension='.mp3', size_bytes=1000, modified_time=100.0)

    def test_full_known_library_needs_no_extraction_after_set_metadata(self):
        numbers = (0, 1, 2)
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

        self.assertEqual([], store.validate(files),
                         'a warm table still asked the sweep for work')
        for entry in _file_rows(queue):
            self.assertEqual(STATE_KNOWN, entry.metadata_state)
            self.assertEqual(227.0, entry.duration)

        # And the structure change that must not lose anything keeps it warm.
        queue.remove_at_display_index(0)
        self.assertEqual([], store.validate(files))
        for entry in _file_rows(queue):
            self.assertEqual(STATE_KNOWN, entry.metadata_state)


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
