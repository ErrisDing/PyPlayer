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
* **The generation is held by the service, and one sweep is one generation.**
  ``start_sweep`` takes a fresh generation and returns it, ``cancel_sweep`` takes one
  too, ``current_generation`` reads the live one. A caller-supplied generation was
  rejected in review because an already-stale argument makes the *correct* behaviour
  ("the previous library's rows are dropped") indistinguishable from a callback that
  simply never fires -- a silently dead feature with green tests. A generation
  *shared by two calls* is rejected for the same kind of reason (ruling B4-R13): the
  second call's callback then also receives the first plan's in-flight rows, and a
  caller counting deliveries against ``len(targets)`` -- which is exactly how Task 7
  learns a sweep finished -- declares the new plan done before its own work lands.
* **A stale result is dropped without calling ``on_row`` at all.** Not "called with
  ``None``": the previous library must not touch the current library's rows even
  to say "nothing found". And the drop has to be the *generation comparison's* work,
  which is why the cancellation test re-uses the cancelled sink under the live
  generation at the end: if the service silenced a switch by detaching the callback
  instead, the comparison would be untested (measured: an "always current" mutation
  survived the first draft of that test for exactly that reason).
* **A bad target list is refused in the caller's own thread, before anything moves**
  (ruling B4-R14). Every entry has to be the ``(str, int, float)`` triple
  ``validate`` hands out: a bare path list or two parallel lists pair a row with
  another row's fingerprint silently, and a path that is not ``str`` would raise
  ``TypeError`` inside ``emit`` on a pool thread -- the same class of escaping
  exception that aborts the process two bullets down. Refusal is also atomic: a bad
  entry late in the list may not leave the rows before it queued and counted against
  a sweep its caller was told never started.
* **A payload the channel refuses costs one row, not the run.** The report step is
  wrapped in ``except Exception``, so a task carrying something the ``str`` slot
  will not take drops that row, delivers the rest of the sweep, and lets the process
  survive to assert it.
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
    from service.metadata_service import MetadataService, MetadataSweepTask
    from service.metadata_store import RowMetadata
except ImportError:  # pragma: no cover - environment without PyQt6
    MetadataService = None
    MetadataSweepTask = None
    RowMetadata = None

#: Paths only: the fake extractor never touches the disk, and Task 4 must not
#: either (spec §8: the sweep is tested without real audio).
MP3 = str(Path('library', 'jazz', 'midnight.mp3'))
FLAC = str(Path('library', 'jazz', 'blue.flac'))
OGG = str(Path('library', 'jazz', 'live.ogg'))

#: Distinct per row on purpose -- a shared fingerprint would let a mispaired
#: ``(size, mtime)`` pass every assertion below.
TARGETS = ((MP3, 1000, 100.0), (FLAC, 2000, 200.5), (OGG, 3000, 300.25))

#: A second plan for the same library, on paths the gated targets do not use, so a
#: re-scan's rows can be told apart from the retired plan's.
EXTRA = ((str(Path('library', 'rock', 'bonus.mp3')), 4000, 400.5),
         (str(Path('library', 'rock', 'encore.flac')), 5000, 500.75))

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
        before = service.current_generation()

        generation = service.start_sweep([], sink)
        self.assertEqual(
            before + 1, generation,
            'an empty sweep still takes a generation of its own: inheriting the '
            'previous one is how that plan\'s rows reach an empty callback')
        self.assertEqual(generation, service.current_generation(),
                         'start_sweep must answer with the generation it just took, '
                         'not the number of queued tasks')
        self._pump_for(DRAIN_MS)
        self.assertEqual([], calls, 'an empty target list started an extraction')
        self.assertEqual([], sink.rows, 'an empty target list called back')

    def test_every_start_and_every_cancel_advances_the_generation(self):
        """Both mutators advance by exactly one; ``start`` is not a read.

        The counter identifies *this* sweep, not this library (ruling B4-R13) -- the
        delivery half of that is pinned by
        :meth:`MetadataSweepRescanTest.test_a_rescan_without_a_cancel_retires_the_first_sweep`,
        which is where sharing an id actually does damage.
        """
        calls = []
        service = self._service(_fake_extractor({}, calls))

        first = service.start_sweep([TARGETS[0]], RowSink())
        self.assertEqual(first, service.current_generation(),
                         'current_generation must report the sweep that is live now')
        second = service.start_sweep([TARGETS[1]], RowSink())
        self.assertEqual(
            first + 1, second,
            'a re-scan of the same library must not share the retired plan\'s '
            'generation; only advancing the counter makes its rows worthless')

        cancelled = service.cancel_sweep()
        self.assertEqual(second + 1, cancelled,
                         'cancel must advance the generation by exactly one and '
                         'answer with the new value')
        self.assertEqual(cancelled, service.current_generation())

        empty = service.start_sweep([], RowSink())
        self.assertEqual(
            cancelled + 1, empty,
            'an empty sweep is still a sweep: it owns a callback, so it must not '
            'inherit one that is still in flight')

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
        self.assertNotEqual(
            new_generation, started_generation,
            'starting the new library takes a generation of its own; the cancel '
            'only retired what was in flight before it')
        self.assertEqual(started_generation, service.current_generation())
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
class MetadataSweepRescanTest(_SweepTestBase):
    """Two sweeps on one library with no cancel between them: one of them survives."""

    def test_a_rescan_without_a_cancel_retires_the_first_sweep(self):
        """Ruling B4-R13 -- the shape the review measured before this fix.

        Three targets queued and blocked, then two more on the same service without
        a cancel. While only ``cancel_sweep`` advanced the counter, both plans shared
        one generation, so the *new* callback received **five** rows -- the retired
        plan's three included -- while the retired callback got none. Task 7 counts
        deliveries against ``len(targets)`` to learn when a sweep finished, so that
        shape declares a two-row sweep done before its own two rows land, and the
        plan it replaced can never reach its own count at all.
        """
        gate = self._new_gate()
        started, returned, calls = [], [], []
        first_sink, second_sink = RowSink(), RowSink()
        values = {path: _song(path) for path, _, _ in TARGETS + EXTRA}
        service = self._service(_fake_extractor(
            values, calls, started=started, returned=returned,
            gates={path: gate for path, _, _ in TARGETS}))

        first = service.start_sweep(list(TARGETS), first_sink)
        self._pump_until(lambda: len(started) == len(TARGETS),
                         'the first plan never reached the pool threads',
                         state=lambda: f'started={started} calls={calls}')

        second = service.start_sweep(list(EXTRA), second_sink)
        self.assertNotEqual(
            first, second,
            'one start_sweep is one generation; sharing one with the plan it '
            'replaced is exactly what lets that plan\'s rows reach this callback')
        self.assertEqual(second, service.current_generation())

        self._pump_until(lambda: len(second_sink.rows) == len(EXTRA),
                         'the re-scan did not deliver its own two rows',
                         state=lambda: f'first={first_sink} second={second_sink}')

        # The retired plan is still in flight: let it finish and land, so the drop
        # below is an observation about the gate and not a race against the pool.
        gate.set()
        self._pump_until(lambda: len(returned) == len(TARGETS) + len(EXTRA),
                         'the blocked extractions never came back',
                         state=lambda: f'returned={returned} started={started}')
        self._pump_for(DRAIN_MS)

        self.assertEqual([], first_sink.rows,
                         'the retired callback still receives its own rows')
        self.assertEqual(
            len(EXTRA), len(second_sink.rows),
            'the live callback received the retired plan as well, so a count '
            f'against len(targets) would finish early: {second_sink}')
        self.assertEqual(sorted(path for path, _, _ in EXTRA),
                         sorted(second_sink.paths),
                         'the rows delivered to the live callback are not the live '
                         'plan\'s')
        for full_path, md, size_bytes, modified_time in second_sink.rows:
            expected = next(triple for triple in EXTRA if triple[0] == full_path)
            self.assertEqual((expected[1], expected[2]), (size_bytes, modified_time),
                             'a re-scan row came back with a fingerprint that is not '
                             'its own')
            self.assertIsNotNone(md, 'the live plan\'s row arrived as nothing')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepInputTest(_SweepTestBase):
    """``start_sweep`` eats ``validate``'s triples, or refuses in the caller's thread."""

    def test_a_bare_path_list_is_refused_before_anything_is_queued(self):
        """The shape review item M7 could only claim behaviourally until now."""
        calls = []
        sink = RowSink()
        service = self._service(_fake_extractor(
            {path: _song(path) for path, _, _ in TARGETS}, calls))
        before = service.current_generation()

        with self.assertRaises(ValueError):
            service.start_sweep([MP3, FLAC], sink)

        self.assertEqual(
            before, service.current_generation(),
            'a refused start_sweep consumed a generation, retiring a sweep that is '
            'still running and that its caller never heard about')
        self._pump_for(DRAIN_MS)
        self.assertEqual([], calls, 'a refused target list queued an extraction')
        self.assertEqual([], sink.rows, 'a refused target list called back')

    def test_every_mis_shaped_or_wrongly_typed_entry_is_refused(self):
        """The triple's types and the list itself are the contract (ruling B4-R14).

        ``ValueError`` for the arity cases, ``TypeError`` for the type cases, and the
        split is not decoration: a caller has to be able to tell "that is not a
        triple" from "that triple carries a path the delivery channel cannot take".
        The ``Path`` case is the one that used to be fatal -- see the payload test.
        """
        cases = [
            ('a path instead of a triple', [MP3], ValueError),
            ('one field', [(MP3,)], ValueError),
            ('a path plus its fingerprint pair -- two parallel lists',
             [(MP3, (1000, 100.0)), (FLAC, (2000, 200.5))], ValueError),
            ('a Path instead of a str path', [(Path(MP3), 1000, 100.0)], TypeError),
            ('no path at all', [(None, 1000, 100.0)], TypeError),
            ('a str instead of the size', [(MP3, '1000', 100.0)], TypeError),
            ('an int instead of the mtime', [(MP3, 1000, 100)], TypeError),
            ('a tuple of triples instead of a list', (TARGETS[0],), TypeError),
            ('an iterator, which a two-pass check would swallow',
             iter([TARGETS[0]]), TypeError),
        ]
        calls = []
        service = self._service(_fake_extractor(
            {path: _song(path) for path, _, _ in TARGETS}, calls))
        before = service.current_generation()

        for what, targets, expected in cases:
            with self.subTest(what):
                with self.assertRaises(expected):
                    service.start_sweep(targets, RowSink())

        self.assertEqual(before, service.current_generation(),
                         'nine refusals consumed nine generations')
        self._pump_for(DRAIN_MS)
        self.assertEqual([], calls, 'a refused target list queued an extraction')

    def test_a_refusal_leaves_the_running_sweep_untouched(self):
        """Review item M2: the old implementation queued while it checked.

        Measured there: a bad triple in the *second* position raised, and the first
        task had already been queued and had already been delivered -- into the
        callback of the sweep its caller had just been told had not started. A
        refusal has to be a no-op, and the live sweep has to survive it.
        """
        calls = []
        running, refused = RowSink(), RowSink()
        values = {path: _song(path) for path, _, _ in TARGETS}
        service = self._service(_fake_extractor(values, calls))

        live = service.start_sweep([TARGETS[0]], running)
        with self.assertRaises(ValueError):
            service.start_sweep([TARGETS[1], (OGG, FLAC)], refused)

        self.assertEqual(
            live, service.current_generation(),
            'a refused start_sweep advanced the counter, so the live sweep\'s rows '
            'went stale in a library nobody switched to')
        self._pump_until(lambda: len(running.rows) == 1,
                         'the live sweep stopped being delivered after a later call '
                         'was refused',
                         state=lambda: f'running={running} refused={refused}')
        self._pump_for(DRAIN_MS)
        self.assertEqual([], refused.rows,
                         'the refused sweep reached the callback it never installed')
        self.assertEqual([MP3], calls,
                         f'a refused sweep queued extra extraction work: {calls}')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataSweepPayloadTest(_SweepTestBase):
    """The report step's own guard: a payload the channel refuses costs one row."""

    def test_a_payload_the_channel_refuses_is_dropped_not_fatal(self):
        """Ruling B4-R14: ``except Exception`` -- and deliberately not ``BaseException``.

        ``_sweep_row_ready`` declares ``str`` for the path, so a non-``str`` payload
        raises ``TypeError`` *inside the emit call*: on a pool thread, inside a Python
        override of a C++ virtual, which is the one shape that takes the whole process
        with it (PyQt6 6.11, measured: exit 127, no traceback, not even the runner's
        summary line). ``start_sweep`` now refuses such a target in the caller's own
        thread, so the way one still reaches a task is a caller that built
        :class:`MetadataSweepTask` directly -- hence the direct construction below.
        This guard is the last line rather than the first, and the test getting as far
        as its own last assertion is the "the process is still here" half of it.

        ``_thread_pool`` and ``_queue_sweep_row`` are read on purpose: the point is to
        send the bad payload through the *real* channel, not through a stand-in that
        could not fail.
        """
        calls = []
        sink = RowSink()
        extractor = _fake_extractor(
            {path: _song(path) for path, _, _ in TARGETS}, calls)
        service = self._service(extractor)

        generation = service.start_sweep([TARGETS[0]], sink)
        service._thread_pool.start(MetadataSweepTask(
            Path(MP3), 9000, 900.5, generation, extractor,
            service._queue_sweep_row,
            # The task's own "still the live plan?" question (ruling B4-R21a). This
            # caller built the task by hand, so it answers the question by hand: the
            # generation above is still current, so the bad payload does reach the
            # report step -- which is the half of the claim being tested.
            lambda: service.current_generation() == generation))

        self._pump_until(lambda: len(sink.rows) == 1,
                         'the good row of the same generation never arrived',
                         state=lambda: f'{sink} calls={calls}')
        # The bad task has had its turn by now: either its row was dropped, or this
        # process is already gone.
        self._pump_for(DRAIN_MS)

        self.assertEqual([MP3], sink.paths,
                         'a payload the str slot refused still reached on_row')
        self.assertEqual(1, len(sink.rows),
                         f'a dropped payload was reported more than once: {sink}')
        self.assertEqual(_song(MP3).artist, sink.rows[0][1].artist,
                         'the row that survived is not the sweep\'s own row')


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

        ``start_sweep`` is patched with ``wraps`` rather than replaced: a plain mock
        swallows a rewire, and the third assertion below was then guaranteed by
        construction (review item M5). With the real method still reachable behind
        the recorder, a rewire *does* run a sweep and *does* light the extractor up,
        so both halves of the reading are falsifiable again -- and the loop is
        rotated before looking at the recorder, so a task the pool had not picked up
        yet cannot hide behind the timing (measured: without this drain, a rewire that
        builds ``MetadataSweepTask`` directly slipped through green).
        """
        calls = []
        service = self._service(_fake_extractor({MP3: _song(MP3)}, calls))
        service.clear_cache()  # the cache is class-level; a warm entry skips loading
        with mock.patch.object(service, 'load_async') as load_async, \
                mock.patch.object(service, 'start_sweep',
                                  wraps=service.start_sweep) as start_sweep:
            service.preload_files([MP3, FLAC])
        self._pump_for(DRAIN_MS)

        self.assertEqual([mock.call(MP3), mock.call(FLAC)], load_async.call_args_list)
        start_sweep.assert_not_called()
        self.assertEqual([], calls, 'a cover preload started a sweep extraction')


if __name__ == '__main__':
    unittest.main(verbosity=2)
