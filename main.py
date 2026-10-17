#!/usr/bin/env python3
"""
PyPlayer - PyQt-based Music Player
Main entry point for the application

Usage:
    python main.py              # Launch GUI
    python main.py --tui        # Launch terminal UI
    python main.py file.mp3     # Play file in CLI mode
"""

import sys
from pathlib import Path
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def build_theme_manager(app, config_service, mode: Optional[str] = None):
    """Create the theme manager and install it on ``app``.

    The only stylesheet/palette source of the GUI: the old ``styles.qss`` file
    and the darwin-only dark palette this function replaced are both gone, so
    a theme is ``resolve(mode, system_scheme)`` -> tokens -> palette + QSS.

    The mode comes from ``config_service.get_theme()`` unless a caller overrides
    it, which is what makes the fallback below a live path: the value was written
    by hand as much as by the app. ``core.theme.resolve`` deliberately raises
    ``ValueError`` on an unrecognised value so a typo'd preference can never
    silently render the wrong theme; left alone that would take the whole app
    down at startup on a ``settings.json`` edited to ``"theme": "Auto"`` (the
    resolver is case-sensitive) or ``"theme": "neon"``. So the seam catches it,
    prints one line and falls back to ``'auto'``.

    ``core.config`` normalises the same value on read, which is why a bad mode
    reaching here is the second line of defence rather than the only one: it
    happens when a caller hands over something that never went through the
    loader.

    Args:
        app: The running ``QApplication`` (must already have its style set).
        config_service: Source of the theme mode and the three transparency
            settings.
        mode: ``'auto'``, ``'light'`` or ``'dark'``; ``None`` (the startup
            default) reads it from ``config_service``.
    """
    from core.theme import AlphaSettings
    from view.theme_manager import ThemeManager

    if mode is None:
        mode = config_service.get_theme()

    alphas = AlphaSettings(
        overlay=config_service.get_overlay_alpha(),
        playlist=config_service.get_playlist_alpha(),
        controls=config_service.get_controls_alpha(),
    )

    try:
        manager = ThemeManager(mode=mode, alphas=alphas)
        manager.apply_to(app)
    except ValueError as exc:
        print(f"Warning: {exc}; falling back to theme mode 'auto'")
        manager = ThemeManager(mode="auto", alphas=alphas)
        manager.apply_to(app)

    return manager


def connect_theme_signal(config_service, theme_manager) -> None:
    """Subscribe ``theme_manager`` to the mode the config service persists.

    ``main_qt`` calls this once, right after the manager is built, and it is the
    only place a running theme is applied:

        dialog -> presenter -> ConfigService.set_theme -> theme_changed(str)
                                                      -> ThemeManager.set_mode

    Doing the apply here rather than in the presenter slot is what keeps it a
    single apply -- a second path from the presenter would restyle twice, and
    the service signal would go back to being a wire nobody listens on.

    The value on the wire is always resolvable, so the slot can be the bare
    method and cannot raise: ``ConfigService.set_theme`` emits only after
    ``SettingsManager.set_theme`` accepted a member of
    ``core.config.THEME_MODES``, and that set is exactly the one
    :func:`core.theme.resolve` renders.

    Kept out of :func:`build_theme_manager` on purpose: that helper is also
    called with a stand-in config (see ``StartupSeamTest``), and the theme layer
    must not have to know about the service layer.

    Args:
        config_service: The ``ConfigService`` that owns the ``theme`` setting.
        theme_manager: The manager built from that same service.
    """
    config_service.theme_changed.connect(theme_manager.set_mode)


def main_qt():
    """Launch the PyQt-based GUI."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create application
    app = QApplication(sys.argv)
    # The style is Fusion for every platform, and it is set before the theme
    # manager pushes its palette + sheet, because both are read at polish time.
    app.setStyle("Fusion")

    # Set base font for consistent cross-platform readability
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)

    # macOS-specific setup
    if sys.platform == "darwin":
        # Show proper app name in macOS menu bar (avoid "python")
        app.setApplicationName("PyPlayer")

    # Import and create MVP components
    from view.main_window import MainWindow
    from service.playback_service import PlaybackService
    from service.queue_service import QueueService
    from service.library_service import LibraryService
    from service.metadata_service import MetadataService
    from service.config_service import ConfigService
    from presenter.main_presenter import MainPresenter

    # Create services
    playback_service = PlaybackService()
    queue_service = QueueService()
    library_service = LibraryService()
    metadata_service = MetadataService()
    config_service = ConfigService()

    # Single styling source: palette + generated sheet, before any widget is
    # constructed so the first polish already sees the theme. The mode is the
    # persisted one -- Task 6 left a literal here, which made the ValueError
    # fallback inside the helper unreachable and meant a chosen theme never
    # survived a restart.
    theme_manager = build_theme_manager(app, config_service)

    # The one direction a mode travels: the service persists and announces it,
    # the theme layer answers. Connected here, once, so no other component can
    # apply the same click a second time.
    connect_theme_signal(config_service, theme_manager)

    # Create view
    view = MainWindow(theme_manager)

    # Create presenter (wiring everything together)
    presenter = MainPresenter(
        view=view,
        playback_service=playback_service,
        queue_service=queue_service,
        library_service=library_service,
        metadata_service=metadata_service,
        config_service=config_service,
        theme_manager=theme_manager
    )

    # Start presenter
    presenter.start()

    # Show window
    view.show()

    # Run event loop
    result = app.exec()

    # Cleanup
    presenter.stop()

    return result


def main_tui():
    """Launch terminal UI."""
    try:
        from tui.tui import main as tui_main
        import curses
        curses.wrapper(tui_main)
    except ImportError:
        print("TUI module not found. Please ensure tui/tui.py exists.")
        return 1
    return 0


def main_cli(filepath: str):
    """Play file in CLI mode."""
    from core.player import create_manager
    import time

    player = create_manager()
    result = player.play(filepath)

    if not result:
        print(f"Failed to play: {filepath}")
        return 1

    print(f"Playing: {filepath}")
    print("Press Ctrl+C to stop")

    try:
        while True:
            status = player.get_status()
            if not status['audio_playing']:
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        player.stop()
        print("\nStopped.")

    return 0


def print_help():
    """Print help message."""
    print("""
PyPlayer - A Python Music Player

Usage:
    python main.py              Launch PyQt GUI (default)
    python main.py --qt         Launch PyQt GUI
    python main.py --tui        Launch terminal UI
    python main.py <file>       Play file in CLI mode
    python main.py --help       Show this help message

Supported formats:
    Audio: MP3, WAV, FLAC, OGG, M4A, AAC
    Video: AVI, MP4, MKV, MOV, WMV
""")


def main():
    """Main entry point."""
    args = sys.argv[1:]

    if not args:
        # Default: launch PyQt GUI
        return main_qt()

    # Parse arguments
    if args[0] in ('--help', '-h'):
        print_help()
        return 0

    if args[0] == '--qt':
        return main_qt()

    if args[0] == '--tui':
        return main_tui()

    # Assume it's a file path
    filepath = args[0]
    if Path(filepath).exists():
        return main_cli(filepath)
    else:
        print(f"File not found: {filepath}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
