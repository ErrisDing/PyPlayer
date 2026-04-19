#!/usr/bin/env python3
"""
FLAC metadata extractor with multi-strategy cover art extraction
"""

import base64
from typing import Optional

from .base import (
    MetadataExtractor,
    ExtractionResult,
    ExtractedPicture,
    PictureType,
)


class FLACExtractor(MetadataExtractor):
    """Extract metadata from FLAC files with robust cover art handling"""

    extensions = ['.flac']

    @classmethod
    def extract(cls, filepath: str) -> ExtractionResult:
        result = ExtractionResult()

        try:
            from mutagen.flac import FLAC, Picture

            audio = FLAC(filepath)

            # Extract text metadata
            result.title = cls._get_first_tag(audio, 'title')
            result.artist = cls._get_first_tag(audio, 'artist')
            result.album = cls._get_first_tag(audio, 'album')
            result.duration = audio.info.length if audio.info else 0.0

            # Extract pictures using multiple strategies
            cls._extract_pictures(audio, result)

            # Populate diagnostics
            result.diagnostics = {
                "has_native_pictures": len(audio.pictures) > 0,
                "has_metadata_block_picture": 'metadata_block_picture' in audio,
                "has_coverart": 'coverart' in audio,
                "vorbis_comment_keys": list(audio.keys()),
            }

        except ImportError as e:
            result.success = False
            result.errors.append(f"mutagen library not available: {e}")
        except Exception as e:
            result.success = False
            result.errors.append(f"Failed to extract FLAC metadata: {e}")

        return result

    @classmethod
    def _get_first_tag(cls, audio, tag_name: str) -> Optional[str]:
        """Get the first value of a Vorbis comment tag"""
        value = audio.get(tag_name)
        if value:
            return str(value[0])
        return None

    @classmethod
    def _extract_pictures(cls, audio, result: ExtractionResult) -> None:
        """
        Extract pictures using multiple strategies.

        Strategy 1: Native FLAC PICTURE blocks (audio.pictures)
        Strategy 2: Vorbis comment METADATA_BLOCK_PICTURE (base64 encoded)
        Strategy 3: Legacy COVERART tag (base64 encoded)
        """
        # Strategy 1: Native PICTURE blocks
        if audio.pictures:
            for pic in audio.pictures:
                picture_type = PictureType.OTHER
                if hasattr(pic, 'type'):
                    try:
                        picture_type = PictureType(pic.type)
                    except ValueError:
                        picture_type = PictureType.OTHER

                result.pictures.append(ExtractedPicture(
                    data=pic.data,
                    mime_type=getattr(pic, 'mime', '') or '',
                    picture_type=picture_type,
                    description=getattr(pic, 'desc', '') or '',
                ))

        # Strategy 2: Vorbis comment METADATA_BLOCK_PICTURE
        if not result.pictures and 'metadata_block_picture' in audio:
            try:
                cls._extract_metadata_block_picture(audio, result)
            except Exception as e:
                result.warnings.append(
                    f"Failed to decode METADATA_BLOCK_PICTURE: {e}"
                )

        # Strategy 3: Legacy COVERART tag
        if not result.pictures and 'coverart' in audio:
            try:
                cls._extract_legacy_coverart(audio, result)
            except Exception as e:
                result.warnings.append(f"Failed to decode COVERART: {e}")

    @classmethod
    def _extract_metadata_block_picture(cls, audio, result: ExtractionResult) -> None:
        """Extract picture from METADATA_BLOCK_PICTURE Vorbis comment"""
        from mutagen.flac import Picture

        encoded_data = audio['metadata_block_picture']
        if not encoded_data:
            return

        # METADATA_BLOCK_PICTURE may be a single value or a list
        if isinstance(encoded_data, list):
            encoded_data = encoded_data[0]

        decoded = base64.b64decode(encoded_data)
        pic = Picture(decoded)

        picture_type = PictureType.OTHER
        if hasattr(pic, 'type'):
            try:
                picture_type = PictureType(pic.type)
            except ValueError:
                picture_type = PictureType.OTHER

        result.pictures.append(ExtractedPicture(
            data=pic.data,
            mime_type=getattr(pic, 'mime', '') or '',
            picture_type=picture_type,
            description=getattr(pic, 'desc', '') or '',
        ))

    @classmethod
    def _extract_legacy_coverart(cls, audio, result: ExtractionResult) -> None:
        """Extract picture from legacy COVERART Vorbis comment"""
        coverart = audio.get('coverart')
        if not coverart:
            return

        encoded_data = coverart[0] if isinstance(coverart, list) else coverart
        decoded = base64.b64decode(encoded_data)

        # Try to detect MIME type from image header
        mime_type = cls._detect_mime_type(decoded)

        result.pictures.append(ExtractedPicture(
            data=decoded,
            mime_type=mime_type,
            picture_type=PictureType.FRONT_COVER,  # Assume front cover
            description="",
        ))
        result.warnings.append(
            "Used legacy COVERART tag - MIME type was auto-detected"
        )

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
