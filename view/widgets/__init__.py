#!/usr/bin/env python3
"""
PyPlayer View Widgets
Custom UI widgets for the player interface
"""

from .playlist_view import PlaylistView
from .bottom_panel import BottomPanel
from .action_rail import ActionRail
from .library_sidebar import LibrarySidebar
from .now_playing_strip import NowPlayingStrip
from .toast import Toast
# Batch 3 Task 2: the right-click menu is a pure builder, not a widget, so its
# ids and its one function are what the package exports (the menu ids are the
# vocabulary Task 3 dispatches on).
from .playlist_context_menu import (
    MENU_PLAY, MENU_REMOVE, MENU_CLEAR, MENU_IDS, build_playlist_menu
)

__all__ = [
    'PlaylistView',
    'BottomPanel',
    'ActionRail',
    'LibrarySidebar',
    'NowPlayingStrip',
    'Toast',
    'MENU_PLAY',
    'MENU_REMOVE',
    'MENU_CLEAR',
    'MENU_IDS',
    'build_playlist_menu',
]
