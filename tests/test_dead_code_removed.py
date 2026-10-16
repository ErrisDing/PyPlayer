#!/usr/bin/env python3
"""Dead code removal guards for Task 2.

Pins three claims so a later restyle task cannot accidentally re-introduce
them:
  1. the zombie widgets superseded by BottomPanel are gone;
  2. the unreachable signal chains are gone;
  3. ``view.models.DisplayEntry`` is the service DTO, not a copy of it.

``context_menu_requested`` is the batch-3 right-click interface: it is declared
but never emitted on purpose, so it must survive this cleanup.

Pure Python assertions, but importing ``view`` pulls PyQt6 QtCore/QtWidgets,
hence the skipUnless guard.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_dead_code_removed -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import PyQt6.QtCore  # noqa: F401  (importing view.models needs QtCore)
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class DeadCodeRemovedTest(unittest.TestCase):
    """Zombie widgets, unreachable signals and the duplicated DTO are gone."""

    def test_display_entry_is_single_type(self):
        """view.models must re-export the service DTO, not redefine it."""
        from view.models import DisplayEntry as ViewEntry
        from service.queue_service import DisplayEntry as QueueEntry

        self.assertIs(
            ViewEntry, QueueEntry,
            'view.models.DisplayEntry duplicates service.queue_service.DisplayEntry',
        )

    def test_dead_widgets_are_gone(self):
        """BottomPanel replaced these; nothing else imports them."""
        for module in ('view.widgets.control_panel', 'view.widgets.progress_slider'):
            with self.subTest(module=module):
                self.assertIsNone(
                    importlib.util.find_spec(module),
                    f'{module} is still importable',
                )

    def test_dead_signals_are_gone(self):
        """Each of these had no reachable emitter or no listener."""
        from view.main_window import MainWindow
        from view.widgets.playlist_view import PlaylistView

        for owner, name in (
            # MainWindow._on_add_library was never wired to any action, so the
            # emit - and therefore the presenter connection - was unreachable.
            (MainWindow, 'add_library_requested'),
            # never emitted by MainWindow (only LibraryManagementDialog has one)
            (MainWindow, 'remove_library_requested'),
            # emitted on click but no presenter/view ever connected to it
            (PlaylistView, 'track_selected'),
        ):
            with self.subTest(signal=f'{owner.__name__}.{name}'):
                self.assertIs(
                    hasattr(owner, name), False,
                    f'{owner.__name__}.{name} is still declared',
                )

    def test_context_menu_signal_survives(self):
        """Batch 3 owns context_menu_requested; it must not be deleted here."""
        from view.widgets.playlist_view import PlaylistView

        self.assertTrue(
            hasattr(PlaylistView, 'context_menu_requested'),
            'PlaylistView.context_menu_requested must survive dead-code cleanup',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
