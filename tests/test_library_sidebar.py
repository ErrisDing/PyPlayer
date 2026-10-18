#!/usr/bin/env python3
"""Tests for ``view.widgets.library_sidebar.LibrarySidebar`` (batch 2, Task 4).

The sidebar is the batch-2 answer to audit item B3 (the media-library switcher
overflowing a horizontal chip row) and to spec §3.2's rule that *choosing* and
*adding* a library live here while every other library action lives on the
icon rail. That makes the contract below mostly about the floating-panel
mechanics rather than about colour:

* **The panel is a child widget, not a window**, so "click outside" has to come
  from an event filter. :meth:`test_click_outside_closes_panel` therefore posts
  a real ``QMouseEvent`` at the parent's content area and runs the event loop --
  calling ``hide_panel()`` directly would assert nothing about the filter, and a
  filter that hides on *every* press (including presses inside the panel) would
  pass such a test. Both directions are asserted.
* **``toggle()`` is the rail button's only entry point**, and the rail button is
  itself outside the panel, so an outside-press dismissal that let the click
  through would close and immediately re-open the panel. The filter consumes the
  dismissing press, which is what a real popup does, and
  :meth:`test_toggle_is_idempotent` pins that two ``toggle()`` calls are a no-op
  from either starting state.
* **Geometry is spec §6**: width ``min(SIDEBAR_WIDTH, parent - RAIL_WIDTH)``,
  internal scrolling, no horizontal scrollbar, no clipping of a long name. The
  narrow-parent case is asserted too, because ``<= min(...)`` on an 820 px parent
  is also satisfied by a panel that never resizes at all.
* **No track counts** (controller constraint, batch 1 ruling):
  ``library_manager.scan_directory()`` never reads metadata, so a per-library
  count is not obtainable this batch. A row shows the name only, and
  :meth:`test_zero_libraries_shows_empty_state_and_add_entry` fails if a row ever
  grows a count suffix -- invented or not.

``REQUIRED_OBJECT_NAMES`` is *not* touched by this task, so the objectName/QSS
pair is asserted here: ``tests/test_view_structure.py::
test_every_required_object_name_exists`` walks the live ``MainWindow`` tree, and
the sidebar only enters it in Task 7 (same ruling Task 3 recorded for
``#actionRail``).

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_library_sidebar -v
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

ELLIPSIS = '…'          # U+2026, what QFontMetrics.elidedText emits
PARENT_SIZE = (820, 600)     # spec §6's 820-wide case


def _libraries(count, prefix='Lib'):
    """``count`` LibraryConfig-shaped stand-ins (only ``.name``/``.path`` are read)."""
    return [SimpleNamespace(name=f'{prefix}{index}', path=f'/media/lib{index}')
            for index in range(count)]


def _push_rows(sidebar):
    """Every ``#libraryRow`` in the panel, library rows and footer entry alike."""
    from PyQt6.QtWidgets import QPushButton

    return sidebar.findChildren(QPushButton, 'libraryRow')


def library_rows(sidebar):
    """The selectable library rows.

    The footer add entry deliberately shares ``#libraryRow`` (a fifth styled
    objectName is outside what the brief lists), and the two are told apart by
    the ``library_path`` dynamic property the widget sets -- the same key
    ``LibrarySelector`` put on its chips.
    """
    return [row for row in _push_rows(sidebar)
            if row.property('library_path') is not None]


def add_row(sidebar):
    """The panel's footer add entry, or ``None`` if the widget lost it."""
    rows = [row for row in _push_rows(sidebar)
            if row.property('library_path') is None]
    return rows[0] if rows else None


def _content_area_class():
    """A content widget that *accepts* its own mouse presses, like ``QListView``.

    This is what makes :meth:`LibrarySidebarPanelTest.test_click_outside_closes_panel`
    prove the filter sits on the application. A passive ``QWidget`` ignores a press
    and Qt re-delivers it to the parent, so a filter installed on the parent widget
    alone would still see it -- measured: swapping the install target for the parent
    kept the whole suite green. A press the receiver itself accepts only ever reaches
    an application-level filter, which is what the panel needs to dismiss on a click
    in the playlist.

    Built lazily so this module stays importable without PyQt6 (the class body is a
    ``QWidget`` subclass, and a syntax-safe import at module scope would make the
    whole file uncollectable).
    """
    from PyQt6.QtWidgets import QWidget

    class ContentArea(QWidget):
        def mousePressEvent(self, event):
            event.accept()

    return ContentArea


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class LibrarySidebarPanelTest(unittest.TestCase):
    """The eight behaviours the brief names, on a real parent window."""

    def setUp(self):
        from core import i18n

        self.app = make_app()
        self._previous_locale = i18n.get_current_locale()
        self.addCleanup(i18n.set_locale, self._previous_locale)

    # === harness ===

    def _sidebar(self, mode='light', size=PARENT_SIZE, locale=None):
        """A sidebar parented to a shown window with a content area behind it.

        Deliberately not ``MainWindow``: Task 7 wires the panel into the real
        shell, and this widget must be testable standalone. ``content`` stands
        for the playlist area -- the surface a dismissing click lands on.
        """
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        from view.widgets.library_sidebar import LibrarySidebar

        if locale is not None:
            from core import i18n
            i18n.set_locale(locale)

        manager = make_manager(mode)
        manager.apply_to(self.app)

        parent = QWidget()
        parent.resize(*size)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        content = _content_area_class()(parent)   # the list area, behind the panel
        content.setObjectName('contentAreaStandIn')
        layout.addWidget(content)
        parent.show()
        self.app.processEvents()

        sidebar = LibrarySidebar(manager, parent)
        # ``addCleanup`` runs last-in-first-out: the panel has to be closed -- which
        # removes its application-level event filter -- before either widget is
        # deleted.
        self.addCleanup(sidebar.deleteLater)
        self.addCleanup(parent.deleteLater)
        self.addCleanup(sidebar.hide_panel)
        self.app.processEvents()
        return sidebar, manager, parent, content

    # === Step 1 tests ===

    def test_zero_libraries_shows_empty_state_and_add_entry(self):
        """First launch (spec §6): empty copy plus an add entry, in both locales."""
        from PyQt6.QtWidgets import QLabel

        from core import i18n

        for locale in ('zh_CN', 'en_US'):
            with self.subTest(locale=locale):
                sidebar, _manager, _parent, _content = self._sidebar(locale=locale)
                sidebar.set_libraries([])
                sidebar.show_panel()
                self.app.processEvents()

                empty = sidebar.findChild(QLabel, 'sidebarEmpty')
                self.assertIsNotNone(empty, '#sidebarEmpty is missing')
                self.assertTrue(empty.text(), 'the empty state renders nothing')
                self.assertNotIn('[MISSING', empty.text(), empty.text())
                self.assertNotEqual(empty.text(), 'sidebar.empty')
                self.assertFalse(empty.isHidden(), 'the empty state is hidden')

                add = add_row(sidebar)
                self.assertIsNotNone(add, 'no add entry without a library')
                self.assertEqual(add.text(), i18n.get('sidebar.add'))
                self.assertNotIn('[MISSING', add.text())
                self.assertTrue(add.isEnabled())
                self.assertFalse(add.isHidden(),
                                 'the add entry must stay visible, not scroll away')

    def test_thirty_libraries_stays_within_window(self):
        """30 rows: the panel fits the window and scrolls inside (audit B3)."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QScrollArea

        from core.theme import RAIL_WIDTH, SIDEBAR_WIDTH

        sidebar, _manager, parent, _content = self._sidebar()
        libraries = _libraries(30)
        sidebar.set_libraries(libraries)
        sidebar.show_panel()
        self.app.processEvents()

        clamp = min(SIDEBAR_WIDTH, parent.width() - RAIL_WIDTH)
        self.assertLessEqual(sidebar.width(), clamp,
                             f'the panel is wider than min(SIDEBAR_WIDTH, {parent.width()} - RAIL_WIDTH)')
        self.assertEqual(clamp, sidebar.width(),
                         'the panel does not take its clamped width')
        self.assertLess(sidebar.height(), parent.height(),
                        'a panel taller than the window cannot scroll, it overflows')
        rows = library_rows(sidebar)
        self.assertEqual(30, len(rows))
        # No track counts (batch 1 ruling): ``scan_directory`` never reads metadata,
        # so a row's whole text is the library name -- not ``name + ' (0)'``.
        self.assertEqual([library.name for library in libraries],
                         [row.text() for row in rows])

        scroll = sidebar.findChild(QScrollArea)
        self.assertIsNotNone(scroll, 'the rows must sit in a QScrollArea')
        self.assertIs(Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                      scroll.verticalScrollBarPolicy(),
                      'the vertical bar has to be reachable when the rows overflow')
        vertical = scroll.verticalScrollBar()
        self.assertTrue(vertical.isVisible(),
                        '30 rows do not fit, so the vertical bar must be reachable')
        self.assertGreater(vertical.maximum(), vertical.minimum(),
                           'the vertical range is empty: the rows cannot be scrolled')

        horizontal = scroll.horizontalScrollBar()
        self.assertIs(Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                      scroll.horizontalScrollBarPolicy(),
                      'the panel must not be able to grow a horizontal bar')
        self.assertFalse(horizontal.isVisible(),
                         'a horizontal bar is the B3 overflow this panel replaces')
        self.assertEqual(0, horizontal.maximum(),
                         'content is wider than the viewport even with the bar hidden')

        # The clamp has to be live, not a constant that happens to fit 820 px.
        parent.resize(260, 600)
        self.app.processEvents()
        sidebar.show_panel()
        self.app.processEvents()
        self.assertLessEqual(sidebar.width(), 260 - RAIL_WIDTH)
        self.assertLess(sidebar.width(), SIDEBAR_WIDTH,
                        'the panel ignored the narrow window')

    def test_long_library_name_is_elided_not_clipped(self):
        """An 80-character name: ellipsis inside the control, full name on hover."""
        from PyQt6.QtGui import QFontMetrics

        from core.theme import SIDEBAR_WIDTH

        sidebar, _manager, _parent, _content = self._sidebar()
        name = 'ExtremelyLongMediaLibraryName' * 3 + 'Tail'   # 96 characters
        self.assertGreater(len(name), 80)
        sidebar.set_libraries([SimpleNamespace(name=name, path='/media/long')])
        sidebar.show_panel()
        self.app.processEvents()

        row = library_rows(sidebar)[0]
        self.assertIn(ELLIPSIS, row.text(),
                      f'a {len(name)}-character name in a {SIDEBAR_WIDTH} px panel '
                      'must be elided, not silently cut')
        self.assertNotEqual(name, row.text())
        self.assertEqual(name, row.toolTip(),
                         'elision has to leave the full name reachable on hover')

        advance = QFontMetrics(row.font()).horizontalAdvance(row.text())
        self.assertLessEqual(advance, row.width(),
                             'the elided text still overflows the row control')
        self.assertLessEqual(row.width(), sidebar.width())
        self.assertLessEqual(sidebar.width(), SIDEBAR_WIDTH)

    def test_clicking_current_library_does_not_reemit(self):
        """The already-current row is a no-op; another row emits exactly once."""
        from core import i18n

        sidebar, _manager, _parent, _content = self._sidebar()
        sidebar.set_libraries(_libraries(2, prefix='Library'))
        sidebar.set_current('/media/lib0')
        sidebar.show_panel()

        emitted = []
        sidebar.library_selected.connect(emitted.append)

        rows = library_rows(sidebar)
        self.assertEqual(['/media/lib0', '/media/lib1'],
                         [row.property('library_path') for row in rows])

        rows[0].click()
        self.assertEqual([], emitted,
                         'clicking the current library must not re-scan the library')

        rows[1].click()
        self.assertEqual(['/media/lib1'], emitted,
                         'switching libraries emitted the wrong value, or twice')
        self.assertEqual('true', rows[1].property('current'))
        self.assertNotEqual('true', rows[0].property('current'))
        # spec §11: choosing a library dismisses the panel, like click-outside and Esc.
        self.assertFalse(sidebar.is_panel_open(),
                         'a selection leaves the panel floating over the list')
        self.assertTrue(add_row(sidebar).text())
        self.assertEqual(i18n.get('sidebar.add'), add_row(sidebar).text())

    def test_toggle_is_idempotent(self):
        """``toggle()`` twice is a no-op, from either starting state."""
        from core.theme import RAIL_WIDTH

        sidebar, _manager, parent, _content = self._sidebar()
        sidebar.set_libraries(_libraries(3))

        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible())

        sidebar.toggle()
        self.assertTrue(sidebar.is_panel_open())
        self.assertTrue(sidebar.isVisible(),
                        'the panel opened but never painted (parent shown)')
        sidebar.toggle()
        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible())

        # And from open: two toggles must come back open, not closed.
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.isVisible())
        self.assertGreaterEqual(sidebar.x(), RAIL_WIDTH,
                                'the panel covers the rail it was opened from')
        sidebar.toggle()
        sidebar.toggle()
        self.assertTrue(sidebar.is_panel_open())
        self.assertTrue(sidebar.isVisible())

    def test_escape_closes_panel(self):
        """A real ``QKeyEvent`` through ``keyPressEvent``, not a direct call."""
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent

        sidebar, _manager, _parent, _content = self._sidebar()
        sidebar.set_libraries(_libraries(2))
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(sidebar, event)
        self.assertTrue(event.isAccepted(),
                        'Escape was ignored, so the panel stays over the list')
        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible())

        # Escape while closed must not raise or re-open anything.
        again = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                          Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(sidebar, again)
        self.assertFalse(sidebar.is_panel_open())

        # A different key must not close it: the panel is not a modal grab.
        sidebar.show_panel()
        other = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(sidebar, other)
        self.assertTrue(sidebar.is_panel_open(),
                        'any key press closes the panel')

    def test_click_outside_closes_panel(self):
        """A posted mouse press on the content area dismisses; one inside does not."""
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QPushButton

        def post(widget, event_type):
            event = QMouseEvent(
                event_type,
                QPointF(widget.width() / 2.0, widget.height() / 2.0),
                widget.mapToGlobal(QPointF(widget.width() / 2.0,
                                           widget.height() / 2.0)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            # Posted, not ``hide_panel()``: the point of the test is the event
            # filter. Posting to a *child* of the parent is also what proves the
            # filter sits on the application rather than only on the parent widget
            # -- a press on a grandchild never reaches a parent-level filter, and a
            # row that accepts its own press (like ``QListView`` does) would leave
            # the panel floating.
            self.app.postEvent(widget, event)
            self.app.processEvents()

        def press_on(widget):
            post(widget, QEvent.Type.MouseButtonPress)

        def click_on(widget):
            post(widget, QEvent.Type.MouseButtonPress)
            post(widget, QEvent.Type.MouseButtonRelease)

        sidebar, _manager, parent, content = self._sidebar()
        sidebar.set_libraries(_libraries(3))
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())

        rows = library_rows(sidebar)
        press_on(rows[0])
        self.assertTrue(sidebar.is_panel_open(),
                        'a press inside the panel dismissed it: the filter does not '
                        'check whether the press landed in its own geometry')
        press_on(sidebar)
        self.assertTrue(sidebar.is_panel_open(),
                        'a press on the panel frame itself dismissed it')

        emitted = []
        sidebar.library_selected.connect(emitted.append)
        press_on(content)
        self.assertFalse(sidebar.is_panel_open(),
                         'a press on the content area left the panel floating')
        self.assertFalse(sidebar.isVisible())
        self.assertEqual([], emitted,
                         'the dismissing press also reached a library row')

        # The rail's library button is the case the filter has to *consume* for:
        # a press that is dismissed-but-delivered becomes a click on that button,
        # ``toggle()`` runs, and the panel re-opens behind the user's own click.
        toggle = QPushButton('toggle', parent)
        toggle.setGeometry(0, 0, 30, 30)      # left of the panel, outside its rect
        toggle.clicked.connect(sidebar.toggle)
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        click_on(toggle)
        self.assertFalse(
            sidebar.is_panel_open(),
            'the click that dismissed the panel also reached its toggle, which '
            're-opened it -- the filter must consume the dismissing press')

    def test_add_entry_emits_path(self):
        """The footer entry opens a directory chooser and emits the chosen path."""
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        sidebar, _manager, _parent, _content = self._sidebar()
        sidebar.set_libraries([])
        sidebar.show_panel()
        self.app.processEvents()

        emitted = []
        sidebar.add_library_requested.connect(emitted.append)
        add = add_row(sidebar)

        with mock.patch.object(QFileDialog, 'getExistingDirectory',
                               return_value='/media/new_library') as chooser:
            add.click()
        self.assertTrue(chooser.called,
                        'the add entry did not open a directory chooser')
        self.assertEqual(['/media/new_library'], emitted)

        # Cancelled chooser: nothing is emitted -- an empty path would add a library
        # rooted at the current directory.
        emitted.clear()
        with mock.patch.object(QFileDialog, 'getExistingDirectory', return_value=''):
            add.click()
        self.assertEqual([], emitted, 'a cancelled chooser still emitted a path')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class LibrarySidebarSheetTest(unittest.TestCase):
    """The QSS half of the pair, plus the two batch-wide style invariants."""

    def setUp(self):
        self.app = make_app()

    def _sidebar(self, mode='light'):
        from PyQt6.QtWidgets import QWidget

        from view.widgets.library_sidebar import LibrarySidebar

        manager = make_manager(mode)
        manager.apply_to(self.app)
        parent = QWidget()
        parent.resize(*PARENT_SIZE)
        sidebar = LibrarySidebar(manager, parent)
        self.addCleanup(sidebar.deleteLater)
        self.addCleanup(parent.deleteLater)
        sidebar.set_libraries(_libraries(2))
        return sidebar, manager, parent

    def test_the_panel_and_rows_carry_the_declared_names(self):
        """``#librarySidebar`` / ``#sidebarTitle`` / ``#libraryRow`` / ``#sidebarEmpty``."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel

        sidebar, _manager, _parent = self._sidebar()
        self.assertEqual('librarySidebar', sidebar.objectName())
        self.assertTrue(sidebar.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
                        'without the attribute the #librarySidebar fill never paints')
        self.assertIsInstance(sidebar.findChild(QLabel, 'sidebarTitle'), QLabel)
        self.assertEqual(2, len(library_rows(sidebar)))
        self.assertIsNotNone(add_row(sidebar))

        empty = sidebar.findChild(QLabel, 'sidebarEmpty')
        self.assertIsNotNone(empty, '#sidebarEmpty must exist even with rows present')
        self.assertTrue(empty.isHidden(), 'the empty state shows while libraries exist')

        # The current marker is the string the sheet selects on, same contract as
        # the library chips and the rail's ``running`` property.
        sidebar.set_current('/media/lib1')
        current = [row.property('current') for row in library_rows(sidebar)]
        self.assertEqual(['false', 'true'], current)
        for value in current:
            self.assertIsInstance(value, str, 'QSS attribute selectors need strings')

    def test_sidebar_rules_are_generated_from_tokens(self):
        """Every rule the panel needs exists in the sheet, in both themes."""
        import re

        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        def block(qss, selector):
            match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', qss)
            self.assertIsNotNone(match, f'no rule block for {selector!r}')
            return match.group(1)

        for theme_name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            qss = build_qss(tokens, AlphaSettings())
            with self.subTest(theme=theme_name):
                for selector in ('#librarySidebar', '#sidebarTitle', '#libraryRow',
                                 '#libraryRow:hover', '#sidebarEmpty',
                                 '#libraryRow[current="true"]'):
                    self.assertIn(f'\n{selector} {{', qss,
                                  f'{selector} is missing; that widget falls back to '
                                  'Fusion chrome')
                panel = block(qss, '#librarySidebar')
                self.assertIn(f'background-color: {tokens.surface};', panel)
                row = block(qss, '#libraryRow')
                self.assertIn(f'color: {tokens.text_primary};', row)
                current = block(qss, '#libraryRow[current="true"]')
                self.assertIn(f'background-color: {tokens.selection_bg};', current,
                              'the current row must wear the sheet\'s selection fill')
                self.assertIn(f'color: {tokens.text_primary};', current,
                              'text_primary on selection_bg is the contrast-pinned pair')
                empty = block(qss, '#sidebarEmpty')
                self.assertIn(f'color: {tokens.text_muted};', empty)

        # The ``folder`` glyph is rasterised from ``tokens.icon`` before QSS ever
        # sees it, so the fill it lands on has to be pinned in the contrast set --
        # the same rule Task 3 recorded for the rail's seven glyphs.
        from tests.test_theme import ThemeContrastTest

        self.assertIn(
            ('icon', 'selection_bg', 3.0), ThemeContrastTest.EXTRA_PAIRS,
            'the current row\'s glyph/background pairing is not pinned at the '
            '3:1 non-text bar; #libraryRow[current="true"] would then be an '
            'unguarded contrast decision')

    def test_the_panel_owns_no_widget_level_stylesheet(self):
        """The one-stylesheet rule of the theme layer (spec §1.6, judgement 6)."""
        from PyQt6.QtWidgets import QWidget

        sidebar, _manager, _parent = self._sidebar()
        self.assertEqual('', sidebar.styleSheet())
        for child in sidebar.findChildren(QWidget):
            self.assertEqual('', child.styleSheet(),
                             f'{type(child).__name__}#{child.objectName()} carries '
                             'an inline sheet')


if __name__ == '__main__':
    unittest.main(verbosity=2)
