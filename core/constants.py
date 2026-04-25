#!/usr/bin/env python3
"""
PyPlayer Constants Module
Defines default values for appearance and other settings
"""


class AppearanceDefaults:
    """Default transparency values for UI components.

    All transparency values use 0.0-1.0 scale for consistency.
    """

    # Background overlay transparency (white overlay on background image)
    # Originally hardcoded as alpha=120 in main_window.py:338
    # Converted: 120/255 = 0.47
    BACKGROUND_OVERLAY_ALPHA = 0.47

    # Playlist background transparency
    # Originally: rgba(250, 250, 250, 0.75) in playlist_view.py:79
    PLAYLIST_BG_ALPHA = 0.75

    # Playlist selected item transparency
    # Originally: rgba(227, 242, 253, 0.85) in playlist_view.py:88
    PLAYLIST_SELECTED_ALPHA = 0.85

    # Playlist hover transparency
    # Originally: rgba(245, 245, 245, 0.85) in playlist_view.py:92
    PLAYLIST_HOVER_ALPHA = 0.85

    # Bottom panel background transparency
    # Originally: rgba(245, 245, 245, 0.85) in bottom_panel.py:99
    BOTTOM_PANEL_BG_ALPHA = 0.85

    # Bottom panel button transparency
    # Originally: rgba(255, 255, 255, 0.7) in bottom_panel.py:102
    BOTTOM_PANEL_BUTTON_ALPHA = 0.7

    # Slider range for transparency settings (percentage)
    SLIDER_MIN = 0
    SLIDER_MAX = 100
