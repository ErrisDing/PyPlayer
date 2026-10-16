#!/usr/bin/env python3
"""Dead code removal guards for Task 2.

Pins these claims so a later restyle task cannot accidentally re-introduce
them:
  1. the zombie widgets superseded by BottomPanel are gone;
  2. the unreachable signal chains are gone, including the background chain
     MainWindow.background_image_changed -> MainPresenter
     ._on_background_image_changed (its only emitters were deleted here);
  3. ``view.models.DisplayEntry`` is the service DTO, not a copy of it;
  4. the background route that IS alive still works end to end:
     AppearanceDialog.background_image_changed (a different signal with the
     same *name*) -> MainPresenter._handle_background_change -> MainWindow.

``context_menu_requested`` is the batch-3 right-click interface: it is declared
but never emitted on purpose, so it must survive this cleanup.

The dead-code asserts are pure Python; the path test needs a QApplication,
hence the skipUnless guard on both classes.

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

    def test_background_dead_chain_is_gone(self):
        """MainWindow.background_image_changed lost its only emitters in Task 2.

        ``_on_set_background`` / ``_on_clear_background`` were deleted (no menu
        ever wired them), so the signal can no longer fire: the declaration,
        the presenter connection and ``_on_background_image_changed`` are all
        dead. Background images are set through AppearanceDialog, which owns a
        separate signal of the same name -- that one must keep working.
        """
        from view.main_window import MainWindow
        from presenter.main_presenter import MainPresenter

        for owner, name in (
            (MainWindow, 'background_image_changed'),
            (MainPresenter, '_on_background_image_changed'),
        ):
            with self.subTest(dead=f'{owner.__name__}.{name}'):
                self.assertIs(
                    hasattr(owner, name), False,
                    f'{owner.__name__}.{name} is still declared',
                )

    def test_dialog_background_signal_survives(self):
        """The live half of the name collision must not be deleted with the dead half."""
        from view.dialogs.appearance_dialog import AppearanceDialog
        from presenter.main_presenter import MainPresenter

        self.assertTrue(
            hasattr(AppearanceDialog, 'background_image_changed'),
            'AppearanceDialog.background_image_changed is the live signal',
        )
        self.assertTrue(
            hasattr(MainPresenter, '_handle_background_change'),
            'MainPresenter._handle_background_change serves the dialog signal',
        )

    def test_context_menu_signal_survives(self):
        """Batch 3 owns context_menu_requested; it must not be deleted here."""
        from view.widgets.playlist_view import PlaylistView

        self.assertTrue(
            hasattr(PlaylistView, 'context_menu_requested'),
            'PlaylistView.context_menu_requested must survive dead-code cleanup',
        )


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class AppearanceBackgroundPathTest(unittest.TestCase):
    """End-to-end guard for the only live background route.

    Real MainWindow + real MainPresenter + real AppearanceDialog; only the file
    chooser and the modal exec() are stubbed. Services are mocks, so no config
    file and no audio device are touched.
    """

    def setUp(self):
        import tempfile
        from unittest.mock import MagicMock

        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtWidgets import QApplication

        from view.main_window import MainWindow
        from presenter.main_presenter import MainPresenter

        self._keep_app = QApplication.instance() or QApplication([])

        self._tmp = tempfile.TemporaryDirectory()
        self.bg_path = str(Path(self._tmp.name) / 'background.png')
        seed = QPixmap(32, 32)
        seed.fill(Qt.GlobalColor.darkGreen)
        self.assertTrue(seed.save(self.bg_path, 'PNG'), 'test fixture PNG failed to write')

        self.view = MainWindow()

        self.playback = MagicMock(name='playback_service')
        self.playback.get_volume.return_value = 0.5
        self.config = MagicMock(name='config_service')
        self.config.get_libraries.return_value = []
        self.config.get_background_image.return_value = None
        self.config.get_overlay_alpha.return_value = 0.3
        self.config.get_playlist_alpha.return_value = 0.5
        self.config.get_controls_alpha.return_value = 0.6
        self.config.set_background_image.return_value = True

        # MainPresenter.__init__ connects to the real view and runs _load_config().
        self.presenter = MainPresenter(
            view=self.view,
            playback_service=self.playback,
            queue_service=MagicMock(name='queue_service'),
            library_service=MagicMock(name='library_service'),
            metadata_service=MagicMock(name='metadata_service'),
            config_service=self.config,
        )

    def tearDown(self):
        self.view.close()
        self._tmp.cleanup()

    def _open_dialog(self, *actions):
        """Open the appearance dialog the way the menu does, then apply actions."""
        from unittest.mock import patch

        from PyQt6.QtWidgets import QFileDialog
        from view.dialogs.appearance_dialog import AppearanceDialog

        def fake_exec(dialog):
            for action in actions:
                action(dialog)
            return AppearanceDialog.DialogCode.Accepted

        with patch.object(QFileDialog, 'getOpenFileName', return_value=(self.bg_path, '')), \
                patch.object(AppearanceDialog, 'exec', fake_exec):
            self.presenter._on_manage_appearance()

    def test_dialog_select_background_reaches_view(self):
        """Select button -> dialog signal -> presenter -> config + view paint."""
        self.assertIsNone(self.view._background_pixmap)

        self._open_dialog(lambda dialog: dialog._select_bg_btn.click())

        self.assertIsNotNone(
            self.view._background_pixmap,
            'appearance dialog no longer reaches MainWindow.set_background_image',
        )
        self.assertFalse(self.view._background_pixmap.isNull())
        self.config.set_background_image.assert_called_once_with(self.bg_path)
        self.assertNotEqual(
            self.view.windowTitle(), self.view._base_title,
            'presenter did not report the background change on the view',
        )

    def test_dialog_clear_background_reaches_view(self):
        """Clear button emits an empty path; presenter must reset to no image."""
        self.view.set_background_image(self.bg_path)
        self.assertIsNotNone(self.view._background_pixmap)

        self._open_dialog(lambda dialog: dialog._clear_bg_btn.click())

        self.assertIsNone(
            self.view._background_pixmap,
            'appearance dialog clear no longer reaches MainWindow.set_background_image',
        )
        self.config.set_background_image.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
