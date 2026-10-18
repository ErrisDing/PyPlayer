#!/usr/bin/env python3
"""
PyPlayer Toast

The timed result message of batch 2 (spec §5). Before this, one
``MainWindow.set_status_message`` slot carried three different kinds of thing --
progress, results and errors -- by rewriting the window title, which is why
spec §2's success criterion 3 ("the title is always the application name") needed
them pulled apart. Progress now lives on the icon-rail button that started it,
errors stay dialogs, and this widget is what "it worked" looks like: one line of
text for 2.5 seconds, then gone.

Two shape decisions, both the same ones ``LibrarySidebar`` made and for the same
reasons:

* **A child of the parent, not a top-level window.** A window-positioned toast has
  to be re-clamped when the window moves, can end up on another monitor, and joins
  the macOS window layering fight batch 2 is trying to stay out of. So it is a
  ``QFrame`` inside the parent's content area, placed above the control bar, and
  Task 7 parents it to the list container so "above the control bar" is the
  parent's own bottom edge rather than a hard-coded bar height.
* **Reuse instead of a queue.** ``show_toast`` sets the text and restarts the one
  timer, so "at most one toast" is structural rather than a policy the presenter
  has to remember: a second message *is* the first widget, re-titled and re-dated.
  Batch 2 has no message that needs to survive another one, and stacking three
  "Refreshed…" copies over the playlist would be the old title-bar problem with a
  nicer font.

It never takes the keyboard: ``WA_ShowWithoutActivating`` plus ``NoFocus`` on the
frame and the label, because a feedback overlay that interrupts a playlist
selection -- the user is mid-arrow-key -- is a defect. It is also transparent to
the mouse, so a toast cannot eat a click meant for the row under it.

Colour is the sheet's (``#toast`` / ``#toastText``, on the batch-1 tooltip tokens
so a toast and a tooltip read as the same kind of object); this widget owns no
stylesheet and needs no theme manager, since it draws no glyph.
"""

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from core.theme import SPACE_2, SPACE_3

#: spec §5: a result message is on screen for 2.5 seconds.
DEFAULT_MSEC = 2500

#: The gap kept from the parent's bottom edge -- one ``SPACE_3``, which is the
#: sheet's own small gutter and the only room a floating strip needs to look
#: floating rather than glued on.
_BOTTOM_GAP = SPACE_3

#: And from each side, so a long message wraps instead of running under the frame.
_SIDE_GAP = 2 * SPACE_3


class Toast(QFrame):
    """One timed feedback line, floating inside its parent.

    Args:
        parent: The widget the toast floats in. Required: without one
            :meth:`show_toast` has nothing to position against, and making the
            toast a top-level window then would be the failure this class exists
            to avoid, so it warns and stays hidden instead.
        timer_factory: Callable returning a ``QTimer``-shaped object
            (``setSingleShot``, ``start``, ``stop``, ``timeout``). Injectable so the
            auto-dismissal chain is testable on a fake clock -- the suite must not
            wait 2.5 real seconds for it. The widget, not the factory, configures
            single-shot behaviour, so a stand-in timer cannot silently become
            repeating.

    There are no signals: a toast is output, and nothing in the app reacts to one
    disappearing.
    """

    def __init__(self, parent: QWidget,
                 timer_factory: Optional[Callable[[], object]] = None):
        super().__init__(parent)
        self._message = ''

        self.setObjectName('toast')
        self.setFrameShape(QFrame.Shape.NoFrame)
        # The sheet paints this frame, the window must not be activated by showing
        # it, and a click must pass straight through it.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel('', self)
        self._label.setObjectName('toastText')
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A result message is worth wrapping; an elided one can hide the number the
        # message exists to report.
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._label)

        self._timer = (timer_factory or QTimer)()
        # One shot: dismissal happens once per message. A repeating timer would
        # re-fire ``dismiss`` forever, which is harmless here and wrong by principle.
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self.hide()

    # === Public API ===

    def show_toast(self, message: str, msec: int = DEFAULT_MSEC) -> None:
        """Show ``message`` for ``msec``, replacing whatever was showing.

        The reuse *is* the "at most one" requirement: the text changes, the widget
        does not multiply, and the timer is stopped and restarted so the second
        message gets its own full interval instead of inheriting the first
        message's remaining third of a second.
        """
        parent = self.parentWidget()
        if parent is None:
            print('Warning: Toast has no parent; the message is not shown '
                  f'({message!r}). A toast floats inside a window on purpose.')
            return

        self._message = message
        self._label.setText(message)
        self._place(parent)
        self.show()
        self.raise_()
        self._timer.stop()
        self._timer.start(msec)

    def dismiss(self) -> None:
        """Hide the toast and stop its timer. Idempotent."""
        self._timer.stop()
        self.hide()

    def current_message(self) -> str:
        """The text the toast holds, or ``''`` before the first message.

        Kept after :meth:`dismiss` -- it is still what was last shown, and the next
        identical message costs no re-layout.
        """
        return self._message

    # === Placement ===

    def _place(self, parent: QWidget) -> None:
        """Bottom-centred in the parent, ``SPACE_3`` above its bottom edge."""
        available_width = max(0, parent.width() - 2 * _SIDE_GAP)
        self._label.setMaximumWidth(available_width)
        self.adjustSize()
        width = min(self.width(), available_width + 2 * SPACE_2)
        height = self.height()
        self.setGeometry(max(0, (parent.width() - width) // 2),
                         max(0, parent.height() - height - _BOTTOM_GAP),
                         width, height)
