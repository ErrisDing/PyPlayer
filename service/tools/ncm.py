#!/usr/bin/env python3
"""
NCM Metadata Extractor - Extracts metadata from NCM files via proxy

NCM is NetEase Cloud Music's encrypted format. This extractor:
1. Gets or creates a proxy file (MP3/FLAC) via NCMProxyManager
2. Delegates metadata extraction to the appropriate format extractor
"""

import os
from pathlib import Path
from typing import Optional

from .base import MetadataExtractor, ExtractionResult


class NCMExtractor(MetadataExtractor):
    """Metadata extractor for NCM encrypted audio files."""

    extensions = ['.ncm']

    # Library path for proxy creation - must be set before extraction
    # This is a class variable that can be set externally
    _current_library_path: Optional[str] = None

    @classmethod
    def set_library_path(cls, library_path: str) -> None:
        """
        Set the library path for proxy file creation.

        This should be called before extract() if the NCM file
        needs to be decrypted.

        Args:
            library_path: Path to the library containing the NCM file
        """
        cls._current_library_path = library_path

    @classmethod
    def extract(cls, filepath: str) -> ExtractionResult:
        """
        Extract metadata from an NCM file via its proxy.

        Args:
            filepath: Path to the NCM file

        Returns:
            ExtractionResult with metadata from the proxy file
        """
        from . import get_extractor

        result = ExtractionResult()

        # Check if file exists
        if not os.path.exists(filepath):
            result.success = False
            result.errors.append(f"File not found: {filepath}")
            return result

        # Get proxy file path
        proxy_path = cls._get_proxy_path(filepath)

        if proxy_path is None:
            result.success = False
            result.errors.append(
                f"Could not create proxy for NCM file: {filepath}. "
                f"Ensure library path is set and ncmdump is available."
            )
            return result

        # Get the appropriate extractor for the proxy file
        proxy_extractor = get_extractor(proxy_path)

        if proxy_extractor is None:
            result.success = False
            proxy_ext = Path(proxy_path).suffix.lower()
            result.errors.append(f"Unsupported proxy format: {proxy_ext}")
            return result

        # Delegate extraction to the proxy's extractor
        result = proxy_extractor.extract(proxy_path)

        # Add diagnostic info about NCM origin
        result.diagnostics['ncm_original_path'] = filepath
        result.diagnostics['ncm_proxy_path'] = proxy_path

        return result

    @classmethod
    def _get_proxy_path(cls, ncm_path: str) -> Optional[str]:
        """
        Get the proxy file path for an NCM file.

        Args:
            ncm_path: Path to the NCM file

        Returns:
            Path to the proxy file, or None if unavailable
        """
        # Try to use the global NCMProxyManager
        try:
            from core.ncm_proxy import get_ncm_proxy_manager

            proxy_manager = get_ncm_proxy_manager()

            # Check if we have a library path set
            if cls._current_library_path:
                return proxy_manager.get_proxy_file(ncm_path, cls._current_library_path)
            else:
                # Try to find existing proxy without creating new one
                # This is useful for cases where the proxy already exists
                # but we don't have library context
                return cls._find_existing_proxy_anywhere(ncm_path, proxy_manager)

        except ImportError:
            return None

    @classmethod
    def _find_existing_proxy_anywhere(cls, ncm_path: str, proxy_manager) -> Optional[str]:
        """
        Try to find an existing proxy file in any library directory.

        Args:
            ncm_path: Path to the NCM file
            proxy_manager: NCMProxyManager instance

        Returns:
            Path to existing proxy file, or None if not found
        """
        import os

        proxy_root = proxy_manager.proxy_root
        if not os.path.exists(proxy_root):
            return None

        stem = Path(ncm_path).stem

        # Search all library directories
        for library_name in os.listdir(proxy_root):
            library_dir = os.path.join(proxy_root, library_name)
            if not os.path.isdir(library_dir):
                continue

            for ext in ['.mp3', '.flac']:
                proxy_path = os.path.join(library_dir, stem + ext)
                if os.path.exists(proxy_path):
                    return proxy_path

        return None
