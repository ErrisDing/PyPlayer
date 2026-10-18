#!/usr/bin/env python3
"""
PyPlayer Action Rail

The 56 px icon column that replaces the native menu bar (batch 2 spec §2, §3.2,
§6). Everything the menu used to hold is now a button here: the media-library
panel toggle, open file, open folder, refresh this library, refresh every
library, the appearance dialog and the about box. "Exit" deliberately stays off
the rail (spec §6), and the floating panel owns *choosing* and *adding* a
library so the same action never appears in two places (spec §3.2).

Two constraints shape this widget:

* **The tooltip is the only text.** Once ``MainWindow._setup_menu()`` is deleted
  in Task 7 there is no menu title and no status-bar copy left to explain a
  glyph, so every button's tooltip comes from ``rail.<action_id>`` in both
  locale files, and ``tests/test_action_rail.py`` asserts it for both locales.
  A missing tooltip is a defect, not a rough edge.
* **The glyphs are beyond QSS's reach.** They are pixmaps rasterised from
  ``resource/icons`` through :func:`view.icons.icon` with a token colour, so a
  theme flip has to come back through :meth:`recolor` -- the same reason
  ``BottomPanel`` still has one. Everything else (fills, borders, radii, the
  running-state tint) is ``#actionRail`` / ``#railButton`` in
  ``core/theme_qss.py``; this widget owns no stylesheet.

Progress state is a *function of state*, not a saved icon: :attr:`_running`
holds the ids that are in flight, :meth:`_glyph_for` answers ``refresh`` for
those and the resting glyph for the rest, and :meth:`_refresh_states` reapplies
both to every button. That is why ``set_progress`` is idempotent (a retried scan
cannot overwrite a resting glyph with a spinner) and why the mutual exclusion
between the two refresh entries -- they walk one library-loading path, so
starting either must close the other, spec §6 -- is expressed once, in
:data:`_BLOCKED_PAIR`, rather than in paired enable/disable calls.
"""

from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from core import i18n
from core.theme import RAIL_WIDTH, SPACE_1, SPACE_2, TRANSPORT_SIZE
from view.icons import icon

# The seven action ids. Values are the wire format: the presenter dispatches on
# them (Task 7 connects ``action_triggered`` to a dict keyed by exactly these),
# so they are constants here and literals in the tests, never derived.
ACTION_LIBRARY = 'library'
ACTION_OPEN_FILE = 'open_file'
ACTION_OPEN_FOLDER = 'open_folder'
ACTION_REFRESH = 'refresh'
ACTION_REFRESH_ALL = 'refresh_all'
ACTION_APPEARANCE = 'appearance'
ACTION_ABOUT = 'about'

#: Rail order, and the contract with ``MainWindow``/presenter. The library entry
#: is first because it is the panel toggle, i.e. the widget that decides what the
#: other six act on; appearance and about sit below the stretch.
ACTION_IDS: tuple[str, ...] = (
    ACTION_LIBRARY,
    ACTION_OPEN_FILE,
    ACTION_OPEN_FOLDER,
    ACTION_REFRESH,
    ACTION_REFRESH_ALL,
    ACTION_APPEARANCE,
    ACTION_ABOUT,
)

# action id -> glyph in ``resource/icons``. ``add`` is authored by this task but
# belongs to Task 4's panel footer, so it is deliberately absent here; the price
# is that ``folder`` serves both the library toggle and "open folder", which is
# the least confusing of the collisions the seven-files/seven-actions count
# leaves open (a media library *is* a folder, and Task 4's rows carry the same
# glyph for the same object). ``tests/test_action_rail.py`` pins this table by
# name, so trading two glyphs between buttons fails a test.
_ACTION_GLYPHS = {
    ACTION_LIBRARY: 'folder',
    ACTION_OPEN_FILE: 'file',
    ACTION_OPEN_FOLDER: 'folder',
    ACTION_REFRESH: 'refresh',
    ACTION_REFRESH_ALL: 'refresh_all',
    ACTION_APPEARANCE: 'settings',
    ACTION_ABOUT: 'info',
}

# The running state reuses ``refresh`` rather than adding an eighth file, so a
# button in flight is legible as "the library scan is going on here".
_PROGRESS_GLYPH = 'refresh'

# Only the shortcuts the rail inherits from the deleted File menu. Ctrl+Q has no
# rail button (spec §6 keeps Exit off the rail), so Task 7 owns that one.
_SHORTCUTS = {
    ACTION_OPEN_FILE: QKeySequence.StandardKey.Open,
}

# Mutual exclusion, symmetric by construction: refreshing every library walks
# the same per-library scan that refreshing one does, so neither entry point may
# be open while the other is in flight.
_BLOCKED_PAIR = {
    ACTION_REFRESH_ALL: (ACTION_REFRESH,),
    ACTION_REFRESH: (ACTION_REFRESH_ALL,),
}

# The glyph size, derived from the transport token so a rail button and a
# transport button are one object (``TRANSPORT_SIZE`` squares inside a
# ``RAIL_WIDTH`` column, ``TRANSPORT_SIZE // 2`` of ink inside both).
RAIL_ICON_SIZE = TRANSPORT_SIZE // 2


class ActionRail(QWidget):
    """Icon-only command column for the seven rail actions.

    Args:
        manager: The running :class:`view.theme_manager.ThemeManager`; only
            ``tokens`` is read, for the glyph colour. ``MainWindow.recolor``
            forwards every ``theme_changed`` into :meth:`recolor`.
        parent: Standard Qt parent. The widget is not constructed by
            ``MainWindow`` until Task 7.

    Signals:
        action_triggered(str): One of :data:`ACTION_IDS` except
            :data:`ACTION_LIBRARY`; the presenter maps these to the slots the
            menu actions used to call directly.
        library_panel_requested: The library button was pressed. Deliberately a
            second signal and not an ``action_triggered(ACTION_LIBRARY)``: the
            panel is a view-mode toggle owned by the window, not a presenter
            action (spec §3.2).
    """

    action_triggered = pyqtSignal(str)
    library_panel_requested = pyqtSignal()

    def __init__(self, manager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = manager
        self._tokens = manager.tokens
        self._buttons: dict[str, QToolButton] = {}
        self._actions: dict[str, QAction] = {}
        self._running: set[str] = set()

        # ``#actionRail`` carries the surface_alt fill and the right-hand
        # divider; WA_StyledBackground is what makes a QWidget subclass paint a
        # QSS background at all.
        self.setObjectName('actionRail')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_1)
        for action_id in ACTION_IDS:
            # The two window-level entries (外观 / 关于) sink to the bottom of
            # the column, away from the file actions they are never confused for.
            if action_id == ACTION_APPEARANCE:
                layout.addStretch(1)
            layout.addWidget(self._make_button(action_id), 0,
                             Qt.AlignmentFlag.AlignHCenter)

        self._generate_icons()

    # === Construction ===

    def _make_button(self, action_id: str) -> QToolButton:
        """One icon-only button, driven by a ``QAction`` that lives on the rail.

        The action carries the tooltip, the icon and (for open-file) the
        shortcut, and it is attached to *this* widget with
        :meth:`QWidget.addAction` so the shortcut is reachable wherever the
        focus is; ``setDefaultAction`` then mirrors all of it onto the button,
        including the enabled state, which is what makes :meth:`set_progress`
        able to disable a button without touching the button itself.

        ``action.triggered`` is the one emission point, and it has to be the one
        that is connected. Attaching the action only *delivers* the shortcut to
        ``QAction.trigger()`` -- nothing reaches this widget's signals unless
        ``triggered`` itself is listened to, so a ``button.clicked`` connect
        leaves ``Ctrl+O`` inert while every mouse test stays green. Wiring the
        action instead costs nothing on the mouse path, because a click on a
        default-action button triggers the action before ``clicked`` is emitted;
        connecting both would emit twice.
        """
        button = QToolButton(self)
        button.setObjectName('railButton')
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(TRANSPORT_SIZE, TRANSPORT_SIZE)
        button.setIconSize(QSize(RAIL_ICON_SIZE, RAIL_ICON_SIZE))
        # Flat until hovered: the sheet paints the hover/pressed fills, and
        # autoRaise keeps Fusion from drawing a button bevel the sheet would
        # have to fight.
        button.setAutoRaise(True)
        # Declared up front so ``#railButton[running="true"]`` has a property to
        # match from the first paint, and so a reader can grep the state name.
        button.setProperty('running', 'false')

        tip = i18n.get(f'rail.{action_id}')
        action = QAction(self)
        action.setObjectName(action_id)      # what the shortcut test looks up
        action.setText(tip)
        action.setToolTip(tip)
        shortcut = _SHORTCUTS.get(action_id)
        if shortcut is not None:
            action.setShortcut(shortcut)
        self.addAction(action)

        button.setDefaultAction(action)
        # The action, never the button: one connection serves both the mouse and
        # the keyboard (see :meth:`_make_button`), and it is the reason
        # :meth:`set_progress` disabling the action also silences the shortcut --
        # ``QAction.activate()`` returns before emitting on a disabled action.
        action.triggered.connect(lambda checked=False: self._on_clicked(action_id))

        self._buttons[action_id] = button
        self._actions[action_id] = action
        return button

    # === State ===

    def button_for(self, action_id: str) -> QToolButton:
        """The button owning ``action_id``. ``ValueError`` for an unknown id.

        Public because the tests and ``MainWindow`` (Task 7) need to reach one
        button without walking the layout.
        """
        try:
            return self._buttons[action_id]
        except KeyError:
            raise ValueError(self._unknown_id(action_id)) from None

    def set_progress(self, action_id: str, running: bool) -> None:
        """Put ``action_id`` into (or out of) its running state.

        Running means: the button shows the progress glyph, carries
        ``running="true"`` for the sheet, and is disabled; the ids paired with
        it in :data:`_BLOCKED_PAIR` are disabled too but keep their own glyph,
        because they are blocked, not working.

        Raises:
            ValueError: an unknown ``action_id``. A typo in a presenter call has
                to fail loudly -- a silently ignored progress report is a button
                that never spins.
        """
        if action_id not in self._buttons:
            raise ValueError(self._unknown_id(action_id))
        if running:
            self._running.add(action_id)
        else:
            self._running.discard(action_id)
        self._refresh_states()

    def is_running(self, action_id: str) -> bool:
        """Whether ``action_id`` is currently in flight."""
        if action_id not in self._buttons:
            raise ValueError(self._unknown_id(action_id))
        return action_id in self._running

    @staticmethod
    def _unknown_id(action_id: str) -> str:
        return (f'Unknown rail action: {action_id!r} '
                f'(expected one of {", ".join(ACTION_IDS)})')

    def _blocked_ids(self) -> set[str]:
        """Everything that may not be clicked right now."""
        blocked = set(self._running)
        for started in self._running:
            blocked.update(_BLOCKED_PAIR.get(started, ()))
        return blocked

    def _glyph_for(self, action_id: str) -> str:
        return _PROGRESS_GLYPH if action_id in self._running else _ACTION_GLYPHS[action_id]

    def _refresh_states(self) -> None:
        """Reapply glyph, enabled state and the ``running`` property everywhere.

        One pass over the whole rail rather than a delta for the id that changed:
        the blocked set is a function of :attr:`_running`, so recomputing it is
        both simpler and the reason two nested ``set_progress`` calls cannot
        strand a button.
        """
        blocked = self._blocked_ids()
        for action_id, action in self._actions.items():
            running = action_id in self._running
            action.setEnabled(action_id not in blocked)
            action.setIcon(self._icon_for(action_id))
            button = self._buttons[action_id]
            if button.property('running') != ('true' if running else 'false'):
                # Strings, not bools: the QSS attribute selector is written
                # against ``running="true"`` and the widget tree declares its
                # properties as strings (same contract as the library chips).
                button.setProperty('running', 'true' if running else 'false')
                style = button.style()
                style.unpolish(button)
                style.polish(button)

    # === Icons ===

    def _icon_for(self, action_id: str):
        """The current glyph for one action, in the resting or running colour."""
        return icon(self._glyph_for(action_id), self._tokens.icon,
                    RAIL_ICON_SIZE, self.devicePixelRatioF())

    def _generate_icons(self) -> None:
        for action_id in ACTION_IDS:
            self._actions[action_id].setIcon(self._icon_for(action_id))

    def recolor(self, tokens) -> None:
        """Regenerate every glyph for a new theme (``MainWindow.recolor``)."""
        self._tokens = tokens
        self._generate_icons()

    # === Slots ===

    def _on_clicked(self, action_id: str) -> None:
        if action_id == ACTION_LIBRARY:
            self.library_panel_requested.emit()
        else:
            self.action_triggered.emit(action_id)
