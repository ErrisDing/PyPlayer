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
"""

from typing import Callable, Dict, Optional, Sequence, Tuple
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
                 report: Callable[..., None]):
        super().__init__()
        self.full_path = full_path
        self.size_bytes = size_bytes
        self.modified_time = modified_time
        self.generation = generation
        self._extractor = extractor
        self._report = report

    def run(self) -> None:
        """Extract this one row; never let anything leave this thread."""
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
        except RuntimeError:
            # The service's C++ side was destroyed while this task was queued or
            # running. There is nobody left to report to; dropping is the only
            # possible answer, and it must not become a second way to escape.
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
        # The library generation (spec 4.5). Touched on the GUI thread only: a
        # worker's result arrives through ``_sweep_row_ready``, which Qt delivers
        # queued, so the staleness test runs where the rows are written and no lock
        # is needed for either side of it.
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
        """
        self._generation += 1
        return self._generation

    def start_sweep(self, targets: Sequence[Tuple[str, int, float]],
                    on_row: Callable[
                        [str, Optional[RowMetadata], int, float], None]) -> int:
        """Extract every target on the shared pool and report rows back.

        Args:
            targets: exactly what ``LibraryMetadataStore.validate`` returned --
                ``(full_path, size_bytes, modified_time)`` per row. A list of paths
                is not accepted, and neither are two parallel lists: the fingerprint
                has to belong to its own row (see :class:`MetadataSweepTask`).
            on_row: called once per target, on the GUI thread, with that target's own
                ``(size_bytes, modified_time)``. A row whose extraction failed arrives
                as ``md=None``; a row whose generation went stale mid-sweep never
                arrives at all. It must not raise: it runs inside a Qt slot, and an
                exception leaving one is the same process abort the task above goes
                out of its way to avoid -- the callback owns its own errors (Task 7
                pins that for the write-back path).

        Returns:
            The generation this sweep runs under -- *not* the number of tasks. The
            service owns it; a caller that passed one in could pass a stale value and
            get a silent no-callback in place of the feature (the reason this shape
            was chosen over the earlier draft).

        One live callback per generation is the model: a second ``start_sweep``
        without an intervening :meth:`cancel_sweep` is the same library asking again,
        and it replaces the callback rather than running two listeners for one
        library. Call this from the GUI thread, like the service's other methods --
        the generation and the callback are read there and nowhere else, which is
        what keeps the whole thing lock-free.

        No concurrency cap is added: the pool already bounds how many files are open
        at once, and a second bound would only delay a library switch showing up.
        Empty ``targets`` still answers with the generation and queues nothing.
        """
        self._sweep_on_row = on_row
        generation = self._generation
        for full_path, size_bytes, modified_time in targets:
            self._thread_pool.start(MetadataSweepTask(
                full_path, size_bytes, modified_time, generation,
                self._extractor, self._queue_sweep_row))
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
