#!/usr/bin/env python3
"""
Metadata extraction tools module

Provides format-specific extractors for audio metadata with diagnostic capabilities.
"""

from pathlib import Path
from typing import Optional, Type

from .base import (
    MetadataExtractor,
    ExtractionResult,
    ExtractedPicture,
    PictureType,
)
from .mp3 import MP3Extractor
from .flac import FLACExtractor
from .m4a import M4AExtractor
from .ogg import OGGExtractor
from .diagnostic import MetadataDiagnostic, DiagnosticReport, DirectorySummary


# Registry of all available extractors
EXTRACTORS: list[Type[MetadataExtractor]] = [
    MP3Extractor,
    FLACExtractor,
    M4AExtractor,
    OGGExtractor,
]


def get_extractor(filepath: str) -> Optional[Type[MetadataExtractor]]:
    """
    Get the appropriate extractor for a file based on its extension.

    Args:
        filepath: Path to the audio file

    Returns:
        The appropriate extractor class, or None if unsupported
    """
    ext = Path(filepath).suffix.lower()
    for extractor in EXTRACTORS:
        if extractor.supports_extension(ext):
            return extractor
    return None


def extract_metadata(filepath: str) -> ExtractionResult:
    """
    Extract metadata from an audio file.

    Automatically detects the file format and uses the appropriate extractor.

    Args:
        filepath: Path to the audio file

    Returns:
        ExtractionResult with metadata and diagnostic information
    """
    extractor = get_extractor(filepath)
    if extractor is None:
        result = ExtractionResult()
        result.success = False
        ext = Path(filepath).suffix.lower()
        result.errors.append(f"Unsupported file format: {ext}")
        return result

    return extractor.extract(filepath)


def diagnose_file(filepath: str) -> dict:
    """
    Run diagnostic analysis on a single file.

    Args:
        filepath: Path to the audio file

    Returns:
        Dictionary with diagnostic information
    """
    extractor = get_extractor(filepath)
    if extractor is None:
        ext = Path(filepath).suffix.lower()
        return {
            "filepath": filepath,
            "success": False,
            "errors": [f"Unsupported file format: {ext}"],
        }

    return extractor.diagnose(filepath)


def get_supported_extensions() -> list[str]:
    """
    Get list of all supported file extensions.

    Returns:
        List of supported extensions (lowercase, with dot)
    """
    extensions = []
    for extractor in EXTRACTORS:
        extensions.extend(extractor.extensions)
    return sorted(set(extensions))


__all__ = [
    # Base classes and types
    'MetadataExtractor',
    'ExtractionResult',
    'ExtractedPicture',
    'PictureType',
    # Extractors
    'MP3Extractor',
    'FLACExtractor',
    'M4AExtractor',
    'OGGExtractor',
    # Diagnostic tools
    'MetadataDiagnostic',
    'DiagnosticReport',
    'DirectorySummary',
    # Functions
    'get_extractor',
    'extract_metadata',
    'diagnose_file',
    'get_supported_extensions',
    # Registry
    'EXTRACTORS',
]
