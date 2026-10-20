#!/usr/bin/env python3
"""
Metadata Service - Async metadata extraction with PyQt signals
Prevents UI blocking when loading album art from large files

Batch 4 adds the library sweep on top of that same pool. ``start_sweep`` eats the
``(full_path, size, mtime)`` triples ``LibraryMetadataStore.validate`` produced and
reports one ``RowMetadata`` per row back through the caller's ``on_row`` -- on the
GUI thread, and only while the sweep's *generation* is still current. Switching
libraries increments that generation instead of trying to retract tasks: queued work
on a shared ``QThreadPool`` cannot be pulled back reliably, and the failure this
prevents is specific and expensive -- the previous library's rows landing in the
current library's cache and view (spec 4.5, spec 10 risk 1).

One sweep is one generation, including two sweeps of the same library back to back:
``start_sweep`` increments too (ruling B4-R13). A generation that identifies a
*library* would leave a re-scan without a cancel sharing its predecessor's id, and
the predecessor's in-flight rows would then be delivered to the *new* callback --
which is how "one delivery per target, count them to know the sweep is done" turns
into "done" too early.
"""

from typing import Callable, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, QThreadPool

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.metadata import SongMetadata, extract_metadata
from service.metadata_store import RowMetadata


def _row_of(extracted: Optional[SongMetadata]) -> Optional[RowMetadata]:
    """Project one extraction result onto one playlist row.

    Only the three columns cross over: the sweep must not drag album art into a row
    payload, because batch 4 caches no covers (spec 7). ``duration`` is passed
    through **un-normalized** on purpose -- ``LibraryMetadataStore.record`` is the
    batch's single normalization site (ruling B4-R7), so a second opinion about
    ``0.0`` here would put a layer between the extractor and the gate that decides.
    """
    if extracted is None:
        return None
    return RowMetadata(artist=extracted.artist, album=extracted.album,
                       duration=extracted.duration)


def _validated_targets(
        targets: list[tuple[str, int, float]]) -> list[tuple[str, int, float]]:
    """Check the whole target list in the calling thread, before anything moves.

    Three failures are closed here, and all three are cheaper here than anywhere
    later (ruling B4-R14, plus review items M7 and M2):

    * **The mispaired shapes.** Two parallel lists were rejected as an API because a
      mispairing raises nowhere -- it just pairs a row with another row's
      fingerprint. Handing this method a bare path list, or entries of the wrong
      length, used to blow up only by an accident of tuple unpacking; requiring a
      typed triple per entry turns that rejection into the tested contract instead
      of a side effect (review item M7).
    * **The payload that kills the process.** ``_sweep_row_ready`` declares its
      second argument as ``str``. A ``pathlib.Path`` (or bytes, or an int) reaches
      that slot inside a pool thread, ``emit`` raises ``TypeError`` there, and an
      exception leaving ``QRunnable.run`` under PyQt6 6.11 aborts the whole player
      (measured: exit 127, no traceback). A caller that violates the contract gets
      a ``TypeError`` in its own thread instead.
    * **The half-started sweep.** Validation is a separate pass over the whole list,
      so a bad entry late in the list cannot leave the earlier rows already queued
      and already counting against a sweep the caller believes never started.

    Raises:
        TypeError: ``targets`` is not a list, or an entry's field has the wrong
            type. A list is required because this function reads the sequence
            twice -- a generator would be consumed by the check and then sweep
            nothing, silently.
        ValueError: an entry is not three fields long.
    """
    if not isinstance(targets, list):
        raise TypeError(
            'targets must be the list validate() returned, not '
            f'{type(targets).__name__}')
    checked = []
    for position, target in enumerate(targets):
        try:
            full_path, size_bytes, modified_time = target
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f'target {position} is not a '
                f'(full_path, size_bytes, modified_time) triple: {target!r} '
                f'({exc})') from exc
        if not isinstance(full_path, str):
            raise TypeError(
                f'target {position} carries a full_path of type '
                f'{type(full_path).__name__}, not str: the delivery channel '
                'declares str, so this would raise inside a pool thread')
        if not isinstance(size_bytes, int):
            raise TypeError(
                f'target {position} carries a size_bytes of type '
                f'{type(size_bytes).__name__}, not int')
        if not isinstance(modified_time, float):
            raise TypeError(
                f'target {position} carries a modified_time of type '
                f'{type(modified_time).__name__}, not float')
        checked.append((full_path, size_bytes, modified_time))
    return checked


class MetadataLoadTask(QRunnable):
    """Runnable task for loading metadata in background thread."""

    def __init__(self, filepath: str, callback):
        super().__init__()
        self.filepath = filepath
        self.callback = callback

    def run(self):
        """Load metadata in background thread."""
        try:
            metadata = extract_metadata(self.filepath)
            self.callback(self.filepath, metadata, None)
        except Exception as e:
            self.callback(self.filepath, None, str(e))


class MetadataSweepTask(QRunnable):
    """One row of a library sweep: extract it on the shared pool, then report it.

    The task carries the ``(size, mtime)`` fingerprint **of its own row** and the
    generation of the sweep that queued it, and hands both back untouched. That is
    not decoration: Task 7 re-checks the pair against the disk before it writes, and
    the store's invalidation compares against the pair ``validate`` handed out. A
    re-stat here would be a third, later opinion of the same file, and a row paired
    with another row's fingerprint is a metadata write for a version that no longer
    exists -- both are silent, which is why the fingerprint travels instead of being
    looked up (spec 4.6).
    """

    def __init__(self, full_path: str, size_bytes: int, modified_time: float,
                 generation: int,
                 extractor: Callable[[str], Optional[SongMetadata]],
                 report: Callable[..., None],
                 is_current: Callable[[], bool]):
        super().__init__()
        self.full_path = full_path
        self.size_bytes = size_bytes
        self.modified_time = modified_time
        self.generation = generation
        self._extractor = extractor
        self._report = report
        self._is_current = is_current

    def run(self) -> None:
        """Extract this one row; never let anything leave this thread.

        The generation is checked **before** the extraction, not after it (ruling
        B4-R21a). ``_deliver_sweep_row`` below is still the only thing that decides
        whether a result is *used*; this check only decides whether the work is done
        at all. Without it a superseded plan pays a full extraction per row and throws
        every answer away -- ``refresh_all`` over k libraries of n rows each used to
        cost ``(k-1) x n`` pure-waste extractions on the same pool the playing track
        borrows. A task that starts while its generation is still live can still be
        superseded halfway through, so this is an optimisation and never a second
        defence: reading ``MetadataService._generation`` from a worker is a plain int
        attribute read (atomic under the GIL), and the worst it can do is *not* skip.

        No guard around the check itself: ``is_current`` is this module's own closure
        over one attribute read, and an unreachable defensive branch is a branch no
        test can ever take.
        """
        if not self._is_current():
            return
        try:
            row = _row_of(self._extractor(self.full_path))
        except Exception:
            # spec 6 item 1: a file that throws is "tried, nothing", so the failure
            # becomes ``md=None`` -- an *answer* the store can persist, not a hole
            # that leaves the row advertising a loading state forever. Per-entry, so
            # one unlabelled file cannot cost the rest of the batch its sweep.
            #
            # The exception may not escape: PyQt aborts the process when a Python
            # override of a C++ virtual raises (measured on PyQt6 6.11 -- exit 127,
            # no traceback), and there is no button to show an error on for a batch
            # nobody started by hand.
            row = None
        try:
            self._report(self.generation, self.full_path, row,
                         self.size_bytes, self.modified_time)
        except Exception:
            # Reporting is allowed to fail and must cost exactly this row (ruling
            # B4-R14). Two shapes reach here: the service's C++ side was destroyed
            # while this task was queued (``RuntimeError``), and a payload the
            # channel refuses -- ``_sweep_row_ready`` declares ``str`` for the path,
            # so anything else raises ``TypeError`` right here, in a pool thread,
            # where an escaping exception is the same process abort the block above
            # goes out of its way to avoid. Either way there is nobody left to
            # report to, so dropping is the only possible answer, and it must not
            # become a second way to escape.
            #
            # ``BaseException`` is deliberately *not* caught, matching the block
            # above: this guard's job is a payload the channel refuses, not an
            # interrupt reaching a worker (ruled deliberate in the ledger, review
            # item M3).
            pass


class MetadataService(QObject):
    """
    Service for async metadata extraction.
    Uses QThreadPool for background loading.
    """

    # Signals
    metadata_loaded = pyqtSignal(str, object)   # filepath, SongMetadata
    album_art_loaded = pyqtSignal(str, bytes)   # filepath, album_art_bytes
    metadata_error = pyqtSignal(str, str)       # filepath, error_message

    #: Marshalling channel for the sweep -- internal, not an API. A pool thread may
    #: not run a callback that goes on to update a model or repaint a widget, so a
    #: result is posted to this object's (GUI) thread and delivered there. It stays
    #: private because Task 7 receives rows through ``on_row``, not through a signal
    #: a caller could forget to connect (batch 3 ruling R9: no route with no station).
    _sweep_row_ready = pyqtSignal(int, str, object, object, object)
    #                        generation, path, row, size, mtime

    # Cache
    _cache: Dict[str, SongMetadata] = {}

    def __init__(self, parent: Optional[QObject] = None,
                 extractor: Optional[Callable[[str], Optional[SongMetadata]]] = None):
        """``extractor`` is the seam for testing the sweep without audio files.

        It replaces ``core.metadata.extract_metadata`` for this instance only, and
        the default is the real facade -- production never passes it. Resolved at
        construction time, so a test that patches the module name has to patch
        before building the service.
        """
        super().__init__(parent)
        self._thread_pool = QThreadPool.globalInstance()
        self._extractor = extract_metadata if extractor is None else extractor
        # The sweep generation (spec 4.5, ruling B4-R13): one identity per
        # ``start_sweep`` call and one per ``cancel_sweep``. **Written** on the GUI
        # thread only. A worker may *read* it -- ``MetadataSweepTask.run`` asks before
        # it extracts, so a superseded plan stops paying for extraction (ruling
        # B4-R21a) -- and that read needs no lock either: one attribute of a plain
        # int, handed back or not, with the delivery gate below still the only place a
        # result is decided.
        self._generation = 0
        self._sweep_on_row: Optional[Callable[..., None]] = None
        self._sweep_row_ready.connect(self._deliver_sweep_row)

    # -- library sweep (batch 4) -------------------------------------------------

    def current_generation(self) -> int:
        """The generation a live sweep result has to match to be delivered."""
        return self._generation

    def cancel_sweep(self) -> int:
        """Make everything in flight worthless; return the new generation.

        Call this when the user switches libraries. Nothing is *retracted* -- tasks
        already queued on the shared pool cannot be pulled back, and one that is
        running is half-way through a file -- so it is invalidated instead: the
        delivery step compares each result's generation with this one and drops a
        mismatch without ever touching a callback.

        The pending ``on_row`` is deliberately *not* cleared here. Dropping is the
        generation comparison's job and nobody else's: a second, independent defence
        would leave the rule untested (a mutation that made it always-current stayed
        green while this line did the work), and it would mean a result is silenced
        by "nobody is listening" when the honest answer is "that library is gone".
        The next :meth:`start_sweep` overwrites it.

        :meth:`start_sweep` advances the same counter, so a cancel and a re-scan have
        the identical effect on what is in flight -- worthless -- and differ only in
        that a cancel queues nothing.
        """
        self._generation += 1
        return self._generation

    def start_sweep(self, targets: list[tuple[str, int, float]],
                    on_row: Callable[
                        [str, Optional[RowMetadata], int, float], None]) -> int:
        """Extract every target on the shared pool and report rows back.

        Args:
            targets: exactly what ``LibraryMetadataStore.validate`` returned --
                ``(full_path, size_bytes, modified_time)`` per row, in a list. The
                shape is checked here, in the calling thread, over the whole list,
                before a single task is queued: a bare path list, two parallel lists
                and a wrongly typed field are each refused, because a mispaired
                fingerprint is silent and a path that is not ``str`` raises inside a
                pool thread, where the casualty is the process (see
                :func:`_validated_targets`).
            on_row: called once per target, on the GUI thread, with that target's own
                ``(size_bytes, modified_time)``. A row whose extraction failed arrives
                as ``md=None``; a row whose generation went stale mid-sweep never
                arrives at all. It must not raise: it runs inside a Qt slot, and an
                exception leaving one is the same process abort the task above goes
                out of its way to avoid -- the callback owns its own errors (Task 7
                pins that for the write-back path).

        Returns:
            The **new** generation this sweep runs under -- *not* the number of tasks,
            and not the value the service held beforehand. The service owns it; a
            caller that passed one in could pass a stale value and get a silent
            no-callback in place of the feature (the reason this shape was chosen over
            the earlier draft).

        Every call takes a fresh identity, so a second ``start_sweep`` without an
        intervening :meth:`cancel_sweep` retires the first one's in-flight rows rather
        than sharing their generation (ruling B4-R13). Sharing was not merely untidy:
        under one id the older plan's rows are delivered to the *newer* callback, so a
        caller that counts deliveries against ``len(targets)`` -- which is exactly how
        Task 7 learns a sweep finished -- would declare the new plan done before its
        own work started, and the replaced plan's count could never reach its own N.
        One live callback is still the model: the newest ``start_sweep`` owns
        ``on_row``, and it is replaced rather than registered twice. Call this from the
        GUI thread, like the service's other methods -- the callback is read there and
        nowhere else, and the generation is *written* there and nowhere else, which is
        what keeps the whole thing lock-free (a worker only ever reads one int, and only
        to decide whether to bother extracting).

        No concurrency cap is added: the pool already bounds how many files are open
        at once, and a second bound would only delay a library switch showing up.
        Empty ``targets`` still answers with a generation of its own and queues
        nothing; taking an id even then is what keeps the previous plan's rows from
        arriving at an empty sweep's callback.
        """
        checked = _validated_targets(targets)
        # The order is the point: check the whole list, and only then take a
        # generation and install the callback. A call that is going to be refused
        # must leave the running sweep exactly as it found it -- its generation, its
        # callback, and nothing new queued against a count its owner is keeping.
        self._generation += 1
        generation = self._generation
        self._sweep_on_row = on_row
        for full_path, size_bytes, modified_time in checked:
            self._thread_pool.start(MetadataSweepTask(
                full_path, size_bytes, modified_time, generation,
                self._extractor, self._queue_sweep_row,
                # The worker's own "is this plan still the live one?" question, read
                # here rather than passed as the generation so the answer cannot be
                # frozen at queueing time (ruling B4-R21a).
                lambda: self._generation == generation))
        return generation

    def _queue_sweep_row(self, generation: int, full_path: str,
                         row: Optional[RowMetadata],
                         size_bytes, modified_time) -> None:
        """Pool-thread entry point: post one finished row to the GUI thread.

        ``size_bytes``/``modified_time`` travel as ``object`` rather than
        ``int``/``float`` so the signal hands back exactly what the target carried --
        Task 7 compares them against the store, and a value Qt coerced on the way is
        a value this service invented.
        """
        self._sweep_row_ready.emit(generation, full_path, row,
                                   size_bytes, modified_time)

    def _deliver_sweep_row(self, generation: int, full_path: str,
                           row: Optional[RowMetadata],
                           size_bytes, modified_time) -> None:
        """Drop a row whose library is gone; deliver one that is still current."""
        if generation != self._generation:
            return
        on_row = self._sweep_on_row
        if on_row is None:
            return
        on_row(full_path, row, size_bytes, modified_time)

    def load_async(self, filepath: str) -> None:
        """
        Load metadata asynchronously.

        Args:
            filepath: Path to the audio file
        """
        # Check cache first
        if filepath in self._cache:
            self.metadata_loaded.emit(filepath, self._cache[filepath])
            if self._cache[filepath].album_art:
                self.album_art_loaded.emit(filepath, self._cache[filepath].album_art)
            return

        # Create and start task
        task = MetadataLoadTask(filepath, self._on_metadata_loaded)
        self._thread_pool.start(task)

    def _on_metadata_loaded(self, filepath: str, metadata: Optional[SongMetadata], error: Optional[str]) -> None:
        """Callback when metadata is loaded."""
        if error:
            self.metadata_error.emit(filepath, error)
            return

        if metadata:
            # Cache the result
            self._cache[filepath] = metadata

            # Emit signals
            self.metadata_loaded.emit(filepath, metadata)

            if metadata.album_art:
                self.album_art_loaded.emit(filepath, metadata.album_art)

    def get_cached(self, filepath: str) -> Optional[SongMetadata]:
        """Get cached metadata if available."""
        return self._cache.get(filepath)

    def load_sync(self, filepath: str) -> Optional[SongMetadata]:
        """
        Load metadata synchronously (blocking).

        Use sparingly - prefer load_async to avoid UI blocking.
        """
        if filepath in self._cache:
            return self._cache[filepath]

        try:
            metadata = extract_metadata(filepath)
            self._cache[filepath] = metadata
            return metadata
        except Exception:
            return None

    def clear_cache(self) -> None:
        """Clear the metadata cache."""
        self._cache.clear()

    def preload_files(self, filepaths: list) -> None:
        """
        Preload metadata for multiple files.

        This is the album-art path, not batch 4's sweep, and it deliberately stayed
        that way: a bare path list carries no ``(size, mtime)`` to travel with the
        row (``validate`` is the one that hands those out, re-stat'ing here would
        invent a second instant), and its results belong to ``_cache``, which the
        sweep must not write (Task 7's job). :meth:`start_sweep` is the method the
        library scan ends up in.

        Args:
            filepaths: List of file paths to preload
        """
        for filepath in filepaths:
            if filepath not in self._cache:
                self.load_async(filepath)
