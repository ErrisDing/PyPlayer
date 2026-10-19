#!/usr/bin/env python3
"""Tests for ``view.widgets.library_sidebar.LibrarySidebar`` (batch 2, Task 4).

The sidebar is the batch-2 answer to audit item B3 (the media-library switcher
overflowing a horizontal chip row) and to spec §3.2's rule that *choosing* and
*adding* a library live here while every other library action lives on the
icon rail. That makes the contract below mostly about the floating-panel
mechanics rather than about colour:

* **The panel is a child widget, not a window**, so neither of its two dismissal
  routes can come from itself. :meth:`test_click_outside_closes_panel` therefore
  posts a real ``QMouseEvent`` at the parent's content area and runs the event
  loop -- calling ``hide_panel()`` directly would assert nothing about the filter,
  and a filter that hides on *every* press (including presses inside the panel)
  would pass such a test. Both directions are asserted.
* **Escape reaches the panel through the same filter, at a focus position the
  panel does not own.** The panel is ``NoFocus``, and Qt delivers a key press to
  ``focusWidget()`` and walks *up* the parent chain on non-accept; the panel is a
  sibling of the list, never its ancestor, so a ``keyPressEvent`` on the panel is
  unreachable with the keyboard in the list.
  :meth:`test_escape_closes_panel` therefore injects into ``app.focusWidget()``
  (and into the window when nothing has focus), never into the panel -- the form
  that could not fail for the reason the handler was wrong.
* **The filter runs on the application, so it must not touch other windows.**
  :meth:`test_a_press_in_another_top_level_window_leaves_the_panel_alone` pins
  that a press in a dialog owned by the panel, or in an unrelated window, is
  neither consumed nor dismissive;
  :meth:`test_a_press_elsewhere_in_the_window_dismisses_outside_the_parent_subtree`
  pins the other half -- a widget that shares the window but sits outside the
  parent's subtree (Task 7's rail, strip and toast are siblings of the content
  area) still closes the panel.
* **A hide that bypasses ``hide_panel()`` gives the filter back.**
  :meth:`test_a_bypassed_hide_stops_consuming_presses` hides through ``hide()``
  and then asserts that a press reaches its receiver: an installed-but-invisible
  panel swallows mouse presses, which reads to the user as a dead rail button.
* **A top-level hide/show round trip cannot leave the panel painted while the
  flag says closed.** Qt replays the on-screen child visibilities when a hidden
  window is shown again, and that restore is not a ``show_panel()`` call, so
  every flag-level assertion in this file was green while the render matrix
  photographed a closed frame wearing a blank 240 px stripe of panel.
  :meth:`test_a_window_hide_show_round_trip_leaves_no_panel_on_screen` and
  :class:`LibrarySidebarMainWindowTest` therefore assert the *pixels*: real
  ``isVisible()`` after a shown window, and which widget is topmost at a point
  inside the panel's geometry.
* **``toggle()`` is the rail button's only entry point**, and the rail button is
  itself outside the panel, so an outside-press dismissal that let the click
  through would close and immediately re-open the panel. The filter consumes the
  dismissing press, which is what a real popup does, and
  :meth:`test_toggle_is_idempotent` pins that two ``toggle()`` calls are a no-op
  from either starting state.
* **Geometry is spec §6**: width ``min(SIDEBAR_WIDTH, parent - RAIL_WIDTH)``,
  internal scrolling, no horizontal scrollbar, no clipping of a long name. The
  narrow-parent case is asserted too, because ``<= min(...)`` on an 820 px parent
  is also satisfied by a panel that never resizes at all -- and it is asserted by
  shrinking the window *while the panel floats*, because a clamp computed at show
  time is a snapshot, not a contract.
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


def reap_deleted_rows():
    """Deliver the ``deleteLater`` queue now.

    ``_rebuild_rows`` hands the old rows to ``deleteLater``, and a deferred delete
    is only processed when an event *loop* is entered -- ``processEvents()`` leaves
    them in the object tree, where ``findChildren`` still returns them (as plain
    ``QPushButton`` wrappers, their ``LibraryRow`` Python side already gone). A test
    that asserts a row count after a rebuild has to flush this way or it counts the
    rows the rebuild removed.
    """
    from PyQt6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def library_rows(sidebar):
    """The selectable library rows.

    The two footer entries deliberately share ``#libraryRow`` (a fifth styled
    objectName is outside what the brief lists), and rows and footer are told
    apart by the ``library_path`` dynamic property the widget sets: a footer entry
    selects no library, so it carries none.
    """
    return [row for row in _push_rows(sidebar)
            if row.property('library_path') is not None]


def _footer_row(sidebar, label: str):
    """The footer entry whose *un-elided* text is ``label``, or ``None``.

    Matched on ``full_name``, not ``text``: a row elides against its own width, so
    the visible string is not an identity. ``library_path`` absence alone cannot
    tell the two footer entries apart since spec §3.2's Task 8 correction gave the
    panel a second administration entry.
    """
    rows = [row for row in _push_rows(sidebar)
            if row.property('library_path') is None and row.full_name == label]
    return rows[0] if len(rows) == 1 else None


def add_row(sidebar):
    """The panel's footer add entry, or ``None`` if the widget lost it."""
    from core import i18n

    return _footer_row(sidebar, i18n.get('sidebar.add'))


def manage_row(sidebar):
    """The panel's footer 管理媒体库 entry, or ``None`` if the widget lost it."""
    from core import i18n

    return _footer_row(sidebar, i18n.get('sidebar.manage'))


def _content_area_class():
    """A content widget that *accepts* its own mouse presses, like ``QListView``.

    This is what makes :meth:`LibrarySidebarPanelTest.test_click_outside_closes_panel`
    prove the filter sits on the application. A passive ``QWidget`` ignores a press
    and Qt re-delivers it to the parent, so a filter installed on the parent widget
    alone would still see it -- measured: swapping the install target for the parent
    kept the whole suite green. A press the receiver itself accepts only ever reaches
    an application-level filter, which is what the panel needs to dismiss on a click
    in the playlist.

    Two more things it does, because ``QListView`` does them and the panel's
    dismissal contract depends on both:

    * ``WheelFocus``, the list's real focus policy, so
      :meth:`test_escape_closes_panel` can put the keyboard where the user puts it
      and deliver the key to ``app.focusWidget()`` instead of to the panel;
    * a ``press_count``, which is the only way to tell "the filter dismissed the
      panel and consumed the press" from "the filter ate the press while the panel
      was not even there" -- a consumption test that only looks at the panel's own
      state cannot make that difference.

    Built lazily so this module stays importable without PyQt6 (the class body is a
    ``QWidget`` subclass, and a syntax-safe import at module scope would make the
    whole file uncollectable).
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget

    class ContentArea(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.press_count = 0
            self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)

        def mousePressEvent(self, event):
            self.press_count += 1
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
        # ``close`` runs first (addCleanup is LIFO): a visible top-level left at
        # the offscreen origin swallows ``QTest.mouseMove`` for every module that
        # runs after this one, and ``deleteLater`` alone never lands because
        # ``unittest`` enters no event loop.
        self.addCleanup(parent.close)
        self.addCleanup(sidebar.close)
        self.addCleanup(sidebar.hide_panel)
        self.app.processEvents()
        return sidebar, manager, parent, content

    # === event delivery ===

    def _post_mouse(self, widget, event_type):
        """Send a real mouse event at ``widget``'s centre and run the loop.

        Posted, not ``hide_panel()``: the point of these tests is the event
        filter. Posting to a *child* of the parent is also what proves the filter
        sits on the application rather than only on the parent widget -- a press
        on a grandchild never reaches a parent-level filter, and a row that
        accepts its own press (like ``QListView`` does) would leave the panel
        floating.
        """
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        position = QPointF(widget.width() / 2.0, widget.height() / 2.0)
        event = QMouseEvent(
            event_type, position,
            widget.mapToGlobal(position),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        self.app.postEvent(widget, event)
        self.app.processEvents()

    def _press_on(self, widget):
        from PyQt6.QtCore import QEvent

        self._post_mouse(widget, QEvent.Type.MouseButtonPress)

    def _release_on(self, widget):
        from PyQt6.QtCore import QEvent

        self._post_mouse(widget, QEvent.Type.MouseButtonRelease)

    def _click_on(self, widget):
        self._press_on(widget)
        self._release_on(widget)

    def _escape(self, receiver):
        """Inject an Escape key press into ``receiver``, and hand the event back."""
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                          Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(receiver, event)
        return event

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

        # The clamp has to be live, not a constant that happens to fit 820 px --
        # and live means *on resize*, because a window shrunk while the panel
        # floats is the case the user actually produces. Re-showing here would
        # hide the missing hook: ``show_panel`` re-places anyway, so the assert
        # below would pass on a panel that never watches the parent.
        parent.resize(260, 600)
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open(),
                        'the panel closed on its own, so the geometry check below '
                        'would be measuring a fresh show rather than a re-place')
        self.assertTrue(sidebar.isVisible())
        narrow = min(SIDEBAR_WIDTH, 260 - RAIL_WIDTH)
        self.assertEqual(narrow, sidebar.width(),
                         'the panel did not re-clamp to the shrunk window')
        self.assertLess(sidebar.width(), SIDEBAR_WIDTH,
                        'the panel ignored the narrow window')
        self.assertLessEqual(sidebar.x() + sidebar.width(), parent.width(),
                             'the panel overhangs the window: the B3 overflow this '
                             'panel exists to remove, reintroduced by a stale clamp')

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
        """Escape reaches the panel from the focus position the user actually has.

        The key is delivered to ``app.focusWidget()`` (and, in the second half, to
        the top-level with nothing focused) -- never to the panel. Injecting into
        the panel would be direct delivery that bypasses Qt's routing, and the
        panel is ``NoFocus`` while the playlist is a *sibling*, not an ancestor, of
        it: with the keyboard in the list a ``keyPressEvent`` on the panel is
        unreachable, which is exactly the failure such a test could not see.
        """
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent

        sidebar, _manager, parent, content = self._sidebar()
        sidebar.set_libraries(_libraries(2))
        sidebar.show_panel()
        content.setFocus()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        self.assertIs(content, self.app.focusWidget(),
                      'the harness has no focus in the list, so this test would be '
                      'back to injecting the key into the panel itself')

        event = self._escape(self.app.focusWidget())
        self.assertTrue(event.isAccepted(),
                        'Escape was ignored, so the panel stays over the list')
        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible())

        # Escape while closed must not raise or re-open anything.
        self._escape(self.app.focusWidget() or parent)
        self.assertFalse(sidebar.is_panel_open())

        # The other position a real window has: no widget focused, so Qt hands
        # the key to the top-level. The panel must still close -- the filter sees
        # both routes, a handler on the panel sees neither.
        content.clearFocus()
        self.app.processEvents()
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        self.assertIsNone(self.app.focusWidget(),
                          'the window kept a focus widget, so this is not the '
                          'no-focus case the comment claims to cover')
        self._escape(parent)
        self.assertFalse(sidebar.is_panel_open(),
                         'Escape with nothing focused left the panel floating')

        # A different key must not close it: the panel is not a modal grab.
        sidebar.show_panel()
        other = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                          Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(parent, other)
        self.assertTrue(sidebar.is_panel_open(),
                        'any key press closes the panel')

    def test_a_bypassed_hide_stops_consuming_presses(self):
        """Both halves of the dismissal gate: the flag, and real visibility.

        ``hide_panel()`` is paired, but it is not the only route out: a presenter
        can call ``sidebar.hide()``/``setVisible(False)``, and Qt hides the panel
        with the window around it. A filter that survives such a hide keeps
        consuming presses -- the gate was the flag alone, so an invisible panel
        still ``return True`` on a press nowhere near it -- and the flag drifting
        from visibility makes the rail's library button look broken rather than
        merely stale: the press is eaten, the next toggle "closes" a panel that is
        already gone, the one after that opens it again.

        The first half hides through ``hide()`` and asserts the press reaches its
        receiver, which only a counter on the receiver can show. The second half
        takes the state no ``QEvent.Hide`` can produce -- ``show_panel()`` while
        the window is hidden, so the flag is true and the screen is not -- and
        asks the same question of the ``isVisible()`` term.
        """
        sidebar, _manager, parent, content = self._sidebar()
        sidebar.set_libraries(_libraries(2))
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())

        sidebar.hide()          # the bypass route: no hide_panel()
        self.app.processEvents()
        self.assertFalse(sidebar.isVisible())
        self.assertFalse(sidebar.is_panel_open(),
                         'the panel is hidden but still reports itself open, so '
                         'the rail button has to be pressed twice to open it again')
        self.assertIsNone(sidebar._filter_host,
                         'the application-level filter survived a hide that did not '
                         'go through hide_panel()')

        # A press in the window now reaches the widget underneath it.
        presses_before = content.press_count
        self._press_on(content)
        self.assertEqual(presses_before + 1, content.press_count,
                         'an invisible panel consumed a mouse press in the window')
        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible())

        # One toggle from here opens: the flag tracks visibility again.
        sidebar.toggle()
        self.assertTrue(sidebar.is_panel_open())
        self.assertTrue(sidebar.isVisible())

        # The other half of the gate: real visibility. Opening a panel whose
        # window is not shown -- Task 7 can restore the shell that way -- leaves
        # ``_is_open`` true and ``isVisible()`` false, and no ``QEvent.Hide`` ever
        # arrives to clear it. Only the visibility term in the gate stops that
        # state from eating a press posted into the hidden window.
        sidebar.hide_panel()
        parent.hide()
        self.app.processEvents()
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible(),
                         'the fixture lost its point: the panel is visible, so the '
                         'visibility term in the gate is not what is being tested')
        presses_before = content.press_count
        self._press_on(content)
        self.assertEqual(presses_before + 1, content.press_count,
                         'a panel that is open but not on screen consumed a press')

    def test_a_window_hide_show_round_trip_leaves_no_panel_on_screen(self):
        """The picture, not the flag: closed means nothing of the panel paints.

        Reproduce the route the render matrix walks on every frame boundary:
        open the panel, hide the top-level, show it again. ``hideEvent`` clears
        ``_is_open`` during the hide, but Qt's ``showChildren`` restores the
        child visibilities that were on screen at hide time -- no caller runs,
        no ``show_panel()``, and before the ``showEvent`` guard the panel was
        back on top of the list while every flag-level assertion in this file
        stayed green. ``is_panel_open()`` alone cannot see that state; a
        ``childAt`` on the panel's own geometry can.
        """
        from PyQt6.QtCore import QPoint

        sidebar, _manager, parent, content = self._sidebar()
        sidebar.set_libraries(_libraries(2))
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.isVisible(),
                        'the fixture never got the panel on screen')

        # A point inside the panel, clear of the footer rows: the panel's own
        # scroll viewport paints here, and with the panel gone the content area
        # must be what answers.
        panel_point = QPoint(sidebar.x() + sidebar.width() // 2,
                             sidebar.y() + sidebar.height() // 2)
        self.assertTrue(sidebar.rect().contains(
            sidebar.mapFromGlobal(parent.mapToGlobal(panel_point))),
            'the fixture point is not inside the panel')
        self.assertIsNot(content, parent.childAt(panel_point),
                         'the open panel does not cover the fixture point')

        parent.hide()
        self.app.processEvents()
        parent.show()
        self.app.processEvents()

        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible(),
                         'the panel survived a hide/show round trip on screen '
                         'while reporting itself closed -- the closed frame that '
                         'blanked the left 240 px of the playlist in the matrix')
        self.assertFalse(sidebar.isVisibleTo(parent))
        self.assertIs(content, parent.childAt(panel_point),
                      'something still paints over the list at the panel\'s '
                      'own geometry: the flag says closed, the pixels disagree')

        # And the rail button still works from here: one toggle opens.
        sidebar.toggle()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        self.assertTrue(sidebar.isVisible())

    def test_a_press_in_another_top_level_window_leaves_the_panel_alone(self):
        """A press in somebody else's window is neither eaten nor an outside click.

        The filter runs on the ``QApplication``, so it sees events for windows the
        panel does not belong to. The two shapes here are the ones this widget can
        actually meet: a dialog the panel *owns* -- the directory chooser
        ``_on_add_clicked`` opens with ``self`` as its parent, and a top-level
        keeps its owner in ``parentWidget()`` while being its own window -- and a
        window unrelated to the tree entirely. The fixture asserts the press point
        is clear of the panel, otherwise it is the position gate, not the window
        gate, doing the work.

        Measured on Qt 6.11: the old ``parent.isAncestorOf(watched)`` gate already
        let both cases through, because ``isAncestorOf`` stops at window
        boundaries. This is therefore a regression pin for the tightened gate, not
        the reproduction of a live dialog defect -- the counterpart that the new
        gate genuinely changes is
        :meth:`test_a_press_elsewhere_in_the_window_dismisses_outside_the_parent_subtree`.
        """
        from PyQt6.QtCore import QPoint, QPointF
        from PyQt6.QtWidgets import QDialog, QPushButton, QWidget

        for owned_by_panel in (True, False):
            with self.subTest(owned_by_panel=owned_by_panel):
                sidebar, _manager, parent, _content = self._sidebar()
                sidebar.set_libraries(_libraries(2))
                sidebar.show_panel()
                self.app.processEvents()

                other = (QDialog(sidebar) if owned_by_panel else QWidget())
                other.setObjectName('otherWindow')
                button = QPushButton('open', other)
                button.setObjectName('otherWindowButton')
                button.setGeometry(4, 4, 120, 30)
                other.resize(220, 90)
                other.show()
                self.app.processEvents()
                # Park it clear of the panel: an owned dialog is centred over its
                # owner by default, and a fixture that lands on top of the panel
                # would be exercising the position gate, not the window gate.
                other.move(parent.mapToGlobal(
                    QPoint(parent.width() - 220, parent.height() - 90)))
                self.app.processEvents()
                self.addCleanup(other.deleteLater)

                self.assertIsNot(other.window(), parent.window(),
                                 'the fixture put its "other window" inside the '
                                 "panel's own window")
                point = other.mapToGlobal(QPointF(button.x() + button.width() / 2,
                                                  button.y() + button.height() / 2)
                                          ).toPoint()
                self.assertFalse(sidebar.rect().contains(sidebar.mapFromGlobal(point)),
                                 'the other window sits on the panel, so the press '
                                 'point -- not the window gate -- decided the outcome')

                pressed = []
                button.pressed.connect(lambda: pressed.append(1))
                self._press_on(button)
                self.assertEqual([1], pressed,
                                 'the filter ate a press meant for another window')
                self.assertTrue(sidebar.is_panel_open(),
                                'a press in another top-level window collapsed the panel')

    def test_a_press_elsewhere_in_the_window_dismisses_outside_the_parent_subtree(self):
        """Task 7's shape: the panel floats in a content area with sibling widgets.

        Once the panel is parented to a *container* rather than to the window, the
        rail, the strip and the toast are siblings of that container -- inside the
        same window, outside its subtree. A press on any of them is an outside
        press and has to dismiss the panel; a subtree test would leave the panel
        floating over the list forever. Measured: with the gate on
        ``parent.isAncestorOf`` this fixture fails (the sibling is not a descendant
        of the container), which is what the window-identity gate changes.
        """
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        from view.widgets.library_sidebar import LibrarySidebar

        manager = make_manager('light')
        manager.apply_to(self.app)

        window = QWidget()
        window.resize(*PARENT_SIZE)
        inner = QVBoxLayout(window)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        # The content area the panel floats in: a child of the window, not the
        # window itself -- Task 7's shape.
        area = QWidget(window)
        area.setObjectName('contentAreaStandIn')
        area.setFixedHeight(520)
        # A rail/strip-shaped sibling: in the window, outside the area's subtree.
        sibling = _content_area_class()(window)
        sibling.setObjectName('siblingStandIn')
        sibling.setFixedSize(60, 60)
        inner.addWidget(area)
        inner.addWidget(sibling)
        window.show()
        self.app.processEvents()

        sidebar = LibrarySidebar(manager, area)
        self.addCleanup(sidebar.hide_panel)
        self.addCleanup(sidebar.deleteLater)
        self.addCleanup(window.deleteLater)
        # Off screen before they die -- see the note in ``_sidebar`` above.
        self.addCleanup(window.close)
        self.addCleanup(sidebar.close)
        sidebar.set_libraries(_libraries(2))
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        # The two halves of the fixture the gate is being tested against.
        self.assertFalse(area.isAncestorOf(sibling),
                         'the sibling ended up inside the parent subtree, so this '
                         'fixture no longer separates subtree from window')
        self.assertIs(sibling.window(), area.window(),
                      'the sibling is not in the same window as the panel')
        centre = sibling.mapToGlobal(QPoint(sibling.width() // 2,
                                           sibling.height() // 2))
        self.assertFalse(sidebar.rect().contains(sidebar.mapFromGlobal(centre)),
                         'the sibling sits under the panel, so the press point -- '
                         'not the window gate -- decided the outcome')

        presses_before = sibling.press_count
        self._press_on(sibling)
        self.assertFalse(sidebar.is_panel_open(),
                         'a press on a widget that shares the window but not the '
                         "parent's subtree left the panel floating")
        self.assertEqual(presses_before, sibling.press_count,
                         'the dismissing press was not consumed, so it also became '
                         'a click on that sibling')

    def test_click_outside_closes_panel(self):
        """A posted mouse press on the content area dismisses; one inside does not."""
        from PyQt6.QtWidgets import QPushButton

        sidebar, _manager, parent, content = self._sidebar()
        sidebar.set_libraries(_libraries(3))
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())

        rows = library_rows(sidebar)
        self._press_on(rows[0])
        self.assertTrue(sidebar.is_panel_open(),
                        'a press inside the panel dismissed it: the filter does not '
                        'check whether the press landed in its own geometry')
        self._press_on(sidebar)
        self.assertTrue(sidebar.is_panel_open(),
                        'a press on the panel frame itself dismissed it')

        emitted = []
        sidebar.library_selected.connect(emitted.append)
        presses_before = content.press_count
        self._press_on(content)
        self.assertFalse(sidebar.is_panel_open(),
                         'a press on the content area left the panel floating')
        self.assertFalse(sidebar.isVisible())
        self.assertEqual([], emitted,
                         'the dismissing press also reached a library row')
        self.assertEqual(presses_before, content.press_count,
                         'the dismissing press was delivered to the list as well, so '
                         'the filter dismisses without consuming')

        # The rail's library button is the case the filter has to *consume* for:
        # a press that is dismissed-but-delivered becomes a click on that button,
        # ``toggle()`` runs, and the panel re-opens behind the user's own click.
        toggle = QPushButton('toggle', parent)
        toggle.setGeometry(0, 0, 30, 30)      # left of the panel, outside its rect
        toggle.clicked.connect(sidebar.toggle)
        sidebar.show_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.is_panel_open())
        self._click_on(toggle)
        self.assertFalse(
            sidebar.is_panel_open(),
            'the click that dismissed the panel also reached its toggle, which '
            're-opened it -- the filter must consume the dismissing press')

    def test_add_entry_emits_path(self):
        """The footer entry opens a directory chooser and emits the chosen path.

        The chooser itself is stubbed: what is under test is the emit-and-cancel
        contract, not Qt's file list. That leaves the *window* the chooser opens
        uncovered here, which is
        :meth:`test_a_press_in_another_top_level_window_leaves_the_panel_alone`'s
        job -- the panel must neither eat the dialog's presses nor collapse under
        it, and a stubbed chooser cannot show that.
        """
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

    def test_manage_entry_emits_and_closes(self):
        """The footer's 管理媒体库 entry: the only route to the management dialog.

        spec §3.2's Task 8 correction gave the panel both administration entries,
        because §6 freezes the rail at seven actions and management is not one of
        them -- so if this row emitted nothing, adding *and* removing libraries
        would both be unreachable from the shipped shell.

        It also has to close the panel: the dialog the presenter opens is modal and
        this panel floats over the list, and a modal behind a floating overlay is
        the "看不见在放哪首" failure spec §11 lists.
        """
        sidebar, _manager, _parent, _content = self._sidebar()
        sidebar.set_libraries(_libraries(2))
        sidebar.show_panel()
        self.app.processEvents()

        emitted = []
        sidebar.manage_requested.connect(lambda: emitted.append(True))
        manage = manage_row(sidebar)
        self.assertIsNotNone(manage, 'the footer lost its 管理媒体库 entry')
        self.assertIsNone(manage.path,
                          'the management entry selects no library: it is not a row')

        manage.click()

        self.assertEqual([True], emitted,
                         'the 管理媒体库 entry emitted nothing: the dialog is '
                         'unreachable from the panel')
        self.assertFalse(sidebar.is_panel_open(),
                         'the panel is still floating behind a modal dialog')

    def test_the_two_footer_entries_are_independent(self):
        """Clicking one administration entry must not fire the other's route."""
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        sidebar, _manager, _parent, _content = self._sidebar()
        sidebar.set_libraries(_libraries(1))
        sidebar.show_panel()
        self.app.processEvents()

        add = add_row(sidebar)
        manage = manage_row(sidebar)
        self.assertIsNotNone(add)
        self.assertIsNotNone(manage)
        self.assertNotEqual(add.full_name, manage.full_name,
                            'both entries render, so both need distinct copy')

        added = []
        managed = []
        sidebar.add_library_requested.connect(added.append)
        sidebar.manage_requested.connect(lambda: managed.append(True))

        with mock.patch.object(QFileDialog, 'getExistingDirectory',
                               return_value='/media/second'):
            add.click()
        self.assertEqual(['/media/second'], added)
        self.assertEqual([], managed,
                         'the add entry opened the management dialog as well')

        sidebar.show_panel()
        manage.click()
        self.assertEqual(['/media/second'], added,
                         'the management entry went through the directory chooser')
        self.assertEqual([True], managed)

    def test_both_footer_entries_survive_an_empty_list(self):
        """spec §6 零媒体库首启: the empty state must not swallow the entries.

        With no library at all, the footer rows are the *only* way in -- the empty
        label sits in the scroll area above them, so a rebuild that hid them would
        strand a first-launch user outside the panel.
        """
        sidebar, _manager, _parent, _content = self._sidebar()
        sidebar.set_libraries(_libraries(3))
        sidebar.set_libraries([])
        sidebar.show_panel()
        # The three dropped rows are ``deleteLater`` candidates, not gone: until the
        # deferred deletes are delivered they answer ``findChildren`` and the empty
        # state would read as a list of three libraries.
        reap_deleted_rows()
        self.app.processEvents()

        for row in (add_row(sidebar), manage_row(sidebar)):
            self.assertIsNotNone(row, 'the footer entry vanished with the libraries')
            self.assertFalse(row.isHidden())
            self.assertTrue(row.isEnabled())
            self.assertTrue(row.text(), 'an unlabelled footer row is not discoverable')
        self.assertEqual([], library_rows(sidebar))


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class LibrarySidebarMainWindowTest(unittest.TestCase):
    """The panel as the shipped shell wears it -- the matrix' own construction.

    The standalone fixture above proves the widget contract; this class proves
    the same thing through ``MainWindow`` at the matrix' 1100x720 size, because
    the defect was photographed there: ``QListView`` geometry correct at full
    width, rows starting ~240 px in, i.e. a closed panel painting over the
    list's left region. The assertion that catches that shape is which widget
    is *topmost* at a point in that region -- a flag check passed on every one
    of the 236 tests while the pixels were wrong.
    """

    #: A point in the list's left region that the open panel covers: the panel
    #: sits at ``RAIL_WIDTH`` inside a ``content_stack`` that itself starts at
    #: ``RAIL_WIDTH``, so window x=150 is inside it and inside the list.
    PROBE = (150, 300)

    def setUp(self):
        self.app = make_app()

    def _window(self):
        from PyQt6.QtWidgets import QListView

        from view.main_window import MainWindow
        from view.widgets import LibrarySidebar

        manager = make_manager('light')
        manager.apply_to(self.app)
        window = MainWindow(manager)
        window.resize(1100, 720)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        sidebar = window.findChild(LibrarySidebar)
        self.addCleanup(sidebar.hide_panel)   # before the window dies
        return window, sidebar, window.findChild(QListView, 'playlistView')

    def test_closed_panel_paints_nothing_over_the_playlist(self):
        """Fresh launch and post-round-trip: the list's viewport is topmost."""
        from PyQt6.QtCore import QPoint

        window, sidebar, view = self._window()
        window.show()
        self.app.processEvents()

        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible(),
                         'the panel painted without ever being opened')
        self.assertFalse(sidebar.isVisibleTo(window))
        topmost = window.childAt(QPoint(*self.PROBE))
        self.assertIs(view.viewport(), topmost,
                      'something other than the playlist covers the list\'s '
                      'left region while the panel is closed')

        # The matrix' frame boundary: open, hide the window, show it again.
        # Before the ``showEvent`` guard the restore repainted the panel here.
        # Twelve libraries so the panel is tall enough to cover the probe --
        # the fixture guards that itself, or the open-half would assert nothing.
        window.set_libraries(_libraries(12))
        window.toggle_library_panel()
        self.app.processEvents()
        self.assertTrue(sidebar.isVisible())
        probe_local = sidebar.mapFrom(window, QPoint(*self.PROBE))
        self.assertTrue(sidebar.rect().contains(probe_local),
                        'the probe point is outside the open panel, so the '
                        'fixture no longer separates panel from playlist')
        self.assertTrue(sidebar.isAncestorOf(window.childAt(QPoint(*self.PROBE))),
                        'the open panel does not cover the probe point')
        window.hide()
        self.app.processEvents()
        window.show()
        self.app.processEvents()

        self.assertFalse(sidebar.is_panel_open())
        self.assertFalse(sidebar.isVisible(),
                         'the closed panel survived the window round trip on '
                         'screen -- the blank 240 px stripe in the matrix frame')
        self.assertFalse(sidebar.isVisibleTo(window))
        self.assertIs(view.viewport(), window.childAt(QPoint(*self.PROBE)),
                      'the restored panel still paints over the list')


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
        # Off screen before they die -- see the note in ``_sidebar`` above.
        self.addCleanup(parent.close)
        self.addCleanup(sidebar.close)
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

                # ``#libraryRow`` reserves a 2 px transparent ``border-left`` so the
                # current marker can paint without moving the text. ``border`` is a
                # shorthand and resets all four sides, so the focus ring must be
                # written per side or focusing a row shifts it by 2 px -- and, on
                # the current row, buries the ``accent`` marker under the ring.
                focus = block(qss, '#libraryRow:focus')
                for side in ('border-top', 'border-right', 'border-bottom'):
                    self.assertIn(f'{side}: 2px solid {tokens.focus_ring};', focus,
                                  f'{side} is missing from the focus ring')
                self.assertNotIn('\n    border:', focus,
                                 'the focus rule uses the ``border`` shorthand, which '
                                 'wipes the 2px border-left gutter the base rule '
                                 'reserves and covers the current marker')
                self.assertNotIn('border-left', focus,
                                 'the focus rule repaints the gutter instead of '
                                 'leaving it to the base and [current] rules')

        # The pairings this diff paints: the ``folder`` glyph (rasterised from
        # ``tokens.icon`` before QSS ever sees it), ``text_primary`` on the two
        # state fills, and the 2 px ``accent`` marker on the current row's
        # selection. Text and marker need a tuple too, because nothing else in
        # the contrast set checks a *state* fill -- ``TEXT_PAIRS`` only lists the
        # four resting surfaces. Same rule Task 3 recorded for the rail's seven
        # glyphs: a token that reaches a pixel needs a pin, not a comment.
        from tests.test_theme import ThemeContrastTest

        expected = (
            ('icon', 'selection_bg', 3.0),           # #libraryRow[current="true"]
            ('text_primary', 'hover_bg', 4.5),       # #libraryRow:hover
            ('text_primary', 'button_pressed', 4.5),  # #libraryRow:pressed
            ('accent', 'selection_bg', 3.0),         # the current marker, non-text
        )
        pinned = set(ThemeContrastTest.EXTRA_PAIRS)
        missing = [pair for pair in expected if pair not in pinned]
        self.assertEqual(
            [], missing,
            'a background this diff paints text or a glyph onto is not pinned in '
            f'ThemeContrastTest.EXTRA_PAIRS: {missing}. Deleting a tuple un-guards '
            'the pairing silently while the ratio still passes, so presence at the '
            'right bar is what is asserted here; the ratios themselves are evaluated '
            'by ThemeContrastTest.test_contrast_requirements over both themes.')

    def test_the_row_glyph_fits_the_row_box_it_claims(self):
        """The size the row's glyph is rasterised at, checked against its own box.

        ``_ROW_ICON_SIZE``'s comment derives 16 from ``ROW_HEIGHT`` less the
        sheet's vertical padding, and the same number feeds
        ``_ROW_TEXT_GUTTER`` (so it also moves the elide point). A comment that
        derives a constant is only worth what a test makes of it: this is the
        inequality the derivation claims, so a token change that lets the glyph
        outgrow its row fails here instead of clipping a name.
        """
        from core.theme import ROW_HEIGHT, SPACE_1

        from view.widgets.library_sidebar import _ROW_ICON_SIZE

        self.assertEqual(ROW_HEIGHT - 2 * SPACE_1, 20,
                         'the content box the comment describes is no longer 20 px; '
                         're-read the derivation before changing either number')
        self.assertLessEqual(_ROW_ICON_SIZE, ROW_HEIGHT - 2 * SPACE_1,
                             'the row glyph is larger than the box its own row '
                             'reserves after the sheet padding')
        self.assertGreater(_ROW_ICON_SIZE, 0)

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
