#!/usr/bin/env python3
"""Task 2: the extraction layer stops inventing values the view has to show.

Three contracts, one per way the old facade lied (spec §2 item 1, §4.2):

* **A missing tag is ``None``, not an English string.** ``core/metadata.py``
  substituted ``"Unknown Artist"`` / ``"Unknown Album"``, so the *extraction*
  layer decided what a *view* renders and "the tag is empty" was
  indistinguishable from "nobody looked yet". Batch 4 persists exactly this
  call's output into the cache's ``md`` -- an invented string would be written
  to disk as if it were a tag, and the "取不到" mark in criterion 3 could never
  be produced.
* **``duration <= 0`` is unknown.** The four mutagen extractors collapse "no
  length" into ``0.0`` (``audio.info.length if audio.info else 0.0``), so 0.0
  is ambiguity, not a measurement. Legal audio is never 0 s, so the rule loses
  no information (spec §4.2). ``normalize_duration`` is the **only** place this
  happens (ruling B4-R7); Task 3's ``LibraryMetadataStore.record`` is its only
  reuse point.
* **No fallback literal survives.** A source scan, in batch 1's shape, so the
  literal cannot creep back through a later edit even if every runtime path
  happens to be covered.

``title``'s ``Path(filepath).stem`` fallback is deliberately **kept**: a
filename is a real display value derived from real data, not an invented
attribute, and spec §2 only condemns the invented *properties*.

No Qt, no filesystem: the ``service.tools`` extraction call is patched, so the
module under test is the only thing deciding the fallbacks.

Run:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_metadata_fallbacks -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.metadata as metadata_module
from core.metadata import SongMetadata, extract_metadata
from service.tools import ExtractionResult

#: A path whose *stem* is a usable display value; the file never has to exist,
#: because the extraction call below is patched.
SONG_PATH = str(Path('library', 'jazz', 'Midnight Drive.mp3'))
SONG_STEM = 'Midnight Drive'

# Scanned source, and the literal form batch 1 used: a quoted substring with the
# trailing space that every invented value in this module carried. A docstring
# mentioning the old copy is not a quoted literal, but this scan is deliberately
# the looser ``Unknown `` so no invented English attribute can return.
SCAN_TARGET = 'core/metadata.py'
FORBIDDEN_SUBSTRINGS = ('Unknown ',)


def _result(**overrides) -> ExtractionResult:
    """An ``ExtractionResult`` with only the fields a test cares about set."""
    fields = {
        'success': True,
        'title': 'Midnight Drive',
        'artist': 'The Trio',
        'album': 'Blue Notes',
        'duration': 227.0,
    }
    fields.update(overrides)
    return ExtractionResult(**fields)


def _extract(**overrides) -> SongMetadata:
    """Run ``extract_metadata`` over a patched extraction result."""
    with mock.patch('service.tools.extract_metadata',
                    return_value=_result(**overrides)):
        return extract_metadata(SONG_PATH)


class MissingTagIsNoneTest(unittest.TestCase):
    """Absent artist/album tags come back as ``None`` -- never as English."""

    def test_missing_artist_is_none(self):
        self.assertIsNone(_extract(artist=None).artist,
                          'the extraction layer still invents an artist')

    def test_missing_album_is_none(self):
        self.assertIsNone(_extract(album=None).album,
                          'the extraction layer still invents an album')

    def test_empty_string_artist_is_none(self):
        """A blank tag is "no artist", and ``or`` must not pass it through."""
        self.assertIsNone(_extract(artist='').artist,
                          'an empty tag string survived as a value')

    def test_empty_string_album_is_none(self):
        self.assertIsNone(_extract(album='').album,
                          'an empty tag string survived as a value')

    def test_present_artist_and_album_pass_through_unchanged(self):
        """The guard must not become "always None": real tags still arrive."""
        metadata = _extract()
        self.assertEqual('The Trio', metadata.artist)
        self.assertEqual('Blue Notes', metadata.album)


class TitleStemFallbackKeptTest(unittest.TestCase):
    """``title`` keeps the filename fallback -- it is data, not an invention."""

    def test_missing_title_falls_back_to_stem(self):
        self.assertEqual(SONG_STEM, _extract(title=None).title,
                         'the stem fallback was removed along with the '
                         'invented artist/album defaults')

    def test_empty_title_falls_back_to_stem(self):
        self.assertEqual(SONG_STEM, _extract(title='').title)

    def test_present_title_passes_through(self):
        self.assertEqual('Midnight Drive', _extract().title)


class NormalizeDurationTest(unittest.TestCase):
    """``duration <= 0`` (and ``None``) is unknown; a real length survives."""

    def test_zero_is_unknown(self):
        self.assertIsNone(metadata_module.normalize_duration(0.0),
                          '0.0 must read as "no duration", not as a value')

    def test_negative_is_unknown(self):
        self.assertIsNone(metadata_module.normalize_duration(-1.0))

    def test_none_is_unknown(self):
        self.assertIsNone(metadata_module.normalize_duration(None))

    def test_positive_value_is_returned_unchanged(self):
        self.assertEqual(227.0, metadata_module.normalize_duration(227.0))

    def test_smallest_positive_value_is_not_unknown(self):
        """The boundary is ``<= 0``: a sub-second length is still a length."""
        self.assertEqual(0.1, metadata_module.normalize_duration(0.1))


class ExtractedDurationTest(unittest.TestCase):
    """The same rule holds for what ``extract_metadata`` hands back."""

    def test_zero_duration_becomes_none(self):
        self.assertIsNone(_extract(duration=0.0).duration,
                          'the 0.0/"no length" ambiguity survived extraction')

    def test_negative_duration_becomes_none(self):
        self.assertIsNone(_extract(duration=-5.0).duration)

    def test_none_duration_becomes_none(self):
        self.assertIsNone(_extract(duration=None).duration)

    def test_real_duration_survives(self):
        self.assertEqual(227.0, _extract(duration=227.0).duration)


class InventedLiteralSourceScanTest(unittest.TestCase):
    """Batch 1's guard shape: the invented English copy is gone from source."""

    def test_no_invented_fallback_literal_left(self):
        source = (ROOT / SCAN_TARGET).read_text(encoding='utf-8')
        for literal in FORBIDDEN_SUBSTRINGS:
            hits = [
                f'{SCAN_TARGET}:{line_number}'
                for line_number, line in enumerate(source.splitlines(), 1)
                if literal in line
            ]
            self.assertFalse(
                hits,
                f'{SCAN_TARGET} still contains the invented fallback literal '
                f'{literal!r} at {", ".join(hits)}',
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
