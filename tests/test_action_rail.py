#!/usr/bin/env python3
"""Tests for ``view.widgets.action_rail.ActionRail`` (batch 2, Task 3).

The rail replaces the menu bar, so everything the menu used to say has to be
carried by a 20 px glyph plus a tooltip. That makes the contract here mostly
about *text and state* rather than pixels:

* the seven action ids are the interface the presenter dispatches on, so they
  are pinned as a literal transcription of the brief, never derived from the
  module (a rename on the widget side would otherwise follow itself);
* every emission is driven through the ``QAction``, not only through the button.
  ``QAction.triggered`` is the single connection point, because that is what both
  a click and ``Ctrl+O`` reach: wiring ``button.clicked`` instead leaves the
  shortcut inert while the mouse tests stay green, and wiring both emits twice.
  One test therefore calls ``activate(Trigger)`` (the reason Qt's own shortcut
  machinery uses) and another asserts that a *disabled* action emits nothing, so
  the progress blocking covers the keyboard as well as the pointer;
* every action has a non-empty tooltip in **both** locales -- spec §6 makes a
  missing tooltip a defect, not a nicety, because once ``_setup_menu()`` is gone
  in Task 7 the tooltip is the only textual affordance these icons will ever
  have;
* the progress state is mutually exclusive between ``refresh`` and
  ``refresh_all`` (they share one library-loading path, spec §6), and an unknown
  ``action_id`` raises instead of being ignored;
* the glyphs are rasterised through :func:`view.icons.icon` from theme tokens,
  so a theme flip has to reach them (QSS cannot recolour a pixmap).

Two assertions run at the *name* level rather than the pixel level, because
batch 1 learned the difference (``tests/test_icons.py``, finding 3): which glyph
lands on which button is wiring, and two same-coloured glyphs traded between
buttons survive every colour assertion. ``test_each_button_draws_its_declared_
glyph`` therefore patches the module's ``icon`` symbol and reads the names back.

The objectName/QSS pair is asserted here and *not* through
``core.theme_qss.REQUIRED_OBJECT_NAMES``: that tuple's other consumer,
``tests/test_view_structure.py::test_every_required_object_name_exists``, walks
the live ``MainWindow`` tree, and the rail only enters that tree in Task 7. A
stylesheet rule naming a widget that is not in the tree yet is inert; a
registered name with no widget in the tree is a red test. Task 7 registers all
four new widgets' names in one go.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_action_rail -v
"""
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

# The seven ids, in rail order, transcribed from the brief's Interfaces block.
# Deliberately a literal: deriving it from the module's ``ACTION_IDS`` would
# make the uniqueness test true by construction.
ACTION_IDS = (
    'library', 'open_file', 'open_folder', 'refresh', 'refresh_all',
    'appearance', 'about',
)

# Which glyph each action draws. ``library`` and ``open_folder`` share
# ``folder``: the plan allocates seven files to seven actions but earmarks
# ``add`` for Task 4's panel footer, so exactly one collision is unavoidable,
# and this is the least confusing pair -- a media library *is* a folder, and
# Task 4's sidebar rows carry the same glyph for the same object. ``add`` is
# authored by this task and deliberately unused on the rail.
ACTION_GLYPHS = {
    'library': 'folder',
    'open_file': 'file',
    'open_folder': 'folder',
    'refresh': 'refresh',
    'refresh_all': 'refresh_all',
    'appearance': 'settings',
    'about': 'info',
}

# The seven resource files this task authors. Literal again, so a rename on
# either side fails a test instead of following itself.
RAIL_ICON_NAMES = (
    'file', 'folder', 'refresh', 'refresh_all', 'settings', 'info', 'add',
)

ICONS_DIR = ROOT / 'resource' / 'icons'
LOCALES = ('zh_CN', 'en_US')


def _action_trigger():
    """``QAction.ActionEvent.Trigger`` on every PyQt6 this repo allows.

    ``QAction.ActionEvent`` is Qt 6.9+; ``requirements.txt`` floors the
    dependency at ``PyQt6>=6.5.0``, and ``QT_AVAILABLE`` is an import check,
    not a version check -- a bare ``QAction.ActionEvent.Trigger`` therefore
    raises ``AttributeError`` on 6.5-6.8 instead of skipping. Those versions
    spell the same value ``QAction.Activation.Trigger``, and 6.9+ drops
    ``Activation``, so *both* names must be probed lazily: the obvious
    ``getattr(QAction, 'ActionEvent', QAction.Activation)`` evaluates its
    default eagerly and dies on exactly the newest Qt the repo runs (measured
    here on 6.11). This is the guarded form the ledger's deferred minor asked
    Task 7 to land before the idiom is reused anywhere (Task 7's own shortcut
    tests drive real ``QKeyEvent``s instead, so the guard has exactly these
    two consumers).
    """
    from PyQt6.QtGui import QAction

    action_event = getattr(QAction, 'ActionEvent', None)
    if action_event is None:  # PyQt6 6.5-6.8
        action_event = QAction.Activation
    return action_event.Trigger

# Anything that reaches outside the file (same list ``tests/test_icons.py`` uses).
# The SVG namespace URI is removed before the scan, so it is the one URL an
# authored file may keep.
FORBIDDEN_NEEDLES = ('xlink:href', 'http://', 'https://', 'url(', '<![CDATA',
                     '<!ENTITY', '@import', '<image', '<script', '<style',
                     '<use', '<filter', '<foreignObject')


def _token(hex_color: str) -> str:
    """A ``#rrggbb`` token in the exact spelling ``QColor.name()`` reports."""
    from PyQt6.QtGui import QColor

    return QColor(hex_color).name().lower()


def _dominant_colour(pixmap):
    """The modal *fully covered* colour of a rasterised glyph.

    Batch 1's helper of the same name counts pixels above 50% alpha, which is
    right for the transport row's solid triangles but not for this set: a
    rail glyph is 20 px of a 24-unit box, so a 2-unit stroke is 1.67 px wide and
    most of its pixels are partial. ``QImage.pixelColor`` un-premultiplies those,
    and the rounding lands a token ``#444444`` on ``#454545`` -- measured on
    ``settings`` and ``add``, whose partial track pixels outnumber their interior
    ones. Counting only opaque pixels keeps the assertion about *which colour*
    was requested instead of about antialiasing arithmetic.
    """
    if pixmap is None or pixmap.isNull():
        return None
    image = pixmap.toImage()
    counts = Counter(
        image.pixelColor(x, y).name().lower()
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() >= 250
    )
    return counts.most_common(1)[0][0] if counts else None


def _fingerprint(pixmap):
    """1-bit shape signature, so two glyph names can be told apart."""
    image = pixmap.toImage()
    return bytes(1 if image.pixelColor(x, y).alpha() > 128 else 0
                 for y in range(image.height()) for x in range(image.width()))


def _block(qss: str, selector: str) -> str:
    """Declaration body of the rule whose selector is exactly ``selector``."""
    match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', qss)
    assert match, f'no rule block for {selector!r}'
    return match.group(1)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ActionRailContractTest(unittest.TestCase):
    """Ids, tooltips, signals, width: the presenter-visible surface."""

    def setUp(self):
        from core import i18n

        self.app = make_app()
        self._previous_locale = i18n.get_current_locale()
        self.addCleanup(i18n.set_locale, self._previous_locale)

    def _rail(self, mode: str = 'light'):
        from view.widgets.action_rail import ActionRail

        manager = make_manager(mode)
        manager.apply_to(self.app)
        rail = ActionRail(manager)
        self.addCleanup(rail.deleteLater)
        return rail, manager

    def test_action_ids_are_unique_and_complete(self):
        """Seven ids, no duplicates, in rail order, matching the brief."""
        from view.widgets.action_rail import ACTION_IDS as MODULE_IDS

        self.assertEqual(7, len(MODULE_IDS))
        self.assertEqual(
            set(MODULE_IDS), set(ACTION_IDS),
            'an action id was renamed; the presenter dispatches on these values')
        self.assertEqual(
            ACTION_IDS, tuple(MODULE_IDS),
            'ACTION_IDS is also the rail order (library first, appearance and '
            'about after the stretch), so a reorder changes the UI and not just '
            'the tuple')
        self.assertEqual(
            7, len(set(MODULE_IDS)), 'ids must be unique: they key the buttons')

    def test_every_action_has_a_nonempty_tooltip(self):
        """Acceptance criterion, not a nicety: no menu bar survives Task 7."""
        from core import i18n

        for locale_str in LOCALES:
            i18n.set_locale(locale_str)
            rail, _manager = self._rail()
            for action_id in ACTION_IDS:
                with self.subTest(locale=locale_str, action=action_id):
                    tip = rail.button_for(action_id).toolTip()
                    self.assertTrue(tip, f'rail.{action_id} gave an empty tooltip')
                    self.assertNotIn('[MISSING', tip, f'rail.{action_id} unresolved')
                    self.assertNotIn(
                        '{', tip,
                        f'rail.{action_id} carries an unsubstituted placeholder')
                    self.assertNotEqual(
                        tip, f'rail.{action_id}',
                        'the tooltip fell back to its own key')

    def test_click_emits_action_triggered(self):
        """Six actions emit their id; the library button opens the panel instead.

        The single-element assertions here are also the double-emit guard: the
        click path reaches the presenter through ``QAction.trigger()``, so a
        second connect on ``button.clicked`` -- the wiring this fix replaced --
        would deliver every id twice.
        """
        from view.widgets.action_rail import ACTION_LIBRARY

        rail, _manager = self._rail()
        for action_id in ACTION_IDS:
            with self.subTest(action=action_id):
                triggered, panels = [], []
                rail.action_triggered.connect(triggered.append)
                rail.library_panel_requested.connect(lambda: panels.append(True))

                rail.button_for(action_id).click()

                if action_id == ACTION_LIBRARY:
                    self.assertEqual(
                        [], triggered,
                        'the library button is a panel toggle, not an action the '
                        'presenter dispatches')
                    self.assertEqual([True], panels)
                else:
                    self.assertEqual([action_id], triggered)
                    self.assertEqual(
                        [], panels,
                        'only the library button may ask for the floating panel')

    def test_rail_width_is_the_token_value(self):
        from core.theme import RAIL_WIDTH

        rail, _manager = self._rail()
        self.assertEqual('actionRail', rail.objectName())
        self.assertEqual(
            RAIL_WIDTH, rail.minimumWidth(),
            'a rail narrower than the token clips a 40 px button')
        self.assertEqual(RAIL_WIDTH, rail.maximumWidth())
        self.assertEqual(RAIL_WIDTH, rail.width())
        self.assertEqual(RAIL_WIDTH, rail.sizeHint().width())

    def test_open_file_action_carries_the_standard_open_shortcut(self):
        """Ctrl+O survives the menu's death (plan Review Focus 4, spec §6).

        The ``QAction`` has to be attached to the rail itself, not only to the
        button: a button that is not focused never delivers its shortcut, which
        is what ``self.addAction`` is for.

        This pins the *carrier* only -- a key sequence on an action nothing
        listens to is inert, and it is exactly what the mouse-only wiring left
        behind. :meth:`test_activating_an_action_emits_what_its_button_emits`
        pins the emission, by driving the action instead of the button.
        """
        from PyQt6.QtGui import QKeySequence

        rail, _manager = self._rail()
        actions = {action.objectName(): action for action in rail.actions()}
        self.assertIn('open_file', actions,
                      'the shortcut-carrying actions must live on the rail')
        self.assertEqual(QKeySequence(QKeySequence.StandardKey.Open),
                         actions['open_file'].shortcut())
        self.assertEqual(
            1, sum(1 for action in rail.actions() if action.shortcuts()),
            'only open-file inherits a standard shortcut here; Ctrl+Q stays with '
            'the window in Task 7 because Exit is not on the rail (spec §6)')

    def _action_for(self, rail, action_id: str):
        """The ``QAction`` behind ``action_id``, found the way the sheet does.

        Deliberately not ``rail._actions``: the actions are public children of
        the rail (that is what makes their shortcuts reachable), so the test can
        reach one without a private lookup, and the objectName key is the same
        one ``test_open_file_action_carries_the_standard_open_shortcut`` uses.
        """
        actions = {action.objectName(): action for action in rail.actions()}
        self.assertIn(action_id, actions, f'{action_id} has no QAction on the rail')
        return actions[action_id]

    def test_activating_an_action_emits_what_its_button_emits(self):
        """The keyboard path, driven as Qt drives it. ``activate(Trigger)`` is
        what a real shortcut call reaches (Qt 6.11: ``QAction.ActionEvent`` has
        only ``Trigger`` and ``Hover``, and the shortcut machinery uses the
        first), so this is the Ctrl+O path measured end to end rather than a
        claim about it.

        Every action is driven, because the wiring is one line per button and
        the mouse test cannot see it: connecting ``button.clicked`` instead of
        ``action.triggered`` kept all seven ``click()`` assertions green while
        ``activate(Trigger)`` emitted nothing at all (measured, and re-run as a
        mutation in the task report).
        """
        from view.widgets.action_rail import ACTION_LIBRARY

        rail, _manager = self._rail()
        for action_id in ACTION_IDS:
            with self.subTest(action=action_id):
                triggered, panels = [], []
                rail.action_triggered.connect(triggered.append)
                rail.library_panel_requested.connect(lambda: panels.append(True))

                self._action_for(rail, action_id).activate(
                    _action_trigger())

                if action_id == ACTION_LIBRARY:
                    self.assertEqual(
                        [], triggered,
                        'the library action is a panel toggle, not a presenter '
                        'dispatch (same rule as the mouse path)')
                    self.assertEqual([True], panels)
                else:
                    self.assertEqual(
                        [action_id], triggered,
                        'the shortcut path emitted nothing, or emitted twice')
                    self.assertEqual([], panels)

    def test_a_disabled_action_emits_nothing_even_through_the_shortcut(self):
        """Blocking reaches the keyboard for free -- asserted, not assumed.

        :meth:`ActionRail.set_progress` disables the *action*, and
        ``QAction.activate()`` returns before emitting when the action is
        disabled, so the in-flight and mutual-exclusion rules cover Ctrl+O
        without a keyboard-specific line in the widget. Each case puts one
        action out of reach (its own running state, or its partner's), drives
        the action rather than the button, then releases it and drives it again:
        a connect that ignored the enabled state -- or a button-only connect that
        emitted while the action was disabled -- fails the first half.
        """
        Trigger = _action_trigger()
        # (action driven, id put into its running state to block it)
        cases = (
            ('open_file', 'open_file'),        # in flight itself
            ('refresh', 'refresh_all'),       # blocked by its partner
            ('refresh_all', 'refresh'),       # the mirror case
        )

        rail, _manager = self._rail()
        for action_id, started in cases:
            with self.subTest(action=action_id, blocked_by=started):
                triggered, panels = [], []
                rail.action_triggered.connect(triggered.append)
                rail.library_panel_requested.connect(lambda: panels.append(True))
                action = self._action_for(rail, action_id)

                rail.set_progress(started, True)
                self.assertFalse(
                    action.isEnabled(),
                    'set_progress must disable the action, not only the button, '
                    'or the keyboard path stays open while the mouse is closed')
                action.activate(Trigger)
                self.assertEqual([], triggered,
                                 'a disabled action fired; its shortcut reaches '
                                 'the presenter during a scan')
                self.assertEqual([], panels)

                rail.set_progress(started, False)
                self.assertTrue(action.isEnabled())
                action.activate(Trigger)
                self.assertEqual([action_id], triggered,
                                 'the action stayed disabled after the scan ended')

    def test_buttons_carry_the_declared_object_names(self):
        """The sheet selects ``#actionRail`` and ``#railButton``; both must exist."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QToolButton

        from core.theme import TRANSPORT_SIZE

        rail, _manager = self._rail()
        buttons = rail.findChildren(QToolButton)
        self.assertEqual(7, len(buttons), 'one button per action, no more')
        for button in buttons:
            self.assertEqual('railButton', button.objectName())
            self.assertEqual(
                Qt.ToolButtonStyle.ToolButtonIconOnly, button.toolButtonStyle(),
                'the rail is icon-only: text beside a 20 px glyph would not fit '
                'a 56 px column (the tooltip carries the words instead)')
            self.assertEqual(TRANSPORT_SIZE, button.width())
            self.assertEqual(TRANSPORT_SIZE, button.height())


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ActionRailProgressStateTest(unittest.TestCase):
    """The running state: disable, block the partner, mark for QSS, restore."""

    def setUp(self):
        self.app = make_app()

    def _rail(self, mode: str = 'light'):
        from view.widgets.action_rail import ActionRail

        manager = make_manager(mode)
        manager.apply_to(self.app)
        rail = ActionRail(manager)
        self.addCleanup(rail.deleteLater)
        return rail, manager

    def test_set_progress_disables_and_restores(self):
        from view.icons import icon
        from view.widgets.action_rail import ACTION_REFRESH

        rail, manager = self._rail()
        button = rail.button_for(ACTION_REFRESH)
        size = button.iconSize()
        tokens = manager.tokens
        resting = _fingerprint(button.icon().pixmap(size))

        rail.set_progress(ACTION_REFRESH, True)
        self.assertFalse(button.isEnabled(),
                         'a running action must not be clickable again')
        self.assertEqual(
            'true', button.property('running'),
            'QSS matches the string "true"; a bool styles nothing a reader can '
            'grep (same convention as the library chips)')
        self.assertEqual(
            _fingerprint(icon('refresh', tokens.icon, size.width()).pixmap(size)),
            _fingerprint(button.icon().pixmap(size)),
            'the running state draws the refresh glyph (no eighth icon exists)')

        rail.set_progress(ACTION_REFRESH, False)
        self.assertTrue(button.isEnabled(), 'the button must come back clickable')
        self.assertEqual('false', button.property('running'))
        self.assertEqual(
            resting, _fingerprint(button.icon().pixmap(size)),
            'the original glyph must return, not stay a spinner')

    def test_refresh_all_blocks_refresh_current(self):
        """One library-loading path, two entry points (plan Review Focus 3)."""
        from view.widgets.action_rail import ACTION_REFRESH, ACTION_REFRESH_ALL

        rail, _manager = self._rail()
        refresh = rail.button_for(ACTION_REFRESH)
        refresh_all = rail.button_for(ACTION_REFRESH_ALL)
        self.assertTrue(refresh.isEnabled() and refresh_all.isEnabled())

        rail.set_progress(ACTION_REFRESH_ALL, True)
        self.assertFalse(refresh_all.isEnabled())
        self.assertFalse(
            refresh.isEnabled(),
            'refreshing every library walks the same scan refresh does, so the '
            'second entry point has to close while the first is open')
        self.assertNotEqual(
            'true', refresh.property('running'),
            'the blocked button is disabled, it is not itself running: only the '
            'initiator may wear the progress glyph')

        rail.set_progress(ACTION_REFRESH_ALL, False)
        self.assertTrue(refresh.isEnabled(), 'the partner must be released too')
        self.assertTrue(refresh_all.isEnabled())

    def test_running_state_swaps_the_glyph_on_a_non_refresh_button(self):
        """The progress glyph, observed where it can actually be told apart.

        The brief's own progress test drives ``ACTION_REFRESH``, whose resting
        glyph *is* the progress glyph, so it cannot see a missing swap: deleting
        the ``_running`` branch from ``_glyph_for`` left every other test green
        (mutation run recorded in the task report). ``appearance`` rests on
        ``settings``, so there the spinner is the only difference, and both
        directions are asserted.
        """
        from view.icons import icon
        from view.widgets.action_rail import ACTION_APPEARANCE

        rail, manager = self._rail()
        button = rail.button_for(ACTION_APPEARANCE)
        size = button.iconSize()
        resting = _fingerprint(button.icon().pixmap(size))

        rail.set_progress(ACTION_APPEARANCE, True)
        shown = _fingerprint(button.icon().pixmap(size))
        self.assertEqual(
            _fingerprint(icon('refresh', manager.tokens.icon,
                              size.width()).pixmap(size)),
            shown, 'a running button wears the shared refresh glyph')
        self.assertNotEqual(resting, shown,
                            'the running glyph is indistinguishable from the resting one')

        rail.set_progress(ACTION_APPEARANCE, False)
        self.assertEqual(resting, _fingerprint(button.icon().pixmap(size)),
                         'the action\'s own glyph must come back')

    def test_blocked_partner_keeps_its_own_glyph(self):
        """Blocking is not the same as running, and the glyph has to say so.

        Both refresh entries disable together, but only the one actually in
        flight wears the spinner; two spinners would tell the user two scans are
        running when one is.
        """
        from view.widgets.action_rail import ACTION_REFRESH, ACTION_REFRESH_ALL

        rail, _manager = self._rail()
        refresh = rail.button_for(ACTION_REFRESH)
        refresh_all = rail.button_for(ACTION_REFRESH_ALL)
        size = refresh.iconSize()
        # Each button is compared against *its own* resting shape. Comparing the
        # blocked button's glyph with the initiator's would prove nothing: the
        # blocked one rests on ``refresh`` and the running one wears it too, so
        # the two are identical by design.
        refresh_resting = _fingerprint(refresh.icon().pixmap(size))
        all_resting = _fingerprint(refresh_all.icon().pixmap(size))
        self.assertNotEqual(refresh_resting, all_resting,
                            'the two refresh actions rest on different glyphs')

        rail.set_progress(ACTION_REFRESH_ALL, True)
        self.assertFalse(refresh.isEnabled())
        self.assertEqual(refresh_resting, _fingerprint(refresh.icon().pixmap(size)),
                         'the blocked button keeps its own glyph')
        self.assertNotEqual(
            all_resting, _fingerprint(refresh_all.icon().pixmap(size)),
            'the initiator must be the one wearing the spinner')

    def test_refresh_current_blocks_refresh_all(self):
        """The mirror case, asserted separately.

        ``_blocked_pair`` is symmetric, so a one-directional test would stay
        green even if the dict lost its ``'refresh'`` key.
        """
        from view.widgets.action_rail import ACTION_REFRESH, ACTION_REFRESH_ALL

        rail, _manager = self._rail()
        rail.set_progress(ACTION_REFRESH, True)
        self.assertFalse(rail.button_for(ACTION_REFRESH_ALL).isEnabled())
        rail.set_progress(ACTION_REFRESH, False)
        self.assertTrue(rail.button_for(ACTION_REFRESH_ALL).isEnabled())

    def test_running_state_survives_a_recolor(self):
        """A theme flip mid-refresh must not hand the resting glyph back."""
        from view.widgets.action_rail import ACTION_REFRESH

        rail, manager = self._rail('light')
        rail.set_progress(ACTION_REFRESH, True)
        manager.set_mode('dark')
        rail.recolor(manager.tokens)

        button = rail.button_for(ACTION_REFRESH)
        self.assertFalse(button.isEnabled(), 'recolor may not re-enable a running button')
        self.assertEqual(_token(manager.tokens.icon),
                         _dominant_colour(button.icon().pixmap(button.iconSize())))
        rail.set_progress(ACTION_REFRESH, False)
        self.assertTrue(button.isEnabled())

    def test_unknown_action_id_raises(self):
        rail, _manager = self._rail()
        for bad in ('nope', '', 'Library', 'library_panel', 'ACTION_REFRESH'):
            with self.subTest(action_id=bad):
                with self.assertRaises(ValueError):
                    rail.set_progress(bad, True)
        self.assertTrue(
            all(rail.button_for(action_id).isEnabled() for action_id in ACTION_IDS),
            'a rejected call must not have disabled anything on the way out')

    def test_progress_is_idempotent(self):
        """Setting the state a button is already in must not lose its glyph.

        The presenter can report the same progress twice (a retried scan); the
        second call may not overwrite the saved resting icon with the spinner,
        or the button never returns to its own glyph.

        Driven on ``appearance``, never on ``refresh``. ``refresh`` rests on the
        progress glyph itself, so its resting and running fingerprints are the
        same bytes (measured: identical), and all three comparisons below would
        be a value against itself -- green under the saved-icon implementation
        this test exists to exclude, which is the same blind spot
        :meth:`test_running_state_swaps_the_glyph_on_a_non_refresh_button`
        closes for mutation D. ``appearance`` rests on ``settings``, so the two
        states can be told apart, and the first assertion below is that
        distinguishability itself: without it the test could quietly regress to
        the vacuous form.
        """
        from view.widgets.action_rail import ACTION_APPEARANCE

        rail, _manager = self._rail()
        button = rail.button_for(ACTION_APPEARANCE)
        size = button.iconSize()
        resting = _fingerprint(button.icon().pixmap(size))

        rail.set_progress(ACTION_APPEARANCE, True)
        running = _fingerprint(button.icon().pixmap(size))
        self.assertNotEqual(
            resting, running,
            'appearance must be able to show the spinner at all, or "idempotent" '
            'has no second state to be idempotent about')
        self.assertTrue(rail.is_running(ACTION_APPEARANCE))

        rail.set_progress(ACTION_APPEARANCE, True)
        self.assertEqual(running, _fingerprint(button.icon().pixmap(size)),
                         'the retry changed the glyph; only one state is running')
        self.assertTrue(rail.is_running(ACTION_APPEARANCE))
        self.assertFalse(button.isEnabled())

        rail.set_progress(ACTION_APPEARANCE, False)
        self.assertEqual(
            resting, _fingerprint(button.icon().pixmap(size)),
            'the second set_progress overwrote the resting glyph and the spinner '
            'is stuck on the appearance button')
        self.assertFalse(rail.is_running(ACTION_APPEARANCE))
        self.assertTrue(button.isEnabled(), 'the retry left the button disabled')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ActionRailIconTest(unittest.TestCase):
    """Glyph provenance: the token pipeline and the authored set."""

    def setUp(self):
        from view.icons import clear_cache

        self.app = make_app()
        clear_cache()
        self.addCleanup(clear_cache)

    def _rail(self, mode: str = 'light'):
        from view.widgets.action_rail import ActionRail

        manager = make_manager(mode)
        manager.apply_to(self.app)
        rail = ActionRail(manager)
        self.addCleanup(rail.deleteLater)
        return rail, manager

    def test_rail_icons_are_recolored(self):
        from core.theme import DARK, LIGHT

        rail, manager = self._rail('light')
        for action_id in ACTION_IDS:
            with self.subTest(action=action_id):
                button = rail.button_for(action_id)
                pixmap = button.icon().pixmap(button.iconSize())
                self.assertFalse(pixmap.isNull(), f'{action_id} drew nothing')
                self.assertEqual(
                    _token(LIGHT.icon), _dominant_colour(pixmap),
                    'a resting rail glyph is tokens.icon, on the rail whose '
                    'sheet fill is surface_alt; that pairing is pinned as '
                    "('icon', 'surface_alt', 3.0) in test_theme.py's EXTRA_PAIRS "
                    'and its presence is asserted by '
                    'test_the_rail_glyph_pairings_are_pinned_in_the_contrast_set')

        manager.set_mode('dark')
        rail.recolor(manager.tokens)
        for action_id in ACTION_IDS:
            with self.subTest(action=action_id, theme='dark'):
                button = rail.button_for(action_id)
                self.assertEqual(
                    _token(DARK.icon),
                    _dominant_colour(button.icon().pixmap(button.iconSize())),
                    'theme_changed must reach the rail glyphs: a pixmap '
                    'rasterised from a token is beyond QSS')

    def test_each_button_draws_its_declared_glyph(self):
        """Name-level wiring, read back through the module's ``icon`` symbol."""
        from unittest import mock

        from PyQt6.QtGui import QIcon

        import view.widgets.action_rail as action_rail_module

        requested = []

        def recording_icon(name, color, size, dpr=1.0):
            self.assertIn(
                name, RAIL_ICON_NAMES,
                f'{name!r} is not one of the seven glyphs this task authors; an '
                'invented name degrades to a null icon in production')
            requested.append(name)
            return QIcon()

        manager = make_manager('light')
        manager.apply_to(self.app)
        with mock.patch.object(action_rail_module, 'icon', recording_icon):
            rail = action_rail_module.ActionRail(manager)
            self.addCleanup(rail.deleteLater)
            self.assertEqual(
                [ACTION_GLYPHS[action_id] for action_id in ACTION_IDS], requested,
                'the glyph each button asks for, in rail order, is the contract '
                'with the icon set and with Task 7: one call per button')


class RailResourceTest(unittest.TestCase):
    """The seven new SVGs, without a QApplication (pure file + text checks)."""

    def test_the_seven_new_svgs_keep_the_authoring_conventions(self):
        for name in RAIL_ICON_NAMES:
            path = ICONS_DIR / f'{name}.svg'
            with self.subTest(icon=name):
                self.assertTrue(path.is_file(), f'{path} is missing')
                text = path.read_text(encoding='utf-8')
                root = ET.fromstring(text)
                self.assertEqual('svg', root.tag.rsplit('}', 1)[-1])
                self.assertEqual(
                    '0 0 24 24', root.get('viewBox'),
                    'the pipeline scales the 24-unit box onto size*dpr, so a '
                    'different viewBox silently rescales the glyph')
                self.assertIn(
                    'currentColor', text,
                    'fill="currentColor" is the placeholder view.icons '
                    'substitutes; a hardcoded colour ignores the tokens')
                paths = 0
                for element in root.iter():
                    tag = element.tag.rsplit('}', 1)[-1]
                    if tag == 'svg':
                        continue
                    self.assertEqual(
                        'path', tag,
                        f'<{tag}> is not a plain path; this set draws its glyphs '
                        'from paths only')
                    paths += 1
                    for attr in ('fill', 'stroke'):
                        value = element.get(attr)
                        if value is not None:
                            self.assertIn(value, ('currentColor', 'none'))
                self.assertGreaterEqual(
                    paths, 1, f'{name}.svg draws nothing: the set has no empty files')

                scannable = text.replace('http://www.w3.org/2000/svg', '')
                for needle in FORBIDDEN_NEEDLES:
                    self.assertNotIn(needle, scannable,
                                     f'{needle} reaches outside the file')

    @unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
    def test_the_seven_new_svgs_parse_for_the_rasteriser(self):
        """The convention test above is lenient where Qt's parser is not.

        ``tests/test_icons.py`` reads these files with ``ElementTree``, which
        accepts a ``--`` inside a comment; ``QSvgRenderer`` (Qt's own XML parser)
        rejects the whole document, and ``view.icons`` then degrades to a null
        ``QIcon`` with one stdout warning -- an invisible blank button. Measured
        while authoring this set: six of the seven files were rejected until the
        comment bodies dropped the sequence.
        """
        from PyQt6.QtCore import QByteArray
        from PyQt6.QtSvg import QSvgRenderer

        for name in RAIL_ICON_NAMES:
            with self.subTest(icon=name):
                text = (ICONS_DIR / f'{name}.svg').read_text(encoding='utf-8')
                self.assertTrue(
                    QSvgRenderer(QByteArray(
                        text.replace('currentColor', '#000000').encode('utf-8')
                    )).isValid(),
                    f'{name}.svg is rejected by QSvgRenderer; the button would '
                    'render nothing')

    @unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
    def test_rail_glyphs_share_one_size_class(self):
        """The seven must look like one set inside a 56 px column.

        Floors and ceilings sit half a unit outside the authored boxes, because
        the mask counts pixels above 50% alpha and antialiasing trims the edge
        (the same tolerance batch 1 documents for ``volume_mute``).
        """
        from PyQt6.QtCore import QByteArray, QRectF, Qt
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer

        make_app()      # a QGuiApplication must exist before QImage

        sample = 96
        scale = sample / 24.0
        for name in RAIL_ICON_NAMES:
            with self.subTest(icon=name):
                text = (ICONS_DIR / f'{name}.svg').read_text(encoding='utf-8')
                renderer = QSvgRenderer(QByteArray(
                    text.replace('currentColor', '#000000').encode('utf-8')))
                image = QImage(sample, sample,
                               QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                try:
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    renderer.render(painter, QRectF(0, 0, sample, sample))
                finally:
                    painter.end()
                ink = {(x, y) for y in range(sample) for x in range(sample)
                       if image.pixelColor(x, y).alpha() > 128}
                self.assertTrue(ink, f'{name} rasterised to an empty glyph')
                xs = [x for x, _y in ink]
                ys = [y for _x, y in ink]
                x0, x1 = min(xs) / scale, max(xs) / scale
                y0, y1 = min(ys) / scale, max(ys) / scale
                self.assertGreaterEqual(x0, 1.0, f'{name} leaves the box left')
                self.assertGreaterEqual(y0, 1.0, f'{name} leaves the box top')
                self.assertLessEqual(x1, 23.0, f'{name} leaves the box right')
                self.assertLessEqual(y1, 23.0, f'{name} leaves the box bottom')
                width, height = x1 - x0, y1 - y0
                self.assertGreaterEqual(
                    min(width, height), 11.0,
                    f'{name} inks {width:.2f} x {height:.2f}; a glyph that small '
                    'reads as a lighter button beside its neighbours')
                self.assertLessEqual(
                    max(width, height), 18.0,
                    f'{name} inks {width:.2f} x {height:.2f}; the rail family is '
                    'authored inside an 18-unit box')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ActionRailSheetTest(unittest.TestCase):
    """The QSS half of the pair, asserted against the generated sheet.

    ``REQUIRED_OBJECT_NAMES`` stays untouched here -- see the module docstring
    for the ruling -- so this is the test that proves the rules exist, are
    scoped, and use tokens.
    """

    def setUp(self):
        self.app = make_app()

    def test_rail_rules_are_generated_from_tokens(self):
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        for name, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            sheet = build_qss(tokens, AlphaSettings())
            with self.subTest(theme=name):
                self.assertIn('\n#actionRail {', sheet)
                self.assertIn('\n#railButton {', sheet)
                for state in (':hover', ':pressed', ':disabled', ':focus',
                              '[running="true"]'):
                    self.assertIn(
                        f'\n#railButton{state} {{', sheet,
                        f'#railButton{state} is missing; the rail would fall '
                        'back to Fusion chrome for that state')
                rail_block = _block(sheet, '#actionRail')
                self.assertIn(f'background-color: {tokens.surface_alt};', rail_block)
                self.assertIn(f'1px solid {tokens.divider}', rail_block)
                self.assertIn(
                    f'background-color: {tokens.hover_bg};',
                    _block(sheet, '#railButton:hover'))
                self.assertIn(
                    f'background-color: {tokens.accent_soft};',
                    _block(sheet, '#railButton[running="true"]'))
                self.assertIn(
                    f'background-color: {tokens.button_disabled_bg};',
                    _block(sheet, '#railButton:disabled'))

    def test_the_rail_glyph_pairings_are_pinned_in_the_contrast_set(self):
        """The four fills a rail glyph paints on are contrast-guarded by name.

        ``tests/test_theme.py`` states the rule at its Task 8 comment: an SVG
        glyph is rasterised from a token *before* it is painted, so QSS can no
        longer be trusted to keep it legible and the pairing has to be pinned in
        ``ThemeContrastTest.EXTRA_PAIRS`` at the 3:1 non-text bar (WCAG 1.4.11).
        The rail introduces four such pairings, and
        :meth:`ActionRailIconTest.test_rail_icons_are_recolored` points a reader
        at that pin -- so this is the test that makes the pointer true rather
        than a claim about a guard that does not exist.

        The ratios themselves are evaluated by
        ``ThemeContrastTest.test_contrast_requirements`` over both themes
        (measured at authoring: LIGHT 8.53-9.09, DARK 7.63-9.29 -- a missing pin,
        not a legibility failure). What is asserted here is presence at the 3.0
        bar, because deleting a tuple un-guards a pairing silently while the
        ratio still passes.

        The three names below are the tokens ``test_rail_rules_are_generated_from
        _tokens`` pins into the sheet, and the resting fill is the rail's own: if
        a rule moves to a different token, that test fails and this tuple has to
        follow. ``:pressed`` is absent on purpose -- it emits ``button_pressed``,
        already pinned for batch 1's transport row.
        """
        from tests.test_theme import ThemeContrastTest

        expected = (
            ('icon', 'surface_alt', 3.0),         # resting: #actionRail's fill
            ('icon', 'hover_bg', 3.0),            # #railButton:hover
            ('icon', 'button_disabled_bg', 3.0),  # #railButton:disabled
            ('icon', 'accent_soft', 3.0),         # #railButton[running="true"]
        )
        pinned = set(ThemeContrastTest.EXTRA_PAIRS)
        missing = [pair for pair in expected if pair not in pinned]
        self.assertEqual(
            [], missing,
            'a glyph/background pairing the rail paints is not pinned in '
            f'ThemeContrastTest.EXTRA_PAIRS at the 3.0 bar: {missing}')

    def test_rail_buttons_have_no_widget_level_stylesheet(self):
        """The one-stylesheet rule of the whole theme layer (spec §1.6)."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget

        from view.widgets.action_rail import ActionRail

        manager = make_manager('light')
        manager.apply_to(self.app)
        rail = ActionRail(manager)
        try:
            self.assertEqual('', rail.styleSheet())
            for child in rail.findChildren(QWidget):
                self.assertEqual(
                    '', child.styleSheet(),
                    f'{type(child).__name__}#{child.objectName()} carries an '
                    'inline sheet; the application sheet is the only source')
            self.assertTrue(
                rail.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
                'without the attribute the #actionRail fill never paints')
        finally:
            rail.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
