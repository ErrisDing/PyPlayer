#!/usr/bin/env python3
"""
MP3 metadata extractor using ID3 tags
"""

from typing import Optional

from .base import (
    MetadataExtractor,
    ExtractionResult,
    ExtractedPicture,
    PictureType,
)


class MP3Extractor(MetadataExtractor):
    """Extract metadata from MP3 files using ID3 tags"""

    extensions = ['.mp3']

    @classmethod
    def extract(cls, filepath: str) -> ExtractionResult:
        result = ExtractionResult()

        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB

            audio = MP3(filepath)
            result.duration = audio.info.length if audio.info else 0.0

            # Try to get ID3 tags
            try:
                tags = ID3(filepath)
                cls._extract_text_tags(tags, result)
                cls._extract_pictures(tags, result)

                # Populate diagnostics
                result.diagnostics = {
                    "id3_version": str(tags.version) if tags.version else None,
                    "has_apic_frames": any(
                        isinstance(frame, APIC) for frame in tags.values()
                    ),
                    "tag_count": len(tags),
                    "tag_keys": [k for k in tags.keys()],
                }
            except Exception as e:
                result.warnings.append(f"No valid ID3 tags found: {e}")

        except ImportError as e:
            result.success = False
            result.errors.append(f"mutagen library not available: {e}")
        except Exception as e:
            result.success = False
            result.errors.append(f"Failed to extract MP3 metadata: {e}")

        return result

    @classmethod
    def _extract_text_tags(cls, tags, result: ExtractionResult) -> None:
        """Extract text metadata from ID3 tags"""
        if TIT2 in tags:
            result.title = str(tags[TIT2].text[0]) if tags[TIT2].text else None
        if TPE1 in tags:
            result.artist = str(tags[TPE1].text[0]) if tags[TPE1].text else None
        if TALB in tags:
            result.album = str(tags[TALB].text[0]) if tags[TALB].text else None

    @classmethod
    def _extract_pictures(cls, tags, result: ExtractionResult) -> None:
        """Extract pictures from APIC frames"""
        from mutagen.id3 import APIC

        for frame in tags.values():
            if isinstance(frame, APIC):
                picture_type = PictureType.OTHER
                try:
                    picture_type = PictureType(frame.type)
                except (ValueError, AttributeError):
                    picture_type = PictureType.OTHER

                result.pictures.append(ExtractedPicture(
                    data=frame.data,
                    mime_type=frame.mime or '',
                    picture_type=picture_type,
                    description=getattr(frame, 'desc', '') or '',
                ))
