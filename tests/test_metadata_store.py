#!/usr/bin/env python3
"""Task 3: ``LibraryMetadataStore`` -- who owns the tri-state and the invalidation.

The cache (Task 1) only says whether an entry carries an ``md`` key. This module
is where that key *means* something, and the rules it exists to enforce are all
in the spec's failure-matrix corner cases:

* **Three states, one author.** ``state_of`` answers ``'pending'`` /
  ``'unknown'`` / ``'known'`` and nothing else; the three strings live in this
  module as ``STATE_PENDING``/``STATE_UNKNOWN``/``STATE_KNOWN`` so Tasks 5/6/8
  import them instead of re-typing them (ruling B4-R5). No enum, no IntFlag --
  the strings are the class's only outward expression of the state. The rule
  itself is the module function ``state_for_values``, which ``state_of`` and
  ``QueueService.set_metadata`` both call: batch 4's review found the queue
  holding a second copy of the same three branches (finding I1), so
  ``SharedTriStateRuleTest`` is where that shared rule -- and only it -- is
  falsifiable for every consumer.
* **"Tried" is key presence, never truthiness** (ruling B4-R8): an entry whose
  three values are all ``None`` was tried and found empty, so it must never be
  re-requested (spec §8's fourth class, criterion 6). Pending therefore means
  "``md`` is ``None``", i.e. something still intends to fetch it.
* **Excluded formats are tried from the first scan.** ``.ncm`` is not swept
  (spec §2), so ``validate`` records it as "no metadata" immediately; leaving it
  pending would make a format nobody will ever fetch look like it is still
  loading (criterion 2 versus criterion 3).
* **An invalidation is a question, never an answer** (spec §4.6, criterion 5). A
  fingerprint mismatch clears the values back to pending *and keeps the stored
  fingerprint*, so a file whose extraction was interrupted is still a target on
  the next scan. Only ``record`` advances a fingerprint, and only onto the
  version its payload describes.
* **Fingerprints are handed out, not re-stat'd.** ``validate`` returns
  ``(full_path, size, mtime)`` taken from the *same* scan it was called with, so
  the sweep (Task 4) and the pre-write re-check (Task 7) compare one instant
  instead of forcing a second stat.
* **A non-positive duration cannot enter the cache.** ``record`` is the single
  reuse point of ``normalize_duration`` (ruling B4-R7, spec §4.2).

B4-R6: this module never imports the queue. The last guard reads the source,
because "the coupling is one-way" is invisible to a behaviour test.

Pure data: no Qt, no filesystem. ``MediaFile.__post_init__`` stats the path and
keeps the handed ``size_bytes``/``modified_time`` when that stat fails, which is
exactly what these fake paths rely on (no ``library/`` directory exists here).

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_metadata_store -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cache_manager import MD_KEYS, CachedFile
from core.library_manager import MediaFile
from service import metadata_store
from service.metadata_store import (
    LibraryMetadataStore,
    RowMetadata,
    STATE_KNOWN,
    STATE_PENDING,
    STATE_UNKNOWN,
    state_for_values,
)

STORE_SOURCE = 'service/metadata_store.py'

STALE_PATH = str(Path('library', 'jazz', 'stale.flac'))
KNOWN_MD = RowMetadata(artist='The Trio', album='Blue Notes', duration=227.0)
EMPTY_MD = RowMetadata(artist=None, album=None, duration=None)
PARTIAL_MD = RowMetadata(artist=None, album=None, duration=227.0)
KNOWN_DICT = {'artist': 'The Trio', 'album': 'Blue Notes', 'duration': 227.0}

NCM_PATH = str(Path('library', 'jazz', 'enclosed.ncm'))
MP3_PATH = str(Path('library', 'jazz', 'midnight.mp3'))
FLAC_PATH = str(Path('library', 'jazz', 'blue.flac'))


def _media(path: str, size: int = 1000, mtime: float = 100.0) -> MediaFile:
    """A scanned file with a controlled fingerprint (see module docstring)."""
    return MediaFile(path=path, title=Path(path).stem, file_type='audio',
                     extension=Path(path).suffix.lower(),
                     size_bytes=size, modified_time=mtime)


def _cached(path: str, md=None, size: int = 1000,
            mtime: float = 100.0) -> CachedFile:
    """A cache entry, ``md`` left absent (pending) unless the test passes one."""
    return CachedFile(path=path, title=Path(path).stem, file_type='audio',
                      extension=Path(path).suffix.lower(), size_bytes=size,
                      modified_time=mtime, md=md)


def _null_dict() -> dict:
    """Task 1's canonical "tried, nothing" payload."""
    return dict.fromkeys(MD_KEYS)


def _dict_of(md: RowMetadata) -> dict:
    """The same payload as the cache would have stored it (no ``record`` gate)."""
    return {key: getattr(md, key) for key in MD_KEYS}


class StateConstantsTest(unittest.TestCase):
    """B4-R5: the three strings are this module's public spelling."""

    def test_constant_spellings_are_pinned(self):
        self.assertEqual('pending', STATE_PENDING)
        self.assertEqual('unknown', STATE_UNKNOWN)
        self.assertEqual('known', STATE_KNOWN)

    def test_default_excluded_extensions_is_ncm(self):
        self.assertEqual(frozenset({'.ncm'}),
                         LibraryMetadataStore().excluded_extensions)


class TriStateMatrixTest(unittest.TestCase):
    """One case per cell of spec §4.1's three states."""

    def test_never_seen_path_is_pending(self):
        store = LibraryMetadataStore()
        self.assertEqual(STATE_PENDING, store.state_of(MP3_PATH))
        self.assertIsNone(store.get(MP3_PATH))

    def test_loaded_entry_without_md_key_is_pending(self):
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH, md=None)])
        self.assertEqual(STATE_PENDING, store.state_of(MP3_PATH))
        self.assertIsNone(store.get(MP3_PATH))

    def test_loaded_entry_with_values_is_known(self):
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH, md=dict(KNOWN_DICT))])
        self.assertEqual(STATE_KNOWN, store.state_of(MP3_PATH))
        self.assertEqual(KNOWN_MD, store.get(MP3_PATH))

    def test_loaded_all_null_md_is_unknown(self):
        """B4-R8: this dict is *present*, so a truthiness test would collapse
        it to pending and put every failed file back in the queue."""
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH, md=_null_dict())])
        self.assertEqual(STATE_UNKNOWN, store.state_of(MP3_PATH))
        self.assertEqual(EMPTY_MD, store.get(MP3_PATH))

    def test_record_known_is_known(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        self.assertEqual(STATE_KNOWN, store.state_of(MP3_PATH))

    def test_record_all_null_row_is_unknown(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, EMPTY_MD, 1000, 100.0)
        self.assertEqual(STATE_UNKNOWN, store.state_of(MP3_PATH))

    def test_record_none_md_counts_as_tried(self):
        """``md=None`` means "tried, got nothing", not "back to pending"."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, None, 1000, 100.0)
        self.assertEqual(STATE_UNKNOWN, store.state_of(MP3_PATH))
        self.assertEqual(EMPTY_MD, store.get(MP3_PATH))

    def test_record_partial_values_is_known(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, PARTIAL_MD, 1000, 100.0)
        self.assertEqual(STATE_KNOWN, store.state_of(MP3_PATH))

    def test_excluded_format_is_unknown_after_validate(self):
        store = LibraryMetadataStore()
        store.validate([_media(NCM_PATH)])
        self.assertEqual(STATE_UNKNOWN, store.state_of(NCM_PATH))

    def test_state_of_never_leaves_the_three_values(self):
        store = LibraryMetadataStore()
        seen = {store.state_of(MP3_PATH)}                 # never seen
        store.load_cache_entries([_cached(FLAC_PATH)])
        seen.add(store.state_of(FLAC_PATH))               # pending
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        seen.add(store.state_of(MP3_PATH))                # known
        store.validate([_media(NCM_PATH)])
        seen.add(store.state_of(NCM_PATH))                # excluded
        self.assertEqual({STATE_PENDING, STATE_KNOWN, STATE_UNKNOWN}, seen)


class SharedTriStateRuleTest(unittest.TestCase):
    """Finding I1: the three branches have **one** author, ``state_for_values``.

    Task 5's queue layer used to carry its own copy of them, and the reconciliation
    test that was supposed to keep the two honest stayed green when that copy was
    rewritten as a truthiness test (review probe A) -- the payload table held no
    sample able to tell the two rules apart. Falsy-but-present values
    (``duration=0.0``: an extractor that answered "no length"; ``artist=''``: an
    empty tag) are those samples, so they are pinned here, where the rule now
    lives, and every consumer is pinned to *calling* it.
    """

    def test_none_payload_is_pending(self):
        self.assertEqual(STATE_PENDING, state_for_values(None))

    def test_all_none_payload_is_unknown_not_pending(self):
        """B4-R8's first half: a *present* row of three ``None`` values was tried."""
        self.assertEqual(STATE_UNKNOWN, state_for_values(EMPTY_MD))

    def test_falsy_but_present_values_are_known(self):
        """The sample set probe A could not pass without.

        ``if md.artist or md.album or md.duration`` agrees with the rule on every
        payload this file used to hold and answers ``unknown`` here -- which would
        put a file the sweep already tried back onto the to-do list (criterion 6).
        """
        for md in (RowMetadata(duration=0.0), RowMetadata(artist=''),
                   RowMetadata(album=''),
                   RowMetadata(artist='', album='', duration=0.0)):
            with self.subTest(md=md):
                self.assertEqual(STATE_KNOWN, state_for_values(md))

    def test_state_of_delegates_instead_of_keeping_a_copy(self):
        """``state_of`` resolves the shared rule **at call time**.

        The sentinel goes onto the module attribute, so a ``state_of`` that had
        grown its own three branches stops seeing it and fails here -- including
        for a path the store does not know at all, which is the ``md is None``
        branch of the same rule.
        """
        store = LibraryMetadataStore()
        store.load_cache_entries([
            _cached(MP3_PATH, md=dict(KNOWN_DICT)),
            _cached(FLAC_PATH, md=_null_dict()),
        ])
        sentinel = 'sentinel-state'
        calls: list = []
        original = metadata_store.state_for_values
        try:
            def spy(md):
                calls.append(md)
                return sentinel

            metadata_store.state_for_values = spy
            self.assertEqual(sentinel, store.state_of(MP3_PATH))
            self.assertEqual(sentinel, store.state_of(FLAC_PATH))
            self.assertEqual(sentinel, store.state_of(NCM_PATH))
        finally:
            metadata_store.state_for_values = original
        self.assertEqual([KNOWN_MD, EMPTY_MD, None], calls,
                         'state_of did not hand its payload to the shared rule')

    def test_state_of_and_the_rule_agree_on_every_stored_shape(self):
        """The behavioural half of the same claim: one payload in, one word out.

        Loaded through ``load_cache_entries`` rather than ``record`` because
        ``record`` rewrites a non-positive duration to ``None`` (ruling B4-R7),
        which would make the two sides describe two different payloads here.
        """
        for md in (None, EMPTY_MD, KNOWN_MD, PARTIAL_MD,
                   RowMetadata(duration=0.0), RowMetadata(artist='')):
            with self.subTest(md=md):
                store = LibraryMetadataStore()
                cached = (_cached(MP3_PATH) if md is None
                          else _cached(MP3_PATH, md=_dict_of(md)))
                store.load_cache_entries([cached])
                self.assertEqual(state_for_values(store.get(MP3_PATH)),
                                 store.state_of(MP3_PATH))


class LoadCacheEntriesTest(unittest.TestCase):

    def test_returns_number_of_usable_entries(self):
        store = LibraryMetadataStore()
        self.assertEqual(2, store.load_cache_entries(
            [_cached(MP3_PATH), _cached(FLAC_PATH, md=_null_dict())]))

    def test_empty_load_returns_zero(self):
        self.assertEqual(0, LibraryMetadataStore().load_cache_entries([]))

    def test_entry_without_path_is_not_usable(self):
        store = LibraryMetadataStore()
        self.assertEqual(1, store.load_cache_entries(
            [_cached(''), _cached(MP3_PATH)]))

    def test_load_replaces_the_previous_library(self):
        """Switching libraries must not keep the old library's rows (spec §10 r1)."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.load_cache_entries([_cached(FLAC_PATH, md=_null_dict())])
        self.assertEqual(STATE_PENDING, store.state_of(MP3_PATH))
        self.assertEqual(STATE_UNKNOWN, store.state_of(FLAC_PATH))

    def test_load_leaves_nothing_dirty(self):
        """Loading is a read; only ``record`` owes a write-back."""
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH, md=_null_dict())])
        self.assertEqual(0, store.dirty_count())
        self.assertEqual([], store.take_dirty())


class ValidateTargetsTest(unittest.TestCase):
    """The invalidation matrix: which files the sweep is asked to fetch."""

    def test_pending_file_is_a_target_with_its_fingerprint(self):
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH, size=1000, mtime=100.0)])
        self.assertEqual([(MP3_PATH, 1000, 100.0)],
                         store.validate([_media(MP3_PATH, size=1000, mtime=100.0)]))

    def test_never_seen_file_is_a_target(self):
        self.assertEqual([(MP3_PATH, 1000, 100.0)],
                         LibraryMetadataStore().validate([_media(MP3_PATH)]))

    def test_target_is_a_triple_not_a_path(self):
        targets = LibraryMetadataStore().validate([_media(MP3_PATH, 1000, 100.0)])
        self.assertEqual(1, len(targets))
        full_path, size, mtime = targets[0]
        self.assertEqual(MP3_PATH, full_path)
        self.assertEqual(1000, size)
        self.assertEqual(100.0, mtime)

    def test_size_change_requests_extraction(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        self.assertEqual([(MP3_PATH, 2000, 100.0)],
                         store.validate([_media(MP3_PATH, size=2000, mtime=100.0)]))

    def test_mtime_change_requests_extraction(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        self.assertEqual([(MP3_PATH, 1000, 200.0)],
                         store.validate([_media(MP3_PATH, size=1000, mtime=200.0)]))

    def test_unchanged_known_is_not_requested(self):
        """Criterion 5: a full library on its second open re-extracts nothing."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        self.assertEqual([], store.validate([_media(MP3_PATH, 1000, 100.0)]))
        self.assertEqual(STATE_KNOWN, store.state_of(MP3_PATH))

    def test_all_null_md_is_not_requested_again(self):
        """Spec §8's fourth class, criterion 6: tried-and-empty is not retried."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, None, 1000, 100.0)
        self.assertEqual([], store.validate([_media(MP3_PATH, 1000, 100.0)]))
        self.assertEqual(STATE_UNKNOWN, store.state_of(MP3_PATH))

    def test_loaded_all_null_md_is_not_requested_again(self):
        """The same rule reached through the cache instead of a record."""
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH, md=_null_dict())])
        self.assertEqual([], store.validate([_media(MP3_PATH, 1000, 100.0)]))

    def test_pending_file_is_requested_on_every_scan_until_filled(self):
        """Pending is a question, not a write: nothing is recorded for it."""
        store = LibraryMetadataStore()
        store.load_cache_entries([_cached(MP3_PATH)])
        self.assertEqual(1, len(store.validate([_media(MP3_PATH)])))
        self.assertEqual(1, len(store.validate([_media(MP3_PATH)])))
        self.assertEqual(0, store.dirty_count())
        self.assertEqual(STATE_PENDING, store.state_of(MP3_PATH))

    def test_excluded_format_is_never_a_target(self):
        store = LibraryMetadataStore()
        self.assertEqual([], store.validate([_media(NCM_PATH)]))
        self.assertEqual([], store.validate([_media(NCM_PATH, size=9999, mtime=9.0)]))

    def test_excluded_format_is_recorded_once_not_every_scan(self):
        store = LibraryMetadataStore()
        store.validate([_media(NCM_PATH)])
        self.assertEqual(1, store.dirty_count(),
                         'the first scan has to write its "no metadata"')
        store.take_dirty()
        store.validate([_media(NCM_PATH)])
        self.assertEqual(0, store.dirty_count(),
                         'an already-tried excluded file must not be re-recorded '
                         'on every scan')

    def test_custom_excluded_set_is_honoured(self):
        store = LibraryMetadataStore(excluded_extensions=frozenset({'.flac'}))
        self.assertEqual([], store.validate([_media(FLAC_PATH)]))
        self.assertEqual(STATE_UNKNOWN, store.state_of(FLAC_PATH))
        self.assertEqual([(MP3_PATH, 1000, 100.0)],
                         store.validate([_media(MP3_PATH)]))

    def test_stale_fingerprint_invalidates_the_old_values(self):
        """A changed file must not keep showing the pre-change tags.

        Invalidating is expressed as *pending*, never as ``unknown``: clearing
        the values answers nothing, while ``record(md=None)`` would answer "this
        version has no tags" on the sweep's behalf.
        """
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.take_dirty()
        store.validate([_media(MP3_PATH, size=2000, mtime=100.0)])
        self.assertEqual(STATE_PENDING, store.state_of(MP3_PATH))
        self.assertIsNone(store.get(MP3_PATH))
        self.assertEqual(0, store.dirty_count(),
                         'a question owes no write-back; only the answer does')
        self.assertEqual([], store.take_dirty())

    def test_invalidation_does_not_store_the_fingerprint_it_just_compared(self):
        """Clearing must not adopt the fingerprint of the version it invalidated.

        The old version of this test asserted the opposite -- that a second scan
        of the same changed file stops looking stale -- and that was the defect
        (spec 4.6, criterion 5): adopting the new fingerprint is what makes the
        file look answered before anything was extracted. The stored fingerprint
        has no public getter, so this reads the entry it belongs to.
        """
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.take_dirty()
        store.validate([_media(MP3_PATH, size=2048, mtime=777.0)])
        self.assertEqual((1000, 100.0), store._entries[MP3_PATH].fingerprint,
                         'the stored fingerprint must stay the one the cleared '
                         'values were taken at, not the one just compared')
        self.assertEqual(0, store.dirty_count())

    def test_stale_and_unfilled_is_listed_again_by_next_validate(self):
        """The falsifiable half of criterion 5: an interrupted extraction retries.

        Two scans with nothing in between stand in for a sweep that was killed,
        crashed or simply has not answered yet.
        """
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.take_dirty()
        self.assertEqual([(MP3_PATH, 2000, 150.0)],
                         store.validate([_media(MP3_PATH, size=2000, mtime=150.0)]))
        self.assertEqual(
            [(MP3_PATH, 2000, 150.0)],
            store.validate([_media(MP3_PATH, size=2000, mtime=150.0)]),
            'an invalidation nobody filled in is still work to do')
        self.assertEqual(STATE_PENDING, store.state_of(MP3_PATH))

    def test_answer_after_invalidation_closes_it_and_advances_the_fingerprint(self):
        """``record`` is the only thing that ends the re-requesting."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.validate([_media(MP3_PATH, size=2000, mtime=150.0)])
        store.record(MP3_PATH, EMPTY_MD, 2000, 150.0)
        self.assertEqual([], store.validate([_media(MP3_PATH, 2000, 150.0)]))
        self.assertEqual(STATE_UNKNOWN, store.state_of(MP3_PATH))

    def test_mixed_library_requests_only_the_files_that_need_it(self):
        store = LibraryMetadataStore()
        store.load_cache_entries([
            _cached(MP3_PATH),                          # pending  -> target
            _cached(FLAC_PATH, md=dict(KNOWN_DICT)),    # known, unchanged -> not
            _cached(NCM_PATH, md=_null_dict()),         # excluded, tried -> not
        ])
        store.record(STALE_PATH, KNOWN_MD, 5, 5.0)      # known, size changed -> target
        store.take_dirty()
        targets = store.validate([
            _media(MP3_PATH),
            _media(FLAC_PATH),
            _media(NCM_PATH),
            _media(STALE_PATH, size=6, mtime=5.0),
        ])
        self.assertEqual({MP3_PATH, STALE_PATH},
                         {path for path, _size, _mtime in targets})


class DurationNormalizationTest(unittest.TestCase):
    """B4-R7: the non-positive rule enters the cache through ``record`` only."""

    def _dirty_md(self, duration) -> dict:
        store = LibraryMetadataStore()
        store.record(MP3_PATH, RowMetadata(artist='A', album='B',
                                           duration=duration), 1000, 100.0)
        return store.take_dirty()[0][1]

    def test_zero_duration_lands_as_none(self):
        self.assertIsNone(self._dirty_md(0.0)['duration'],
                          'a 0.0 duration reached the write-back batch')

    def test_negative_duration_lands_as_none(self):
        self.assertIsNone(self._dirty_md(-1)['duration'])

    def test_positive_duration_is_kept(self):
        self.assertEqual(227.0, self._dirty_md(227.0)['duration'])

    def test_normalized_value_also_reaches_get(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, RowMetadata('A', 'B', 0.0), 1000, 100.0)
        self.assertIsNone(store.get(MP3_PATH).duration)

    def test_normalization_alone_does_not_make_a_row_known(self):
        """Every field unknown is exactly ``STATE_UNKNOWN``, not ``0:00``."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, RowMetadata(None, None, 0.0), 1000, 100.0)
        self.assertEqual(STATE_UNKNOWN, store.state_of(MP3_PATH))

    def test_known_row_keeps_its_state_when_only_the_length_is_dropped(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, RowMetadata('A', 'B', 0.0), 1000, 100.0)
        self.assertEqual(STATE_KNOWN, store.state_of(MP3_PATH),
                         'a file with artist/album is still known even with no '
                         'length; normalization must not change the state')


class TakeDirtyTest(unittest.TestCase):
    """Task 7's write-back batch: keys verbatim, and the flag clears."""

    def test_dict_keys_are_exactly_md_keys(self):
        """B4-R1: what lands on disk is Task 1's canonical shape."""
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        [(full_path, md)] = store.take_dirty()
        self.assertEqual(MP3_PATH, full_path)
        self.assertEqual(set(MD_KEYS), set(md),
                         'write-back keys must be exactly artist/album/duration')
        self.assertEqual(KNOWN_DICT, md)

    def test_record_none_md_lands_as_all_null_dict(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, None, 1000, 100.0)
        [(_path, md)] = store.take_dirty()
        self.assertEqual(_null_dict(), md,
                         'md=None means "tried, nothing", which on disk is the '
                         'three-null dict -- never an absent key')

    def test_take_dirty_is_idempotent(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.record(FLAC_PATH, EMPTY_MD, 1000, 100.0)
        self.assertEqual(2, store.dirty_count())
        self.assertEqual(2, len(store.take_dirty()))
        self.assertEqual(0, store.dirty_count())
        self.assertEqual([], store.take_dirty())

    def test_second_record_keeps_one_entry_and_remarks_it_dirty(self):
        store = LibraryMetadataStore()
        store.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        store.take_dirty()
        store.record(MP3_PATH, EMPTY_MD, 1000, 100.0)
        self.assertEqual(1, store.dirty_count())
        self.assertEqual(1, len(store.take_dirty()))


class StoreIsolationTest(unittest.TestCase):
    """Two libraries (two instances) never share rows."""

    def test_records_do_not_leak_between_instances(self):
        first = LibraryMetadataStore()
        second = LibraryMetadataStore()
        first.record(MP3_PATH, KNOWN_MD, 1000, 100.0)
        self.assertEqual(STATE_PENDING, second.state_of(MP3_PATH))
        self.assertIsNone(second.get(MP3_PATH))
        self.assertEqual(0, second.dirty_count())

    def test_loaded_entries_do_not_leak_between_instances(self):
        first = LibraryMetadataStore()
        second = LibraryMetadataStore()
        first.load_cache_entries([_cached(MP3_PATH, md=dict(KNOWN_DICT))])
        self.assertEqual(STATE_PENDING, second.state_of(MP3_PATH))

    def test_default_excluded_set_is_not_shared_state(self):
        first = LibraryMetadataStore()
        second = LibraryMetadataStore()
        first.validate([_media(NCM_PATH)])
        self.assertEqual(STATE_PENDING, second.state_of(NCM_PATH))


class QueueCouplingScanTest(unittest.TestCase):
    """B4-R6: the queue's tests may read the store, never the reverse."""

    def test_store_does_not_import_the_queue_or_the_layers_above_it(self):
        forbidden = ('queue_service', 'QueueService', 'DisplayEntry',
                     'presenter', 'main_presenter')
        imports = [
            line.strip() for line in
            (ROOT / STORE_SOURCE).read_text(encoding='utf-8').splitlines()
            if line.strip().startswith(('import ', 'from '))
        ]
        self.assertTrue(imports, f'{STORE_SOURCE} should have imports to scan')
        for line in imports:
            for name in forbidden:
                self.assertNotIn(
                    name, line,
                    f'{STORE_SOURCE} imports through {line!r}, which references '
                    f'{name!r}: the coupling must stay one-way (ruling B4-R6)',
                )


if __name__ == '__main__':
    unittest.main(verbosity=2)
