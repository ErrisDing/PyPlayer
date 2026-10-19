#!/usr/bin/env python3
"""View layer smoke tests.

Constructs the real widgets offscreen and paints them, so that import-time
mistakes in the view layer (missing symbols, typo'd classes) fail loudly
instead of crashing the app at startup.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_view_smoke -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PyQt6.QtWidgets import QApplication
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False


def make_app():
    """Return the running QApplication, creating one if needed."""
    return QApplication.instance() or QApplication([])


def make_manager(mode: str = 'light'):
    """A theme manager for tests that only need *a* theme, resolved now.

    ``MainWindow`` takes a mandatory ``ThemeManager`` since Task 6 (it is the
    only styling source), so every harness that builds the window has to build
    the manager first. ``light`` is the default because that is what ``auto``
    resolves to on the offscreen platform anyway, and a test should not depend
    on the platform's colour scheme.
    """
    from view.theme_manager import ThemeManager

    return ThemeManager(mode=mode)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ViewSmokeTest(unittest.TestCase):
    """MainWindow must construct and paint without raising."""

    def test_main_window_constructs_and_paints(self):
        from view.main_window import MainWindow

        app = make_app()

        w = MainWindow(make_manager())
        w.resize(900, 600)
        w.show()
        app.processEvents()

        pm = w.grab()
        self.assertFalse(pm.isNull(), 'MainWindow paint returned a null pixmap')
        self.assertGreater(pm.width(), 0, 'MainWindow paint returned an empty pixmap')

        w.close()

    def test_empty_app_launches(self):
        """First launch, spec §6: nothing configured, zero libraries, zero entries.

        The shell built in Task 7 adds three always-present overlays (rail,
        floating panel, toast) and the strip row, and every one of them must
        survive construction and paint with no data fed through any public
        ``set_*``/``update_*`` call -- an empty player is the first screen a
        fresh install shows, not an error path.
        """
        from view.main_window import MainWindow

        app = make_app()

        w = MainWindow(make_manager())
        try:
            w.show()
            app.processEvents()

            self.assertFalse(w.is_library_panel_open(),
                             'the floating panel starts closed, never pre-shown')
            pm = w.grab()
            self.assertFalse(pm.isNull(), 'the empty shell painted nothing')
            self.assertGreater(pm.width(), 0)
        finally:
            w.close()
            w.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
