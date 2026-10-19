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
# The right-click menu is deliberately **not** re-exported here. Batch 3 Task 2 put
# its ids and its builder on the package, but every consumer reaches the module by
# name -- ``view/widgets/playlist_view.py``, ``tests/test_playlist_context_menu.py``,
# ``tests/test_playlist_selection.py`` and ``tests/tools/render_matrix.py`` all import
# ``view.widgets.playlist_context_menu`` -- so the five extra names only ever widened
# the package surface, and a second spelling of one import path is how a re-export
# goes stale unnoticed. The package exports widgets; the builder stays where it lives.

__all__ = [
    'PlaylistView',
    'BottomPanel',
    'ActionRail',
    'LibrarySidebar',
    'NowPlayingStrip',
    'Toast',
]
