#!/usr/bin/env python3
"""
Audio metadata extraction module for PyPlayer
Supports MP3 (ID3), FLAC, M4A/MP4, OGG Vorbis, and NCM formats

This module provides a backward-compatible facade over the tools module.
For detailed diagnostics, use the service.tools module directly.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SongMetadata:
    """Container for song metadata.

    ``artist``, ``album`` and ``duration`` use ``None`` for "this file gives me
    nothing" (spec 4.1/4.2). The facade used to substitute English strings here,
    which made the *extraction* layer decide what a *view* paints: a column that
    was never fetched then looked identical to one whose tag is empty, and batch
    4 persists exactly this output into the cache, so an invented string would be
    written to disk as if it were a real tag. The view owns the display mark;
    this layer only reports what the file said.
    """
    title: str
    artist: Optional[str]
    album: Optional[str]
    duration: Optional[float]  # seconds; None means no length could be read
    album_art: Optional[bytes] = None
    original_path: Optional[str] = None  # Original NCM path if this is a proxy


def normalize_duration(value: Optional[float]) -> Optional[float]:
    """Collapse "no length" and "non-positive length" into ``None`` (spec 4.2).

    Every mutagen extractor writes ``audio.info.length if audio.info else 0.0``,
    so ``0.0`` is the *same value* for "the container has no length" and for a
    real measurement. Legal audio is never 0 s, so treating ``<= 0`` as unknown
    loses nothing and removes the ambiguity at its source.

    ``value`` is accepted as ``None`` even though ``ExtractionResult.duration``
    is declared ``float``: the field is `set` from container info and callers
    hand over whatever they hold, and "no value" must land on the same answer as
    "zero value" rather than raise.

    This is the module's only normalization site (ruling B4-R7) -- Task 3's
    ``LibraryMetadataStore.record`` is its single reuse point, so a non-positive
    duration can never reach the cache.
    """
    if value is None or value <= 0:
        return None
    return value


def extract_metadata(filepath: str, library_path: Optional[str] = None) -> SongMetadata:
    """Extract metadata from an audio file.

    Args:
        filepath: Path to the audio file
        library_path: Optional library path for NCM proxy creation

    Returns:
        SongMetadata object with extracted information. ``artist``/``album``
        are ``None`` when the tag is absent or blank and ``duration`` is ``None``
        when no positive length was read; ``title`` alone keeps a fallback,
        because a filename is a display value taken from the path rather than an
        invented attribute.
    """
    from service.tools import extract_metadata as _extract_metadata_impl
    from service.tools.ncm import NCMExtractor

    # For NCM files, set the library path for proxy creation
    ext = Path(filepath).suffix.lower()
    original_path = None

    if ext == '.ncm':
        original_path = filepath
        if library_path:
            NCMExtractor.set_library_path(library_path)

    result = _extract_metadata_impl(filepath)
    filename = Path(filepath).stem

    # Map ExtractionResult to SongMetadata. Only `title` gets a fallback, and it
    # comes from the path; a blank tag stays None (see the SongMetadata docstring).
    return SongMetadata(
        title=result.title or filename,
        artist=result.artist or None,
        album=result.album or None,
        duration=normalize_duration(result.duration),
        album_art=result.album_art,
        original_path=original_path,
    )


# Re-export for backward compatibility
__all__ = ['SongMetadata', 'extract_metadata', 'normalize_duration']
