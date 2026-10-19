#!/usr/bin/env python3
"""Tests for ``view.widgets.toast.Toast`` (batch 2, Task 6).

The toast is where spec §5 sends every *result* message the old
``set_status_message`` wrote into the window title ("Refreshed 128 files from 2
libraries", "Switched to library: X"). Progress goes to the rail button and errors
stay dialogs; this widget only answers "did that work", for 2.5 seconds.

The three things worth failing on:

* **At most one, by construction.** ``show_toast`` reuses the instance: it changes
  the text and restarts the timer. A queue of toasts would need a second widget, so
  :meth:`test_second_toast_replaces_first` counts the *visible* ``#toast`` objects in
  the parent, not just the text -- a re-titled second widget passes the text
  assertion and fails this one.
* **The timer is the dismissal, and it is measured on a fake clock.** The brief
  forbids ``QTest.qWait``-ing a real 2.5 s in the suite, so ``timer_factory`` is
  injectable and :meth:`test_toast_auto_dismisses` asserts the whole chain: single
  shot, the requested interval, restart on the second message, ``timeout`` wired to
  ``dismiss``, and ``dismiss`` stopping the timer.
* **A child, not a window, and it does not take focus.** A top-level toast would
  have to be tracked across monitors and re-stacked on macOS (the same reason
  ``LibrarySidebar`` floats inside the parent). ``WA_ShowWithoutActivating``,
  ``WA_TransparentForMouseEvents`` and ``NoFocus`` are asserted alongside
  ``focusWidget()``, because the focus call alone is green for a widget that never
  asks for focus and for one that grabs it.

``#toast`` / ``#toastText`` are styled in ``core/theme_qss.py`` but not registered
in ``REQUIRED_OBJECT_NAMES`` in this task (Task 7's ruling); the names and the
"one stylesheet in the repo" invariant are asserted here.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_toast -v
"""
import sys
import unittest
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

PARENT_SIZE = (820, 600)


class FakeTimer:
    """The ``QTimer`` surface :class:`view.widgets.toast.Toast` uses, on a rail.

    Deliberately *not* a ``QObject``: the widget must work against the four members
    it actually touches (``setSingleShot``, ``start``, ``stop``, ``timeout``), and a
    plain class makes a fifth call (``setInterval``, ``start()`` with no argument,
    ``isActive``) fail loudly instead of quietly working on a real timer.
    """

    def __init__(self):
        self.timeout_handlers = []
        self.single = None
        self.interval = None
        self.starts = 0
        self.stops = 0

    # === the QTimer surface the widget may use ===

    def setSingleShot(self, single):
        self.single = single

    def start(self, msec):
        self.starts += 1
        self.interval = msec

    def stop(self):
        self.stops += 1
        self.interval = None

    @property
    def timeout(self):
        return _Signal(self)

    # === the test's clock ===

    def advance(self):
        """Fire the timer the way Qt would: emit, and leave the interval to ``stop``."""
        assert self.interval is not None, 'nothing was scheduled to fire'
        for handler in list(self.timeout_handlers):
            handler()


class _Signal:
    """``timeout.connect`` stand-in."""

    def __init__(self, owner):
        self._owner = owner

    def connect(self, handler):
        self._owner.timeout_handlers.append(handler)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ToastTest(unittest.TestCase):
    """One instance, a restartable timer, no focus, no queue."""

    def setUp(self):
        self.app = make_app()

    def _parent(self, width=PARENT_SIZE[0], height=PARENT_SIZE[1]):
        """A shown window with a focusable widget that keeps the focus."""
        from PyQt6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

        window = QWidget()
        window.resize(width, height)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        focusable = QLineEdit(window)
        focusable.setObjectName('focusHolder')
        layout.addWidget(focusable)
        window.show()
        self.app.processEvents()
        focusable.setFocus()
        self.app.processEvents()
        self.addCleanup(window.deleteLater)
        return window, focusable

    def _toast(self, parent, timer_factory=None):
        """A toast on ``parent``, plus the list of every timer object it was handed.

        ``timer_factory`` is the injectable clock the brief asks for; the wrapper
        records each instance, so "one timer, reused" is a measurement rather than a
        reading of a private attribute.
        """
        from view.widgets.toast import Toast

        manager = make_manager('light')
        manager.apply_to(self.app)
        self.addCleanup(manager.deleteLater)

        timers = []
        inner = timer_factory or FakeTimer

        def factory():
            timer = inner()
            timers.append(timer)
            return timer

        toast = Toast(parent, timer_factory=factory)
        self.addCleanup(toast.deleteLater)
        self.app.processEvents()
        return toast, timers

    # === Step 1 tests ===

    def test_show_toast_sets_text_and_visible(self):
        from PyQt6.QtWidgets import QLabel

        window, _focus = self._parent()
        toast, timers = self._toast(window)

        self.assertFalse(toast.isVisible(), 'a fresh toast is not on screen')
        self.assertEqual('', toast.current_message())

        toast.show_toast('已刷新：128 个文件')
        self.app.processEvents()

        self.assertTrue(toast.isVisible())
        self.assertEqual('已刷新：128 个文件', toast.current_message())
        label = toast.findChild(QLabel, 'toastText')
        self.assertIsNotNone(label, '#toastText is missing')
        self.assertEqual('已刷新：128 个文件', label.text())
        self.assertEqual('toast', toast.objectName())
        self.assertEqual(1, timers[0].starts, 'the timer was not started')

        # spec §5's geometry: bottom-centred, one SPACE_3 above the parent's bottom
        # edge (Task 7 parents the toast to the list container, whose bottom edge is
        # the control bar's top).
        from core.theme import SPACE_3

        # Brief Step 3 shape decision, asserted structurally: the toast is a child
        # of the parent, not a top-level window. The geometry and focus assertions
        # below also break under a window-flagged toast, but for reasons that are
        # easy to argue away as coincidence; these two cannot.
        self.assertIs(window, toast.parentWidget())
        self.assertFalse(toast.isWindow(),
                         'the toast is a top-level window; it must float *inside* '
                         'the parent (see the module docstring)')
        self.assertEqual(SPACE_3, window.height() - (toast.y() + toast.height()),
                         'the toast is not floating SPACE_3 above the control bar')
        self.assertLessEqual(
            abs(toast.x() - (window.width() - toast.width()) // 2), 1,
            'the toast is not centred in the content area')
        self.assertGreaterEqual(toast.x(), 0)
        self.assertLessEqual(toast.x() + toast.width(), window.width() + 1)

    def test_second_toast_replaces_first(self):
        """At most one toast: the second message reuses the widget."""
        window, _focus = self._parent()
        toast, _timers = self._toast(window)

        toast.show_toast('first')
        toast.show_toast('second')
        self.app.processEvents()

        self.assertEqual('second', toast.current_message())
        from PyQt6.QtWidgets import QFrame

        instances = [widget for widget in window.findChildren(QFrame, 'toast')
                     if widget.isVisible()]
        self.assertEqual(1, len(instances),
                         'a queue of toasts: the second message built a second widget')
        self.assertIs(toast, instances[0])
        # The one instance is the one that answers, and it is the same object.
        self.assertEqual('second', instances[0].current_message())

    def test_toast_auto_dismisses(self):
        """The injectable clock, not a real 2.5 s wait."""
        window, _focus = self._parent()
        toast, timers = self._toast(window)
        self.assertEqual(1, len(timers), 'the toast built its timer lazily or twice')
        self.assertTrue(timers[0].single,
                        'a repeating timer re-fires; dismissal is one shot')

        toast.show_toast('background set')
        timer = timers[0]
        self.assertEqual(2500, timer.interval,
                         'spec §5 sets the result feedback at 2.5 s')
        self.assertTrue(toast.isVisible())
        timer.advance()
        self.assertFalse(toast.isVisible(), 'the timer fired and the toast stayed up')
        self.assertIsNone(timer.interval,
                          'dismiss() did not stop the timer')

        # The per-message interval, and the restart on the second message.
        toast.show_toast('short', msec=400)
        self.assertEqual(400, timer.interval)
        restarts = timer.starts
        toast.show_toast('longer')
        self.assertEqual(restarts + 1, timer.starts,
                         'the second message did not restart the timer, so it keeps '
                         'the remaining time of the first one')
        self.assertEqual(2500, timer.interval)
        self.assertEqual(1, len(timers),
                         'the second message built a second timer -- and so, a second toast')
        timer.advance()
        self.assertFalse(toast.isVisible())

    def test_dismiss_is_idempotent(self):
        window, _focus = self._parent()
        toast, timers = self._toast(window)

        toast.dismiss()                      # never shown
        toast.show_toast('message')
        toast.dismiss()
        toast.dismiss()                      # already gone
        self.assertFalse(toast.isVisible())
        self.assertIsNone(timers[0].interval, 'a second dismiss re-started the timer')
        self.assertEqual(1, timers[0].starts)

    def test_toast_does_not_steal_focus(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel

        window, focusable = self._parent()
        toast, _timers = self._toast(window)
        self.assertIs(focusable, self.app.focusWidget(),
                      'the harness lost the focus it is meant to protect')

        toast.show_toast('switched library')
        self.app.processEvents()

        self.assertIs(focusable, self.app.focusWidget(),
                      'the toast took the keyboard away from the playlist')
        self.assertFalse(toast.hasFocus())
        for widget in [toast, toast.findChild(QLabel, 'toastText')]:
            self.assertEqual(Qt.FocusPolicy.NoFocus, widget.focusPolicy(),
                             f'{type(widget).__name__}#{widget.objectName()} can be '
                             'tabbed into')
        self.assertTrue(toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating),
                        'showing a toast must not activate the window')
        self.assertTrue(toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
                        'a toast that swallows a click is a toast in the way')

    def test_the_toast_is_named_and_styled_by_the_sheet(self):
        """``#toast`` / ``#toastText`` rules exist, come from tokens, and are the only source."""
        import re

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget

        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        def block(qss, selector):
            match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', qss)
            self.assertIsNotNone(match, f'no rule block for {selector!r}')
            return match.group(1)

        for theme_name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            qss = build_qss(tokens, AlphaSettings())
            with self.subTest(theme=theme_name):
                for selector in ('#toast', '#toastText'):
                    self.assertIn(f'\n{selector} {{', qss,
                                  f'{selector} is missing; the overlay would be '
                                  'painted in palette colours')
                # Batch 1 decided the floating language: tooltip colours, so the
                # toast and a tooltip read as the same kind of thing.
                self.assertIn(f'background-color: {tokens.tooltip_bg};', block(qss, '#toast'))
                self.assertIn(f'color: {tokens.tooltip_text};', block(qss, '#toast'))
                self.assertIn(f'color: {tokens.tooltip_text};', block(qss, '#toastText'))

        window, _focus = self._parent()
        toast, _timers = self._toast(window)
        self.assertEqual('', toast.styleSheet())
        for child in toast.findChildren(QWidget):
            self.assertEqual('', child.styleSheet(),
                             f'{type(child).__name__}#{child.objectName()} carries '
                             'an inline sheet')
        self.assertTrue(toast.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
                        'without the attribute the #toast fill never paints')


if __name__ == '__main__':
    unittest.main(verbosity=2)
