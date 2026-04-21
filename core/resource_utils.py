#!/usr/bin/env python3
"""
Resource path utilities for PyInstaller compatibility.
Handles path resolution for both development and bundled execution.
"""

import sys
from pathlib import Path


def get_base_path() -> Path:
    """
    Get the base path for resource files.

    Returns:
        Path to project root in development, or PyInstaller temp dir when bundled.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys._MEIPASS)
    else:
        # Running in development
        return Path(__file__).parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to a resource file.

    Args:
        relative_path: Path relative to project root (e.g., 'resource/default_cover.png')

    Returns:
        Absolute path to the resource
    """
    return get_base_path() / relative_path


def get_locales_path() -> Path:
    """Get path to locales directory."""
    return get_base_path() / 'locales'


def get_resource_file(filename: str) -> Path:
    """Get path to a file in the resource directory."""
    return get_resource_path(f'resource/{filename}')
