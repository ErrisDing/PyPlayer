#!/usr/bin/env python3
"""
Audio metadata extraction module for PyPlayer
Supports MP3 (ID3), FLAC, M4A/MP4, and OGG Vorbis formats

This module provides a backward-compatible facade over the tools module.
For detailed diagnostics, use the service.tools module directly.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SongMetadata:
    """Container for song metadata"""
    title: str
    artist: str
    album: str
    duration: float  # in seconds
    album_art: Optional[bytes] = None


def extract_metadata(filepath: str) -> SongMetadata:
    """Extract metadata from an audio file.

    Args:
        filepath: Path to the audio file

    Returns:
        SongMetadata object with extracted information
    """
    from service.tools import extract_metadata as _extract_metadata_impl

    result = _extract_metadata_impl(filepath)
    filename = Path(filepath).stem

    # Map ExtractionResult to SongMetadata with fallbacks
    return SongMetadata(
        title=result.title or filename,
        artist=result.artist or "Unknown Artist",
        album=result.album or "Unknown Album",
        duration=result.duration,
        album_art=result.album_art,
    )


# Re-export for backward compatibility
__all__ = ['SongMetadata', 'extract_metadata']
