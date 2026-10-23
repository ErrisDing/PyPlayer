#!/usr/bin/env python3
"""Batch 4 Task 7: the presenter's metadata wiring, end to end.

Everything upstream was tested alone: the store (Task 3), the sweep (Task 4), the
queue's row table (Task 5), the model's targeted update (Task 6). This file is the
only place they run as one chain, so every claim below is about a *joint* -- and four
joints were measured to be able to fail silently, which is why each gets a nail
rather than a comment:

1. **A re-pushed table does not repaint the columns.** ``PlaylistModel`` and
   ``QueueService`` hold the *same* ``DisplayEntry`` objects, and at an unchanged row
   count the model compares only ``display_text``/``is_playing``: after
   ``apply_metadata`` a fresh ``set_playlist_entries`` lets the model *read* the new
   values while emitting zero ``dataChanged`` (the Task 5+6 reviewer verified this,
   :meth:`TargetedUpdateIsTheOnlyRepaintTest.test_repushing_the_table_repaints_nothing`
   reproduces it here). Filling a row therefore has exactly one route --
   ``apply_metadata``'s return value to ``MainWindow.update_row_metadata`` -- so the
   count of ``dataChanged`` emissions is what proves the route was taken.
2. **The ``on_row`` callback may not raise.** On this host (PyQt6 6.11) an exception
   leaving ``QRunnable.run`` aborts the process (exit 127, no traceback, not even the
   runner's ``Ran`` line), and the delivery half of that guard belongs to this
   callback: the service's ``except`` only covers its own ``emit``. The safety tests
   therefore call ``_on_metadata_row`` the way the slot does, at the Python level, so
   a missing guard is a *failed assertion* rather than a dead run.
3. **Completion is "deliveries of the current generation == len(its targets)"**, and
   the count belongs to that generation: a retired plan delivers nothing (0, not N),
   so the count resets when the generation does; a duplicated path counts per
   *target* (one file legitimately occupies several rows); an empty plan still takes
   a generation; one call is one generation. Those five conditions are
   ``task-4-report.md`` §5.1 as amended by rulings B4-R13/R14.
4. **A write-back decides ``md`` and fingerprint together, from the store's state**
   (ruling B4-R10): a row that went back to pending must not be handed over at all --
   neither a payload nor a fingerprint it does not describe. ``take_dirty``'s
   ``dict | None`` ``None`` branch is the shape that carries this, and
   :meth:`MetadataWriteBackTest.test_a_pending_row_is_never_written_with_a_fingerprint`
   is its nail (and the reason that branch is *not* dead code).

Rules are read from production, not assumed: the batch size is
``presenter.main_presenter.METADATA_WRITE_BATCH`` (patched with
``mock.patch.object`` on that module), the progressable ids come from
``_progressable_action_ids`` (the rail's own ``PROGRESSABLE_IDS``, parsed from its
source), the state words are ``service.metadata_store``'s ``STATE_*``, and the target
shape is what ``MetadataService.start_sweep`` itself accepts.

Harness: a **real** ``MainWindow``, a **real** ``QueueService``, a **real**
``MetadataService`` with an injected fake extractor, and a **real** ``LibraryService``
scanning **real** files in a temporary directory whose JSON cache is redirected to the
same tree (``~/.pyplayer`` is never touched). Only ``PlaybackService`` and
``ConfigService`` are ``MagicMock``s. The three real services are *subclassed*, never
patched on an instance: PyQt looks Python overrides up on the type, so an attribute
hung on an instance is inert and any assertion reading it is green forever. The other
half of the observation is connected signals (``display_changed``, ``dataChanged``).

Concurrency, as in ``tests/test_metadata_sweep.py``: every wait is
``processEvents()`` rotation under a wall-clock cap, a blocked extractor waits on a
``threading.Event`` with a capped timeout, and every gate is opened in ``tearDown``.
One test parks the *whole* shared pool on such an event (:meth:`_park_the_pool`) to
make "this task never started" observable; the blocker is released by an ``addCleanup``
registered the moment it exists, so no path through the suite leaves it parked.

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_metadata_wiring -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cache_manager import LibraryCacheManager
from core.metadata import SongMetadata, normalize_duration
from service.metadata_store import (
    LibraryMetadataStore,
    RowMetadata,
    STATE_KNOWN,
    STATE_PENDING,
    STATE_UNKNOWN,
)
from view.models.playlist_model import PlaylistModel

from tests.test_presenter_status import _progressable_action_ids, _spied
from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

try:  # the wiring needs Qt; the skipUnless below is what guards it.
    from presenter import main_presenter as presenter_module
    from presenter.main_presenter import MainPresenter
    from core.library_manager import MediaFile, Track
    from service.library_service import LibraryService
    from service.metadata_service import MetadataService
    from service.queue_service import QueueService
    from view.main_window import MainWindow
except ImportError:  # pragma: no cover - environment without PyQt6
    MainPresenter = None
    LibraryService = None
    MetadataService = None
    QueueService = None
    MainWindow = None
    presenter_module = None

#: Wall-clock caps, as in ``tests/test_metadata_sweep.py``: generous against real
#: timing (these conditions settle in milliseconds), short enough to keep a real
#: regression loud and finite.
PUMP_LIMIT_MS = 4000
DRAIN_MS = 250

#: Cap for a blocked fake extractor, so a production change that extracted on the
#: calling thread fails an assertion instead of deadlocking the suite.
GATE_WAIT_S = 3.0

#: Cap for the pool blockers of :meth:`WiringHarness._park_the_pool`. The event is
#: released by ``addCleanup`` the moment it is created, so this only bounds the case
#: where a blocker outlives its own test -- and a blocker that outlived the run would
#: otherwise park every later sweep in the process.
BLOCK_WAIT_S = 20.0

METADATA_ROLES = frozenset({
    PlaylistModel.DurationRole, PlaylistModel.ArtistRole,
    PlaylistModel.AlbumRole, PlaylistModel.MetadataStateRole})


def _song(full_path: str) -> SongMetadata:
    """What the fake facade answers for one path, derived from its filename."""
    stem = Path(full_path).stem
    return SongMetadata(title=stem, artist=f'artist::{stem}', album=f'album::{stem}',
                        duration=123.5, album_art=None)


def _track(media_file) -> Track:
    return Track(path=media_file.path, title=media_file.title)


class RecordingMetadataService(MetadataService):
    """The real sweep, with its two entry points journaled.

    A subclass and not a mock because the delivery has to be real: rows must arrive
    through ``_sweep_row_ready`` on the GUI thread, and the generation rules are the
    service's own. Recording ``start_sweep``/``cancel_sweep`` is what lets a test
    state an *order* ("cancel before the wipe") and a *plan size* ("this generation
    owns exactly these targets") instead of guessing at either.
    """

    def __init__(self, extractor, journal):
        super().__init__(extractor=extractor)
        self.journal = journal
        self.plans = []      # ``(generation, targets)`` per accepted start
        self.refused = []    # what ``super().start_sweep`` raised, per refusal

    def start_sweep(self, targets, on_row):
        try:
            generation = super().start_sweep(targets, on_row)
        except (TypeError, ValueError) as exc:
            self.refused.append(exc)
            raise
        self.plans.append((generation, list(targets)))
        self.journal.append(('start_sweep', generation, len(targets)))
        return generation

    def cancel_sweep(self):
        generation = super().cancel_sweep()
        self.journal.append(('cancel_sweep', generation))
        return generation


class RecordingQueueService(QueueService):
    """The real queue, with the whole-table fill journaled.

    ``set_metadata`` is the joint the warm start and the library switch both cross,
    and it deliberately emits no signal -- the journal is the only way to see *when*
    it ran relative to the display push.
    """

    def __init__(self, journal):
        super().__init__()
        self.journal = journal
        self.fills = []

    def set_metadata(self, mapping):
        self.fills.append(len(mapping))
        self.journal.append(('set_metadata', len(mapping)))
        super().set_metadata(mapping)


class ExplodingQueueService(QueueService):
    """A queue whose targeted update fails, for the callback-safety nail."""

    def apply_metadata(self, full_path, md, state):
        raise RuntimeError('the queue died under the sweep')


class RecordingLibraryService(LibraryService):
    """The real scan, with the two cache joints journaled."""

    def __init__(self, journal):
        super().__init__()
        self.journal = journal
        self.written = []    # ``(library_path, updates)`` per write-back call

    def get_cache_entries(self, library_path):
        self.journal.append(('get_cache_entries', library_path))
        return super().get_cache_entries(library_path)

    def save_cache_metadata(self, library_path, updates):
        self.written.append((library_path, dict(updates)))
        self.journal.append(('save_cache_metadata', library_path, len(updates)))
        return super().save_cache_metadata(library_path, updates)


class WalkedLibraryService(RecordingLibraryService):
    """``refresh_all_libraries`` over an explicit list, not over the user's settings.

    ``LibraryService.refresh_all_libraries`` reads ``SettingsManager`` -- the real
    ``~/.pyplayer`` config -- which this harness must never touch, and the presenter's
    route needs the *walk* rather than the config read. So only the list is handed in:
    every library still goes through the real :meth:`refresh_library`, which re-scans the
    real directory and fires ``library_loaded`` once per library, which is exactly the
    shape the joint plan has to survive.
    """

    def __init__(self, journal, paths=None):
        super().__init__(journal)
        self.paths = list(paths or [])

    def refresh_all_libraries(self):
        result = {}
        for path in self.paths:
            result[path] = self.refresh_library(path)
        self.all_libraries_loaded.emit()
        return result


class WiringHarness:
    """Real view + real queue + real sweep + real library scan, in one temp tree."""

    def setUp(self):
        self.app = make_app()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        cache_dir = self.root / 'cache' / 'libraries'
        # Class-level: the scanner's manager, the service's writes and this file's own
        # reads share one directory, and ``~/.pyplayer`` is never touched.
        patcher = mock.patch.object(LibraryCacheManager, '_get_cache_dir',
                                    lambda manager: cache_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache_dir = cache_dir

        self.journal = []
        self.extract_calls = []
        self.failures = set()
        self.gates = {}

        self.view = MainWindow(make_manager())
        self.addCleanup(self.view.deleteLater)
        self.model = self.view._playlist_view._model
        self.changes = []
        self.model.dataChanged.connect(
            lambda top, bottom, roles=None: self.changes.append(
                (top.row(), bottom.row(), frozenset(roles or ()))))

        self.playback = mock.MagicMock(name='playback_service')
        self.playback.get_volume.return_value = 0.5
        self.playback.current_track = None
        self.config = mock.MagicMock(name='config_service')
        self.config.get_libraries.return_value = []
        self.config.get_background_image.return_value = None
        self.config.get_overlay_alpha.return_value = 0.3
        self.config.get_playlist_alpha.return_value = 0.5
        self.config.get_controls_alpha.return_value = 0.6

        self.library = self._make_library_service()
        self.queue = RecordingQueueService(self.journal)
        self.metadata = RecordingMetadataService(self._extract, self.journal)
        self.presenter = MainPresenter(
            view=self.view,
            playback_service=self.playback,
            queue_service=self.queue,
            library_service=self.library,
            metadata_service=self.metadata,
            config_service=self.config,
        )
        # The push the view sees, recorded through the real signal: an ordering claim
        # ("the table was filled before the push") only has an observable shape.
        self.queue.display_changed.connect(
            lambda entries: self.journal.append(('display_changed', len(entries))))

    def tearDown(self):
        for gate in self.gates.values():
            gate.set()
        self.gates.clear()
        self._pump_for(50)

    # === the library service (built before the presenter connects) ===

    def _make_library_service(self):
        """The library side of the harness, built *before* the presenter.

        A hook rather than a swap after ``setUp``: the presenter connects to
        ``library_loaded`` in its constructor, so replacing the service afterwards would
        leave the signal -- the whole route a multi-library scan travels -- wired to the
        object the test threw away. ``MultiLibraryJointPlanTest`` hands in the walk.
        """
        return RecordingLibraryService(self.journal)

    # === the fake extractor ===

    def _extract(self, full_path):
        """Runs on a pool thread: records, may block on this test's gate, answers."""
        self.extract_calls.append(full_path)
        gate = self.gates.get(full_path)
        if gate is not None:
            gate.wait(GATE_WAIT_S)
        if full_path in self.failures:
            raise RuntimeError('undecodable container')
        return _song(full_path)

    def _gate(self, *paths):
        for path in paths:
            self.gates[str(path)] = threading.Event()

    def _release(self, *paths):
        for path in paths:
            self.gates[str(path)].set()

    def _park_the_pool(self):
        """Occupy every worker of the shared pool, so later tasks cannot *start*.

        ``QThreadPool`` cannot pull a queued task back, and the only way to prove a
        task was never given the chance to extract is to keep it queued while the
        generation it belongs to is replaced. Every blocker waits on one event this
        test (and, as a backstop, ``BLOCK_WAIT_S``) releases, so no failure path here
        can leave the suite's shared pool parked.
        """
        from PyQt6.QtCore import QRunnable, QThreadPool

        pool = QThreadPool.globalInstance()
        slots = pool.maxThreadCount()
        self.assertGreaterEqual(slots, 1, 'the global pool reports no worker at all')
        gate = threading.Event()
        self.addCleanup(gate.set)

        class _Blocker(QRunnable):
            def run(self):
                gate.wait(BLOCK_WAIT_S)

        for _ in range(slots):
            pool.start(_Blocker())
        self._pump_until(lambda: pool.activeThreadCount() >= slots,
                         'the shared pool never took the blockers on',
                         state=lambda: f'active={pool.activeThreadCount()} of {slots}')
        return gate

    # === library fixtures ===

    def _make_library(self, name='rock', count=3, prefix='track'):
        """A real directory of ``count`` real ``.mp3`` files; returns its path."""
        library = self.root / name
        library.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (library / f'{prefix}{index}.mp3').write_bytes(b'x' * (16 + index))
        return library

    def _file_paths(self, library):
        return sorted(str(path) for path in Path(library).glob('*.mp3'))

    def _scan(self, library):
        """The route a user takes: ``scan_folder_requested`` -> ``load_library``."""
        self.view.scan_folder_requested.emit(str(library))

    # === reads ===

    def _cache_manager(self):
        return LibraryCacheManager()

    def _raw_cache(self, library):
        path = self._cache_manager()._get_cache_filepath(str(library))
        return json.loads(path.read_text(encoding='utf-8'))

    def _raw_by_name(self, library):
        return {Path(entry['path']).name: entry
                for entry in self._raw_cache(library)['files']}

    def _states(self):
        return [self.model.data(self.model.index(row),
                                PlaylistModel.MetadataStateRole)
                for row in range(self.model.rowCount())]

    def _state_by_path(self):
        """Row states keyed by the path they show, so a test need not guess the sort."""
        return {
            self.model.data(self.model.index(row), PlaylistModel.FullPathRole):
                self.model.data(self.model.index(row),
                                PlaylistModel.MetadataStateRole)
            for row in range(self.model.rowCount())}

    def _artists(self):
        return [self.model.data(self.model.index(row), PlaylistModel.ArtistRole)
                for row in range(self.model.rowCount())]

    def _metadata_repaints(self):
        """``dataChanged`` calls whose role set is exactly the four metadata roles."""
        return [change for change in self.changes
                if change[2] and change[2] <= METADATA_ROLES]

    def _writes_for(self, library):
        return [item for item in self.library.written if item[0] == str(library)]

    def _emit(self, service, signal_name, *args):
        """Fire a service signal through the connection the presenter made."""
        signal = getattr(service, signal_name)
        receivers = [call.args[0] for call in signal.connect.call_args_list]
        self.assertTrue(receivers,
                        f'nothing is connected to {signal_name}: the presenter lost '
                        'the route')
        for receiver in receivers:
            receiver(*args)

    # === bounded waits ===

    def _pump_until(self, condition, what, state=None, limit_ms=PUMP_LIMIT_MS):
        from PyQt6.QtCore import QElapsedTimer

        clock = QElapsedTimer()
        clock.start()
        spins = 0
        while True:
            self.app.processEvents()
            spins += 1
            if condition():
                return spins
            if clock.elapsed() >= limit_ms:
                detail = f'; state: {state()}' if state is not None else ''
                self.fail(f'{what} did not happen within {limit_ms} ms '
                          f'({spins} processEvents() spins{detail})')

    def _pump_for(self, budget_ms):
        from PyQt6.QtCore import QElapsedTimer

        clock = QElapsedTimer()
        clock.start()
        while clock.elapsed() < budget_ms:
            self.app.processEvents()

    def _await_plan(self, targets, what='the sweep'):
        """Wait for *this* plan's own count: deliveries == len(its targets).

        The completion rule Task 7 is handed, read back off the presenter's counters:
        a widget state cannot tell "still filling" from "stalled" when some rows were
        already warm. Tests then assert the *observable* consequence (rows, cache,
        write count), never the counter itself.
        """
        presenter = self.presenter
        expected = len(targets)
        self._pump_until(
            lambda: (presenter._metadata_generation
                     == self.metadata.current_generation()
                     and presenter._metadata_expected == expected
                     and presenter._metadata_delivered == expected),
            f'{what} did not deliver every target',
            state=lambda: (f'expected={presenter._metadata_expected} '
                           f'delivered={presenter._metadata_delivered} '
                           f'generation={presenter._metadata_generation} '
                           f'live={self.metadata.current_generation()} '
                           f'calls={self.extract_calls}'))
        self._pump_for(DRAIN_MS)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepStartTest(WiringHarness, unittest.TestCase):
    """Scan -> file table -> ``validate`` -> sweep, and the rows that come back."""

    def test_a_scan_starts_a_sweep_and_every_row_comes_back_known(self):
        library = self._make_library(count=3)
        paths = self._file_paths(library)

        self._scan(library)

        self.assertEqual(
            1, len(self.metadata.plans),
            'the scan never started a sweep: three rows would stay "未取到" forever')
        generation, targets = self.metadata.plans[0]
        self.assertEqual(
            paths, sorted(triple[0] for triple in targets),
            'the sweep was handed something other than validate\'s targets')
        # B4-R16: what reaches ``start_sweep`` is ``(str, int, float)`` exactly.
        for full_path, size_bytes, modified_time in targets:
            with self.subTest(path=full_path):
                self.assertIsInstance(full_path, str)
                self.assertIsInstance(size_bytes, int)
                self.assertIsInstance(
                    modified_time, float,
                    'start_sweep refuses an int mtime, so an un-normalised triple is '
                    'a refused plan and a library whose columns never fill')

        self.assertIsInstance(generation, int)
        self._await_plan(paths)

        self.assertEqual([STATE_KNOWN] * 3, self._states(),
                          f'rows did not come back known: {self._states()}')
        self.assertEqual(['artist::track0', 'artist::track1', 'artist::track2'],
                         self._artists())
        self.assertEqual(123.5, self.model.data(self.model.index(0),
                                                PlaylistModel.DurationRole),
                         'the update reached the queue\'s objects but not the model')

    def test_the_returned_generation_is_the_one_the_sweep_runs_under(self):
        """``_start_metadata_sweep`` answers with *this plan's* generation (B4-R13)."""
        library = self._make_library(count=2)

        self._scan(library)
        first = self.metadata.plans[0][0]
        second = self.presenter._start_metadata_sweep(
            self.library.get_files(str(library)))

        self.assertIsInstance(second, int,
                              'the interface says int: a caller has to be able to '
                              'compare this against current_generation() later')
        self.assertEqual(first + 1, second,
                         'a second sweep reported the generation it retired instead '
                         'of its own')
        self.assertEqual(second, self.metadata.current_generation())

    def test_the_table_is_filled_before_the_display_is_pushed(self):
        """Warm start order: ``set_metadata`` before ``build_from_tracks``.

        ``_rebuild_display_entries`` is the only place the queue's table reaches the
        rows (spec §4.9's "no second lookup at paint time"), and a re-pushed table
        repaints nothing (fact 1) -- a fill that runs *after* the push is invisible
        until something else touches the row.
        """
        library = self._make_library(count=2)
        self._scan(library)
        self._await_plan(self._file_paths(library))

        self.journal.clear()
        self._scan(library)

        kinds = [step[0] for step in self.journal]
        self.assertIn('display_changed', kinds, str(self.journal))
        self.assertLess(
            kinds.index('set_metadata'), kinds.index('display_changed'),
            f'the row table was not filled before the push: {self.journal}')

    def test_a_warm_library_extracts_nothing_but_still_takes_a_generation(self):
        """Spec §5's second paragraph, and Task 5's deferred M4 half.

        A fully cached library has no targets -- and an empty plan must still consume
        a generation, because that is what retires the rows an earlier plan left in
        flight (§5.1's fourth condition).
        """
        library = self._make_library(count=2)
        self._scan(library)
        self._await_plan(self._file_paths(library))
        before = self.metadata.current_generation()
        self.extract_calls.clear()
        self.library.written.clear()

        self._scan(library)

        self.assertEqual(
            before + 1, self.metadata.current_generation(),
            'a warm rescan took no generation, so an older plan\'s rows are still '
            'live against this library\'s callback')
        self.assertEqual([], self.metadata.plans[-1][1],
                          'a warm library was handed out as extraction targets')
        self._pump_for(DRAIN_MS)
        self.assertEqual([], self.extract_calls,
                          'a warm library was extracted again (criterion 6)')
        self.assertEqual([], self.library.written,
                         'a sweep with nothing to write still rewrote the cache')
        self.assertEqual([STATE_KNOWN] * 2, self._states(),
                         'the cached values never reached the rows')

    def test_an_extraction_failure_lands_as_unknown_and_is_persisted(self):
        """spec §6 item 1 + criterion 6: "tried, nothing" survives a restart.

        The row must read ``unknown`` (not ``pending``, which would promise a retry
        that never comes), and the cache must carry the present-but-empty ``md`` that
        makes the same call after the next start.
        """
        library = self._make_library(count=2)
        paths = self._file_paths(library)
        self.failures.add(paths[1])

        self._scan(library)
        self._await_plan(paths)

        self.assertEqual([STATE_KNOWN, STATE_UNKNOWN], self._states(),
                         f'{self._states()} -- a failed extraction must be unknown, '
                         'and the good row must not be dragged down with it')
        self.assertIsNone(self._artists()[1], 'the failed row invented a value')
        entry = self._raw_by_name(library)['track1.mp3']
        self.assertIn('md', entry,
                      'a tried-and-empty row lost its key: the next start would treat '
                      'it as never tried and extract it again forever')
        self.assertEqual({'artist': None, 'album': None, 'duration': None}, entry['md'])
        self.assertEqual(os.stat(paths[1]).st_mtime, entry['modified_time'],
                         'a persisted failure was not stamped with the version it '
                         'describes, so the row could never be re-tried when it '
                         'actually changes')

    def test_a_refresh_keeps_the_answers_the_new_file_table_still_describes(self):
        """The carry-over in ``_save_to_cache``, read the way a restart reads it.

        A refresh re-scans and rewrites the whole cache file from ``MediaFile`` objects,
        which have no ``md`` at all -- so the scan's own write is the one place the
        persisted answers can be thrown away, and nothing in this process would notice:
        the presenter's store is still warm in memory. Only the next start reads the
        file, which is why this test drops the store by hand to stand for the next
        process. The rule is the store's, applied at the writer (ruling B4-R10): an old
        payload travels only with the fingerprint it describes, so the file that moved
        is the one file that has to be extracted again.
        """
        library = self._make_library(count=3)
        paths = self._file_paths(library)
        moved = paths[1]
        self._scan(library)
        self._await_plan(paths)

        stat = os.stat(moved)
        os.utime(moved, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.extract_calls.clear()
        self.library.written.clear()
        self.presenter._metadata_stores = {}

        self._scan(library)

        self.assertEqual([moved], [triple[0] for triple in self.metadata.plans[-1][1]],
                         'the re-scan either threw every cached answer away or kept one '
                         'that no longer describes its file')
        self._await_plan([moved], what='the post-refresh sweep')
        self.assertEqual([moved], self.extract_calls,
                         'a file the cache still answers for was extracted again: the '
                         'refresh silently dropped its md (spec §4.3 criterion 7 shape)')
        self.assertEqual([STATE_KNOWN] * 3, self._states())

    def test_an_excluded_format_is_answered_on_the_spot_and_persisted(self):
        """spec §2 through the wiring: ``.ncm`` is never swept, and never ``⋯`` either.

        ``validate`` answers an excluded file itself, with the pair of the scan that
        listed it -- so the row is ``unknown`` the moment it is drawn, the file is not in
        the sweep's target list (decrypting one writes a proxy file, per row, across a
        whole library), and the answer still reaches the cache like any other.
        """
        library = self._make_library(count=1)
        (library / 'locked.ncm').write_bytes(b'ncm' * 24)
        mp3 = self._file_paths(library)[0]
        ncm = str(library / 'locked.ncm')

        self._scan(library)

        self.assertEqual([mp3], [triple[0] for triple in self.metadata.plans[-1][1]],
                         'an excluded format was handed to the sweep')
        self._await_plan([mp3])
        self.assertEqual(
            {mp3: STATE_KNOWN, ncm: STATE_UNKNOWN}, self._state_by_path(),
            f'{self._state_by_path()}: the .ncm row must read "取不到", not "未取到", '
            'and must not drag the good row down')
        entry = self._raw_by_name(library)['locked.ncm']
        self.assertEqual({'artist': None, 'album': None, 'duration': None},
                         entry.get('md'),
                         'the excluded format\'s answer never reached the cache file')

    def test_a_library_whose_rows_are_all_answered_on_the_spot_still_flushes(self):
        """I1: a plan with no target has no delivery, so nothing ever *closes* it.

        The closing write-back is keyed to "every target came back". A library made
        only of excluded formats takes no target at all -- ``validate`` answers each
        row itself with "tried, nothing" -- so those records used to live in memory
        for the length of the run and never reach the file: every start re-made them.
        Spec §4.1's invariant is that ``md`` is missing exactly when something is
        waiting to fetch it, and nothing is ever going to fetch an ``.ncm``, so the
        answer has to be persisted. The display was never the symptom (the row reads
        取不到 either way), which is why the nail is the file.

        The second scan is the other half of the rule: a plan with nothing *dirty*
        must still cost zero writes (criterion 6).
        """
        library = self._make_library('ncm-only', count=0)
        for name in ('locked-a.ncm', 'locked-b.ncm'):
            (library / name).write_bytes(b'ncm' * 24)
        names = sorted(path.name for path in library.glob('*.ncm'))

        self._scan(library)
        self._pump_for(DRAIN_MS)

        self.assertEqual(1, len(self.metadata.plans),
                         'a library of excluded formats started no plan at all, so '
                         'the rows never got their answer')
        self.assertEqual([], self.metadata.plans[-1][1],
                         'an excluded format was handed to the sweep')
        self.assertEqual([], self.extract_calls,
                         'the sweep extracted a format the store answers by itself')
        writes = self._writes_for(library)
        self.assertEqual(1, len(writes),
                         f'a plan with zero targets never ran its closing write-back: '
                         f'{self.library.written} -- those "tried, nothing" records are '
                         're-made on every start and never persisted')
        _, updates = writes[0]
        self.assertEqual(sorted(str(library / name) for name in names),
                         sorted(updates),
                         'the zero-target flush wrote something other than the rows '
                         'validate had answered')
        by_name = self._raw_by_name(library)
        for name in names:
            with self.subTest(entry=name):
                self.assertEqual({'artist': None, 'album': None, 'duration': None},
                                 by_name[name].get('md'),
                                 'the answer never reached the file: without the ``md`` '
                                 'key the next start reads the row as never tried')
        self.assertEqual([STATE_UNKNOWN] * 2, self._states(),
                         f'{self._states()} -- the rows must read 取不到, not 未取到')

        self.library.written.clear()
        self._scan(library)
        self._pump_for(DRAIN_MS)

        self.assertEqual([], self.library.written,
                         'a warm all-excluded library rewrote its cache file for '
                         'nothing: the closing flush must still cost zero writes when '
                         'no row is dirty')
        self.assertEqual([STATE_UNKNOWN] * 2, self._states())

    def test_an_empty_library_starts_no_sweep_and_writes_nothing(self):
        library = self._make_library(count=0)

        self._scan(library)

        self.assertEqual([], self.metadata.plans,
                         'a library with no files started a sweep')
        self.assertEqual([], self.library.written)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class TargetedUpdateIsTheOnlyRepaintTest(WiringHarness, unittest.TestCase):
    """Fact 1: filling a row must go through ``apply_metadata``'s row numbers."""

    def test_repushing_the_table_repaints_nothing(self):
        """Characterization: ``set_playlist_entries`` is not the refresh mechanism.

        Model and queue share the ``DisplayEntry`` objects, so after a targeted update
        the model *reads* the new values and still emits zero ``dataChanged`` at an
        unchanged row count. Without this nail, "I called ``set_playlist_entries``, so
        the columns refresh" stays an invisible mistake -- the presenter would look
        right and the screen would stay stale.
        """
        library = self._make_library(count=3)
        self._scan(library)
        self._await_plan(self._file_paths(library))

        rows = self.queue.apply_metadata(self._file_paths(library)[0],
                                         RowMetadata(artist='re-pushed'), STATE_KNOWN)
        self.assertEqual([0], rows)
        self.changes.clear()
        self.view.set_playlist_entries(self.queue.get_display_entries())
        self.assertEqual(
            [], self.changes,
            'a re-push reported the new value to the view: the claim under test is '
            'that it does not, so the presenter must never count on it')
        self.assertEqual('re-pushed', self.model.data(
            self.model.index(0), PlaylistModel.ArtistRole),
                         'the value is readable -- which is exactly why the mistake '
                         'is invisible without this nail')

    def test_the_sweep_callback_emits_exactly_one_dataChanged_per_row(self):
        """The other half: the route the presenter takes *does* repaint, once per row."""
        library = self._make_library(count=3)
        self._scan(library)

        self.changes.clear()
        self._await_plan(self._file_paths(library))

        repaints = self._metadata_repaints()
        self.assertEqual(3, len(repaints),
                          f'one metadata repaint per row expected: {self.changes}')
        self.assertEqual([0, 1, 2], sorted(top for top, _, _ in repaints))
        for top, bottom, roles in repaints:
            self.assertEqual(top, bottom, f'{top}..{bottom} repaints a range')
            self.assertEqual(METADATA_ROLES, roles,
                             'a metadata repaint arrived with the wrong role set')
        self.assertEqual(0, len([change for change in self.changes
                                 if change[2] == frozenset({PlaylistModel.IsPlayingRole})]),
                         'a sweep repaint also touched the playing highlight')

    def test_every_row_of_one_path_is_repainted_by_every_delivery(self):
        """One file can legitimately occupy several rows, and is asked for per target.

        Counting per *target* (§5.1's third condition) and repainting every row
        ``apply_metadata`` names are one fact seen from two sides: three targets on one
        path is three deliveries, and three rows on that path is three repaints per
        delivery. A count deduplicated by path would never reach ``len(targets)`` at all,
        and a first-match-only update would leave the same song showing a length in one
        row and ``⋯`` in the next.
        """
        library = self._make_library(count=2)
        first = self.library.get_files(str(library))[0]

        # Production order, called directly because a queue built from one MediaFile
        # three times is not something a scan produces: fill and schedule, then push.
        generation = self.presenter._start_metadata_sweep([first, first, first])
        self.queue.build_from_tracks([_track(first)] * 3)
        self.changes.clear()

        self.assertEqual(3, len(self.metadata.plans[-1][1]),
                         'a duplicated path was deduplicated out of the plan, so the '
                         'count that decides completion can never reach its own N')
        self._await_plan([0, 1, 2], what='the duplicated-path sweep')
        repaints = self._metadata_repaints()
        self.assertEqual(9, len(repaints),
                         'three deliveries, each repainting every one of the three '
                         f'rows that carry the path: {repaints}')
        self.assertEqual([0, 1, 2] * 3, [row for row, _, _ in repaints],
                         'a row that carries the path was skipped by some delivery')
        self.assertEqual([STATE_KNOWN] * 3, self._states(),
                         'the same song shows a length in one row and ⋯ in another')
        self.assertEqual(generation, self.metadata.current_generation())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataWriteBackTest(WiringHarness, unittest.TestCase):
    """Batched writes, the pre-write re-check, and B4-R10."""

    def test_a_small_sweep_writes_once_not_once_per_row(self):
        """The O(n^2) nail at the shipped constant: ceil(3 / B) == 1 write-back."""
        library = self._make_library(count=3)

        self._scan(library)
        self._await_plan(self._file_paths(library))

        writes = self._writes_for(library)
        self.assertEqual(1, len(writes),
                         f'expected ceil(3/METADATA_WRITE_BATCH) == 1 write-back, got '
                         f'{len(writes)}: {self.library.written}')
        raw = self._raw_cache(library)
        self.assertEqual(3, len([entry for entry in raw['files'] if 'md' in entry]),
                         'the one write-back did not carry all three rows')
        self.assertEqual('2.0', raw['version'])

    def test_the_batch_boundary_flushes_mid_sweep(self):
        """``ceil(N / METADATA_WRITE_BATCH)`` writes, and the boundary really fires.

        The constant is patched on the *production* module: a test that only ever
        sees the completion flush cannot tell a batch of 4 from a batch of 500, and
        "one write per row" would look identical at N < B.
        """
        library = self._make_library(count=12)
        paths = self._file_paths(library)
        with mock.patch.object(presenter_module, 'METADATA_WRITE_BATCH', 4):
            self._scan(library)
            self._await_plan(paths)

        writes = self._writes_for(library)
        self.assertEqual([4, 4, 4], [len(update) for _, update in writes],
                         f'ceil(12/4) batches of 4 expected, got '
                         f'{[len(update) for _, update in writes]}')
        raw = self._raw_cache(library)
        self.assertEqual(12, len([entry for entry in raw['files'] if 'md' in entry]))

    def test_a_written_entry_carries_md_and_the_fingerprint_it_describes(self):
        """B4-R10 at the writer: the pair travels together, and only together."""
        library = self._make_library(count=1)
        path = self._file_paths(library)[0]

        self._scan(library)
        self._await_plan([path])

        entry = self._raw_cache(library)['files'][0]
        self.assertEqual(
            {'artist': 'artist::track0', 'album': 'album::track0',
             'duration': normalize_duration(123.5)}, entry['md'],
            'the md payload is not what the sweep answered (or drifted off B4-R1\'s '
            'key set)')
        stat = os.stat(path)
        self.assertEqual((stat.st_size, stat.st_mtime),
                         (entry['size_bytes'], entry['modified_time']),
                         'the fingerprint on disk does not describe the version the '
                         'md was taken from: the row is stale on every later scan')

    def test_a_file_deleted_after_the_scan_is_not_written_back(self):
        """Review Focus 1: the row updates; the cache never hears about the corpse."""
        library = self._make_library(count=3)
        paths = self._file_paths(library)
        gone = paths[1]
        stat_before = os.stat(gone)
        self._gate(*paths)

        self._scan(library)
        os.remove(gone)
        self._release(*paths)
        self._await_plan(paths)

        written_paths = {key for _, update in self._writes_for(library) for key in update}
        self.assertNotIn(gone, written_paths,
                         'the deleted path reached the write-back payload: the '
                         'pre-write re-check is what drops it')
        by_name = self._raw_by_name(library)
        self.assertIn('track1.mp3', by_name,
                      'the write-back invented a table row for a file that is gone -- '
                      'or the scan lost it; neither is this task\'s business')
        self.assertNotIn('md', by_name['track1.mp3'], 'a deleted file was written md')
        self.assertEqual((stat_before.st_size, stat_before.st_mtime),
                         (by_name['track1.mp3']['size_bytes'],
                          by_name['track1.mp3']['modified_time']),
                         'a row that was skipped still advanced its fingerprint: the '
                         'file now looks extracted at a version nothing described')
        for name in ('track0.mp3', 'track2.mp3'):
            self.assertIn('md', by_name[name], f'{name} lost its write-back')

    def test_a_file_rewritten_after_the_scan_is_not_written_back(self):
        """The other half of the re-check: same path, different version."""
        library = self._make_library(count=2)
        paths = self._file_paths(library)
        changed = paths[0]
        self._gate(*paths)

        self._scan(library)
        stat = os.stat(changed)
        os.utime(changed, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self._release(*paths)
        self._await_plan(paths)

        entry = next(item for item in self._raw_cache(library)['files']
                     if item['path'] == changed)
        self.assertNotIn('md', entry,
                         'an md extracted against the old version was stamped next to '
                         'the new fingerprint')
        self.assertEqual(stat.st_mtime, entry['modified_time'],
                         'the fingerprint moved with a payload that does not describe '
                         'the new version')
        self.assertEqual(STATE_KNOWN, self._states()[0],
                         'the in-memory row was dropped along with the write-back')

    def test_a_pending_row_is_never_written_with_a_fingerprint(self):
        """B4-R10, on ``take_dirty``'s ``None`` branch -- and why it is not dead code.

        ``record`` always stores a row, so a ``None`` payload appears only when a row
        that is *already dirty* is invalidated by a later ``validate`` -- the state a
        reused store holds when a file changes between two scans of the same library,
        before the batch it belongs to was ever flushed. Handing that row over would
        stamp a fingerprint the payload does not describe (or drop an answer the disk
        still supports), and either way the invalidation stops being re-fetchable.

        The flush is called directly here: it is the same call a batch boundary makes,
        and driving it this way keeps the nail about the *rule* instead of about
        thread timing.
        """
        library = self._make_library(count=2)
        paths = self._file_paths(library)
        pending, kept = paths[0], paths[1]
        self._scan(library)
        self._await_plan(paths)
        before = {Path(entry['path']).name: dict(entry)
                  for entry in self._raw_cache(library)['files']}
        self.assertEqual(2, len([e for e in before.values() if 'md' in e]))

        pending_stat = os.stat(pending)
        kept_stat = os.stat(kept)
        os.utime(pending, ns=(pending_stat.st_atime_ns,
                              pending_stat.st_mtime_ns + 5_000_000_000))
        # Re-statted, the way a scan produces them: ``get_cached_files`` would answer
        # with the *previous* scan's MediaFile objects, whose mtime still matches.
        restatted = [MediaFile(path=path, title=Path(path).name,
                               file_type='audio', extension='.mp3')
                     for path in paths]

        def invalidated_store():
            """The state to be flushed: an answered batch in which ``pending`` has since
            been invalidated. Built twice on purpose -- ``take_dirty`` clears the flags
            it reports, so probing the shape and flushing it cannot share one store.
            """
            store = LibraryMetadataStore()
            store.load_cache_entries(self.library.get_cache_entries(str(library)))
            store.record(pending, RowMetadata(artist='stale'),
                         pending_stat.st_size, pending_stat.st_mtime)
            # A second answered row, so the flush has something to write *besides* the
            # one it must refuse: an empty batch would pass for the wrong reason.
            store.record(kept, store.get(kept), kept_stat.st_size, kept_stat.st_mtime)
            store.validate(restatted)
            return store

        dirty = sorted(invalidated_store().take_dirty(), key=lambda pair: pair[0])
        self.assertEqual([pending, kept], [path for path, _ in dirty],
                         'the invalidated row dropped out of the write-back set')
        self.assertIsNone(dict(dirty)[pending],
                          'the invalidated row came back with a payload: this is the '
                          'shape B4-R10 is about and the reason take_dirty answers '
                          'dict | None, so the test fixture and the store must agree')

        self.presenter._metadata_stores = {str(library): invalidated_store()}
        # The pending row's pair *matches the disk*: the only reason it may not be
        # written is that its store state says pending.
        fresh_pending_stat = os.stat(pending)
        self.presenter._metadata_fingerprints = {
            pending: (fresh_pending_stat.st_size, fresh_pending_stat.st_mtime),
            kept: (kept_stat.st_size, kept_stat.st_mtime),
        }
        self.library.written.clear()

        self.presenter._flush_metadata_cache()

        self.assertEqual(1, len(self.library.written), str(self.library.written))
        _, updates = self.library.written[0]
        self.assertEqual([kept], sorted(updates),
                         'a pending row was handed to the writer: the write-back must '
                         'decide md and fingerprint from the store\'s state, together')
        after = {Path(entry['path']).name: entry
                 for entry in self._raw_cache(library)['files']}
        self.assertEqual(before['track0.mp3'], after['track0.mp3'],
                         'the invalidated row was rewritten (md dropped, fingerprint '
                         'advanced) instead of left describing what it still holds')

    def test_a_failing_cache_write_keeps_the_rows_and_the_callback_quiet(self):
        """spec §6's third item, through the real delivery channel.

        With the guard missing, the ``OSError`` would leave ``_deliver_sweep_row`` --
        a slot invoked from C++ -- and PyQt6 answers that with ``qFatal``: this run
        would end here instead of reporting anything. ``CallbackSafetyTest`` carries
        the falsifiable half; this test is the "the app is still standing, the columns
        are filled" half.
        """
        library = self._make_library(count=3)
        paths = self._file_paths(library)
        self._gate(*paths)
        self._scan(library)
        # Only the write-back may fail: the scan's own cache write has already run.
        patcher = mock.patch.object(LibraryCacheManager, 'save_cache',
                                    side_effect=OSError('read-only disk'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self._release(*paths)
        self._await_plan(paths)

        self.assertEqual([STATE_KNOWN] * 3, self._states(),
                         'a failed cache write took the in-memory results with it')
        self.assertEqual(['artist::track0', 'artist::track1', 'artist::track2'],
                         self._artists())
        self.assertEqual(1, len(self._writes_for(library)),
                         'the failing write-back was retried on every later row')
        self.assertEqual(0, sum(self.presenter._metadata_since_flush.values()),
                         'a failed flush left the batch counter armed, so every row '
                         'after it walks the disk again')
        raw = self._raw_cache(library)
        self.assertEqual(0, len([entry for entry in raw['files'] if 'md' in entry]),
                         'the fixture wrote a cache the failing call was supposed to own')

    def test_the_flush_is_a_no_op_when_nothing_is_dirty(self):
        """No rows to write, no rewrite of the whole file (the completion flush's cost)."""
        library = self._make_library(count=2)
        self._scan(library)
        self._await_plan(self._file_paths(library))
        self.library.written.clear()

        self.presenter._flush_metadata_cache()

        self.assertEqual([], self.library.written,
                         'an empty flush still rewrote the whole cache file')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataProgressTest(WiringHarness, unittest.TestCase):
    """Progress belongs to the action that started the work, and only to it."""

    def test_the_open_folder_route_never_touches_the_progress_channel(self):
        """0 calls, counted -- not "tolerated".

        ``set_progress`` *raises* for a known-but-not-progressable id (measured at
        ``view/widgets/action_rail.py:269-270``) and the presenter reaches it from a
        Qt slot, so a spinner for 打开文件夹 is a crash-on-touch rather than a cosmetic
        slip. The sweep itself stays unreported: the ``⋯`` marks on the rows are its
        progress (spec §10 risk 4). The sweep must be provably live in the same test,
        or a 0 that comes from "no sweep happened" would read the same.
        """
        library = self._make_library(count=2)
        from PyQt6.QtWidgets import QFileDialog

        with _spied(self.view, 'set_action_progress') as calls:
            with mock.patch.object(QFileDialog, 'getExistingDirectory',
                                   lambda *args, **kwargs: str(library)):
                self.view._rail.button_for('open_folder').click()
            self._await_plan(self._file_paths(library))
            self.assertEqual([], calls['set_action_progress'],
                              'the 打开文件夹 sweep reported progress on a button with '
                              'no running state; the rail raises on that call')
        self.assertEqual([STATE_KNOWN] * 2, self._states(),
                         'the sweep was not actually running, so the 0 above proves '
                         'nothing about progress reporting')

    def test_the_refresh_route_reports_one_balanced_pair_and_no_more(self):
        """``refresh`` brackets the *scan*; the sweep that follows reports nothing.

        ``PROGRESSABLE_IDS`` is read from the rail rather than assumed: it is the
        list the rail refuses everything else against, and the shape batch 2's
        guard points at ("widening it is a spec decision, not a test edit").
        """
        library = self._make_library(count=2)
        self._scan(library)
        self._await_plan(self._file_paths(library))
        progressable = _progressable_action_ids()
        self.assertEqual(('refresh', 'refresh_all'), progressable,
                         'the whitelist the progress claim is checked against could '
                         'not be read from the rail')

        with _spied(self.view, 'set_action_progress') as calls:
            self.view._rail.button_for(progressable[0]).click()
            self.assertEqual([('refresh', True), ('refresh', False)],
                             calls['set_action_progress'],
                             'a refresh must put its own button in flight and take it '
                             'out again, with no third state')
            self._await_plan([])
            self.assertEqual([('refresh', True), ('refresh', False)],
                             calls['set_action_progress'],
                             'the sweep that followed the scan reported progress of '
                             'its own -- the row marks are that progress')
        self.assertFalse(self.view._rail.is_running('refresh'),
                         'the rail was left spinning after a warm refresh')

    def test_a_switch_reports_no_progress_at_all(self):
        """Switching libraries is not a button with a running state."""
        first = self._make_library('rock', count=2)
        second = self._make_library('jazz', count=2)
        self._scan(first)
        self._await_plan(self._file_paths(first))

        with _spied(self.view, 'set_action_progress') as calls:
            self.view.library_selected.emit(str(second))
            self._scan(second)
            self._await_plan(self._file_paths(second))
            self.assertEqual([], calls['set_action_progress'])


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class NowPlayingStripTest(WiringHarness, unittest.TestCase):
    """spec §6's fourth item: filling a row must not repaint the strip."""

    def test_filling_the_playing_row_never_repaints_the_strip(self):
        from PyQt6.QtWidgets import QWidget

        library = self._make_library(count=2)
        paths = self._file_paths(library)
        strip = self.view.findChild(QWidget, 'nowPlayingStrip')
        self.assertIsNotNone(strip, '#nowPlayingStrip must be part of the shell')

        self._gate(*paths)
        self._scan(library)
        # Row 0 is the one the strip is about, so the sweep really does come for the
        # playing row -- the row it must fill without saying so anywhere else.
        self.queue.set_position_by_display_index(0)

        playing = Track(path=paths[0], title='Song A', artist='', album='')
        self.playback.current_track = playing
        self._emit(self.playback, 'track_changed', playing)
        self.assertEqual('Song A', strip._title_text, strip._title_text)
        # ``_on_track_changed`` also starts the *cover* load, whose answer legitimately
        # headlines the strip (spec §6: covers stay on the playback route). Drain it
        # before the window below, so what is counted there is the sweep and nothing
        # else -- the rows are still parked on their gates.
        self._pump_for(DRAIN_MS)
        headline = strip._title_text

        with _spied(self.view, 'update_track_info', 'clear_now_playing') as calls:
            self._release(*paths)
            self._await_plan(paths)
            self.assertEqual([], calls['update_track_info'],
                              'the sweep re-headlined the strip to say "正在播放": the '
                              'title flickers because a column was filled')
            self.assertEqual([], calls['clear_now_playing'])
        self.assertEqual(headline, strip._title_text,
                         'the strip changed text while the sweep filled rows')
        self.assertEqual(STATE_KNOWN, self._states()[0],
                         'the playing row never got its columns')
        self.assertEqual(['artist::track0', 'artist::track1'], self._artists())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class LibrarySwitchTest(WiringHarness, unittest.TestCase):
    """B4-R18 and spec §10 risk 1, on the wiring side."""

    def test_a_switch_cancels_before_wiping(self):
        first = self._make_library('rock', count=2)
        second = self._make_library('jazz', count=2)
        self._gate(*self._file_paths(first))
        self._scan(first)
        self.journal.clear()

        self.view.library_selected.emit(str(second))

        kinds = [step[0] for step in self.journal]
        self.assertIn('cancel_sweep', kinds, 'the switch never invalidated the sweep')
        self.assertIn('set_metadata', kinds, 'the switch never wiped the row table')
        self.assertLess(
            kinds.index('cancel_sweep'), kinds.index('set_metadata'),
            f'B4-R18 order broken: {self.journal} -- wiping before the cancel leaves '
            'the library being left a live callback on the table that was just cleared')
        self._release(*self._file_paths(first))

    def test_in_flight_rows_of_the_library_being_left_touch_nothing(self):
        """A's late rows neither repaint B nor land in B's cache."""
        first = self._make_library('rock', count=2)
        second = self._make_library('jazz', count=1, prefix='jazz')
        first_paths = self._file_paths(first)
        second_paths = self._file_paths(second)
        self._gate(*first_paths)
        self._scan(first)
        self.extract_calls.clear()

        self.view.library_selected.emit(str(second))
        self._scan(second)
        self._await_plan(second_paths)
        self._release(*first_paths)
        self._pump_until(lambda: len(self.extract_calls) >= 2,
                         'the retired plan\'s extraction never came back',
                         state=lambda: str(self.extract_calls))
        self._pump_for(DRAIN_MS)

        self.assertEqual(['artist::jazz0'], self._artists(),
                         'a row of the library being left reached the rows that are '
                         'displayed')
        for entry in self._raw_cache(second)['files']:
            with self.subTest(path=entry['path']):
                self.assertEqual(
                    f'artist::{Path(entry["path"]).stem}',
                    (entry.get('md') or {}).get('artist'),
                    'a late row of the previous library was written into the library '
                    'that arrived (spec §10 risk 1): every persisted value must '
                    'describe the file it is stored under')

    def test_the_count_that_decides_completion_belongs_to_one_generation(self):
        """§5.1's conditions ② and ⑤ on the wiring side.

        Plan 1 (two targets, both gated) is replaced by plan 2 (one target) without
        ever delivering. A shared counter would make plan 2 wait for three rows, so
        its completion flush would never come and its cache would stay unwritten --
        the mirror image of the "done too early" bug B4-R13 fixed.
        """
        first = self._make_library('rock', count=2)
        first_paths = self._file_paths(first)
        self._gate(*first_paths)
        self._scan(first)
        before = self.metadata.current_generation()
        self.journal.clear()

        second = self._make_library('jazz', count=1)
        second_paths = self._file_paths(second)
        self._scan(second)

        self.assertEqual(before + 1, self.metadata.current_generation(),
                         'one start_sweep consumed more than one generation')
        self.assertEqual(1, self.presenter._metadata_expected,
                         'the live plan\'s count is not its own target list')
        self._release(*first_paths)
        self._await_plan(second_paths, what='the second plan')
        self.assertEqual(1, len(self._writes_for(second)),
                         f'the count leaked across generations, so the new plan never '
                         f'finished its flush: {self.library.written}')
        self.assertEqual(0, len(self._writes_for(first)),
                         'a retired plan\'s rows were flushed into the library it was '
                         'replaced by')


    def test_a_plan_replaced_before_it_started_never_extracts(self):
        """I2(a), ruling B4-R21a: the generation is compared *before* extracting.

        ``_deliver_sweep_row`` already refused a superseded row, so the old shape was
        *correct* -- and paid one full extraction per row for an answer it then threw
        away. ``refresh_all`` walks k libraries and every scan replaces the previous
        plan, so the bill was (k-1) x n extractions on the same pool the playing track
        borrows.

        The parked workers are what makes the claim observable. While every worker of
        the global pool is blocked, a queued task cannot have started, so a path of the
        *first* library anywhere in the extraction log means the check ran after the
        work instead of before it -- which is exactly the shape that used to be true.
        """
        first = self._make_library('rock', count=2)
        second = self._make_library('jazz', count=1, prefix='jazz')
        first_paths = set(self._file_paths(first))
        second_paths = self._file_paths(second)
        gate = self._park_the_pool()

        self.presenter._metadata_library_path = str(first)
        self.presenter._start_metadata_sweep(self.library.get_files(str(first)))
        self.assertEqual(1, len(self.metadata.plans))
        self.assertEqual([], self.extract_calls,
                         'the pool was not really parked: the first plan had already '
                         'extracted before it was replaced, so the assertion below '
                         'would prove nothing')

        self.presenter._metadata_library_path = str(second)
        generation = self.presenter._start_metadata_sweep(
            self.library.get_files(str(second)))
        gate.set()

        self._await_plan(second_paths, what='the replacing plan')
        self.assertEqual(generation, self.metadata.current_generation())
        self.assertEqual([], sorted(set(self.extract_calls) & first_paths),
                         'a superseded plan still ran every one of its extractions and '
                         'threw the answers away at delivery (I2a): the cost is pool '
                         'time the listener is paying for while it plays')
        self.assertEqual(sorted(second_paths), sorted(self.extract_calls),
                         f'the live plan is the one that must still do its work: '
                         f'{self.extract_calls}')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MultiLibraryJointPlanTest(WiringHarness, unittest.TestCase):
    """I2(b), ruling B4-R21b: one walk of k libraries is **one** plan, k cache files.

    The library-side half of the claim is read from each library's *store*, not from the
    screen: after a refresh-all the playlist carries only the last library's rows, because
    ``_on_library_loaded`` rebuilds the queue once per library -- the pre-existing shape
    this ruling inherits and does not change (and the one
    ``test_player.TestHierarchicalPlaylist.test_multiple_libraries_display`` is about).
    What the joint plan is about is that the *other* libraries are no longer left waiting
    for a plan that was retired before it started.
    """

    def _make_library_service(self):
        return WalkedLibraryService(self.journal)

    def _walk(self, *libraries):
        """Point the refresh-all route at these real directories."""
        self.library.paths = [str(path) for path in libraries]
        self.assertEqual([], self.library.written,
                         'the walk already ran: the harness never emits '
                         'refresh_all_requested on its own')

    def _store_states(self, library):
        """``path -> state`` as one library's store answers for its own files."""
        store = self.presenter._metadata_stores[str(library)]
        paths = sorted(media.path for media in self.library.get_files(str(library)))
        return {path: store.state_of(path) for path in paths}

    def test_one_refresh_all_answers_every_library_and_writes_each_file_once(self):
        rock = self._make_library('rock', count=2)
        jazz = self._make_library('jazz', count=1, prefix='jazz')
        (jazz / 'locked.ncm').write_bytes(b'ncm' * 24)
        rock_paths = self._file_paths(rock)
        jazz_paths = self._file_paths(jazz)
        ncm = str(jazz / 'locked.ncm')
        self._walk(rock, jazz)

        self.view.refresh_all_requested.emit()

        self.assertEqual(1, len(self.metadata.plans),
                         f'a two-library walk started {len(self.metadata.plans)} sweeps: '
                         'every start_sweep retires the plan before it, so the columns of '
                         'every library but the last stay at ⋯ for the whole session (I2b)')
        _, targets = self.metadata.plans[0]
        self.assertEqual(sorted(rock_paths + jazz_paths),
                         sorted(triple[0] for triple in targets),
                         'the joint plan did not carry every library\'s to-do list')
        self._await_plan(rock_paths + jazz_paths)

        self.assertEqual({path: STATE_KNOWN for path in rock_paths},
                         self._store_states(rock),
                         'the first library of the walk was left with nothing answered: '
                         'its plan was replaced before its rows came back')
        self.assertEqual({**{path: STATE_KNOWN for path in jazz_paths},
                          ncm: STATE_UNKNOWN}, self._store_states(jazz),
                         'the last library of the walk is the one that used to survive; '
                         'it must still work, excluded format included')
        self.assertEqual(
            {**{path: STATE_KNOWN for path in jazz_paths}, ncm: STATE_UNKNOWN},
            self._state_by_path(),
            f'the rows on screen are not answered: {self._state_by_path()}')

        rock_writes, jazz_writes = self._writes_for(rock), self._writes_for(jazz)
        self.assertEqual(1, len(rock_writes),
                         f'rock did not get exactly one closing write-back: {rock_writes}')
        self.assertEqual(1, len(jazz_writes),
                         f'jazz did not get exactly one closing write-back: {jazz_writes}')
        self.assertEqual(sorted(rock_paths), sorted(rock_writes[0][1]),
                         'a write-back carried another library\'s rows')
        self.assertEqual(sorted(jazz_paths + [ncm]), sorted(jazz_writes[0][1]),
                         'the joint plan\'s flush did not carry the whole of one library')
        for library, own in ((rock, rock_paths), (jazz, jazz_paths + [ncm])):
            entries = self._raw_cache(library)['files']
            self.assertEqual(sorted(own), sorted(entry['path'] for entry in entries),
                             f'{library}: a foreign path entered this cache file')
            for entry in entries:
                with self.subTest(path=entry['path']):
                    self.assertIn('md', entry,
                                  'the answer never reached the file it belongs to')
                    if entry['path'] == ncm:
                        self.assertEqual({'artist': None, 'album': None,
                                          'duration': None}, entry['md'])
                    else:
                        self.assertEqual(
                            f'artist::{Path(entry["path"]).stem}', entry['md']['artist'],
                            'one library\'s metadata was written into another library\'s '
                            'cache file (spec §10 risk 1)')

    def test_the_batch_boundary_is_per_library_not_per_plan(self):
        """Each library flushes on its own count, into its own file.

        ``METADATA_WRITE_BATCH`` is patched to 1 so the boundary fires on every row, and
        the deliveries of two libraries interleave freely -- what has to hold either way
        is that a write-back names one library and carries rows of that library alone. A
        single plan-wide counter would instead flush a library on another library's rows.
        """
        rock = self._make_library('rock', count=2)
        jazz = self._make_library('jazz', count=2, prefix='jazz')
        rock_paths, jazz_paths = self._file_paths(rock), self._file_paths(jazz)
        self._walk(rock, jazz)

        with mock.patch.object(presenter_module, 'METADATA_WRITE_BATCH', 1):
            self.view.refresh_all_requested.emit()
            self._await_plan(rock_paths + jazz_paths)

        for library, own in ((rock, rock_paths), (jazz, jazz_paths)):
            writes = self._writes_for(library)
            self.assertEqual(2, len(writes),
                             f'{library}: one row per batch means one write per row of '
                             f'this library: {writes}')
            for _, updates in writes:
                self.assertEqual(1, len(updates), str(updates))
                self.assertTrue(next(iter(updates)).startswith(str(library)),
                                f'a flush of {library} carried {sorted(updates)}')

    def test_a_path_two_libraries_share_is_answered_in_both_files(self):
        """Overlapping libraries: one row of the plan per library that asked, and both
        cache files get the answer.

        ``scan_directory`` walks recursively, so a library and its own subfolder are two
        libraries over the same absolute files -- the shape spec §10 risk 1 names. The
        joint plan must not let the second library's copy of a path be answered by the
        first one's store alone, and must not write a payload into a file that does not
        list the path.
        """
        root = self.root / 'nested'
        inner = root / 'inner'
        inner.mkdir(parents=True)
        outer = root / 'outer.mp3'
        shared = inner / 'shared.mp3'
        outer.write_bytes(b'x' * 24)
        shared.write_bytes(b'y' * 32)
        root_paths = sorted(str(path) for path in root.rglob('*.mp3'))
        self._walk(root, inner)

        self.view.refresh_all_requested.emit()
        self._await_plan(root_paths + [str(shared)])

        _, targets = self.metadata.plans[0]
        self.assertEqual(sorted(root_paths + [str(shared)]),
                         sorted(triple[0] for triple in targets),
                         'a path two libraries share was dropped from the plan, so one '
                         'of the two stores could never be answered')
        self.assertEqual({path: STATE_KNOWN for path in root_paths},
                         self._store_states(root))
        self.assertEqual({str(shared): STATE_KNOWN}, self._store_states(inner))
        inner_entries = self._raw_cache(inner)['files']
        self.assertEqual([str(shared)], [entry['path'] for entry in inner_entries])
        for entry in inner_entries:
            self.assertEqual('artist::shared', (entry.get('md') or {}).get('artist'),
                             'the subfolder library got no answer of its own')
        self.assertEqual(sorted(root_paths),
                         sorted(entry['path'] for entry in self._raw_cache(root)['files']))


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class CallbackSafetyTest(WiringHarness, unittest.TestCase):
    """Fact 2: nothing may leave ``_on_metadata_row``."""

    def test_a_collaborator_that_raises_is_contained_and_the_row_is_recorded(self):
        """The delivery is a slot; the process is what is being protected.

        Called at the Python level on purpose: an exception escaping a slot invoked
        from C++ does not raise in a test, it ends the run (exit 127, no traceback),
        so the only way to make this claim *red* rather than *fatal* is to hand the
        callback a row the way ``_deliver_sweep_row`` does and catch here.
        """
        library = self._make_library(count=1)
        path = self._file_paths(library)[0]
        self._scan(library)
        self._await_plan([path])
        self.library.written.clear()

        exploding = ExplodingQueueService()
        exploding.build_from_tracks([_track(self.library.get_files(str(library))[0])])
        self.presenter._queue = exploding
        self.addCleanup(setattr, self.presenter, '_queue', self.queue)
        stat = os.stat(path)
        try:
            self.presenter._on_metadata_row(
                path, RowMetadata(artist='late'), stat.st_size, stat.st_mtime)
        except BaseException as exc:  # noqa: BLE001 - the claim is "never"
            self.fail(f'the on_row callback let {type(exc).__name__} escape: a '
                      'delivery that raises takes the process with it')

        self.assertEqual(
            'late', self.presenter._metadata_stores[str(library)].get(path).artist,
            'the store did not get the row: record must happen before the update '
            'that failed')
        self.assertEqual(1, len(self._writes_for(library)),
                         'the row whose repaint failed also lost its write-back, so '
                         'the batch it belonged to never reached the disk')

    def test_a_row_the_display_dropped_is_still_counted_and_recorded(self):
        """A delivery whose row is gone still advances the count.

        The user removing a row mid-sweep is the ordinary way this happens, and
        ``apply_metadata`` answering ``[]`` must not stall the plan: the result is
        still recorded (the file has an answer now) and the completion flush still
        comes. Neither half is guaranteed by anything upstream -- the queue
        deliberately forgets a row it cannot name, and the count is this file's.
        """
        library = self._make_library(count=2)
        paths = self._file_paths(library)
        self._gate(*paths)
        self._scan(library)
        self.library.written.clear()

        self.assertTrue(self.queue.remove_at_display_index(1))
        self._release(*paths)
        self._await_plan(paths)

        self.assertEqual(1, self.model.rowCount(),
                         'the row the test removed is still on screen: nothing was '
                         'actually taken out from under the sweep')
        self.assertEqual([STATE_KNOWN], self._states(),
                         'the surviving row never got its columns')
        self.assertEqual(1, len(self._writes_for(library)),
                         'the removed row\'s delivery either stalled the completion '
                         'flush or came back as a save of its own')
        _, updates = self._writes_for(library)[0]
        self.assertEqual(sorted(paths), sorted(updates),
                         'the answer for the file that left the playlist was dropped: '
                         'the store keeps it, so the next open does not re-extract')


    def test_clearing_the_playlist_mid_sweep_loses_no_answer_and_breaks_nothing(self):
        """Empty rows, still answers: the store persists what the display no longer has.

        ``QueueService.apply_metadata`` deliberately remembers nothing for a path it
        cannot name (Task 5), and ``clear()`` keeps the metadata table (ruling B4-R18),
        so the risk on this joint is a sweep that either stalls forever on a plan whose
        rows are gone -- the completion flush would then never come -- or writes an
        answer nobody asked for any more. Neither may happen.
        """
        library = self._make_library(count=2)
        paths = self._file_paths(library)
        self._gate(*paths)
        self._scan(library)
        self.library.written.clear()

        self.view.clear_playlist_requested.emit()
        self.assertEqual(0, self.model.rowCount(), 'the clear never reached the view')
        self._release(*paths)
        self._await_plan(paths)

        self.assertEqual(1, len(self._writes_for(library)),
                         'the plan whose rows were cleared never ran its flush')
        for entry in self._raw_cache(library)['files']:
            with self.subTest(path=entry['path']):
                self.assertIn('md', entry,
                              'an answer extracted for a row the user cleared was '
                              'dropped instead of persisted')
        self.assertEqual(0, self.model.rowCount())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class FingerprintNormalisationTest(WiringHarness, unittest.TestCase):
    """B4-R16: ``start_sweep`` refuses an ``int`` mtime, so the producer must not send one."""

    def test_an_integer_mtime_still_starts_a_sweep(self):
        """A hand-edited cache entry must not cost a whole library its columns.

        The symptom is the silent one: ``start_sweep`` refuses the triple, no sweep
        ever starts, and every row shows ``⋯`` forever with nothing on screen saying
        why. Ruling: the sweep's strictness stays, and the *producer* normalises.
        """
        library = self._make_library(count=2)
        files = self.library.get_files(str(library))
        for media in files:
            media.modified_time = int(media.modified_time)
        self.presenter._metadata_library_path = str(library)

        generation = self.presenter._start_metadata_sweep(files)
        # The scan entry points' own second half, spelled out because this test hands
        # the presenter a file list no scan would produce.
        self.queue.build_from_tracks([_track(media) for media in files])

        self.assertEqual([], self.metadata.refused,
                          f'the presenter handed start_sweep a payload it refuses: '
                          f'{self.metadata.refused}')
        self.assertEqual(generation, self.metadata.current_generation())
        for _, _, modified_time in self.metadata.plans[-1][1]:
            self.assertIsInstance(modified_time, float,
                                  'the target mtime was not normalised to float')
        self._await_plan([0, 1], what='the integer-mtime sweep')
        self.assertEqual([STATE_KNOWN] * 2, self._states())

    def test_a_non_numeric_fingerprint_drops_that_row_and_keeps_the_sweep(self):
        """One unreadable fingerprint is one row, not one dead plan."""
        library = self._make_library(count=2)
        paths = self._file_paths(library)
        files = self.library.get_files(str(library))
        files[0].modified_time = 'not a number'
        self.presenter._metadata_library_path = str(library)

        self.presenter._start_metadata_sweep(files)
        self.queue.build_from_tracks([_track(media) for media in files])

        self.assertEqual([], self.metadata.refused)
        self.assertEqual([paths[1]], [triple[0] for triple in self.metadata.plans[-1][1]],
                         'a row whose fingerprint is not a number was queued, or took '
                         'the whole plan down with it')
        self._await_plan([paths[1]])
        self.assertEqual([STATE_PENDING, STATE_KNOWN], self._states(),
                         'the dropped row was reported as anything but "not fetched"')

    def test_a_refused_plan_does_not_take_the_slot_or_the_app_down(self):
        """``start_sweep`` raises in the caller's thread -- and the scan survives it.

        A ``MediaFile`` whose path is not a ``str`` reaches ``start_sweep``'s shape
        check (ruling B4-R14), which raises on purpose. ``_on_library_loaded`` is a
        slot, so that exception has to be answered here: the rows the user can see
        must stay, and the sweep that was already running must not stay live against
        a library nobody is looking at any more.
        """
        library = self._make_library(count=1)
        paths = self._file_paths(library)
        files = self.library.get_files(str(library))
        files[0].path = Path(paths[0])          # the shape the channel refuses
        self.presenter._metadata_library_path = str(library)

        try:
            self.presenter._on_library_loaded(str(library), files)
        except BaseException as exc:  # noqa: BLE001 - the claim is "never"
            self.fail(f'a refused sweep escaped the library-loaded slot as '
                      f'{type(exc).__name__}: Qt answers that with qFatal')

        self.assertEqual(1, len(self.metadata.refused),
                         'the payload was never handed to start_sweep, so this test '
                         'is not about the refusal')
        self.assertEqual(1, self.model.rowCount(),
                         'a refused metadata plan took the file table down with it')
        self.assertEqual([STATE_PENDING], self._states())
        self.assertEqual(-1, self.presenter._metadata_generation,
                         'the presenter kept claiming a live plan after the refusal, '
                         'so a late row of the retired sweep would still be counted')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ClosingFlushDomainTest(WiringHarness, unittest.TestCase):
    """I3 / ruling B4-R23: a closing flush may only spend the libraries of its own plan.

    ``_flush_metadata_cache(None)`` closes a plan, and it used to walk **every store
    the presenter holds** while filtering against the *live plan's* fingerprint map.
    A store belonging to a retired plan is reachable without exotic timing --
    打开文件夹 while the previous sweep still has rows in flight starts a new plan
    without cancelling, so the old store survives with rows that were answered and
    not yet written. The wide walk consumed those rows' dirty flags and then skipped
    them (their paths are no longer in the map), i.e. threw away paid-for work for
    the rest of the session; the review's "the wide walk is free" is exactly the
    claim that is false -- it costs the flags. The plan's own libraries are already
    knowable (``_metadata_since_flush`` is seeded from ``join.targets``), which is
    why the fix is a range and not a redesign.

    Both halves are asserted: the flag survives (the store can still answer for it),
    **and** the answer reaches the file when that library's own plan closes --
    "not consumed" that never lands would only be a leak with better manners.
    """

    def test_a_closing_flush_leaves_another_library_s_dirty_flags_alone(self):
        first = self._make_library('rock', count=2)
        second = self._make_library('jazz', count=1, prefix='jazz')
        first_paths = self._file_paths(first)
        second_paths = self._file_paths(second)
        # Park the tail of A's plan so it stays *answered but unflushed*: with
        # METADATA_WRITE_BATCH far above 2 the only thing that flushes A is A's own
        # completion, and this gate is what keeps that from happening.
        self._gate(first_paths[1])

        self._scan(first)
        self._pump_until(
            lambda: self.presenter._metadata_delivered == 1,
            'the first library never answered its unblocked row',
            state=lambda: (f'delivered={self.presenter._metadata_delivered} '
                           f'calls={self.extract_calls}'))
        store_a = self.presenter._metadata_stores[str(first)]
        self.assertEqual(1, store_a.dirty_count(),
                         'the fixture is wrong: A owes no write-back, so this test '
                         'has nothing to lose')

        # The library route that does *not* cancel: a new plan replaces A's.
        self._scan(second)
        self._await_plan(second_paths)
        self._release(first_paths[1])

        self.assertEqual(
            1, store_a.dirty_count(),
            "B's closing flush drained A's dirty flags without writing them: A's "
            'answered row is now unwritable for the rest of the session (its path is '
            'not in the live plan\'s fingerprint map), so the extraction A paid for '
            'is redone after every restart (ruling B4-R23)')
        # The plan's own library still got its own write: the narrowing is a domain,
        # not a suppression.
        self.assertEqual(1, len(self._writes_for(second)),
                         'the closing flush never wrote the library it belongs to')
        self.assertIsNone(
            self._raw_by_name(first)['track0.mp3'].get('md'),
            'A was written by B\'s flush after all -- the cross-library leak '
            'spec §10 risk 1 forbids, and the reason the flags and the writes '
            'have to share one domain')

        # And A still reaches its own file when *A's* plan closes.
        self._scan(first)
        self._await_plan([first_paths[1]])

        by_name = self._raw_by_name(first)
        for name in ('track0.mp3', 'track1.mp3'):
            with self.subTest(entry=name):
                self.assertEqual(
                    f'artist::{Path(name).stem}',
                    (by_name[name].get('md') or {}).get('artist'),
                    'the row A had already answered never reached A\'s cache file: '
                    'its dirty flag was consumed by another plan, so the answer was '
                    'thrown away (durability, ruling B4-R23)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
