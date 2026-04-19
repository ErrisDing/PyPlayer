#!/usr/bin/env python3
"""
Audio metadata extraction module for PyPlayer
Supports MP3 (ID3), FLAC, M4A/MP4, and OGG Vorbis formats
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
    ext = Path(filepath).suffix.lower()
    filename = Path(filepath).stem

    if ext == '.mp3':
        metadata = _extract_mp3_metadata(filepath)
    elif ext == '.flac':
        metadata = _extract_flac_metadata(filepath)
    elif ext in {'.m4a', '.mp4'}:
        metadata = _extract_m4a_metadata(filepath)
    elif ext == '.ogg':
        metadata = _extract_ogg_metadata(filepath)
    else:
        # Unsupported format - return basic info
        return SongMetadata(
            title=filename,
            artist="Unknown Artist",
            album="Unknown Album",
            duration=0.0,
            album_art=None
        )

    # Apply fallbacks for missing fields
    if not metadata.title or not metadata.title.strip():
        metadata.title = filename
    if not metadata.artist or not metadata.artist.strip():
        metadata.artist = "Unknown Artist"
    if not metadata.album or not metadata.album.strip():
        metadata.album = "Unknown Album"

    return metadata


def _extract_mp3_metadata(filepath: str) -> SongMetadata:
    """Extract metadata from MP3 file using ID3 tags."""
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, APIC

        audio = MP3(filepath)

        title = ""
        artist = ""
        album = ""
        album_art = None
        duration = audio.info.length if audio.info else 0.0

        # Try to get ID3 tags
        try:
            tags = ID3(filepath)
            title = str(tags.get('TIT2', [''])[0]) if tags.get('TIT2') else ""
            artist = str(tags.get('TPE1', [''])[0]) if tags.get('TPE1') else ""
            album = str(tags.get('TALB', [''])[0]) if tags.get('TALB') else ""

            # Extract album art
            for tag in tags.values():
                if isinstance(tag, APIC):
                    album_art = tag.data
                    break
        except Exception:
            pass

        return SongMetadata(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            album_art=album_art
        )
    except Exception as e:
        return SongMetadata(
            title=Path(filepath).stem,
            artist="Unknown Artist",
            album="Unknown Album",
            duration=0.0,
            album_art=None
        )


def _extract_flac_metadata(filepath: str) -> SongMetadata:
    """Extract metadata from FLAC file."""
    try:
        from mutagen.flac import FLAC

        audio = FLAC(filepath)

        title = audio.get('title', [''])[0] if audio.get('title') else ""
        artist = audio.get('artist', [''])[0] if audio.get('artist') else ""
        album = audio.get('album', [''])[0] if audio.get('album') else ""
        duration = audio.info.length if audio.info else 0.0

        # Extract album art
        album_art = None
        if audio.pictures:
            album_art = audio.pictures[0].data

        return SongMetadata(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            album_art=album_art
        )
    except Exception as e:
        return SongMetadata(
            title=Path(filepath).stem,
            artist="Unknown Artist",
            album="Unknown Album",
            duration=0.0,
            album_art=None
        )


def _extract_m4a_metadata(filepath: str) -> SongMetadata:
    """Extract metadata from M4A/MP4 file."""
    try:
        from mutagen.mp4 import MP4

        audio = MP4(filepath)

        title = ""
        artist = ""
        album = ""
        album_art = None
        duration = audio.info.length if audio.info else 0.0

        # MP4 tags use different keys
        # \xa9nam = title, \xa9ART = artist, \xa9alb = album
        if '\xa9nam' in audio:
            title = str(audio['\xa9nam'][0])
        if '\xa9ART' in audio:
            artist = str(audio['\xa9ART'][0])
        if '\xa9alb' in audio:
            album = str(audio['\xa9alb'][0])

        # Album art is stored in covr tag
        if 'covr' in audio and audio['covr']:
            album_art = bytes(audio['covr'][0])

        return SongMetadata(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            album_art=album_art
        )
    except Exception as e:
        return SongMetadata(
            title=Path(filepath).stem,
            artist="Unknown Artist",
            album="Unknown Album",
            duration=0.0,
            album_art=None
        )


def _extract_ogg_metadata(filepath: str) -> SongMetadata:
    """Extract metadata from OGG Vorbis file."""
    try:
        from mutagen.oggvorbis import OggVorbis

        audio = OggVorbis(filepath)

        title = audio.get('title', [''])[0] if audio.get('title') else ""
        artist = audio.get('artist', [''])[0] if audio.get('artist') else ""
        album = audio.get('album', [''])[0] if audio.get('album') else ""
        duration = audio.info.length if audio.info else 0.0

        # Extract album art from metadata block picture
        album_art = None
        if 'metadata_block_picture' in audio:
            try:
                import base64
                from mutagen.flac import Picture

                pic_data = base64.b64decode(audio['metadata_block_picture'][0])
                picture = Picture(pic_data)
                album_art = picture.data
            except Exception:
                pass

        return SongMetadata(
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            album_art=album_art
        )
    except Exception as e:
        return SongMetadata(
            title=Path(filepath).stem,
            artist="Unknown Artist",
            album="Unknown Album",
            duration=0.0,
            album_art=None
        )
