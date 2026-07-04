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

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def main_qt():
    """Launch the PyQt-based GUI."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPalette, QColor

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create application
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Set base font for consistent cross-platform readability
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)

    # macOS-specific setup
    if sys.platform == "darwin":
        # Show proper app name in macOS menu bar (avoid "python")
        app.setApplicationName("PyPlayer")

        # Detect and apply dark mode palette
        if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 45))
            dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
            dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
            dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 60))
            dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.ColorRole.Button, QColor(55, 55, 55))
            dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
            dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
            dark_palette.setColor(QPalette.ColorRole.Link, QColor(100, 180, 255))
            dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(80, 140, 220))
            dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            app.setPalette(dark_palette)

    # Load global stylesheet
    from core.resource_utils import get_resource_path
    qss_path = get_resource_path("view/resources/styles.qss")
    if qss_path.exists():
        try:
            with open(qss_path, 'r', encoding='utf-8') as f:
                qss_content = f.read()

            # On macOS, ensure native window chrome areas don't get covered
            if sys.platform == "darwin":
                qss_content += """
                /* macOS-specific: let native title bar show through */
                QMenuBar {
                    background-color: transparent;
                }
                """

            app.setStyleSheet(qss_content)
        except (OSError, IOError) as e:
            print(f"Warning: Failed to load styles.qss: {e}")

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

    # Create view
    view = MainWindow()

    # Create presenter (wiring everything together)
    presenter = MainPresenter(
        view=view,
        playback_service=playback_service,
        queue_service=queue_service,
        library_service=library_service,
        metadata_service=metadata_service,
        config_service=config_service
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
