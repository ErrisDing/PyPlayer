#!/usr/bin/env python3
"""LibraryMetadataStore -- the owner of the metadata tri-state and its expiry.

Batch 4 shows three playlist columns, and the cache (``core.cache_manager``,
format 2.0) stores one ``md`` key per entry for that. The key alone is only a
contract; this class is the behaviour:

* **Tri-state** (spec 4.1). ``pending`` = nothing was ever tried, ``unknown`` =
  extraction ran (or was deliberately skipped) and the tag had nothing,
  ``known`` = at least one value. The three states are exposed as the module
  strings ``STATE_PENDING``/``STATE_UNKNOWN``/``STATE_KNOWN`` and those strings
  are the *only* outward spelling -- no enum, no flag type (ruling B4-R5).
  Pending is decided by ``md is None``, never by truthiness: a row of three
  ``None`` values is a *present* payload and would otherwise collapse back into
  "not fetched yet" (ruling B4-R8), which is precisely what spec criterion 6
  forbids.
* **Per-file expiry** (spec 4.6). Every entry remembers the ``(size, mtime)``
  fingerprint its ``md`` was extracted against; a mismatch invalidates it. The
  coarse root-directory check that guards the *file table* is not reused here --
  it cannot see a tag edited in place.
* **Excluded formats are answered immediately** (spec 2). ``.ncm`` is never
  swept (decrypting one writes a proxy file), so ``validate`` records it as
  "tried, nothing" on the spot. Left pending it would advertise a loading state
  that no code will ever complete -- and a row that lies is worse than a row
  that says "no metadata".
* **Fingerprints travel with the request.** ``validate`` hands back
  ``(full_path, size, mtime)`` read from the scan it was given, never a re-stat,
  so the sweep (Task 4) and the pre-write re-check (Task 7) all compare *one*
  instant. Returning only paths would force each of them to stat again and let
  the three views of "current" drift apart mid-sweep.
* **A non-positive duration cannot enter the cache.** ``record`` is the single
  reuse point of ``normalize_duration`` (ruling B4-R7, spec 4.2), so ``0.0`` --
  the value the mutagen extractors use for "no length" -- is never persisted and
  can never be drawn as ``0:00``.

This module deliberately does *not* know about the queue or the display layers:
the coupling is one-way, the queue reads the store (ruling B4-R6).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.cache_manager import MD_KEYS, CachedFile
from core.library_manager import MediaFile
from core.metadata import normalize_duration

#: The three outward states of one row's metadata (ruling B4-R5). Consumers
#: import these instead of re-typing the words, so a rename cannot silently
#: desynchronise the store, the queue and the delegate.
STATE_PENDING = 'pending'
STATE_UNKNOWN = 'unknown'
STATE_KNOWN = 'known'

#: Formats the sweep must not touch (spec 2). NCM extraction decrypts the file
#: into a proxy on disk, which is a side effect no "show a column" feature may
#: cause per-file across a whole library.
DEFAULT_EXCLUDED_EXTENSIONS: frozenset[str] = frozenset({'.ncm'})


@dataclass(frozen=True)
class RowMetadata:
    """One row's three columns. ``None`` means "this file has no such tag".

    Frozen because instances are handed to the queue (Task 5) and to the sweep
    callback (Task 4); a shared mutable row would let one library's update show
    up in another's rows. Every field defaults to ``None`` so an all-unknown row
    is spelled ``RowMetadata()``.
    """
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[float] = None


@dataclass
class _Entry:
    """Store-side record: the values, the fingerprint they were taken at, dirty.

    ``md`` is ``None`` for pending and an all-``None`` ``RowMetadata`` for
    "tried, got nothing" -- the same distinction the JSON makes between an absent
    ``md`` key and a present one.
    """
    md: Optional[RowMetadata]
    fingerprint: Tuple[int, float]
    dirty: bool = False


def _row_from_md(md: Optional[dict]) -> Optional[RowMetadata]:
    """Read Task 1's ``CachedFile.md`` into a ``RowMetadata``.

    ``None`` (the key was absent) stays ``None``: pending. A dict is indexed by
    ``MD_KEYS`` with ``get``, so extra keys written by a future format are
    ignored and a missing canonical key reads as "no value" rather than raising.
    Values are *not* re-normalized here (ruling B4-R7 puts that gate in
    ``record`` alone); the cache this build writes has already passed it.
    """
    if md is None:
        return None
    return RowMetadata(**{key: md.get(key) for key in MD_KEYS})


def _md_from_row(row: Optional[RowMetadata]) -> Optional[dict]:
    """Build the canonical ``md`` payload (ruling B4-R1: exactly ``MD_KEYS``)."""
    if row is None:
        return None
    return {key: getattr(row, key) for key in MD_KEYS}


class LibraryMetadataStore:
    """Per-scan metadata table: fill it from the cache, expire it per file.

    One instance belongs to one library at one time. ``load_cache_entries``
    *replaces* the whole table, which is what stops a library switch from
    keeping the previous library's rows (spec 10 risk 1) -- merging instead would
    leave the old paths queryable, and Task 7's write-back would then be able to
    put them into the new library's cache file.
    """

    def __init__(self,
                 excluded_extensions: frozenset[str] = DEFAULT_EXCLUDED_EXTENSIONS):
        #: Frozen copy: a caller-built set must not be able to change the
        #: exclusion rule from underneath a running sweep.
        self.excluded_extensions = frozenset(excluded_extensions)
        self._entries: Dict[str, _Entry] = {}

    # -- loading ---------------------------------------------------------------

    def load_cache_entries(self, files: List[CachedFile]) -> int:
        """Replace the table with entries read back from a library cache.

        Returns the number of entries the store accepted and can serve, so the
        caller can log "N rows warm-started" without re-walking the input. An
        entry without a path cannot be keyed and is dropped rather than stored
        under ``''``; everything else is kept verbatim, pending included --
        "``md`` missing" is the sweep's to-do list, not a defect.
        """
        entries: Dict[str, _Entry] = {}
        for cached in files:
            if not cached.path:
                continue
            entries[cached.path] = _Entry(
                md=_row_from_md(cached.md),
                fingerprint=(cached.size_bytes, cached.modified_time),
                dirty=False,
            )
        self._entries = entries
        return len(entries)

    # -- querying --------------------------------------------------------------

    def get(self, full_path: str) -> Optional[RowMetadata]:
        """The row's values, or ``None`` when nothing has been tried yet."""
        entry = self._entries.get(full_path)
        return entry.md if entry is not None else None

    def state_of(self, full_path: str) -> str:
        """``'pending' | 'unknown' | 'known'`` for one path (ruling B4-R8).

        Absent entry *or* an entry whose ``md`` is ``None`` is pending. An entry
        with values is known; one whose three values are all ``None`` is
        unknown. The check is ``is None`` on purpose -- ``if entry.md:`` would
        read an all-``None`` row as pending and re-queue a file that was already
        tried.
        """
        entry = self._entries.get(full_path)
        if entry is None or entry.md is None:
            return STATE_PENDING
        if (entry.md.artist is not None or entry.md.album is not None
                or entry.md.duration is not None):
            return STATE_KNOWN
        return STATE_UNKNOWN

    # -- expiry ----------------------------------------------------------------

    def _extension_of(self, full_path: str) -> str:
        """Lower-case suffix taken from the path, the row's identity.

        ``CachedFile.extension``/``MediaFile.extension`` are whatever the scanner
        happened to write; the suffix of the path is the one value every layer
        agrees on, and an upper-case ``.NCM`` must not slip past the rule.
        """
        return Path(full_path).suffix.lower()

    def is_excluded(self, full_path: str) -> bool:
        """Whether this format is deliberately never extracted."""
        return self._extension_of(full_path) in self.excluded_extensions

    def validate(self, files: List[MediaFile]) -> List[Tuple[str, int, float]]:
        """Return the ``(full_path, size, mtime)`` triples to extract now.

        Three cases, in the order the spec settles them:

        * **pending** (no entry, or an entry with no ``md``) -- requested, and
          *not* recorded: pending is a question, and writing ``md`` for it would
          put "no metadata" on disk before the sweep had any chance to answer.
        * **fingerprint changed** -- the stored ``md`` is stale, so it is
          invalidated with ``record(md=None)`` first and then requested. A row
          that shows the pre-edit tags is a lie, and if the app dies before the
          sweep finishes the invalidation must already be on its way to disk.
        * **excluded format not yet tried** -- recorded as ``md=None`` on the
          spot and *never* returned. It is answered by the decision itself, not
          by extraction, so it must land in ``unknown`` and stay there. An
          already-tried excluded file is left alone rather than re-recorded,
          because re-marking the whole NCM set dirty on every scan would buy
          write-backs for no state change.

        Anything else -- known and unchanged, or tried-and-empty and unchanged
        (spec 8's fourth class, criterion 6) -- is not requested again. The
        fingerprints in the result are the ones handed in, so the caller's sweep
        and Task 7's write-back re-check stay comparable against a single instant.
        """
        targets: List[Tuple[str, int, float]] = []
        for media in files:
            full_path = media.path
            fingerprint = (media.size_bytes, media.modified_time)
            entry = self._entries.get(full_path)

            if self.is_excluded(full_path):
                if entry is None or entry.md is None:
                    self.record(full_path, None, *fingerprint)
                continue

            if entry is None or entry.md is None:
                targets.append((full_path, fingerprint[0], fingerprint[1]))
            elif entry.fingerprint != fingerprint:
                self.record(full_path, None, *fingerprint)
                targets.append((full_path, fingerprint[0], fingerprint[1]))
        return targets

    # -- writing ---------------------------------------------------------------

    def record(self, full_path: str, md: Optional[RowMetadata],
               size_bytes: int, modified_time: float) -> None:
        """Store one row and mark it for write-back.

        ``md=None`` is *not* "back to pending": it means "tried and there was
        nothing" and is stored as an all-``None`` row, which is what makes an
        extraction failure or an excluded format survive a restart instead of
        being retried on every launch (spec 4.1, criterion 6).

        ``duration`` passes through ``normalize_duration`` here -- the only place
        batch 4 applies that rule (ruling B4-R7) -- so a non-positive length can
        never be persisted and never reach the delegate as ``0:00``.
        """
        if md is None:
            row = RowMetadata()
        else:
            row = RowMetadata(artist=md.artist, album=md.album,
                              duration=normalize_duration(md.duration))
        entry = self._entries.get(full_path)
        if entry is None:
            self._entries[full_path] = _Entry(
                md=row, fingerprint=(size_bytes, modified_time), dirty=True)
        else:
            entry.md = row
            entry.fingerprint = (size_bytes, modified_time)
            entry.dirty = True

    def dirty_count(self) -> int:
        """How many rows still owe a write-back."""
        return sum(1 for entry in self._entries.values() if entry.dirty)

    def take_dirty(self) -> List[Tuple[str, Optional[dict]]]:
        """Drain the write-back batch: ``(full_path, md)`` with the flags cleared.

        Task 7 batches these so a library of N new rows costs a handful of
        ``json.dump`` calls instead of N. ``md`` is Task 1's canonical payload --
        exactly the ``MD_KEYS`` names -- so the caller can stamp it straight onto
        ``CachedFile.md``. A ``None`` here would mean "write no ``md`` key", i.e.
        pending, and the sweep never marks a pending row dirty; it is part of the
        signature because the cache's tri-state has that third shape and the
        writer must not have to guess which ones it may receive.
        """
        taken: List[Tuple[str, Optional[dict]]] = []
        for full_path, entry in self._entries.items():
            if not entry.dirty:
                continue
            entry.dirty = False
            taken.append((full_path, _md_from_row(entry.md)))
        return taken
