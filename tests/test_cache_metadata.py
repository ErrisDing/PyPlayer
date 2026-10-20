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

#: The canonical key set of ``md`` (B4-R1). Task 3's ``record`` builds dicts in
#: this shape; Tasks 5-8 consume these names verbatim.
MD_KEYS = ('artist', 'album', 'duration')

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
        """A pre-batch-4 file: no ``md`` key anywhere, old shape only."""
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
        self.assertEqual(sorted(MD_KEYS), sorted(raw['files'][0]['md'].keys()))
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
