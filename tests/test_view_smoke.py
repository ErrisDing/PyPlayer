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


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ViewSmokeTest(unittest.TestCase):
    """MainWindow must construct and paint without raising."""

    def test_main_window_constructs_and_paints(self):
        from view.main_window import MainWindow

        app = make_app()

        w = MainWindow()
        w.resize(900, 600)
        w.show()
        app.processEvents()

        pm = w.grab()
        self.assertFalse(pm.isNull(), 'MainWindow paint returned a null pixmap')
        self.assertGreater(pm.width(), 0, 'MainWindow paint returned an empty pixmap')

        w.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
