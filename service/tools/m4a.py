#!/usr/bin/env python3
"""
M4A/MP4 metadata extractor
"""

from typing import Optional

from .base import (
    MetadataExtractor,
    ExtractionResult,
    ExtractedPicture,
    PictureType,
)


class M4AExtractor(MetadataExtractor):
    """Extract metadata from M4A/MP4 audio files"""

    extensions = ['.m4a', '.mp4', '.m4b', '.m4p']

    # MP4 tag keys
    TAG_TITLE = '\xa9nam'
    TAG_ARTIST = '\xa9ART'
    TAG_ALBUM = '\xa9alb'
    TAG_COVER = 'covr'

    @classmethod
    def extract(cls, filepath: str) -> ExtractionResult:
        result = ExtractionResult()

        try:
            from mutagen.mp4 import MP4

            audio = MP4(filepath)
            result.duration = audio.info.length if audio.info else 0.0

            # Extract text metadata
            if cls.TAG_TITLE in audio:
                result.title = str(audio[cls.TAG_TITLE][0])
            if cls.TAG_ARTIST in audio:
                result.artist = str(audio[cls.TAG_ARTIST][0])
            if cls.TAG_ALBUM in audio:
                result.album = str(audio[cls.TAG_ALBUM][0])

            # Extract cover art
            cls._extract_pictures(audio, result)

            # Populate diagnostics
            result.diagnostics = {
                "has_cover_art": cls.TAG_COVER in audio,
                "tag_keys": list(audio.keys()),
            }

        except ImportError as e:
            result.success = False
            result.errors.append(f"mutagen library not available: {e}")
        except Exception as e:
            result.success = False
            result.errors.append(f"Failed to extract M4A/MP4 metadata: {e}")

        return result

    @classmethod
    def _extract_pictures(cls, audio, result: ExtractionResult) -> None:
        """Extract pictures from covr atom"""
        if cls.TAG_COVER not in audio:
            return

        covers = audio[cls.TAG_COVER]
        for idx, cover_data in enumerate(covers):
            # MP4 cover data is bytes-like
            data = bytes(cover_data)

            # Determine MIME type from image header
            mime_type = cls._detect_mime_type(data)

            # MP4 doesn't have picture types in the same way
            # First image is typically front cover
            picture_type = PictureType.FRONT_COVER if idx == 0 else PictureType.OTHER

            result.pictures.append(ExtractedPicture(
                data=data,
                mime_type=mime_type,
                picture_type=picture_type,
                description="",
            ))

    @staticmethod
    def _detect_mime_type(data: bytes) -> str:
        """Detect MIME type from image header bytes"""
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        elif data[:2] == b'\xff\xd8':
            return 'image/jpeg'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
        return ''
