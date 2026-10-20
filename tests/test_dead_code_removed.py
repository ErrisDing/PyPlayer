#!/usr/bin/env python3
"""Dead code removal guards for Task 2 and Task 9.

Pins these claims so a later restyle task cannot accidentally re-introduce
them:
  1. the zombie widgets superseded by BottomPanel are gone;
  2. the unreachable signal chains are gone, including the background chain
     MainWindow.background_image_changed -> MainPresenter
     ._on_background_image_changed (its only emitters were deleted here);
  3. ``view.models.DisplayEntry`` is the service DTO, not a copy of it;
  4. the background route that IS alive still works end to end:
     MainWindow.manage_appearance_requested (emitted in production by the
     **ActionRail**: ``MainWindow._on_rail_action`` maps ``ACTION_APPEARANCE`` to it;
     the File menu that used to be the emitter is gone, deleted by batch 2) ->
     MainPresenter._on_manage_appearance -> AppearanceDialog.background_image_changed
     (a different signal with the same *name* as the dead MainWindow one) ->
     MainPresenter._handle_background_change -> MainWindow.
     Whole-branch review finding 5 moved the first half of that chain into the
     test: the signal is the only way a user can reach the appearance/theme dialog,
     and calling the presenter's slot straight from the helper skipped the action
     connection and the presenter's ``connect``, so the live route could be deleted
     with this file still green.
  5. batch 2 Task 9: the left panel and the library chip row are deleted, *and* no
     ``*.py`` in the repo still names either class -- comments and docstrings
     included, because a prose pointer at a file that no longer exists is the same
     stale claim one layer further down.
  6. batch 3's final wave: ``PlaylistView.get_current_selection``, ``set_selection``
     and ``scroll_to_playing``, ``MainWindow``'s three stored transport ``QAction``
     attributes with their unused object names, and the five
     ``playlist_context_menu`` names the package re-exported without a consumer, are
     gone. Each had zero callers in production *and* in tests. The reason
     ``get_current_selection`` went is not "a getter nobody used": it read
     ``selectedIndexes()[0]``, whose order Qt leaves unspecified and which Task 1
     measured as **click order** on this host, so it did not even equal
     ``selected_display_indices()[0]`` for a Ctrl-clicked batch -- order-dependent
     semantics wearing a name that promises a row. Re-introducing either that method
     or an untested ``selectedIndexes()`` read re-opens the defect.

``context_menu_requested`` is batch 3's right-click observation hook. The reason it
gives is no longer batch 1's: it is **emitted** (``PlaylistView.contextMenuEvent``
since Task 3) and has **no production slot**, deliberately -- it is the automated
witness that a right-click routed through the handler at all, and its two listeners
are ``tests/test_playlist_selection.py`` and ``tests/tools/render_matrix.py``. It
must survive this cleanup for that reason, not because it is un-emitted.

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
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The two widgets batch 2 Task 9 deletes, and the names they must vanish from.
SUPERSEDED_PANEL_MODULES = (
    'view.widgets.now_playing_panel',
    'view.widgets.library_selector',
)

# Built from parts, deliberately: a scan for a name has to be able to say the name
# without containing it, or the test file becomes the one place the deleted class
# may still be mentioned -- and mentions are exactly what this census forbids.
SUPERSEDED_PANEL_CLASSES = ('NowPlaying' + 'Panel', 'Library' + 'Selector')

#: Directories with no source under them: a virtualenv (it ships PyQt6 stubs and
#: third-party code that mention nothing here), the object store, and the build
#: output a frozen copy leaves behind.
SKIP_SCAN_PARTS = frozenset({'.git', '.venv', '__pycache__', 'build', 'dist'})

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

    def test_superseded_panels_are_gone(self):
        """Batch 2 Task 9: the left panel and the chip row are gone, not unused.

        :data:`SUPERSEDED_PANEL_CLASSES` are the two widget classes those files
        exported. The cover and its two text lines moved to the control bar's
        strip; the chip row -- which overflowed at three libraries, exactly audit
        item B3 -- moved to the floating sidebar. Task 7 took both out of the
        widget tree, and leaving the files behind is what made them rot: they
        still wore the five object names whose rules this task deletes, and a
        reader cannot tell dead paint from live.
        """
        for module in SUPERSEDED_PANEL_MODULES:
            with self.subTest(module=module):
                self.assertIsNone(
                    importlib.util.find_spec(module),
                    f'{module} is still importable',
                )

        import view.widgets as widgets

        for class_name in SUPERSEDED_PANEL_CLASSES:
            with self.subTest(package_class=class_name):
                self.assertIs(
                    hasattr(widgets, class_name), False,
                    f'view.widgets still re-exports {class_name}',
                )
        self.assertEqual([], [
            name for name in getattr(widgets, '__all__', ())
            if name in SUPERSEDED_PANEL_CLASSES],
            'the export list still advertises a deleted panel')

    def test_no_reference_to_superseded_panels(self):
        """No ``*.py`` in the repo may name either class -- comments and tests too.

        A prose mention of a deleted widget is a pointer a later reader cannot
        follow: Task 7's shell, ``tests/test_theme_qss.py``'s transparency pin and
        two batch-1 docstrings all described behaviour through these two names, and
        every one of them went stale when the files did. The scan therefore covers
        comments and docstrings, not just code, and covers this file: the two names
        are assembled from parts above so the census itself is not an exception.
        """
        hits = []
        for source in ROOT.rglob('*.py'):
            if SKIP_SCAN_PARTS & set(source.parts):
                continue
            text = source.read_text(encoding='utf-8', errors='replace')
            for needle in SUPERSEDED_PANEL_CLASSES:
                for number, line in enumerate(text.splitlines(), 1):
                    if needle in line:
                        hits.append(f'{source.relative_to(ROOT)}:{number}')
        self.assertEqual(
            [], hits,
            f'these files still name a class deleted in Task 9: {hits}',
        )

    def test_dead_signals_are_gone(self):
        """Each of these had no reachable emitter or no listener."""
        from view.main_window import MainWindow
        from view.widgets.playlist_view import PlaylistView

        for owner, name in (
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

        # ``MainWindow.add_library_requested`` was on this list while its only
        # emitter (the never-wired ``_on_add_library`` slot) was gone. Task 7's
        # shell revived it with a live producer: the floating panel's footer
        # add entry, pinned by
        # ``tests/test_view_structure.py::test_sidebar_add_reaches_the_window_exactly_once``.
        # A revived signal belongs to the surviving side of this file, not here.
        self.assertTrue(hasattr(MainWindow, 'add_library_requested'))

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

    def test_batch3_dead_view_surface_stays_gone(self):
        """The final wave's deletions, pinned the way this file pins everything else.

        Batch 3 shipped four pieces of surface with zero callers in production *and*
        in tests: two selection methods on ``PlaylistView``, one scroll method, three
        stored ``QAction`` attributes plus three object names on ``MainWindow``, and
        five ``playlist_context_menu`` names the package re-exported while every
        consumer imported the module directly. ``get_current_selection`` in particular
        is not a harmless getter -- see the module docstring, item 6.

        Assembled from parts, for the same reason ``SUPERSEDED_PANEL_CLASSES`` is: a
        scan for a name must not contain it, or this file becomes the only place the
        deleted names survive. The second half of the test is what stops the scan
        being satisfied by a widget that lost more than it was supposed to.
        """
        import view.widgets as widgets
        from view.widgets.playlist_view import PlaylistView
        from view.main_window import MainWindow

        removed = {
            'selection getter': 'get_current_' + 'selection',
            'selection setter': 'set_' + 'selection',
            'scroll helper': 'scroll_to_' + 'playing',
            'stored transport action': 'self._play_pause_' + 'shortcut',
            'object name 1': 'shortcut' + 'PlayPause',
            'object name 2': 'shortcut' + 'Prev',
            'object name 3': 'shortcut' + 'Next',
        }
        this_file = Path(__file__).resolve()
        hits = []
        for source in ROOT.rglob('*.py'):
            # This file is the one place the deleted names are spelled out -- the
            # docstring above and the labels here have to say them to forbid them. The
            # scan therefore covers the rest of the repo, and the hasattr checks below
            # cover this file's own subject matter directly.
            if source.resolve() == this_file:
                continue
            if SKIP_SCAN_PARTS & set(source.parts):
                continue
            text = source.read_text(encoding='utf-8', errors='replace')
            for label, needle in removed.items():
                if needle in text:
                    hits.append(f'{label} in {source.relative_to(ROOT)}')
        self.assertEqual([], hits, 'a dead batch-3 name is back in the source')

        for name in ('get_current_' + 'selection', 'set_' + 'selection',
                     'scroll_to_' + 'playing'):
            with self.subTest(method=name):
                self.assertFalse(hasattr(PlaylistView, name),
                                 f'PlaylistView.{name} is reachable again')

        self.assertEqual(
            [], [n for n in getattr(widgets, '__all__', ())
                 if n.startswith('MENU_') or n == 'build_' + 'playlist_menu'],
            'view.widgets re-exports the menu builder again: the consumers import '
            'view.widgets.playlist_context_menu directly, so the package surface is '
            'a second spelling that nothing maintains')

        # ... and the live surface this wave must NOT have taken with it.
        for name in ('selected_display_indices', 'display_index_at',
                     'context_menu_requested', 'set_current_playing'):
            self.assertTrue(hasattr(PlaylistView, name),
                            f'PlaylistView.{name} is batch 3\'s live API')
        self.assertTrue(hasattr(MainWindow, '_add_shortcut'),
                        'the transport bindings still have to be built somewhere')

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
        """Batch 3 owns context_menu_requested; it must not be deleted here.

        Batch 1's reason ("declared, never emitted, batch 3 will own it") is stale:
        Task 3 wired the emit, and the whole-branch review confirmed by grep that no
        production code connects to it. It survives for the *current* reason -- it is
        the observation hook that proves a right-click reached
        ``PlaylistView.contextMenuEvent``, read by ``tests/test_playlist_selection.py``
        and ``tests/tools/render_matrix.py`` -- and ``PlaylistView``'s own signal
        comment states the no-production-slot fact rather than leaving it implied.
        """
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
        from tests.test_view_smoke import make_manager

        self._keep_app = QApplication.instance() or QApplication([])

        self._tmp = tempfile.TemporaryDirectory()
        self.bg_path = str(Path(self._tmp.name) / 'background.png')
        seed = QPixmap(32, 32)
        seed.fill(Qt.GlobalColor.darkGreen)
        self.assertTrue(seed.save(self.bg_path, 'PNG'), 'test fixture PNG failed to write')

        self.view = MainWindow(make_manager())

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
        """Open the appearance dialog the way the menu does, then apply actions.

        Whole-branch review finding 5: this fires
        ``MainWindow.manage_appearance_requested`` instead of reaching into the
        presenter. The menu action's ``triggered`` connection
        (``view/main_window.py:140``) plus the presenter's connect of that signal
        to ``_on_manage_appearance`` (``presenter/main_presenter.py:100``) is the
        *only* route from the UI to the theme/appearance dialog, and calling the
        slot directly skipped both -- the route could be deleted and this file
        stayed green. Now a dropped connect means no dialog, no ``fake_exec``, no
        assertions.
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QFileDialog
        from view.dialogs.appearance_dialog import AppearanceDialog

        def fake_exec(dialog):
            for action in actions:
                action(dialog)
            return AppearanceDialog.DialogCode.Accepted

        with patch.object(QFileDialog, 'getOpenFileName', return_value=(self.bg_path, '')), \
                patch.object(AppearanceDialog, 'exec', fake_exec):
            opened = []
            # Connected after the presenter, so its ``_on_manage_appearance``
            # runs first: this only records that the signal has a listener and
            # that the emit below is what opens the dialog.
            self.view.manage_appearance_requested.connect(lambda: opened.append(True))
            self.view.manage_appearance_requested.emit()
            self.assertTrue(
                opened,
                'nothing listens to manage_appearance_requested: the menu item is '
                'a dead control',
            )

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
        # The report still has to reach the view -- but since Task 7 the carrier
        # is the toast, not the window title (spec §1 criterion 3 froze the
        # title, §5 made results transient feedback; Task 8 rewrites the
        # presenter's call sites onto ``show_toast`` directly). What this
        # assertion refuses to tolerate is the report vanishing.
        from PyQt6.QtWidgets import QFrame

        toast = self.view.findChild(QFrame, 'toast')
        self.assertIsNotNone(toast, '#toast must be part of the shell')
        self.assertNotEqual('', toast.current_message(),
                            'presenter did not report the background change on the view')
        self.assertTrue(toast.isVisibleTo(self.view),
                        'the report must be shown, not merely stored')
        self.assertEqual(
            self.view.windowTitle(), self.view._base_title,
            'the title is no longer a status channel (spec §1 criterion 3)',
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
