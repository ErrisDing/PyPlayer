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
    """Container for song metadata"""
    title: str
    artist: str
    album: str
    duration: float  # in seconds
    album_art: Optional[bytes] = None
    original_path: Optional[str] = None  # Original NCM path if this is a proxy


def extract_metadata(filepath: str, library_path: Optional[str] = None) -> SongMetadata:
    """Extract metadata from an audio file.

    Args:
        filepath: Path to the audio file
        library_path: Optional library path for NCM proxy creation

    Returns:
        SongMetadata object with extracted information
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

    # Map ExtractionResult to SongMetadata with fallbacks
    return SongMetadata(
        title=result.title or filename,
        artist=result.artist or "Unknown Artist",
        album=result.album or "Unknown Album",
        duration=result.duration,
        album_art=result.album_art,
        original_path=original_path,
    )


# Re-export for backward compatibility
__all__ = ['SongMetadata', 'extract_metadata']
