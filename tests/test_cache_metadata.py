#!/usr/bin/env python3
"""Batch 4 Task 1: the ``md`` three-state contract on the per-library JSON cache.

Spec 2026-10-20-ui-batch4-metadata-columns §4.1/§4.3, ruling B4-R1.

Everything downstream in this batch (metadata store, sweep, queue rows, model
roles, delegate columns) reads the two states pinned here, so this file is the
cheapest place to catch a collapse of the distinction:

  * ``md`` **absent from the JSON** = never extracted, still pending. A later
    sweep must come back for it.
  * ``md`` **present, all three values null** = extraction was tried and the
    tag has nothing (unknown), or the format is excluded (NCM). A sweep must
    *not* retry it, and the UI must draw "取不到" rather than "未取到".

Because the two states differ by key presence, not by value, ``None`` in the
dataclass means "no key", and ``to_dict`` must then leave the key out entirely
-- writing ``"md": null`` would turn every pending row into a tried-and-empty
one and silently kill the background fill on the second open of a library.

A third shape reaches the reader only from a half-written or hand-edited file:
``md`` present but not a mapping (``5``, ``"abc"``, a bare ``null``). It reads
as the same "tried, nothing" dict and must never raise -- ``load_cache`` guards
just OSError/JSONDecodeError, so an exception here would take the whole file
table down for one bad cell.

Pure data: ``core.cache_manager`` imports no Qt, so no ``QApplication`` here.
The cache directory is redirected through ``_get_cache_dir`` so the real
``~/.pyplayer`` is never touched; filename hashing, ``_get_cache_filepath``,
``save_cache`` and ``load_cache`` are all the production implementations.

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_cache_metadata -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import cache_manager
from core.cache_manager import CachedFile, LibraryCacheManager

#: The canonical key set of ``md`` (B4-R1), spelled locally on purpose: later
#: batch-4 tasks are expected to use these names, and a test that imported the
#: production constant would not notice a rename on either side.
MD_KEYS = ('artist', 'album', 'duration')

#: Sentinel for "this entry has no ``md`` key at all" (= pending). No md *value*
#: can express that -- ``None`` is the other state (present, tried, found empty).
NO_MD_KEY = object()

#: A full "known" entry -- the values are arbitrary but must survive verbatim.
KNOWN_MD = {'artist': 'B', 'album': 'M', 'duration': 227.0}

#: The "tried, nothing there" shape: the key exists, every value is null.
EMPTY_MD = {'artist': None, 'album': None, 'duration': None}


class CacheMetadataTestCase(unittest.TestCase):
    """Shared fixture: a manager writing into a throwaway cache directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        cache_dir = Path(self._tmp.name) / 'cache' / 'libraries'
        # Redirected before __init__ runs, so the real ~/.pyplayer is untouched
        # (and never created by a test run).
        patcher = mock.patch.object(
            LibraryCacheManager, '_get_cache_dir', lambda self: cache_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.manager = LibraryCacheManager()
        self.assertTrue(cache_dir.is_dir(), '_ensure_cache_dir must still run')
        # Unique per test, and only ever hashed -- no library directory needed,
        # since none of save/load path resolution stats it.
        self.library_path = str(Path(self._tmp.name) / 'library')

    def _entry(self, path: str, md=None) -> CachedFile:
        """One cached file, with or without ``md``."""
        return CachedFile(
            path=path,
            title=Path(path).stem,
            file_type='audio',
            extension='.mp3',
            size_bytes=1024,
            modified_time=1700000000.0,
            md=md,
        )

    def _cache_file(self) -> Path:
        return self.manager._get_cache_filepath(self.library_path)

    def _read_raw(self) -> dict:
        """The JSON actually on disk -- the state the contract is about."""
        return json.loads(self._cache_file().read_text(encoding='utf-8'))

    def _write_raw(self, payload: dict) -> None:
        """Drop a hand-built cache file, bypassing every write path."""
        self._cache_file().write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def _legacy_payload(self, version: str = '1.0') -> dict:
        """A file whose entries carry no ``md`` key at all, i.e. all pending.

        That is the pre-batch-4 shape, but the version stamp is a parameter so
        read-side cases can hold ``md`` shapes ``to_dict`` never writes.
        """
        return {
            'version': version,
            'library_path': self.library_path,
            'library_name': 'library',
            'scan_timestamp': 1700000000.0,
            'files': [
                {
                    'path': str(Path(self.library_path) / 'one.mp3'),
                    'title': 'one',
                    'file_type': 'audio',
                    'extension': '.mp3',
                    'size_bytes': 1,
                    'modified_time': 1.0,
                },
                {
                    'path': str(Path(self.library_path) / 'two.flac'),
                    'title': 'two',
                    'file_type': 'audio',
                    'extension': '.flac',
                    'size_bytes': 2,
                    'modified_time': 2.0,
                },
            ],
        }

    def _write_entry_md(self, md=NO_MD_KEY, index: int = 0) -> dict:
        """Hand-write a 2.0 file whose entry ``index`` carries this raw ``md``.

        ``to_dict`` cannot produce a present-but-null or non-mapping value, so
        those shapes reach the reader only through the file itself.
        """
        payload = self._legacy_payload(version='2.0')
        if md is not NO_MD_KEY:
            payload['files'][index]['md'] = md
        self._write_raw(payload)
        return payload


class CacheMdRoundTripTest(CacheMetadataTestCase):
    """``md`` presence and absence survive a save/load cycle as two states."""

    def test_round_trip_preserves_md_and_absence(self):
        """One filled ``md``, one absent: both must come back as themselves.

        The absence half is asserted against the JSON on disk, not against the
        in-memory ``None``: only the file shows whether the key was left out or
        written as ``null`` -- and those two are the states the whole batch
        distinguishes.
        """
        self.assertTrue(
            self.manager.save_cache(self.manager.create_cache(
                self.library_path, 'library',
                [self._entry('a.mp3', md=dict(KNOWN_MD)),
                 self._entry('b.mp3', md=None)])),
            'save_cache refused to write')

        raw = self._read_raw()
        self.assertEqual('2.0', raw['version'], 'the write side must emit 2.0')
        self.assertEqual(
            KNOWN_MD, raw['files'][0]['md'],
            'the known md dict lost or renamed a key (B4-R1: artist/album/duration)')
        self.assertNotIn(
            'md', raw['files'][1],
            'a pending entry gained an "md" key: presence is how pending and '
            '"tried, nothing" are told apart, so writing "md": null collapses '
            'the two states and stops the sweep ever filling the row')

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(loaded, 'a 2.0 cache must load')
        self.assertEqual(2, len(loaded.files))
        self.assertEqual(KNOWN_MD, loaded.files[0].md, 'known md did not round-trip')
        self.assertIsNone(
            loaded.files[1].md,
            'a missing md key must load as None (= pending), not as an empty dict')
        # The untouched fields still round-trip (this task must not eat them).
        self.assertEqual('a.mp3', Path(loaded.files[0].path).name)
        self.assertEqual(1024, loaded.files[0].size_bytes)
        self.assertEqual(1700000000.0, loaded.files[0].modified_time)

    def test_explicit_md_with_all_nulls_is_present_and_distinct_from_absent(self):
        """``md`` with three nulls is a state of its own, not ``None``.

        This is the entry an excluded format (NCM) or an empty-tag file gets
        (spec 4.1): "already tried". Written deliberately, read back as a dict,
        and never equal to the pending entry it sits next to.
        """
        self.assertTrue(self.manager.save_cache(self.manager.create_cache(
            self.library_path, 'library',
            [self._entry('c.ncm', md=dict(EMPTY_MD)),
             self._entry('d.mp3', md=None)])))

        raw = self._read_raw()
        self.assertIn('md', raw['files'][0],
                      'an all-null md lost its key on the way out')
        self.assertEqual(EMPTY_MD, raw['files'][0]['md'])
        # No separate "keys are exactly MD_KEYS" check here: it is entailed by
        # the equality above and could never be the first failure. The key set is
        # pinned independently by
        # test_mapping_md_missing_canonical_key_comes_back_complete.
        self.assertNotIn('md', raw['files'][1])

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(loaded)
        present, absent = loaded.files[0].md, loaded.files[1].md
        self.assertIsNotNone(
            present,
            'an existing all-null "md" key loaded as None: the reader cannot '
            'tell "tried, nothing" from "not tried" any more')
        self.assertEqual(EMPTY_MD, present)
        self.assertNotEqual(present, absent,
                            'all-null md and absent md loaded to the same value')
        self.assertIsNone(absent)


class CacheVersionCompatibilityTest(CacheMetadataTestCase):
    """2.0 is written; 1.0 is still read, and nothing else is."""

    def test_version_one_zero_cache_still_loads_as_pending(self):
        """An old file loads, keeps its file table, and reads as all-pending.

        The point of accepting 1.0 is spec criterion 7: upgrading the version
        must not invalidate the file table, or every existing library gets
        re-scanned on the day this ships. Entries without a key load as ``None``
        (pending) rather than as empty dicts, which is what lets the sweep fill
        them later.
        """
        self._write_raw(self._legacy_payload())

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(
            loaded,
            'a version 1.0 cache was rejected: the compatibility window is not '
            'open, so every pre-batch-4 library is treated as uncached')
        self.assertEqual(2, len(loaded.files), 'the 1.0 file table came back empty')
        self.assertEqual(
            ['one.mp3', 'two.flac'],
            [Path(f.path).name for f in loaded.files])
        for entry in loaded.files:
            with self.subTest(path=entry.path):
                self.assertIsNone(
                    entry.md,
                    '1.0 entries must load as pending (no md key), not as '
                    '"tried, nothing" -- the latter would stop the sweep')

    def test_wrong_version_is_still_rejected(self):
        """Accepting 1.0 must not mean accepting everything.

        An unknown version has no defined meaning for ``md``, so guessing would
        put arbitrary dicts in front of the view layer. The window is exactly
        {1.0, 2.0}.
        """
        self._write_raw(self._legacy_payload(version='3.0'))

        self.assertIsNone(
            self.manager.load_cache(self.library_path),
            'a 3.0 cache loaded: the compatibility window opened past its edge')
        self.assertEqual(
            frozenset({'1.0', '2.0'}), cache_manager.SUPPORTED_CACHE_VERSIONS,
            'the supported-version set drifted from the 1.0/2.0 contract')
        self.assertEqual('2.0', cache_manager.CACHE_VERSION)
        self.assertEqual(
            cache_manager.SUPPORTED_CACHE_VERSIONS,
            LibraryCacheManager.SUPPORTED_CACHE_VERSIONS,
            'the class-level and module-level spellings of the window differ')

    def test_saving_a_one_zero_library_writes_two_zero(self):
        """Load 1.0 -> save -> the file is 2.0, still with its entries intact.

        Spec 4.3 calls this the in-place upgrade: the library is written back in
        the new format on its next save without a re-scan, so the file table and
        every path survive the version bump.
        """
        self._write_raw(self._legacy_payload())

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(loaded, 'a 1.0 cache was rejected')
        self.assertTrue(self.manager.save_cache(loaded), 'saving the upgraded library failed')

        raw = self._read_raw()
        self.assertEqual(
            '2.0', raw['version'],
            'a library read from 1.0 was written back as '
            f"{raw['version']!r}: it never leaves the old format")
        self.assertEqual(2, len(raw['files']))
        self.assertEqual(
            ['one.mp3', 'two.flac'],
            [Path(entry['path']).name for entry in raw['files']])

        reloaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(reloaded, 'the upgraded file does not load back')
        self.assertEqual(2, len(reloaded.files))
        for entry in reloaded.files:
            with self.subTest(path=entry.path):
                self.assertIsNone(entry.md,
                                  'the upgrade invented md keys for old entries')


class CacheMdReadSideToleranceTest(CacheMetadataTestCase):
    """The ``md`` shapes ``to_dict`` cannot write, read off the disk as written.

    Every case here builds the JSON by hand. That is the point: a round-trip
    through the writer cannot reach these branches, so a regression that folds
    them into "pending" (or lets them raise) would keep the other five cases
    green.
    """

    def test_present_null_md_reads_as_tried_not_pending(self):
        """``"md": null`` on disk loads as the all-null dict, never as ``None``.

        The two states are separated by key presence alone, so a key that is
        present with a null payload still claims "extraction was tried". Reading
        it as ``None`` -- the shortest "simplification" of ``_read_md`` -- makes
        every excluded (NCM) or empty-tag file pending again, and the next start
        retries it forever (spec criterion 6).
        """
        self._write_entry_md(md=None)

        # Guard the fixture itself: the file must really hold key-present-null
        # on entry 0 and no key at all on entry 1.
        raw = self._read_raw()
        self.assertIn('md', raw['files'][0], 'the fixture lost the md key')
        self.assertIsNone(raw['files'][0]['md'], 'the fixture wrote a value, not null')
        self.assertNotIn('md', raw['files'][1], 'the fixture did not build the pair')

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(
            loaded, 'a 2.0 cache whose md is null was refused outright')
        tried, pending = loaded.files[0].md, loaded.files[1].md
        self.assertIsNotNone(
            tried,
            'an "md" key present with a null value loaded as None: presence is the '
            'only claim that extraction was tried, so this collapses "tried, '
            'nothing" into "not tried" and the sweep retries the file forever')
        self.assertEqual(
            EMPTY_MD, tried,
            'a present-null md did not load as the three-null dict')
        self.assertIsNone(
            pending,
            'the keyless entry in the same file stopped being pending')
        self.assertNotEqual(
            tried, pending,
            'present-null and absent md loaded to the same value')

    def test_corrupt_md_value_reads_as_tried_and_never_raises(self):
        """A non-mapping ``md`` is the same state as a null one -- and cannot raise.

        ``dict(5)`` / ``dict("abc")`` raise ValueError/TypeError, while
        ``load_cache`` catches only OSError/IOError/JSONDecodeError, so the
        exception escaped all four read APIs (``load_cache``,
        ``has_valid_cache``, ``is_cache_fresh``, ``get_cached_files``) and cost
        the library its whole file table for one damaged cell -- even though the
        same reader refuses a truncated JSON file quietly. A damaged md counts as
        "already tried": no retry, no raise.
        """
        for md in (5, 'abc'):
            with self.subTest(md=md):
                self._write_entry_md(md=md)

                loaded = self.manager.load_cache(self.library_path)
                self.assertIsNotNone(
                    loaded,
                    f'an md value of {md!r} was allowed to abort load_cache '
                    'instead of reading as "tried, nothing"')
                self.assertEqual(
                    EMPTY_MD, loaded.files[0].md,
                    f'a corrupt md value of {md!r} did not load as the '
                    'three-null dict')

                # The other three public read APIs parse the same file; each must
                # return a verdict rather than propagate.
                self.assertTrue(
                    self.manager.has_valid_cache(self.library_path),
                    'has_valid_cache did not treat the damaged md as readable')
                self.assertFalse(
                    self.manager.is_cache_fresh(self.library_path),
                    'is_cache_fresh reports on the missing directory, not the md')
                self.assertIsNone(
                    self.manager.get_cached_files(self.library_path),
                    'get_cached_files returned entries for a stale library')

    def test_mapping_md_missing_canonical_key_comes_back_complete(self):
        """A mapping with gaps comes back holding all three canonical keys.

        The reader is the one place that knows B4-R1's key set, so it fills the
        gap with ``None`` (= unknown) instead of leaving consumers to index a
        missing key or each invent a default. Values that are present survive
        verbatim; nothing is invented for them.
        """
        self._write_entry_md(md={'artist': 'x', 'duration': 227.0})

        self.assertEqual(
            {'artist': 'x', 'duration': 227.0}, self._read_raw()['files'][0]['md'],
            'the fixture did not write a gap in the mapping')

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(loaded, 'a mapping md with a missing key was refused')
        md = loaded.files[0].md
        self.assertEqual(
            sorted(MD_KEYS), sorted(md),
            'a mapping md missing a canonical key came back with a different key '
            'set: consumers were promised artist/album/duration')
        self.assertIsNone(md['album'], 'the filled-in canonical key is not unknown')
        self.assertEqual('x', md['artist'], 'a present value was overwritten')
        self.assertEqual(227.0, md['duration'], 'a present value was overwritten')


class CacheMdValueShapeTest(CacheMetadataTestCase):
    """A *mapping* ``md`` whose values have the wrong shape stays "already tried".

    Final-review C1. The container is validated (see
    :class:`CacheMdReadSideToleranceTest`) and the values were not, which stopped
    mattering until batch 4 made this file a **display source**: a hand-edited
    cache (someone pasting a duration, fixing a tag, a copy from another tool)
    with ``{"duration": "227.0"}`` read back as a *known* row carrying a string,
    the queue pushed it onto a row, and ``PlaylistItemDelegate.paint`` handed it
    to ``format_time`` -- which compares ``seconds < 0`` and raised ``TypeError``
    inside a Python override of a C++ virtual. Measured on this host: exit 127,
    no traceback, on **every** launch, because the file is still there. That
    turns spec criteria 4 and 7 into "this library will not open".

    Two halves of the rule, and the first is the reason this is not a raise:
    the **key** is what claims "extraction was tried" (spec 4.1), so a value that
    cannot be a value downgrades to ``None`` and the entry stays in the
    "tried, nothing" bucket -- never back to pending, which would make the sweep
    retry damage forever. The second is that "is a value" is a *type* question
    with two traps: ``bool`` is a subclass of ``int``, so ``True`` would pass for
    a duration and paint ``0:01``; and a non-positive duration is not an answer
    either (spec 4.2, the same ``normalize_duration`` ``record`` applies -- one
    author, ruling B4-R7).
    """

    def test_wrongly_typed_values_downgrade_to_none_and_stay_tried(self):
        """``{"artist": 123, "album": null, "duration": "227.0"}`` -> three ``None``.

        Asserted against the *file*, because these are the shapes ``to_dict``
        cannot write: a round trip through the writer would only prove the
        writer agrees with itself.
        """
        self._write_entry_md(md={'artist': 123, 'album': None, 'duration': '227.0'})

        raw = self._read_raw()
        self.assertEqual({'artist': 123, 'album': None, 'duration': '227.0'},
                         raw['files'][0]['md'], 'the fixture rewrote the damage')

        loaded = self.manager.load_cache(self.library_path)
        self.assertIsNotNone(loaded, 'a damaged md value was refused outright')
        md = loaded.files[0].md
        self.assertIsNotNone(
            md,
            'a present md key whose values are damaged read as None: presence is '
            'the only claim that extraction was tried, so this sends the file '
            'back to pending and the sweep retries damage on every start')
        self.assertEqual(EMPTY_MD, md, 'a damaged md value survived the reader')
        self.assertEqual(sorted(MD_KEYS), sorted(md),
                         'the key set drifted while the values were being fixed')
        # The untouched pending entry in the same file is still the other state.
        self.assertIsNone(loaded.files[1].md)
        self.assertNotEqual(md, loaded.files[1].md)

    def test_bool_is_not_a_duration_and_not_an_artist(self):
        """``True`` is an ``int`` subclass, and that is exactly why it is refused.

        ``format_time(True)`` paints ``0:01`` and ``normalize_duration(True)``
        answers ``True`` (``True <= 0`` is False), so a bool that survives the
        shape test becomes a fabricated length on screen -- the same defect spec
        4.2 exists to remove, arriving from the other direction.
        """
        #: ``(md, the duration the reader is allowed to hand back)``.
        for md, expected_duration in (
                ({'artist': None, 'album': None, 'duration': True}, None),
                ({'artist': None, 'album': None, 'duration': False}, None),
                ({'artist': True, 'album': 5, 'duration': 227.0}, 227.0)):
            with self.subTest(md=md):
                self._write_entry_md(md=dict(md))
                loaded = self.manager.load_cache(self.library_path)
                self.assertIsNotNone(loaded)
                read = loaded.files[0].md
                self.assertIsNotNone(read, 'the md key itself was lost')
                self.assertIsNone(read['artist'], 'a bool was accepted as an artist')
                self.assertIsNone(read['album'], 'a non-str was accepted as an album')
                self.assertEqual(
                    expected_duration, read['duration'],
                    'a bool was accepted as a duration (True paints a fabricated '
                    '0:01 -- the 0.0 ambiguity of spec 4.2 from the other side), '
                    'or a legal number was dropped by the guard')

    def test_non_positive_duration_is_not_an_answer(self):
        """``0``/``-3`` in the file read as "no duration" (spec 4.2).

        The writer never produces these (``record`` normalizes), so only an
        external edit can; and the spec is explicit that ``0.0`` is not allowed
        in the cache, because a known duration of zero paints ``0:00`` -- spec
        criterion 2's forbidden shape.
        """
        for value in (0, 0.0, -3, -1.5):
            with self.subTest(value=value):
                self._write_entry_md(
                    md={'artist': 'A', 'album': 'B', 'duration': value})
                read = self.manager.load_cache(
                    self.library_path).files[0].md
                self.assertIsNone(
                    read['duration'],
                    f'a duration of {value!r} was kept: the cache would then hold '
                    'a length the spec forbids and the view would paint 0:00')
                self.assertEqual('A', read['artist'],
                                 'one damaged field took the healthy ones with it')
                self.assertEqual('B', read['album'])

    def test_values_with_the_right_shape_survive_verbatim(self):
        """The guard rejects shapes, not content: a real answer is untouched.

        ``0.0`` and ``''`` are *falsy but present* values (ruling B4-R8), so this
        case is also the half that stops a truthiness shortcut -- ``if value``
        would drop an empty artist that the extractor genuinely reported.
        """
        self._write_entry_md(md={'artist': '', 'album': 'B', 'duration': 227})
        read = self.manager.load_cache(self.library_path).files[0].md
        self.assertEqual('', read['artist'],
                         'an empty artist was dropped: presence, not truthiness, '
                         'is what makes a value an answer (B4-R8)')
        self.assertEqual('B', read['album'])
        self.assertEqual(227, read['duration'],
                         'an int duration -- a legal number -- was refused')

    def test_the_damaged_values_survive_a_round_trip_as_unknown(self):
        """Read, write, read: the downgrade is stable, not a one-load-only mask.

        ``save_cache`` re-emits what the reader returned, so a repaired entry
        lands on disk as the all-null dict and stops being damage -- otherwise
        every launch would re-pay the same repair (and re-expose the paint path).
        """
        self._write_entry_md(md={'artist': 123, 'album': None, 'duration': '227.0'})
        loaded = self.manager.load_cache(self.library_path)
        self.assertTrue(self.manager.save_cache(loaded))
        self.assertEqual(EMPTY_MD, self._read_raw()['files'][0]['md'],
                         'the repaired payload did not reach the file')
        self.assertEqual(EMPTY_MD,
                         self.manager.load_cache(self.library_path).files[0].md)


if __name__ == '__main__':
    unittest.main(verbosity=2)
