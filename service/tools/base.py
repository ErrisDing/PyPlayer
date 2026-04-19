#!/usr/bin/env python3
"""
Base classes and data structures for metadata extraction tools
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional


class PictureType(IntEnum):
    """Picture type according to ID3/APIC and FLAC specification"""
    OTHER = 0
    FILE_ICON = 1
    OTHER_FILE_ICON = 2
    FRONT_COVER = 3
    BACK_COVER = 4
    LEAFLET_PAGE = 5
    MEDIA = 6
    LEAD_ARTIST = 7
    ARTIST = 8
    CONDUCTOR = 9
    BAND = 10
    COMPOSER = 11
    LYRICIST = 12
    RECORDING_LOCATION = 13
    DURING_RECORDING = 14
    DURING_PERFORMANCE = 15
    VIDEO_CAPTURE = 16
    BRIGHT_COLORED_FISH = 17
    ILLUSTRATION = 18
    BAND_LOGO = 19
    PUBLISHER_LOGO = 20


@dataclass
class ExtractedPicture:
    """Represents an extracted picture from audio metadata"""
    data: bytes
    mime_type: str = ""
    picture_type: PictureType = PictureType.FRONT_COVER
    description: str = ""


@dataclass
class ExtractionResult:
    """Result of metadata extraction with diagnostic information"""
    success: bool = True
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: float = 0.0
    pictures: List[ExtractedPicture] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    @property
    def album_art(self) -> Optional[bytes]:
        """Get the front cover image data (for backward compatibility)"""
        # Priority: FRONT_COVER > OTHER > any other
        for pic in self.pictures:
            if pic.picture_type == PictureType.FRONT_COVER:
                return pic.data
        for pic in self.pictures:
            if pic.picture_type == PictureType.OTHER:
                return pic.data
        if self.pictures:
            return self.pictures[0].data
        return None

    @property
    def has_cover_art(self) -> bool:
        """Check if any cover art was extracted"""
        return len(self.pictures) > 0


class MetadataExtractor(ABC):
    """Abstract base class for format-specific metadata extractors"""

    # Supported file extensions (lowercase, with dot)
    extensions: List[str] = []

    @classmethod
    @abstractmethod
    def extract(cls, filepath: str) -> ExtractionResult:
        """
        Extract metadata from the given file.

        Args:
            filepath: Path to the audio file

        Returns:
            ExtractionResult with extracted metadata and diagnostic info
        """
        pass

    @classmethod
    def diagnose(cls, filepath: str) -> dict:
        """
        Generate diagnostic information for the file.

        Args:
            filepath: Path to the audio file

        Returns:
            Dictionary with diagnostic details
        """
        result = cls.extract(filepath)
        return {
            "filepath": filepath,
            "success": result.success,
            "title": result.title,
            "artist": result.artist,
            "album": result.album,
            "duration": result.duration,
            "has_cover_art": result.has_cover_art,
            "picture_count": len(result.pictures),
            "pictures": [
                {
                    "type": pic.picture_type.name,
                    "mime": pic.mime_type,
                    "size": len(pic.data),
                    "description": pic.description,
                }
                for pic in result.pictures
            ],
            "errors": result.errors,
            "warnings": result.warnings,
            "diagnostics": result.diagnostics,
        }

    @classmethod
    def supports_extension(cls, ext: str) -> bool:
        """Check if this extractor supports the given file extension"""
        return ext.lower() in cls.extensions
