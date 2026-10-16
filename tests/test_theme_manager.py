#!/usr/bin/env python3
"""Contract tests for :mod:`view.theme_manager` (Task 6: 样式来源切换).

``ThemeManager`` is the only thing in the app that pushes an application-wide
stylesheet and palette: the global ``styles.qss`` and the per-widget inline
sheets are gone, so the manager is the single seam where a theme becomes
pixels. These tests are therefore the regression net for the whole swap -- if
it stops emitting the sheet, the app is unstyled.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_theme_manager -v

Note on ``auto`` under offscreen: ``QStyleHints.colorScheme()`` reports
``ColorScheme.Unknown`` there, so ``auto`` resolves to ``LIGHT``. The
system-flip test drives the slot directly with a scheme name instead of
pretending the platform has a real scheme.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_view_smoke import QT_AVAILABLE, make_app
from tests.test_theme_qss import _rule_block

try:
    from PyQt6.QtGui import QColor, QPalette, QPixmap
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ThemeManagerTest(unittest.TestCase):
    """The manager owns the app's stylesheet, palette and theme signal."""

    def setUp(self):
        self.app = make_app()
        # Only the palette is put back. The application sheet is deliberately
        # left as the last theme this module applied: Task 6's acceptance gate
        # is that ``view/theme_manager.py`` holds the single sheet-installing
        # call in the product, so a test may not make one either -- and every
        # assertion here reads the sheet right after its own ``apply_to``, so a
        # leftover sheet from another test can never be mistaken for its own.
        self._saved_palette = self.app.palette()

    def tearDown(self):
        self.app.setPalette(self._saved_palette)

    def _manager(self, mode='light', alphas=None):
        from view.theme_manager import ThemeManager

        return ThemeManager(mode=mode, alphas=alphas)

    def test_alpha_keys_are_the_three_dialog_alphas(self):
        from view.theme_manager import ThemeManager

        self.assertEqual(
            {'overlay', 'playlist', 'controls'}, set(ThemeManager.ALPHA_KEYS),
            'the manager must accept exactly the three appearance sliders, '
            'which are also the three fields of core.theme.AlphaSettings',
        )

    def test_apply_to_sets_stylesheet_and_palette(self):
        from core.theme import LIGHT

        mgr = self._manager('light')
        mgr.apply_to(self.app)

        sheet = self.app.styleSheet()
        self.assertIn('#bottomPanel', sheet)
        self.assertIn('#playlistView', sheet)
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Base),
            QColor(LIGHT.surface),
            'Fusion sub-controls (menu arrows, scrollbars, dialog chrome) read '
            'the palette, so apply_to must set it and not only the sheet',
        )
        # The hovered library-list row sets a background but no foreground (the
        # sheet's ``QDialog QListWidget::item:hover`` rule), so its text colour
        # is the palette's Text role: that pairing is what keeps it legible.
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Text),
            QColor(LIGHT.text_primary),
        )

    def test_set_mode_swaps_tokens(self):
        from core.theme import DARK

        mgr = self._manager('light')
        mgr.apply_to(self.app)

        received = []
        mgr.theme_changed.connect(received.append)
        mgr.set_mode('dark')

        self.assertIs(mgr.tokens, DARK)
        self.assertEqual(
            len(received), 1,
            'set_mode must notify listeners with exactly one theme_changed',
        )
        self.assertIs(received[0], DARK)
        self.assertIn('#bottomPanel', self.app.styleSheet())

    def test_set_alpha_rebuilds_qss(self):
        mgr = self._manager('light')
        mgr.apply_to(self.app)

        mgr.set_alpha('playlist', 0.5)

        self.assertIn(
            ', 0.5)', _rule_block(self.app.styleSheet(), '#playlistView'),
            'the playlist alpha must reach the regenerated sheet, not only the '
            'manager\'s own state',
        )
        self.assertAlmostEqual(mgr.alphas.playlist, 0.5)

    def test_set_alpha_rejects_unknown_which(self):
        """Deviation from the brief (controller ruling R2): ``ValueError``.

        The brief expected ``KeyError``, which ``dataclasses.replace`` would
        never raise either; ``resolve()`` already answers a bad preference with
        ``ValueError``, so the manager matches it.
        """
        from core.theme import AlphaSettings

        mgr = self._manager('light', AlphaSettings())
        mgr.apply_to(self.app)
        sheet_before = self.app.styleSheet()

        with self.assertRaises(ValueError):
            mgr.set_alpha('nope', 0.5)

        self.assertEqual(
            sheet_before, self.app.styleSheet(),
            'a rejected call must not have touched the sheet',
        )

    def test_set_mode_rejects_unknown_mode(self):
        """A typo'd mode is a ``ValueError``, never a silent theme (Task 3 contract)."""
        mgr = self._manager('light')
        mgr.apply_to(self.app)
        with self.assertRaises(ValueError):
            mgr.set_mode('Auto')

    def test_auto_mode_follows_system_flip(self):
        from core.theme import DARK, LIGHT

        mgr = self._manager('auto')
        mgr.apply_to(self.app)
        # Offscreen reports ColorScheme.Unknown -> auto resolves to LIGHT.
        self.assertIs(mgr.tokens, LIGHT)

        mgr._on_system_scheme_changed('Dark')
        self.assertIs(mgr.tokens, DARK)
        self.assertIn('#bottomPanel', self.app.styleSheet())

        mgr._on_system_scheme_changed('Light')
        self.assertIs(mgr.tokens, LIGHT)

    def test_non_auto_mode_ignores_the_system_flip(self):
        from core.theme import DARK, LIGHT

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        mgr._on_system_scheme_changed('Dark')
        self.assertIs(
            mgr.tokens, LIGHT,
            'a manual mode is an override: the slot must return early',
        )

        mgr.set_mode('dark')
        mgr._on_system_scheme_changed('Light')
        self.assertIs(mgr.tokens, DARK)

    def test_scheme_enum_is_accepted_as_well_as_the_name(self):
        """The real Qt signal carries ``Qt.ColorScheme``, the tests a string."""
        from PyQt6.QtCore import Qt

        from core.theme import DARK, LIGHT

        mgr = self._manager('auto')
        mgr.apply_to(self.app)
        mgr._on_system_scheme_changed(Qt.ColorScheme.Dark)
        self.assertIs(mgr.tokens, DARK)
        mgr._on_system_scheme_changed(Qt.ColorScheme.Light)
        self.assertIs(mgr.tokens, LIGHT)

    def test_missing_color_scheme_signal_is_tolerated(self):
        """Older/other Qt: no ``colorSchemeChanged`` must not break ``apply_to``."""
        from core.theme import LIGHT

        hints = SimpleNamespace()  # no colorScheme(), no colorSchemeChanged
        with mock.patch.object(QApplication, 'styleHints', return_value=hints):
            mgr = self._manager('light')
            mgr.apply_to(self.app)

        self.assertIs(mgr.tokens, LIGHT)
        self.assertIn('#bottomPanel', self.app.styleSheet())
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Base),
            QColor(LIGHT.surface),
        )

    def test_scrim_color_tracks_theme(self):
        import tempfile

        from core.theme import DARK, LIGHT

        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                bg = Path(tmp) / 'background.png'
                self.assertTrue(QPixmap(8, 8).save(str(bg), 'PNG'))
                window.set_background_image(str(bg))

                self.assertEqual(window.scrim_color().name().lower(), LIGHT.scrim)
                mgr.set_mode('dark')
                self.assertEqual(window.scrim_color().name().lower(), DARK.scrim)
                window.set_background_image(None)
        finally:
            window.close()
            window.deleteLater()

    def test_scrim_alpha_comes_from_the_manager(self):
        import tempfile

        from core.theme import AlphaSettings

        from view.main_window import MainWindow

        mgr = self._manager('light', AlphaSettings(overlay=0.4))
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            self.assertAlmostEqual(window._overlay_alpha, 0.4)
            self.assertAlmostEqual(window.scrim_color().alphaF(), 0.4, places=3)
            window.set_overlay_alpha(0.8)
            self.assertAlmostEqual(mgr.alphas.overlay, 0.8)
            self.assertAlmostEqual(window._overlay_alpha, 0.8)
            self.assertEqual(window.scrim_color().name().lower(), '#ffffff')
        finally:
            window.close()
            window.deleteLater()

    def test_widgets_are_given_the_manager(self):
        """The manager is threaded down to the widgets that paint from it."""
        from view.main_window import MainWindow
        from view.widgets.bottom_panel import BottomPanel
        from view.widgets.playlist_view import PlaylistView

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            self.assertIsInstance(window._bottom_panel, BottomPanel)
            self.assertIsInstance(window._playlist_view, PlaylistView)
            self.assertIs(window._bottom_panel._theme, mgr)
            self.assertIs(window._playlist_view._theme, mgr)
            # The delegate paints from the manager, so a mode flip changes the
            # colours it reads with no widget-side stylesheet anywhere.
            delegate = window._playlist_view._list_view.itemDelegate()
            self.assertIs(delegate._manager, mgr)
            self.assertGreaterEqual(
                mgr.receivers(mgr.theme_changed), 1,
                'MainWindow must stay subscribed to theme_changed',
            )
        finally:
            window.close()
            window.deleteLater()

    def test_recolor_forwards_to_the_widgets_that_paint(self):
        """``MainWindow.recolor`` is the fan-out point for the theme signal."""
        from core.theme import DARK

        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            seen = []
            window._bottom_panel.recolor = lambda tokens: seen.append(
                ('bottom', tokens))
            window._playlist_view.recolor = lambda: seen.append(('playlist', None))
            window.recolor(DARK)
            self.assertEqual(
                [('bottom', DARK), ('playlist', None)], seen,
                'recolor() must reach the bottom panel icons and the playlist '
                'viewport, the two things QSS cannot restyle by itself',
            )
        finally:
            window.close()
            window.deleteLater()

    def test_no_widget_keeps_its_own_stylesheet(self):
        """The inline-style era is over: nothing below the window is styled.

        ``grep`` proves it for the shipped tree; this proves it for the live
        widget tree, where an inherited inline sheet would still win over the
        application sheet and re-split the styling.
        """
        from PyQt6.QtWidgets import QWidget

        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            styled = [
                f'{type(child).__name__}#{child.objectName()}'
                for child in window.findChildren(QWidget)
                if child.styleSheet()
            ]
            self.assertEqual(
                [], styled,
                'per-widget stylesheets survived Task 6; the app sheet is the '
                'only styling source',
            )
            self.assertEqual(
                '', window.styleSheet(),
                'MainWindow must be styled by the application sheet too',
            )
        finally:
            window.close()
            window.deleteLater()

    def test_widgets_take_their_colours_from_tokens(self):
        """The transport icons are regenerated from the tokens, not hardcoded."""
        from core.theme import DARK, LIGHT

        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            panel = window._bottom_panel
            play_pixmap = panel._play_btn.icon().pixmap(
                panel._play_btn.iconSize())
            before = play_pixmap.toImage().pixelColor(
                play_pixmap.width() // 2, play_pixmap.height() // 2)
            mgr.set_mode('dark')
            after = panel._play_btn.icon().pixmap(
                panel._play_btn.iconSize()).toImage().pixelColor(
                play_pixmap.width() // 2, play_pixmap.height() // 2)
            self.assertEqual(
                before.name().lower(), QColor(LIGHT.icon_on_accent).name().lower())
            self.assertEqual(
                after.name().lower(), QColor(DARK.icon_on_accent).name().lower(),
                'recolor() must regenerate the hand-drawn icons from the new '
                'tokens (SVG pipeline is Task 8)',
            )
        finally:
            window.close()
            window.deleteLater()


    def test_model_carries_no_presentation(self):
        """Step 4: colours and fonts left ``PlaylistModel`` for the delegate.

        The model answers data roles only, so a theme flip cannot leave a
        stale ``QColor`` cached in model data the delegate would have to
        second-guess.
        """
        from PyQt6.QtCore import Qt

        from service.queue_service import DisplayEntry
        from view.models.playlist_model import PlaylistModel

        for constant in ('PLAYING_BG_COLOR', 'FOLDER_COLOR'):
            self.assertFalse(
                hasattr(PlaylistModel, constant),
                f'{constant} must be gone: the delegate reads the tokens instead',
            )

        model = PlaylistModel()
        model.set_entries([
            DisplayEntry(display_text='A folder', node_idx=0, is_folder=True,
                         path='/lib/album'),
            DisplayEntry(display_text='A track', node_idx=1, is_folder=False,
                         path='/lib/album/t.mp3', is_playing=True),
        ])
        for row in (0, 1):
            index = model.index(row)
            for role in (Qt.ItemDataRole.BackgroundRole,
                         Qt.ItemDataRole.ForegroundRole,
                         Qt.ItemDataRole.FontRole,
                         Qt.ItemDataRole.DecorationRole):
                value = model.data(index, role)
                self.assertFalse(
                    self._present(value),
                    f'row {row} still answers {role} with a presentation value',
                )

    @staticmethod
    def _present(value) -> bool:
        """Whether a model role was answered with something (not QVariant/None)."""
        if value is None:
            return False
        if hasattr(value, 'isValid'):
            return bool(value.isValid())
        return True

    def test_delegate_paints_the_tokens(self):
        """The playlist row colours come out of the manager, end to end.

        Task 6 moved presentation from ``PlaylistModel`` into the delegate, so
        the only proof that matters is on the pixels: a playing row must be
        ``playing_bg`` and a selected row ``selection_bg``, in the theme that
        is currently active.
        """
        from core.theme import DARK

        from service.queue_service import DisplayEntry
        from view.main_window import MainWindow

        mgr = self._manager('dark')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            window.set_playlist_entries([
                DisplayEntry(display_text='Playing.mp3', node_idx=0,
                             is_folder=False, path='/lib/Playing.mp3',
                             sub_index=0, is_playing=True),
                DisplayEntry(display_text='Other.mp3', node_idx=1,
                             is_folder=False, path='/lib/Other.mp3',
                             sub_index=0),
            ])
            list_view = window._playlist_view._list_view
            list_view.resize(320, 200)
            list_view.show()
            self.app.processEvents()

            def colour_census(widget):
                pixmap = widget.viewport().grab()
                image = pixmap.toImage()
                seen = set()
                for y in range(image.height()):
                    for x in range(image.width()):
                        seen.add(image.pixelColor(x, y).name().lower())
                return seen

            colours = colour_census(list_view)
            self.assertIn(
                DARK.playing_bg, colours,
                'the delegate must fill the playing row with playing_bg',
            )

            list_view.setCurrentIndex(list_view.model().index(1))
            self.app.processEvents()
            colours = colour_census(list_view)
            self.assertIn(
                DARK.selection_bg, colours,
                'the delegate must fill the selected row with selection_bg',
            )
            list_view.hide()
        finally:
            window.close()
            window.deleteLater()

    def test_playlist_row_metrics_come_from_the_delegate(self):
        """``ROW_HEIGHT`` is the row height, and the row still spans the view.

        Task 6 moves the presentation out of ``PlaylistModel``, whose Font/
        Background/Foreground roles are now gone, and gives the delegate a
        ``sizeHint``. A ``QSize(0, ROW_HEIGHT)`` would collapse the row to the
        text width in ``Adjust`` resize mode, so the painted row must be
        checked, not assumed.
        """
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from core.theme import ROW_HEIGHT

        from service.queue_service import DisplayEntry
        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            window.set_playlist_entries([
                DisplayEntry(display_text='Album/Track 01.mp3', node_idx=0,
                             is_folder=False, path='/lib/Album/Track 01.mp3',
                             relative_position='Album'),
            ])
            list_view = window._playlist_view._list_view
            list_view.resize(420, 240)
            list_view.show()
            self.app.processEvents()

            delegate = list_view.itemDelegate()
            index = list_view.model().index(0)
            option = QStyleOptionViewItem()
            option.initFrom(list_view)
            hint = delegate.sizeHint(option, index)
            self.assertEqual(
                ROW_HEIGHT, hint.height(),
                'the delegate owns the row height now (the QSS does not set it)',
            )
            rect = list_view.visualRect(index)
            self.assertEqual(ROW_HEIGHT, rect.height())
            self.assertGreater(
                rect.width(), 200,
                'the row collapsed to its content width; the delegate sizeHint '
                'must keep the row spanning the viewport',
            )
            list_view.hide()
        finally:
            window.close()
            window.deleteLater()


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class StartupSeamTest(unittest.TestCase):
    """``main.py`` must survive a hand-edited ``settings.json``.

    ``resolve()`` raises ``ValueError`` on an unrecognised mode (deliberately,
    so a typo'd preference cannot silently render the wrong theme). That makes
    the construction of the manager a startup hazard, so the seam has to catch
    it, fall back to ``auto`` and say so once.

    ``main_qt`` still passes ``mode='auto'`` literally (Task 6 hardcodes it);
    the helper takes the mode as an argument so the fallback is reachable and
    tested, and Task 7 only has to hand it ``config_service.get_theme()``.
    """

    def setUp(self):
        self.app = make_app()
        # Palette only, for the reason recorded in ``ThemeManagerTest.setUp``.
        self._saved_palette = self.app.palette()

    def tearDown(self):
        self.app.setPalette(self._saved_palette)

    @staticmethod
    def _config():
        return SimpleNamespace(
            get_overlay_alpha=lambda: 0.47,
            get_playlist_alpha=lambda: 0.75,
            get_controls_alpha=lambda: 0.85,
        )

    def test_bad_mode_falls_back_to_auto(self):
        import io
        from contextlib import redirect_stdout

        import main as main_module
        from core.theme import LIGHT

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            mgr = main_module.build_theme_manager(
                self.app, self._config(), mode='Auto')
        out = buffer.getvalue()

        self.assertEqual(
            out.count('Warning'), 1,
            f'exactly one warning line is expected, got: {out!r}',
        )
        self.assertEqual(mgr.mode, 'auto')
        self.assertIs(mgr.tokens, LIGHT)
        self.assertIn('#bottomPanel', self.app.styleSheet())

    def test_good_mode_is_passed_through(self):
        import io
        from contextlib import redirect_stdout

        import main as main_module
        from core.theme import DARK

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            mgr = main_module.build_theme_manager(
                self.app, self._config(), mode='dark')
        self.assertEqual(
            '', buffer.getvalue(), 'a valid mode must not print anything')

        self.assertEqual(mgr.mode, 'dark')
        self.assertIs(mgr.tokens, DARK)
        self.assertAlmostEqual(mgr.alphas.playlist, 0.75)
        self.assertAlmostEqual(mgr.alphas.controls, 0.85)
        self.assertAlmostEqual(mgr.alphas.overlay, 0.47)


if __name__ == '__main__':
    unittest.main(verbosity=2)
