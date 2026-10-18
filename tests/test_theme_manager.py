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
        """``MainWindow.recolor`` is the fan-out point for the theme signal.

        Task 7 grew the fan-out from two entries to four: the rail's seven
        glyphs and the sidebar row/footer glyphs join the bottom panel's icons
        and the playlist viewport as the things QSS cannot restyle by itself.
        ``NowPlayingStrip`` rides inside ``BottomPanel.recolor`` (its own
        ``recolor`` draws no glyph; the forward keeps one call shape per
        batch-2 widget), so it is not a fifth entry here.
        """
        from core.theme import DARK

        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            seen = []
            window._rail.recolor = lambda tokens: seen.append(('rail', tokens))
            window._sidebar.recolor = lambda tokens: seen.append(('sidebar', tokens))
            window._bottom_panel.recolor = lambda tokens: seen.append(
                ('bottom', tokens))
            window._playlist_view.recolor = lambda: seen.append(('playlist', None))
            window.recolor(DARK)
            self.assertEqual(
                [('rail', DARK), ('sidebar', DARK),
                 ('bottom', DARK), ('playlist', None)], seen,
                'recolor() must reach the rail and sidebar glyphs, the bottom '
                'panel icons and the playlist viewport -- everything that '
                'paints a colour QSS cannot restyle',
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

    def test_dark_palette_keeps_the_hovered_list_row_legible(self):
        """Task 4's carried-over dependency, now closed.

        ``QDialog QListWidget::item:hover`` sets a background and no foreground,
        so the hovered library row reads its text colour from the palette. That
        was only safe once something actually installed a palette -- Task 6
        installed it, Task 7 makes ``'dark'`` reachable for real (it used to be
        unreachable behind the hardcoded ``mode='auto'``), so the pairing is
        asserted in the theme a user can now persist.
        """
        from tests.test_theme import ThemeContrastTest

        from core.theme import DARK

        mgr = self._manager('dark')
        mgr.apply_to(self.app)

        hover = _rule_block(self.app.styleSheet(),
                            'QDialog QListWidget::item:hover')
        self.assertIn('background-color', hover)
        self.assertNotIn(
            'color:', hover.replace('background-color', ''),
            'the hover rule must keep taking its foreground from the palette '
            'or this test stops proving the palette pairing',
        )
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Text),
            QColor(DARK.text_primary),
        )
        self.assertGreaterEqual(
            ThemeContrastTest.contrast(DARK.text_primary, DARK.hover_bg), 4.5,
            'hovered library text is body text: WCAG 2.1 AA needs 4.5:1',
        )

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

    def test_delegate_paints_the_row_divider_and_inset(self):
        """Whole-branch review finding 4: the row's divider is pixels, not a rule.

        ``#playlistView::item`` was dropped from the generated sheet because a
        delegate that overrides ``paint()`` never asks the style to draw the item
        sub-control, so its ``padding`` and ``border-bottom`` could not render (a
        live viewport measured 0 ``divider`` pixels, and deleting the rule left a
        window grab pixel-identical). The two values the mapping table asked for
        are therefore asserted here, where they are actually produced: a 1px
        ``divider`` on each row's bottom edge, and a ``SPACE_2`` side inset for
        the name and the position read-out.

        Before this test the inset was 5px and nothing drew a divider at all, so
        both halves bite: the inset assertions fail at 5, and the divider
        assertions fail when the ``fillRect`` is removed. The playing row is
        included because the layer order (divider, then the accent bar) is what
        keeps the 3px marker unbroken at the row's bottom edge.
        """
        from core.theme import DARK, LIGHT, ROW_HEIGHT, SPACE_2
        from view.delegates.playlist_delegate import PLAYING_BAR_WIDTH

        from service.queue_service import DisplayEntry
        from view.main_window import MainWindow

        mgr = self._manager('light')
        mgr.apply_to(self.app)
        window = MainWindow(mgr)
        try:
            window.set_playlist_entries([
                DisplayEntry(display_text='Album/Track 01.mp3', node_idx=0,
                             is_folder=False, path='/lib/Album/Track 01.mp3',
                             relative_position='Album', sub_index=0),
                DisplayEntry(display_text='Album/Track 02.mp3', node_idx=0,
                             is_folder=False, path='/lib/Album/Track 02.mp3',
                             relative_position='Album', sub_index=1,
                             is_playing=True),
            ])
            list_view = window._playlist_view._list_view
            list_view.resize(420, 120)
            list_view.show()
            self.app.processEvents()

            def image():
                self.app.processEvents()
                return list_view.viewport().grab().toImage()

            def row_rect(row):
                return list_view.visualRect(list_view.model().index(row))

            ink = LIGHT.text_primary
            divider = LIGHT.divider
            shot = image()

            for row in (0, 1):
                rect = row_rect(row)
                with self.subTest(row=row):
                    # The divider is one pixel tall, on the row's own bottom edge.
                    self.assertEqual(
                        divider,
                        shot.pixelColor(rect.left() + 40, rect.bottom()).name().lower(),
                        f'row {row} draws no divider on its bottom edge')
                    self.assertNotEqual(
                        divider,
                        shot.pixelColor(rect.left() + 40, rect.bottom() - 1).name().lower(),
                        f'row {row}: the divider is more than 1px, or the row '
                        f'background is being mis-read as a divider')

            # The playing row's accent bar survives the divider it crosses:
            # ``PLAYING_BAR_WIDTH`` covers the row's left edge, bottom included.
            rect = row_rect(1)
            self.assertEqual(
                LIGHT.playing_bar,
                shot.pixelColor(rect.left() + PLAYING_BAR_WIDTH - 1,
                                rect.bottom()).name().lower(),
                'the accent bar must be painted over the divider, not notched by it')

            # Left inset: nothing of the name may live inside the SPACE_2 gutter.
            rect = row_rect(0)
            columns = [
                x for x in range(rect.left(), rect.right())
                if any(shot.pixelColor(x, y).name().lower() == ink
                       for y in range(rect.top(), rect.bottom()))]
            self.assertTrue(columns, 'the name painted no ink at all')
            self.assertGreaterEqual(
                columns[0] - rect.left(), SPACE_2,
                f'the name starts {columns[0] - rect.left()}px in; the row inset '
                f'is the delegate\'s own SPACE_2 (8px), not the old 5px')
            self.assertLessEqual(
                columns[0] - rect.left(), SPACE_2 + 2,
                'the inset drifted away from SPACE_2 rather than following it')

            # Right gutter: the position read-out is right-aligned inside the
            # same inset, so its last ink column sits at least SPACE_2 in from
            # the row edge (the bracket's side bearing makes an exact figure
            # font-dependent, so only the containment is pinned here -- the left
            # inset above is the measurement with teeth, since 5px put ink
            # demonstrably inside the gutter).
            muted = LIGHT.text_muted
            right_columns = [
                x for x in range(rect.left(), rect.right())
                if any(shot.pixelColor(x, y).name().lower() == muted
                       for y in range(rect.top(), rect.bottom()))]
            self.assertTrue(right_columns, 'the position read-out painted no ink')
            self.assertGreaterEqual(
                rect.right() - max(right_columns), SPACE_2,
                'the right-hand read-out is drawn inside the SPACE_2 gutter, so '
                'it is not using the delegate\'s shared text rectangle')

            # The divider follows the theme, so it is a token and not a literal.
            mgr.set_mode('dark')
            shot = image()
            for row in (0, 1):
                rect = row_rect(row)
                self.assertEqual(
                    DARK.divider,
                    shot.pixelColor(rect.left() + 40, rect.bottom()).name().lower(),
                    'a dark row must draw the dark `divider` token')
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

    Since Task 7 the mode comes from ``config_service.get_theme()``, which is
    what makes that protective catch a live code path instead of decoration
    around a literal. Two layers defend the same value: ``core.config``
    normalises it on read (``tests/test_config_theme.py``), and this seam still
    catches anything unresolvable that reaches it -- so a future caller that
    hands over a raw value cannot brick startup either.
    """

    def setUp(self):
        self.app = make_app()
        # Palette only, for the reason recorded in ``ThemeManagerTest.setUp``.
        self._saved_palette = self.app.palette()

    def tearDown(self):
        self.app.setPalette(self._saved_palette)

    @staticmethod
    def _config(theme='auto'):
        """A stand-in ``ConfigService``: the three alphas plus the persisted mode."""
        return SimpleNamespace(
            get_overlay_alpha=lambda: 0.47,
            get_playlist_alpha=lambda: 0.75,
            get_controls_alpha=lambda: 0.85,
            get_theme=lambda: theme,
        )

    def test_persisted_mode_is_read_from_the_config_service(self):
        """No literal any more: the stored ``'dark'`` is what the manager starts on.

        Before Task 7 this failed by construction -- ``main_qt`` handed
        ``mode='auto'`` and the config value was never consulted.
        """
        import io
        from contextlib import redirect_stdout

        import main as main_module
        from core.theme import DARK

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            mgr = main_module.build_theme_manager(
                self.app, self._config(theme='dark'))

        self.assertEqual(
            '', buffer.getvalue(),
            'a valid persisted mode must not print a fallback warning')
        self.assertEqual('dark', mgr.mode)
        self.assertIs(
            DARK, mgr.tokens,
            'the mode the app started with has to be the persisted one')

    def test_bad_persisted_mode_falls_back_with_one_warning(self):
        """Task 6's guard, now reachable from a real stored value.

        ``build_theme_manager`` is handed only the config service, so the bad
        mode can have come from nowhere but ``get_theme()``: this is the
        hand-edited ``"theme": "Auto"`` / ``"theme": "neon"`` case, and startup
        must survive it.
        """
        import io
        from contextlib import redirect_stdout

        import main as main_module
        from core.theme import LIGHT

        for persisted in ('Auto', 'neon', ''):
            with self.subTest(persisted=persisted):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    mgr = main_module.build_theme_manager(
                        self.app, self._config(theme=persisted))
                out = buffer.getvalue()

                self.assertEqual(
                    1, out.count('Warning'),
                    f'exactly one warning line is expected, got: {out!r}')
                self.assertEqual('auto', mgr.mode)
                self.assertIs(LIGHT, mgr.tokens)
                self.assertIn('#bottomPanel', self.app.styleSheet())

    def test_main_qt_does_not_hardcode_the_mode(self):
        """The literal that made the guard unreachable must stay gone."""
        import inspect

        import main as main_module

        source = inspect.getsource(main_module.main_qt)
        self.assertNotIn('mode="auto"', source)
        self.assertNotIn("mode='auto'", source)
        self.assertIn('build_theme_manager(app, config_service)', source)

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


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class AppearanceThemeChoiceTest(unittest.TestCase):
    """The dialog's three-mode group and the presenter route that persists it.

    ``AppearanceDialog`` owns no service: it emits ``theme_selected(str)`` and
    ``MainPresenter`` is the only thing allowed to persist the mode. Applying it
    is the service's job -- ``ConfigService.set_theme`` emits ``theme_changed``
    and ``main.py`` connects that signal to ``ThemeManager.set_mode``, which is
    what makes the choice take effect without a restart.
    """

    MODES = {'themeAuto': 'auto', 'themeLight': 'light', 'themeDark': 'dark'}

    def setUp(self):
        self.app = make_app()
        self._saved_palette = self.app.palette()

    def tearDown(self):
        self.app.setPalette(self._saved_palette)

    def _dialog(self, theme_mode='auto'):
        """Built the way the presenter builds it, with the mode it persists."""
        from view.dialogs import AppearanceDialog

        dialog = AppearanceDialog(
            background_image=None,
            overlay_alpha=1.0,
            playlist_alpha=1.0,
            controls_alpha=1.0,
            theme_mode=theme_mode,
        )
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _radio(self, dialog, object_name):
        from PyQt6.QtWidgets import QRadioButton

        radio = dialog.findChild(QRadioButton, object_name)
        self.assertIsNotNone(
            radio, f'#{object_name} is missing from the appearance dialog')
        return radio

    def test_theme_group_is_the_first_group_of_the_dialog(self):
        """The mode picker precedes the background sliders: it is the bigger choice."""
        from PyQt6.QtWidgets import QGroupBox

        from core import i18n

        dialog = self._dialog('light')
        first = dialog.layout().itemAt(0).widget()
        self.assertIsInstance(first, QGroupBox)
        self.assertEqual(
            i18n.dialog('appearance.group.theme'), first.title(),
            'the theme group must be the first group box in the dialog')
        self.assertEqual(
            i18n.dialog('dialog.title.appearance'), dialog.windowTitle())

    def test_the_three_modes_are_one_exclusive_group(self):
        from core import i18n

        dialog = self._dialog('auto')
        for object_name, mode in self.MODES.items():
            with self.subTest(mode=mode):
                radio = self._radio(dialog, object_name)
                self.assertEqual(
                    i18n.dialog(f'appearance.theme_{mode}'), radio.text())
                self.assertNotIn(
                    '[MISSING', radio.text(),
                    'the label must be in both dialog catalogues')
                self.assertEqual(
                    'auto' == mode, radio.isChecked(),
                    'constructing with the mode must check exactly that radio')

    def test_the_radio_set_covers_every_theme_mode(self):
        """Drift guard: the picker is driven by ``core.config.THEME_MODES``.

        ``THEME_CHOICES`` pairs each mode with its objectName, so it is a second
        list of the same three values. A fourth mode added to the resolver (or a
        rename) would otherwise leave the dialog unable to reach a mode the
        settings file can store and ``ThemeManager.set_mode`` accepts -- and no
        sheet rule or test would notice, because every radio would simply still
        work. Uniqueness is checked too: two radios on one mode would fight.
        """
        from core.config import THEME_MODES
        from view.dialogs.appearance_dialog import THEME_CHOICES

        modes = [mode for mode, _ in THEME_CHOICES]
        self.assertEqual(set(THEME_MODES), set(modes))
        self.assertEqual(len(THEME_MODES), len(modes), 'a mode is listed twice')
        names = [name for _, name in THEME_CHOICES]
        self.assertEqual(len(names), len(set(names)),
                         'objectNames must be unique')
        self.assertEqual(self.MODES, dict(zip(names, modes)),
                         'the objectName -> mode map the tests click on must be '
                         'the one the dialog builds')

    def test_clicking_a_mode_emits_theme_selected(self):
        """One click, one emission, the mode string -- and nothing else reached."""
        dialog = self._dialog('auto')
        emitted = []
        dialog.theme_selected.connect(emitted.append)

        self._radio(dialog, 'themeDark').click()
        self._radio(dialog, 'themeLight').click()

        self.assertEqual(['dark', 'light'], emitted)
        self.assertTrue(self._radio(dialog, 'themeLight').isChecked())
        self.assertFalse(
            self._radio(dialog, 'themeDark').isChecked(),
            'the radios must be mutually exclusive, not three checkboxes')

    def test_an_unrecognised_stored_mode_is_shown_as_auto(self):
        """The dialog degrades like the loader does: never an unchecked group.

        ``MainPresenter`` can hand it anything (in these tests a ``MagicMock``),
        and a group with no checked radio is a UI dead end.
        """
        from types import SimpleNamespace

        for bad in ('neon', 'Auto', None, SimpleNamespace()):
            with self.subTest(theme_mode=bad):
                dialog = self._dialog(bad)
                self.assertTrue(self._radio(dialog, 'themeAuto').isChecked())

    def test_the_sliders_still_work_after_the_new_group(self):
        """Regression guard for the group inserted above them.

        The alpha sliders and the background label are looked up by objectName
        by other suites; an insert at the top of the layout must not have
        shifted or orphaned any of them.
        """
        from PyQt6.QtWidgets import QLabel, QSlider

        dialog = self._dialog('dark')
        for object_name in ('overlaySlider', 'playlistSlider', 'controlsSlider'):
            self.assertIsNotNone(
                dialog.findChild(QSlider, object_name),
                f'#{object_name} is no longer a child of the dialog')
        self.assertIsNotNone(dialog.findChild(QLabel, 'bgPathLabel'))

    def test_reset_defaults_moves_the_sliders_but_not_the_theme(self):
        """The mode has its own control; "reset" must not restyle the app.

        The button predates the theme group and answers the three sliders. Since
        Task 7 a click would otherwise be able to persist ``'auto'`` and flip
        every colour while the user was only chasing opacity, so the exclusion
        is a decision -- and now it is pinned.
        """
        dialog = self._dialog('dark')
        emitted = []
        dialog.theme_selected.connect(emitted.append)

        dialog._on_reset_defaults()

        self.assertEqual([], emitted,
                         'reset must not emit theme_selected')
        self.assertEqual('dark', dialog.theme_mode)
        self.assertTrue(self._radio(dialog, 'themeDark').isChecked())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PresenterThemeFlowTest(unittest.TestCase):
    """dialog -> presenter -> config, and nothing else.

    The presenter's job ends at the write. ``ConfigService.theme_changed`` is
    what applies a mode (wired to ``ThemeManager.set_mode`` in ``main.py``), and
    the class name that used to sit here -- "the live theme change" -- describes
    the second apply path this suite now guards against: with the config
    stubbed, the signal cannot fire, so a manager that moves at all proves the
    presenter is calling ``set_mode`` behind the service's back.
    """

    def setUp(self):
        from unittest.mock import MagicMock

        from presenter.main_presenter import MainPresenter
        from tests.test_view_smoke import make_manager
        from view.main_window import MainWindow

        self.app = make_app()
        self._saved_palette = self.app.palette()

        self.manager = make_manager('auto')
        self.manager.apply_to(self.app)
        self.view = MainWindow(self.manager)
        self.addCleanup(self.view.deleteLater)

        self.config = MagicMock(name='config_service')
        self.config.get_libraries.return_value = []
        self.config.get_background_image.return_value = None
        self.config.get_overlay_alpha.return_value = 0.47
        self.config.get_playlist_alpha.return_value = 0.75
        self.config.get_controls_alpha.return_value = 0.85
        self.config.get_theme.return_value = 'auto'
        self.config.set_theme.return_value = True

        # ``MainPresenter.__init__`` runs ``_load_config``, which reads the real
        # view, so the mocks answer with the types the view expects.
        self.playback = MagicMock(name='playback_service')
        self.playback.get_volume.return_value = 0.5

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
        self.app.setPalette(self._saved_palette)

    def _pick(self, object_name):
        """Open the dialog the way the menu does and click one mode radio.

        The emit below goes through ``MainWindow.manage_appearance_requested`` ->
        ``MainPresenter._on_manage_appearance``, i.e. the only route the menu has
        (whole-branch review finding 5; ``ThemeRestartIntegrationTest._pick`` and
        ``tests/test_dead_code_removed.py`` emit it for the same reason).
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QRadioButton

        from view.dialogs.appearance_dialog import AppearanceDialog

        def fake_exec(dialog):
            radio = dialog.findChild(QRadioButton, object_name)
            self.assertIsNotNone(radio, f'#{object_name} missing from dialog')
            radio.click()
            return AppearanceDialog.DialogCode.Accepted

        with patch.object(AppearanceDialog, 'exec', fake_exec):
            self.view.manage_appearance_requested.emit()

    def test_choosing_a_mode_persists_it_and_applies_nothing_itself(self):
        """The slot writes; only the service signal may restyle.

        ``self.config`` is a ``MagicMock``, so ``set_theme`` records the call and
        emits nothing. If the presenter still reached for
        ``ThemeManager.set_mode`` the manager would move here -- which is exactly
        the double apply the service wire exists to remove. The end-to-end
        version (real service, signal connected, manager flipped) is
        ``ThemeRestartIntegrationTest``.
        """
        from core.theme import LIGHT

        self.assertIs(LIGHT, self.manager.tokens)

        self._pick('themeDark')
        self._pick('themeLight')

        self.assertEqual(
            [mock.call('dark'), mock.call('light')],
            self.config.set_theme.call_args_list)
        self.assertEqual(
            'auto', self.manager.mode,
            'the presenter must not apply the mode itself')
        self.assertIs(
            LIGHT, self.manager.tokens,
            'a stubbed service emits no theme_changed, so nothing may restyle')

    def test_the_dialog_opens_on_the_persisted_mode(self):
        """``get_theme()`` is what pre-checks a radio, so the dialog cannot lie."""
        from unittest.mock import patch

        from view.dialogs.appearance_dialog import AppearanceDialog

        self.config.get_theme.return_value = 'dark'
        seen = {}

        def fake_exec(dialog):
            seen['mode'] = dialog._theme_mode
            return AppearanceDialog.DialogCode.Accepted

        with patch.object(AppearanceDialog, 'exec', fake_exec):
            self.presenter._on_manage_appearance()

        self.assertEqual('dark', seen['mode'])

    def test_a_failed_write_reports_to_the_user(self):
        """A rejected persist must not be a silent no-op for the user.

        ``ConfigService.set_theme`` answers False when the write fails (full or
        read-only disk, a Windows ``os.replace`` collision). It then emits no
        ``theme_changed``, so nothing restyles -- the running theme and the file
        keep the old mode while the click did nothing visible. The presenter's
        job is to say so on the view's one status surface, not to add a second
        apply path.
        """
        from unittest.mock import patch

        from core import i18n

        self.config.set_theme.return_value = False
        with patch.object(self.view, 'set_status_message') as status:
            self.presenter._handle_theme_change('dark')

        status.assert_called_once_with(i18n.get('status.theme_save_failed'))
        self.assertEqual(
            'auto', self.manager.mode,
            'a refused write emits nothing, so a failed save may not restyle')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ThemeRestartIntegrationTest(unittest.TestCase):
    """Task 7's headline promise -- "survives restart" -- with nothing stubbed.

    The two suites above each break the chain in one place:
    ``PresenterThemeFlowTest`` asserts persistence against a ``MagicMock``
    service, and ``StartupSeamTest`` hands :func:`main.build_theme_manager` a
    ``SimpleNamespace``. Two adjacencies therefore went unexecuted: a *real*
    ``ConfigService`` (temp file) driving the *real* theme manager over its
    ``theme_changed`` wire, and a dialog click landing in that *real* file. This
    class runs both, on both sides of a restart. The only stand-ins are the four
    services the presenter polls for playback state, which have no part in a
    theme; the config service, the theme manager, the window and the dialog are
    the production objects.

    Everything writes into a temporary ``settings.json``.
    """

    def setUp(self):
        import tempfile
        from unittest.mock import MagicMock

        import main as main_module

        from presenter.main_presenter import MainPresenter
        from service.config_service import ConfigService
        from view.main_window import MainWindow

        self.app = make_app()
        self._saved_palette = self.app.palette()

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings_file = str(Path(self._tmp.name) / 'settings.json')

        self.config = ConfigService(config_file=self.settings_file)
        # The real startup seam, then the real wiring main_qt performs.
        self.manager = main_module.build_theme_manager(self.app, self.config)
        main_module.connect_theme_signal(self.config, self.manager)

        self.view = MainWindow(self.manager)
        self.addCleanup(self.view.deleteLater)

        playback = MagicMock(name='playback_service')
        playback.get_volume.return_value = 0.5
        self.presenter = MainPresenter(
            view=self.view,
            playback_service=playback,
            queue_service=MagicMock(name='queue_service'),
            library_service=MagicMock(name='library_service'),
            metadata_service=MagicMock(name='metadata_service'),
            config_service=self.config,
        )

    def tearDown(self):
        self.presenter.stop()
        self.view.close()
        self.app.setPalette(self._saved_palette)

    def _disk_theme(self) -> str:
        """The raw ``theme`` value written into the settings file."""
        import json

        return json.loads(
            Path(self.settings_file).read_text(encoding='utf-8'))['theme']

    def _pick(self, object_name):
        """Click one mode radio in the dialog the way the menu opens it.

        Whole-branch review finding 5: the emit below is the route, not a
        convenience. ``MainWindow``'s menu action (``view/main_window.py:140``)
        and ``MainPresenter``'s connect of ``manage_appearance_requested``
        (``presenter/main_presenter.py:100``) are the only path from the UI to
        the theme dialog; this class used to call ``_on_manage_appearance``
        directly, so deleting that connect left the suite green while taking the
        feature off the menu for real. Emitting from the view means a dropped
        connect never opens the dialog, never runs ``fake_exec``, and leaves the
        persisted-mode assertions below unsatisfied.
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QRadioButton

        from view.dialogs.appearance_dialog import AppearanceDialog

        def fake_exec(dialog):
            radio = dialog.findChild(QRadioButton, object_name)
            self.assertIsNotNone(radio, f'#{object_name} missing from dialog')
            radio.click()
            return AppearanceDialog.DialogCode.Accepted

        with patch.object(AppearanceDialog, 'exec', fake_exec):
            self.view.manage_appearance_requested.emit()

    def test_the_service_signal_is_what_applies_the_mode(self):
        """``theme_changed`` is a live wire, not decoration.

        Nothing in this test touches the manager except the connect performed in
        ``setUp``: delete the ``connect`` inside
        :func:`main.connect_theme_signal` and the mode never reaches
        ``ThemeManager.set_mode``, so the assertions below fail.
        """
        import io
        from contextlib import redirect_stdout

        from core.theme import DARK

        emitted = []
        self.config.theme_changed.connect(emitted.append)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertTrue(self.config.set_theme('dark'))

        self.assertEqual(['dark'], emitted)
        self.assertEqual('dark', self.manager.mode)
        self.assertIs(
            DARK, self.manager.tokens,
            'the persisted mode must be applied through the service signal')
        self.assertIn('#bottomPanel', self.app.styleSheet())

    def test_a_dialog_click_persists_and_survives_a_restart(self):
        """Click dark -> real file -> fresh service + fresh manager -> dark."""
        import io
        from contextlib import redirect_stdout

        from PyQt6.QtGui import QColor, QPalette
        from PyQt6.QtWidgets import QRadioButton

        import main as main_module

        from core.theme import DARK
        from service.config_service import ConfigService
        from view.dialogs.appearance_dialog import AppearanceDialog

        emitted = []
        self.config.theme_changed.connect(emitted.append)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self._pick('themeDark')

        self.assertEqual(
            ['dark'], emitted,
            'one click, one write, one theme_changed emission')
        self.assertEqual('dark', self._disk_theme())
        self.assertEqual('dark', self.manager.mode)
        self.assertIs(DARK, self.manager.tokens)

        # Wipe the dark palette the click above already pushed onto the shared
        # app, so the repaint check after the restart can only be satisfied by
        # the restart itself re-applying the theme. Left alone it reads DARK
        # with or without the restart path and proves nothing about it.
        perturbed = QPalette()
        perturbed.setColor(QPalette.ColorRole.Base, QColor('#010203'))
        self.app.setPalette(perturbed)
        self.assertNotEqual(
            QColor(DARK.surface).name().lower(),
            self.app.palette().color(QPalette.ColorRole.Base).name().lower(),
            'the perturbation must clear the dark base, or the check below is '
            'the tautology it used to be')

        # --- restart: a second process would build exactly these two objects ---
        restarted = ConfigService(config_file=self.settings_file)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            restarted_manager = main_module.build_theme_manager(
                self.app, restarted)
        self.assertEqual(
            '', buffer.getvalue(),
            f'a persisted mode must start cleanly, got {buffer.getvalue()!r}')

        self.assertEqual('dark', restarted.get_theme())
        self.assertEqual('dark', restarted_manager.mode)
        self.assertIs(
            DARK, restarted_manager.tokens,
            'the mode read back from disk must resolve to the tokens it implies')
        self.assertEqual(
            QColor(DARK.surface).name().lower(),
            self.app.palette().color(QPalette.ColorRole.Base).name().lower(),
            'the restart must repaint: the dark base was wiped just above, so '
            'only ThemeManager.apply_to on the restarted path can put it back')

        # And the dialog tells the truth about it on the next open.
        dialog = AppearanceDialog(
            background_image=None,
            overlay_alpha=restarted.get_overlay_alpha(),
            playlist_alpha=restarted.get_playlist_alpha(),
            controls_alpha=restarted.get_controls_alpha(),
            theme_mode=restarted.get_theme(),
        )
        try:
            checked = [name for name in ('themeAuto', 'themeLight', 'themeDark')
                       if dialog.findChild(QRadioButton, name).isChecked()]
            self.assertEqual(['themeDark'], checked)
        finally:
            dialog.deleteLater()

    def test_main_qt_connects_the_signal_at_startup(self):
        """Keep the wire from going dead again.

        :func:`main.connect_theme_signal` only has a subscriber in production
        once ``main_qt`` calls it; a dropped call would turn the signal back
        into the unlistened-for API ``tests/test_dead_code_removed.py`` deletes.
        Read off the AST rather than as a substring of the source, because
        commented-out code keeps its text and loses its wiring -- and the whole
        point of this test is wiring that silently stopped happening.
        """
        import ast
        import inspect
        import textwrap

        import main as main_module

        tree = ast.parse(
            textwrap.dedent(inspect.getsource(main_module.main_qt)))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, 'id', None) == 'connect_theme_signal'
        ]
        self.assertEqual(
            1, len(calls),
            'main_qt must connect the theme signal exactly once, at startup')
        self.assertEqual(
            ['config_service', 'theme_manager'],
            [getattr(argument, 'id', None) for argument in calls[0].args],
            'the objects wired together have to be the startup service and the '
            'startup manager')


if __name__ == '__main__':
    unittest.main(verbosity=2)
