#!/usr/bin/env python3
"""Task 4: the background metadata sweep -- generations, delivery, event loop.

``MetadataService.start_sweep`` is the only place batch 4 turns Task 3's
``validate`` output into actual extraction, and it has two jobs that a
single-threaded test cannot fake: run on ``QThreadPool.globalInstance()`` *while
the GUI thread keeps serving events*, and throw away anything that belongs to a
library the user has already left (spec §4.5, §6, §8).

What is pinned below, in the order the rules bite:

* **The fingerprint travels with its own row.** ``on_row`` is handed the
  ``(size, mtime)`` of *that* target -- the pair ``validate`` handed out, never a
  re-stat and never a parallel list (Task 3's ruling: one instant, shared by the
  sweep and Task 7's write-back re-check). A sweep that re-stats lets the three
  views of "current" drift apart mid-sweep; a sweep that zips two lists mispairs
  silently, and a mispaired fingerprint is a dirty write (spec §10 risk 1).
* **The generation is held by the service, not passed in by the caller.**
  ``start_sweep`` returns the generation it ran under, ``cancel_sweep`` increments
  and returns the new one, ``current_generation`` reads it. A caller-supplied
  generation was rejected in review because an already-stale argument makes the
  *correct* behaviour ("the previous library's rows are dropped") indistinguishable
  from a callback that simply never fires -- a silently dead feature with green tests.
* **A stale result is dropped without calling ``on_row`` at all.** Not "called with
  ``None``": the previous library must not touch the current library's rows even
  to say "nothing found". And the drop has to be the *generation comparison's* work,
  which is why the cancellation test re-uses the cancelled sink under the live
  generation at the end: if the service silenced a switch by detaching the callback
  instead, the comparison would be untested (measured: an "always current" mutation
  survived the first draft of that test for exactly that reason).
* **One bad file is one row, not one sweep** (spec §6's first two items): the
  extraction is wrapped per entry, the failure arrives as ``md=None`` (which is
  "tried, nothing" to the store, so it survives a restart instead of being retried
  on every launch), the rest of the batch still lands, and nothing escapes the
  pool thread. That last clause is not cosmetic: on PyQt6 6.11 an exception
  leaving ``QRunnable.run`` aborts the *process* (measured: exit 127, no traceback),
  and a background batch has no button to hang a dialog on either, so the sweep
  emits **no signal** at all.
* **The event loop keeps running while the sweep runs** (spec §8's last line).
  This is the only place "background" is falsifiable, so it is measured, not
  assumed: a fake extractor parks on a flag, and a single-shot ``QTimer`` still
  fires in that window, *before* any row is delivered.

Concurrency rules this file follows (deliberately, so it cannot hang the suite):

* every wait is ``QApplication.processEvents()`` rotation under an explicit
  wall-clock cap (:meth:`_SweepTestBase._pump_until`), and a timeout reports the
  counters instead of spinning forever. No ``time.sleep``, no unbounded wait, no
  ``QThreadPool.waitForDone`` polling.
* a blocked fake extractor waits on ``threading.Event.wait(GATE_WAIT_S)`` -- a
  *capped* wait. A production change that ran the extraction on the calling thread
  therefore fails an assertion instead of deadlocking the run: the caller would be
  stuck inside ``start_sweep``, and the assertion right after it is the red.
* every gate a test creates is opened in ``tearDown``, so no pool thread outlives
  the test that blocked it.
"""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_view_smoke import QT_AVAILABLE, make_app

from core.metadata import SongMetadata

try:  # ``MetadataService`` needs Qt; the skipUnless below is what guards it.
    from service.metadata_service import MetadataService
    from service.metadata_store import RowMetadata
except ImportError:  # pragma: no cover - environment without PyQt6
    MetadataService = None
    RowMetadata = None

#: Paths only: the fake extractor never touches the disk, and Task 4 must not
#: either (spec §8: the sweep is tested without real audio).
MP3 = str(Path('library', 'jazz', 'midnight.mp3'))
FLAC = str(Path('library', 'jazz', 'blue.flac'))
OGG = str(Path('library', 'jazz', 'live.ogg'))

#: Distinct per row on purpose -- a shared fingerprint would let a mispaired
#: ``(size, mtime)`` pass every assertion below.
TARGETS = ((MP3, 1000, 100.0), (FLAC, 2000, 200.5), (OGG, 3000, 300.25))

#: How long a blocked fake extractor may hold a pool thread. Capped so that a
#: regression which runs the sweep on the calling thread surfaces as a failed
#: assertion rather than a suite that never exits.
GATE_WAIT_S = 3.0

#: Wall-clock caps for the event-loop waits below. Generous against real timing
#: (these conditions settle in milliseconds), small enough to keep a real
#: regression loud and short.
PUMP_LIMIT_MS = 1500
DRAIN_MS = 300


def _song(full_path: str) -> SongMetadata:
    """What the real facade answers for one path, derived from it."""
    stem = Path(full_path).stem
    return SongMetadata(title=stem, artist=f'artist::{stem}',
                        album=f'album::{stem}', duration=100.0 + len(stem),
                        album_art=b'never-read-by-the-sweep')


class RowSink:
    """An ``on_row`` target: records every delivery and the thread it arrived on."""

    def __init__(self):
        self.rows = []        # ``(full_path, md, size_bytes, modified_time)``
        self.threads = []     # ``threading.get_ident()`` per delivery

    def __call__(self, full_path, md, size_bytes, modified_time):
        self.rows.append((full_path, md, size_bytes, modified_time))
        self.threads.append(threading.get_ident())

    @property
    def paths(self):
        return [row[0] for row in self.rows]

    def __str__(self):
        return f'rows={self.rows!r} threads={self.threads!r}'


def _fake_extractor(values, calls, started=None, gates=None, returned=None):
    """A stand-in for ``extract_metadata`` with every branch a test needs.

    ``values`` maps a path to what the extractor answers. An ``Exception``
    *instance* is raised instead of returned (spec §6's failing file); anything
    else is returned as-is, so a ``None`` answer and a ``SongMetadata`` answer are
    both expressible. ``gates`` holds one optional flag per path, which lets a
    test block only the sweep it is watching while a later sweep on the same
    service runs freely.

    ``list.append`` is atomic under CPython, so the three recorders need no lock:
    they are written by pool threads and read by the GUI thread only *after* an
    event-loop wait.
    """
    def extract(full_path):
        calls.append(full_path)
        if started is not None:
            started.append(full_path)
        gate = None if gates is None else gates.get(full_path)
        if gate is not None:
            gate.wait(GATE_WAIT_S)
        if returned is not None:
            returned.append(full_path)
        value = values.get(full_path)
        if isinstance(value, BaseException):
            raise value
        return value

    return extract


class _SweepTestBase(unittest.TestCase):
    """Shared harness: the app, the gate bookkeeping, and the bounded waits."""

    def setUp(self):
        self.app = make_app()
        self._gates = []

    def tearDown(self):
        # Nothing may leave the test holding a pool thread hostage.
        for gate in self._gates:
            gate.set()
        self._pump_for(50)

    def _new_gate(self):
        gate = threading.Event()
        self._gates.append(gate)
        return gate

    def _service(self, extractor):
        return MetadataService(extractor=extractor)

    def _pump_until(self, condition, what, state=None, limit_ms=PUMP_LIMIT_MS):
        """Rotate the event loop until ``condition()`` or the cap expires.

        ``processEvents()`` is what delivers both timer events and the queued
        cross-thread sweep results, so this replaces every kind of wait in this
        file: sleeping would block the loop under test, and an unbounded spin
        would turn a defect into a hung CI run.
        """
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
        """Give posted events ``budget_ms`` of event loop, then look away."""
        from PyQt6.QtCore import QElapsedTimer

        clock = QElapsedTimer()
        clock.start()
        while clock.elapsed() < budget_ms:
            self.app.processEvents()


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepTest(_SweepTestBase):
    """The sweep's outward contract: one delivery per target, with its own data."""

    def test_every_target_is_delivered_once_with_its_own_fingerprint(self):
        calls = []
        sink = RowSink()
        service = self._service(
            _fake_extractor({path: _song(path) for path, _, _ in TARGETS}, calls))

        generation = service.start_sweep(list(TARGETS), sink)
        self.assertEqual(
            generation, service.current_generation(),
            'start_sweep must answer with the generation it ran under, not the '
            'number of queued tasks')

        self._pump_until(
            lambda: len(sink.rows) == len(TARGETS),
            'the sweep did not deliver every target',
            state=lambda: f'{sink} calls={calls}')

        self.assertEqual(len(TARGETS), len(sink.rows),
                         f'one delivery per target expected: {sink}')
        self.assertEqual(sorted(path for path, _, _ in TARGETS), sorted(sink.paths),
                         'the sweep delivered a different path set than it was given')
        for full_path, md, size_bytes, modified_time in sink.rows:
            expected = next(triple for triple in TARGETS if triple[0] == full_path)
            self.assertEqual(
                (expected[1], expected[2]), (size_bytes, modified_time),
                f'{full_path} came back with a fingerprint that is not its own '
                f'-- Task 7 re-checks this pair against the disk')
            self.assertIsInstance(md, RowMetadata,
                                  'the sweep speaks rows, not SongMetadata')
            self.assertEqual(_song(full_path).artist, md.artist)
            self.assertEqual(_song(full_path).album, md.album)
            self.assertEqual(_song(full_path).duration, md.duration)
        self.assertEqual(sorted(path for path, _, _ in TARGETS), sorted(calls),
                         'each path must be extracted exactly once')

    def test_absent_tags_stay_none_and_the_row_is_not_invented(self):
        """Task 2's ``None`` semantics survive the trip into a row."""
        empty = SongMetadata(title='blue', artist=None, album=None, duration=None)
        calls = []
        sink = RowSink()
        service = self._service(_fake_extractor(
            {MP3: _song(MP3), FLAC: empty, OGG: None}, calls))

        service.start_sweep(list(TARGETS), sink)
        self._pump_until(lambda: len(sink.rows) == len(TARGETS),
                         'the sweep did not deliver every target',
                         state=lambda: str(sink))

        rows = {row[0]: row[1] for row in sink.rows}
        self.assertEqual(
            RowMetadata(artist=None, album=None, duration=None), rows[FLAC],
            'an all-None extraction is a *present* row of unknowns (ruling B4-R8), '
            'not a re-phrase into pending and not an invented "Unknown Artist"')
        self.assertIsNone(rows[OGG],
                          'an extractor that answers nothing must reach the row as '
                          'None; the store turns it into "tried, nothing"')
        self.assertEqual((_song(MP3).artist, _song(MP3).album),
                         (rows[MP3].artist, rows[MP3].album))

    def test_extractor_failure_is_one_none_row_and_stays_off_the_dialogue(self):
        """spec §6 items 1-2: a raising file, the batch intact, nothing escaping."""
        boom = RuntimeError('undecodable container')
        calls = []
        sink = RowSink()
        service = self._service(_fake_extractor(
            {MP3: _song(MP3), FLAC: boom, OGG: _song(OGG)}, calls))

        # "不弹窗" has a shape in this class: the error signal is the only channel
        # a presenter could hang a dialog on, and the sweep must not feed it -- nor
        # the album-art path it deliberately does not belong to.
        emitted = []
        for name in ('metadata_error', 'metadata_loaded', 'album_art_loaded'):
            getattr(service, name).connect(
                lambda *args, _name=name: emitted.append((_name,) + args))

        service.start_sweep(list(TARGETS), sink)
        self._pump_until(lambda: len(sink.rows) == len(TARGETS),
                         'a raising extractor swallowed the rest of the batch',
                         state=lambda: f'{sink} calls={calls} emitted={emitted}')

        rows = {row[0]: row for row in sink.rows}
        self.assertIsNone(rows[FLAC][1],
                          'the failed file must arrive as md=None ("tried, nothing")')
        self.assertEqual(_song(MP3).artist, rows[MP3][1].artist)
        self.assertEqual(_song(OGG).artist, rows[OGG][1].artist)
        self.assertEqual([], emitted,
                         'the sweep reported a background failure through a signal '
                         '-- a batch nobody started a button for (spec §6)')

    def test_sweep_writes_no_cache(self):
        """Task 7 owns persistence; a sweep that cached rows would fake a warm start."""
        calls = []
        sink = RowSink()
        service = self._service(_fake_extractor({MP3: _song(MP3)}, calls))
        service.clear_cache()

        service.start_sweep([(MP3, 1000, 100.0)], sink)
        self._pump_until(lambda: len(sink.rows) == 1,
                         'the sweep did not deliver its only target',
                         state=lambda: str(sink))

        self.assertIsNone(service.get_cached(MP3),
                          'the sweep put a row into the metadata cache: the batch 4 '
                          'rows are the queue\'s, and writing them is Task 7')

    def test_empty_targets_return_the_generation_and_start_nothing(self):
        calls = []
        sink = RowSink()
        service = self._service(_fake_extractor({}, calls))

        # Lift the generation off zero: an implementation that returned the
        # enqueue count would answer 0 here and look like a generation.
        service.cancel_sweep()
        service.cancel_sweep()
        generation = service.current_generation()

        self.assertEqual(generation, service.start_sweep([], sink))
        self.assertEqual(generation, service.current_generation(),
                         'an empty sweep must not consume a generation')
        self._pump_for(DRAIN_MS)
        self.assertEqual([], calls, 'an empty target list started an extraction')
        self.assertEqual([], sink.rows, 'an empty target list called back')

    def test_generations_move_only_on_cancel(self):
        """``start`` adopts, ``cancel`` advances: the generation is the library's."""
        calls = []
        service = self._service(_fake_extractor({}, calls))
        first = service.start_sweep([TARGETS[0]], RowSink())
        second = service.start_sweep([TARGETS[1]], RowSink())
        self.assertEqual(
            first, second,
            'a second sweep of the same library must not invalidate the first one; '
            'only switching libraries (cancel) does that (spec §4.5)')

        cancelled = service.cancel_sweep()
        self.assertEqual(cancelled, service.current_generation())
        self.assertEqual(first + 1, cancelled,
                         'cancel must advance the generation by exactly one and '
                         'answer with the new value')
        self.assertEqual(cancelled, service.start_sweep([], RowSink()),
                         'the sweep after a cancel runs under the new generation')
        self.assertEqual(cancelled, service.cancel_sweep() - 1)

    def test_default_extractor_is_the_real_extraction_entry_point(self):
        """Injection is a test seam, not the production path.

        The default is resolved when the service is built, so the patch has to be
        in place first; either way the name under test is the one production
        imports (``core.metadata.extract_metadata``).
        """
        calls = []
        sink = RowSink()
        with mock.patch('service.metadata_service.extract_metadata',
                        side_effect=_fake_extractor({MP3: _song(MP3)}, calls)):
            service = MetadataService()
            service.start_sweep([(MP3, 1000, 100.0)], sink)
            self._pump_until(lambda: len(sink.rows) == 1,
                             'the default extractor never came back',
                             state=lambda: f'{sink} calls={calls}')

        self.assertEqual([MP3], calls)
        self.assertEqual(_song(MP3).artist, sink.rows[0][1].artist)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepCancellationTest(_SweepTestBase):
    """Switching libraries mid-sweep: the old rows never reach the new library."""

    def test_in_flight_results_of_a_cancelled_generation_are_dropped(self):
        gate = self._new_gate()
        started, returned, calls = [], [], []
        values = {path: _song(path) for path, _, _ in TARGETS}
        old_sink, new_sink = RowSink(), RowSink()
        service = self._service(_fake_extractor(values, calls, started=started,
                                                gates={MP3: gate}, returned=returned))

        old_generation = service.start_sweep([TARGETS[0]], old_sink)
        self._pump_until(lambda: len(started) == 1,
                         'the sweep never reached the pool thread',
                         state=lambda: f'started={started} calls={calls}')

        new_generation = service.cancel_sweep()
        self.assertNotEqual(old_generation, new_generation)
        self.assertEqual(new_generation, service.current_generation())

        # Let the blocked extraction finish: its result now exists, and is stale.
        gate.set()
        self._pump_until(lambda: len(returned) == 1,
                         'the extraction never came back after the gate opened',
                         state=lambda: f'returned={returned} started={started}')
        # The result is posted to the GUI thread; give it its chance to arrive, so
        # "dropped" is an observation and not an unscheduled race.
        self._pump_for(DRAIN_MS)
        self.assertEqual([], old_sink.rows,
                          'a cancelled generation delivered to on_row -- the '
                          'previous library just wrote into the current rows')

        # The same service must still sweep the new library normally.
        started_generation = service.start_sweep([TARGETS[1]], new_sink)
        self.assertEqual(new_generation, started_generation)
        self._pump_until(lambda: len(new_sink.rows) == 1,
                         'the sweep after a cancel never delivered',
                         state=lambda: f'new={new_sink} old={old_sink}')
        self.assertEqual((FLAC, TARGETS[1][1], TARGETS[1][2]),
                         (new_sink.rows[0][0], new_sink.rows[0][2],
                          new_sink.rows[0][3]))
        self._pump_for(DRAIN_MS)
        self.assertEqual([], old_sink.rows,
                          'the stale result arrived late, under the new callback')

        # ... and ``old_sink`` was never deaf: handed the *current* generation it
        # receives at once. Without this the drop above could equally be explained by
        # a callback the service quietly detached on cancel, and a generation
        # comparison that always answered "current" would stay green.
        service.start_sweep([TARGETS[2]], old_sink)
        self._pump_until(lambda: len(old_sink.rows) == 1,
                         'the cancelled sink never received a current-generation row',
                         state=lambda: f'old={old_sink} new={new_sink}')
        self.assertEqual([OGG], old_sink.paths,
                          'the stale row arrived after all, next to the live one')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepConcurrencyTest(_SweepTestBase):
    """The two claims that only hold when the work really is in another thread."""

    def test_event_loop_stays_responsive_while_the_sweep_is_blocked(self):
        """spec §8: "sweep 期间事件循环仍可响应".

        The extractor parks on a flag; a single-shot ``QTimer`` must still fire in
        that window, and it must fire *before* any row is delivered. An
        implementation that extracted on the calling thread would sit inside
        ``start_sweep`` until the gate's own cap expired -- which is why the wait
        is capped, and why the first assertion below is the one that goes red.
        """
        gate = self._new_gate()
        started, returned, calls = [], [], []
        extractor = _fake_extractor({path: _song(path) for path, _, _ in TARGETS},
                                    calls, started=started, gates={
                                        MP3: gate, FLAC: gate, OGG: gate},
                                    returned=returned)
        sink = RowSink()
        service = self._service(extractor)
        order = []

        from PyQt6.QtCore import QTimer

        QTimer.singleShot(25, lambda: order.append('timer'))
        service.start_sweep(list(TARGETS), sink)

        self.assertEqual([], returned,
                         'start_sweep only returned once every extraction had '
                         'finished -- it ran on the calling thread, so the UI would '
                         'freeze for the whole library')
        self._pump_until(lambda: len(started) == len(TARGETS),
                         'the pool threads never entered the extractor',
                         state=lambda: f'started={started} calls={calls}')
        self._pump_until(lambda: 'timer' in order,
                         'a single-shot QTimer never fired while the sweep ran',
                         state=lambda: f'order={order} started={started} sink={sink}')
        self.assertEqual([], sink.rows,
                         'a row was delivered while its extraction was still '
                         'blocked -- the ordering proof is void')
        self.assertEqual('timer', order[0],
                         'the first event the loop served was not the timer')

        gate.set()
        self._pump_until(lambda: len(sink.rows) == len(TARGETS),
                         'the sweep did not finish after the gate opened',
                         state=lambda: f'{sink} returned={returned}')

    def test_rows_are_delivered_on_the_gui_thread(self):
        """A pool thread must not run a callback that goes on to touch a widget."""
        calls = []
        sink = RowSink()
        service = self._service(
            _fake_extractor({MP3: _song(MP3), FLAC: _song(FLAC)}, calls))

        service.start_sweep([TARGETS[0], TARGETS[1]], sink)
        self._pump_until(lambda: len(sink.rows) == 2,
                         'the sweep did not deliver both targets',
                         state=lambda: f'{sink} calls={calls}')

        self.assertEqual([threading.get_ident()] * 2, sink.threads,
                         'on_row ran on a pool thread; Task 7 hands it a model '
                         'update and a repaint')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepShapeTest(_SweepTestBase):
    """The reuse the plan asked for, so the batch does not grow a second pool."""

    def test_sweep_runs_on_the_shared_global_pool(self):
        from PyQt6.QtCore import QThreadPool

        gate = self._new_gate()
        started, returned, calls = [], [], []
        service = self._service(_fake_extractor({MP3: _song(MP3)}, calls,
                                                started=started,
                                                gates={MP3: gate},
                                                returned=returned))
        self.assertIs(QThreadPool.globalInstance(), service._thread_pool,
                      'a second thread pool for batch 4 is exactly what the plan '
                      'ruled out')

        service.start_sweep([TARGETS[0]], RowSink())
        self._pump_until(lambda: len(started) == 1,
                         'the global pool never picked the task up',
                         state=lambda: f'started={started}')
        self.assertGreaterEqual(QThreadPool.globalInstance().activeThreadCount(), 1,
                                'the sweep is not running in the pool it claims to '
                                'reuse')
        gate.set()
        self._pump_until(lambda: len(returned) == 1,
                         'the blocked extraction never finished',
                         state=lambda: f'returned={returned}')

    def test_preload_files_is_not_the_sweep(self):
        """``preload_files`` keeps its album-art meaning; Task 4 did not rewire it.

        It has no fingerprints to travel with (``validate`` hands those out, a bare
        path list does not) and its results belong to the cover cache, which batch
        4 does not touch. Wiring it to ``start_sweep`` would therefore either stat
        behind the store's back or hand a ``RowMetadata`` to ``load_async``'s cover
        path. This pins that reading so a later task cannot merge the two by
        accident -- the sweep's caller is Task 7's presenter.
        """
        calls = []
        service = self._service(_fake_extractor({MP3: _song(MP3)}, calls))
        service.clear_cache()  # the cache is class-level; a warm entry skips loading
        with mock.patch.object(service, 'load_async') as load_async, \
                mock.patch.object(service, 'start_sweep') as start_sweep:
            service.preload_files([MP3, FLAC])

        self.assertEqual([mock.call(MP3), mock.call(FLAC)], load_async.call_args_list)
        start_sweep.assert_not_called()
        self.assertEqual([], calls, 'a cover preload started a sweep extraction')


if __name__ == '__main__':
    unittest.main(verbosity=2)
