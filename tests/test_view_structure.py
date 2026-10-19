#!/usr/bin/env python3
"""Widget-tree structure tests for the theme layer's scoping contract.

``core/theme_qss.py`` emits rules scoped only by ``#objectName`` and
``[prop="value"]`` selectors, and it declares which ones it uses in
:data:`REQUIRED_OBJECT_NAMES` / :data:`REQUIRED_DYN_PROPERTIES`. Those two
tuples are the contract; this module is the widget side of it, so a rename on
either end fails a test instead of silently dropping a rule onto Fusion
defaults.

Three directions are pinned across the two files:

* **tuple -> sheet** (``tests/test_theme_qss.py``): everything registered is
  styled, in both themes;
* **tree -> tuple** (:meth:`ViewStructureTest.test_every_required_object_name_exists`):
  a built ``MainWindow`` really carries every registered name;
* **sheet -> tree** (:class:`StyleSheetSelectorsHaveWearersTest`, added for
  batch-2 review finding 3): read the *generated* sheet back and demand a wearer
  for every selector token, or an explicit entry in
  :data:`core.theme_qss.KNOWN_DEAD_SELECTORS` -- and, since the batch-2 *final*
  review (finding 1), for every bare class a selector names, or a name on the
  generator's own chrome exemption with a recorded reason. The first version asked
  only about ``#name`` and ``[prop="value"]`` tokens, which is how the two
  zero-wearer ``QSplitter::handle`` rules survived the pass that deleted the
  splitter.

Only the third makes Task 9's deletions permanent. The first two look at what is
declared, so re-emitting a rule for ``#albumArt`` -- a name no widget can carry
any more -- kept them both green; the report admits exactly that at §A.6.

Two deliberate deviations from the original plan text, both recorded in
``.superpowers/sdd/2026-10-16-ui-batch1-theme-tokens/progress.md``:

* ``#appearanceDialog`` / ``#bgPathLabel`` live on a dialog the presenter builds
  on demand (:meth:`presenter.main_presenter.MainPresenter._on_manage_appearance`),
  not on :class:`view.main_window.MainWindow`. A single-tree ``findChildren``
  sweep can therefore never see them, so the coverage test collects the union of
  both trees.
* The three transparency sliders of
  ``view/dialogs/appearance_dialog.py`` are named here
  (:data:`DIALOG_SLIDER_NAMES`). Task 5 gave them objectNames but no rules --
  Task 4's gate test pins ``REQUIRED_OBJECT_NAMES`` and the sheet did not style
  them yet -- and Task 6 wrote the rules and folded the three names into that
  tuple, so this module's union is now just ``REQUIRED_OBJECT_NAMES``. The
  constant stays so the dialog side of the tree is asserted explicitly.

Task 7 (the shell swap) changed the rules of this module in three places, all
recorded in ``.superpowers/sdd/2026-10-18-ui-batch2-layout/task-7-report.md``:

* The twelve batch-2 widget names (rail, sidebar, strip, toast) are registered
  in ``REQUIRED_OBJECT_NAMES``, and the five names of the deleted left panel
  (``nowPlayingPanel``/``albumArt``/``trackTitle``/``trackArtist``/``trackAlbum``)
  leave the tuple with it: the tuple is the *live-tree* half of the contract,
  and the panel no longer enters it. Task 9 then deleted the panel's files *and*
  the five rules that scoped those names, so neither half now mentions them; the
  sheet's transparency pin moved to ``#nowPlayingStrip`` with them.
* A fixed-integer ``MULTIPLICITY`` cannot express ``#libraryRow`` (one per
  media library plus the footer entry, and the library count is uncapped), so
  :data:`UNBOUNDED_NAMES` names the exempt class explicitly and
  :func:`multiplicity_failures` keeps the default-1 rule for everyone else.
* The menu bar is gone. ``test_shortcuts_survive_menu_removal`` drives the real
  key events so Ctrl+O/Ctrl+Q cannot be lost to the swap, and the two
  ``*exactly_once*`` tests pin the ledger rule that ``MainWindow`` connects
  ``ActionRail.action_triggered`` and nothing on the buttons.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_view_structure -v
"""
import re
import sys
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

# The sheet's own selector splitter, imported rather than re-implemented: two
# parsers of one format is how the sheet -> tree guard and the tree -> sheet guard
# start disagreeing about what a selector is.
from tests.test_theme_qss import (
    EXEMPT_CHROME_CLASSES,
    EXEMPT_CHROME_DECISIONS,
    _bare_class_selectors,
    _selector_members,
)

from core.theme_qss import (
    KNOWN_DEAD_SELECTORS,
    REQUIRED_DYN_PROPERTIES,
    REQUIRED_OBJECT_NAMES,
)

try:
    from PyQt6.QtCore import QObject
    from PyQt6.QtWidgets import QLabel, QPushButton
except ImportError:  # pragma: no cover - environment without PyQt6
    QT_AVAILABLE = False

# ``#timeLabel`` is the one name the sheet reuses: the bottom panel uses it for
# both the elapsed and the total-duration label, which are styled identically.
# ``#railButton`` is the rail's seven actions, one button each (Task 3 pins the
# count through ``ACTION_IDS``; the shell adds the rail to the tree in Task 7).
MULTIPLICITY = {'timeLabel': 2, 'railButton': 7}

# Names whose instance count is set by *data*, not by the sheet. ``#libraryRow``
# is one per media library plus the two footer administration entries, which
# deliberately share the name (Task 4's ruling for the add entry, spec §3.2's
# Task 8 correction for the manage one: same glyph slot, same hover, same height),
# and ``Settings.media_libraries`` is uncapped -- so no fixed integer can bound it:
# 1 would go red for anyone with one library, 8 only moves the red to the
# ninth. The semantics here are "exists at least once, ceiling-free": existence
# is already pinned by ``test_every_required_object_name_exists`` (the name is
# in the tuple), so this set only exempts the ceiling, and it exempts nothing
# that is not listed -- ``test_unknown_repeated_name_still_trips_the_default``
# holds the default-1 rule open with a synthetic ``Counter``.
UNBOUNDED_NAMES = frozenset({'libraryRow'})

# The three transparency sliders of ``view/dialogs/appearance_dialog.py``.
# Task 5 named them and left them unstyled (Task 4's gate pins
# ``REQUIRED_OBJECT_NAMES`` and the sheet had no rule for them yet); Task 6
# wrote the rules and folded the names into that tuple, so the union below is
# now ``REQUIRED_OBJECT_NAMES`` itself. Kept as its own constant because this
# module asserts the dialog side of the tree explicitly.
DIALOG_SLIDER_NAMES = ('overlaySlider', 'playlistSlider', 'controlsSlider')


def collect_names(widget) -> list:
    """Object names of ``widget`` itself plus every descendant, duplicates kept."""
    return [widget.objectName()] + [
        child.objectName() for child in widget.findChildren(QObject)
    ]


# The two token kinds a QSS rule can scope itself by -- the same two the
# generator is allowed to use (``core/theme_qss.py`` module header, rule 1).
# Pseudo-classes and sub-controls are not tokens: ``#railButton`` and
# ``#railButton:hover:pressed`` want the *same* wearer, and ``QDialog QPushButton``
# wants none (it is ancestor-scoped by decision). A bare class is not a token
# either, but it is not exempt from the guard: it names a *whole class*, so
# :func:`worn_classes` answers the same question one level up -- see
# :meth:`StyleSheetSelectorsHaveWearersTest.test_every_emitted_bare_class_is_worn_or_exempted`.
SELECTOR_NAME_RE = re.compile(r'#([A-Za-z_][A-Za-z0-9_]*)')
SELECTOR_PROPERTY_RE = re.compile(r'\[([a-z_]+)="([^"]*)"\]')


def worn_properties(*trees) -> set:
    """Every ``(property, value)`` pair the given widget trees actually carry.

    Read off ``dynamicPropertyNames()`` rather than from a fixed list of
    properties to probe, so a widget that grows a new state is visible to the
    sheet -> tree guard without that guard being edited first. ``QByteArray``
    names are decoded because Qt hands them back as bytes.
    """
    from PyQt6.QtCore import QObject

    worn = set()
    for tree in trees:
        for widget in [tree] + list(tree.findChildren(QObject)):
            for raw in widget.dynamicPropertyNames():
                worn.add((bytes(raw).decode('utf-8'),
                          str(widget.property(raw))))
    return worn


def worn_classes(*trees) -> set:
    """Every Qt class name the given trees instantiate, base classes included.

    The bare-class half of the sheet -> tree guard asks whether a rule like
    ``QScrollBar::handle:horizontal`` has anything to paint, and QSS matches on the
    *class*, so the answer is the whole MRO of every widget in the tree, not just
    its most-derived type: a ``QTableView``'s scroll bar is a plain ``QScrollBar``,
    but a subclass instance still wears its base's rule. Names that do not start
    with ``Q`` (this project's own classes, ``object``) are skipped -- the sheet
    cannot select on them, so counting them would only make the answer
    platform-shaped rather than wrong in a useful way.
    """
    from PyQt6.QtCore import QObject

    worn = set()
    for tree in trees:
        for widget in [tree] + list(tree.findChildren(QObject)):
            for klass in type(widget).__mro__:
                if klass.__name__.startswith('Q'):
                    worn.add(klass.__name__)
    return worn


def selector_offenders(member: str, names: set, properties: set) -> list:
    """The tokens of one selector member that no widget in the tree wears.

    ``[]`` means every ``#name`` is an objectName in the tree and every
    ``[prop="value"]`` is a pair some widget currently holds -- i.e. the rule can
    paint something. A non-empty answer is dead paint, and the only legal reasons
    for it are the two halves of :data:`KNOWN_DEAD_SELECTORS`'s contract: the whole
    member is listed there, or it should not be emitted at all.
    """
    offenders = []
    for name in SELECTOR_NAME_RE.findall(member):
        if name not in names:
            offenders.append(f'#{name}')
    for pair in SELECTOR_PROPERTY_RE.findall(member):
        if pair not in properties:
            offenders.append('[%s="%s"]' % pair)
    return offenders


def multiplicity_failures(counts) -> list:
    """The multiplicity violations for a name->count mapping, as strings.

    Returns failures instead of asserting so the *same* rule can be run against
    the live tree and against a synthetic :class:`Counter` -- the synthetic form
    is the only way to prove an unregistered-but-repeated name still trips the
    default of 1 without shipping a widget that repeats a name on purpose.

    ``counts`` may be any mapping with ``__missing__``-style zero answers (a
    :class:`collections.Counter`); names outside the registered union are not
    this contract's business.
    """
    failures = []
    expected = set(REQUIRED_OBJECT_NAMES) | set(DIALOG_SLIDER_NAMES)
    for name in sorted(expected):
        if name in UNBOUNDED_NAMES:
            continue
        limit = MULTIPLICITY.get(name, 1)
        count = counts[name]
        if count > limit:
            failures.append(
                f'#{name} appears {count} times, the sheet assumes at most {limit}')
    return failures


def make_appearance_dialog():
    """Build the appearance dialog the way the presenter does, minus the config."""
    from view.dialogs import AppearanceDialog

    return AppearanceDialog(
        background_image=None,
        overlay_alpha=1.0,
        playlist_alpha=1.0,
        controls_alpha=1.0,
    )


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ViewStructureTest(unittest.TestCase):
    """The real widget tree must carry the names and properties the sheet selects on."""

    def setUp(self):
        self.app = make_app()

    def test_every_required_object_name_exists(self):
        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        dialog = make_appearance_dialog()
        try:
            collected = set(collect_names(window)) | set(collect_names(dialog))
            expected = set(REQUIRED_OBJECT_NAMES) | set(DIALOG_SLIDER_NAMES)
            missing = sorted(expected - collected)
            self.assertFalse(
                missing,
                f'Widgets are missing objectNames the stylesheet scopes rules by: {missing}',
            )
        finally:
            dialog.deleteLater()
            window.deleteLater()

    def test_transport_and_library_row_properties(self):
        """The sheet's dynamic-property pairs, declared and then worn.

        The literals below are the contract; assert the tuple first so an edit
        there fails here rather than in an ``in`` test that would silently
        shrink to zero buttons to check.

        Three of the four pairs are *worn* here (``role``/``current``/``running``,
        by the transport buttons, the sidebar rows and the rail).
        ``('chip', 'true')`` is the fourth and is the one entry this test can only
        pin as *declared*: Task 9 deleted the chip row, so nothing constructs a
        ``chip="true"`` widget any more. That asymmetry is not hidden here any
        more either -- it is written down in
        :data:`core.theme_qss.KNOWN_DEAD_SELECTORS` and enforced by
        :class:`StyleSheetSelectorsHaveWearersTest`, whose whole job is wearing,
        so this class can keep its job (the tree carries what the sheet selects on)
        without pretending the chip family still has a wearer. Task 10 owns that
        family's fate; see the hand-off note in the batch report.
        ``('current', 'true')`` and ``('running', 'true')`` are the Task 7
        registrations: the sheet has styled them since Tasks 3/4, and they enter
        the tree with this shell.
        """
        from view.main_window import MainWindow

        self.assertIn(('role', 'transport'), REQUIRED_DYN_PROPERTIES)
        self.assertIn(('chip', 'true'), REQUIRED_DYN_PROPERTIES)
        self.assertIn(('current', 'true'), REQUIRED_DYN_PROPERTIES)
        self.assertIn(('running', 'true'), REQUIRED_DYN_PROPERTIES)

        window = MainWindow(make_manager())
        try:
            transports = [
                button for button in window.findChildren(QPushButton)
                if button.property('role') == 'transport'
            ]
            self.assertGreaterEqual(
                len(transports), 3,
                'Previous/Stop/Next must all carry property("role") == "transport"',
            )

            window.set_libraries([
                SimpleNamespace(name='Rock', path='/lib/rock'),
                SimpleNamespace(name='Jazz', path='/lib/jazz'),
            ])
            rows = [
                row for row in window.findChildren(QPushButton, 'libraryRow')
                if row.property('library_path') is not None
            ]
            self.assertEqual(len(rows), 2,
                             'One selectable sidebar row per media library')

            # ``#libraryRow[current="true"]`` is written against strings, and
            # strings are the contract this test enforces (Qt's attribute
            # selector would also match Python bools, but the sheet's own text
            # is what a reader greps, so the widgets declare strings).
            for row in rows:
                current = row.property('current')
                self.assertIsInstance(
                    current, str,
                    f'row {row.full_name!r} sets current as {type(current).__name__}, '
                    'but the sheet is written against the strings "true"/"false"',
                )
                self.assertIn(current, ('true', 'false'))

            window.set_current_library('/lib/jazz')
            self.assertEqual(
                [row.full_name for row in rows if row.property('current') == 'true'],
                ['Jazz'],
                'exactly the row for the current library carries current="true"',
            )
        finally:
            window.deleteLater()

    def test_object_names_are_unique_per_scope(self):
        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        dialog = make_appearance_dialog()
        try:
            counts = Counter(collect_names(window) + collect_names(dialog))
            self.assertEqual(
                [], multiplicity_failures(counts),
                'a styled objectName repeated beyond its contract makes the '
                'sheet ambiguous: every rule for it hits all instances',
            )
            self.assertEqual(
                counts['timeLabel'], 2,
                '#timeLabel must sit on both the elapsed and the total-duration label',
            )
            self.assertEqual(
                counts['railButton'], 7,
                'one #railButton per rail action -- the seven spec §6 fixes',
            )
            self.assertEqual(
                counts['libraryRow'], 2,
                'with no library loaded only the two footer entries wear the name '
                '(add + manage, spec §3.2 correction)',
            )
        finally:
            dialog.deleteLater()
            window.deleteLater()

    def test_bg_path_label_empty_property(self):
        dialog = make_appearance_dialog()
        try:
            label = dialog.findChild(QLabel, 'bgPathLabel')
            self.assertIsNotNone(label, '#bgPathLabel must be a child of the dialog')
            # ``#bgPathLabel[empty="true"]`` is string-matched, same as the chips.
            for path, expected in ((None, 'true'), ('C:/bg.png', 'false'), (None, 'true')):
                dialog.set_background_image(path)
                empty = label.property('empty')
                self.assertIsInstance(
                    empty, str,
                    f'empty is {type(empty).__name__}, QSS property selectors need '
                    'the strings "true"/"false"',
                )
                self.assertEqual(
                    empty, expected,
                    f'after set_background_image({path!r}) the sheet should see '
                    f'empty="{expected}"',
                )
        finally:
            dialog.deleteLater()

    # === Task 7: the shell (rail + full-width list + floating panel) ===

    def test_no_menu_bar(self):
        """The menu is deleted, not hidden: no action may hang on the bar.

        ``QMainWindow.menuBar()`` creates the bar lazily even when queried, so
        the assertion is about content: an empty bar is a Qt artefact, a bar
        with actions is the shell dispatching twice.
        """
        from PyQt6.QtWidgets import QMenu

        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        try:
            menubar = window.menuBar()
            self.assertEqual([], list(menubar.actions()),
                             'the rail owns every action the menu carried')
            self.assertEqual([], window.findChildren(QMenu),
                             'a leftover QMenu is a shell that dispatches twice')
        finally:
            window.deleteLater()

    def test_rail_and_sidebar_in_tree(self):
        """``REQUIRED_OBJECT_NAMES`` covers the batch-2 widgets, and the shell
        actually puts them in the live tree the structure contract walks."""
        from PyQt6.QtWidgets import QWidget

        from view.main_window import MainWindow

        expected = ('actionRail', 'railButton', 'librarySidebar', 'sidebarTitle',
                    'libraryRow', 'sidebarEmpty', 'nowPlayingStrip', 'stripArt',
                    'stripTitle', 'stripArtist', 'toast', 'toastText')
        for name in expected:
            self.assertIn(name, REQUIRED_OBJECT_NAMES,
                          f'#{name} styles the live shell but is not registered')
        self.assertNotIn(
            'playlistContainer', REQUIRED_OBJECT_NAMES,
            'the list container is a layout host only: no rule, no registration '
            '(ledger R2) -- registering it would demand a styled name the sheet '
            'deliberately does not emit',
        )

        window = MainWindow(make_manager())
        try:
            collected = set(collect_names(window))
            for name in ('actionRail', 'librarySidebar'):
                self.assertIn(name, collected,
                              f'#{name} must sit in the MainWindow tree')
            self.assertIsNotNone(window.findChild(QWidget, 'actionRail'))
            self.assertIsNotNone(window.findChild(QWidget, 'librarySidebar'))
        finally:
            window.deleteLater()

    def _press_shortcut(self, window, key) -> None:
        """Inject a Ctrl-<key> press the way the keyboard does it.

        Delivered to ``focusWidget()`` (falling back to the window) so the
        ``QShortcutMap`` sees it inside the active window, which is what both
        the deleted menu's actions and the rail/window actions use as their
        ``WindowShortcut`` context.
        """
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent

        receiver = window.focusWidget() or window
        self.app.sendEvent(
            receiver,
            QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.ControlModifier))

    def test_shortcuts_survive_menu_removal(self):
        """Review Focus 4 / spec §6: Ctrl+O and Ctrl+Q must outlive the menu.

        Green before the swap (the menu's QActions answered) and green after
        it (the rail's open-file action and a window-level exit action), so
        what this test refuses to tolerate is a shell that quietly drops one.
        Ctrl+Q deliberately has no rail button -- closing the window quits
        (spec §6) -- so it needs a window-level owner, which is what the
        second half pins.
        """
        from unittest.mock import patch

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QFileDialog

        from view.main_window import MainWindow

        song = str(Path('C:/media/song.mp3'))
        window = MainWindow(make_manager())
        emitted: list = []
        window.scan_folder_requested.connect(emitted.append)
        try:
            window.resize(900, 600)
            window.show()
            window.activateWindow()
            self.app.processEvents()

            # The chooser is what Ctrl+O *reaches*, not what this test runs:
            # a real modal dialog would block the offscreen event loop.
            with patch.object(QFileDialog, 'getOpenFileNames',
                              lambda *args, **kwargs: ([song], '')):
                self._press_shortcut(window, Qt.Key.Key_O)
            self.assertEqual(
                [str(Path(song).parent)], emitted,
                'Ctrl+O must reach scan_folder_requested exactly once, via the '
                'file that the chooser "returned"',
            )

            self._press_shortcut(window, Qt.Key.Key_Q)
            self.app.processEvents()
            self.assertFalse(window.isVisible(),
                             'Ctrl+Q must close the window even with no menu bar')
        finally:
            window.deleteLater()

    def test_rail_dispatch_reaches_the_window_exactly_once(self):
        """Ledger constraint 3 *and* spec §1 criterion 4: each id does real work.

        A rail click already routes ``clicked -> action.trigger() -> triggered``,
        and the rail itself connects only the action (Task 3's critical fix) -- so a
        window that *also* wired the button or the action would deliver every click
        twice. ``click()`` drives the real route, and one click per id is what makes
        the count the assertion rather than a side note.

        The second half is what the batch-2 final review (finding 3) found missing:
        this test used to drive two of the seven ids, because ``MainWindow``'s
        dispatch table ignores an unknown id on purpose ("a crash in a click handler
        is worse than a no-op") -- so deleting the ``ACTION_OPEN_FOLDER`` or the
        ``ACTION_ABOUT`` entry from the table kept the entire suite green while
        removing a user-visible action from the app. A deliberately silent fallback
        cannot be tested by absence, only by presence: every id is clicked and every
        id's *effect* is observed, which is the only way a dropped table entry shows
        up. The table's own shape is pinned too (one expectation per declared id), so
        an eighth id cannot join ``ACTION_IDS`` without a dispatch case here.
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

        from core import i18n
        from view.main_window import MainWindow
        from view.widgets.action_rail import (
            ACTION_ABOUT,
            ACTION_APPEARANCE,
            ACTION_IDS,
            ACTION_LIBRARY,
            ACTION_OPEN_FILE,
            ACTION_OPEN_FOLDER,
            ACTION_REFRESH,
            ACTION_REFRESH_ALL,
        )

        song = str(Path('C:/media/song.mp3'))
        folder = 'C:/media/folder-library'
        current = '/media/rock'

        window = MainWindow(make_manager())
        # The panel installs an *application-level* filter while it is open (Task 4),
        # and ``deleteLater`` does not run until the loop spins -- so a panel left
        # open here would eat mouse presses for the tests that follow. ``hide_panel``
        # is documented idempotent, so this can be unconditional.
        sidebar = window.findChild(QWidget, 'librarySidebar')
        self.addCleanup(sidebar.hide_panel)
        try:
            rail = window.findChild(QWidget, 'actionRail')
            self.assertIsNotNone(rail, '#actionRail must live in the window tree')

            # ``_on_refresh_library`` only emits when the window knows a current
            # library, so the id has to be driven on a window that looks used.
            window.set_libraries([SimpleNamespace(name='Rock', path=current)])
            window.set_current_library(current)

            seen = {'scan': [], 'refresh': [], 'refresh_all': [],
                    'appearance': [], 'about': []}
            about: list = []
            window.scan_folder_requested.connect(seen['scan'].append)
            window.refresh_library_requested.connect(seen['refresh'].append)
            window.refresh_all_requested.connect(lambda: seen['refresh_all'].append(True))
            window.manage_appearance_requested.connect(lambda: seen['appearance'].append(True))

            def check_library():
                self.assertTrue(
                    window.is_library_panel_open(),
                    'the library id toggles the floating panel through its own '
                    'signal -- it never reaches the dispatch table (spec §3.2), so '
                    'this is the only witness that the button does anything')

            def check_about():
                self.assertEqual(
                    [(window, i18n.get('dialog.about.title'),
                      i18n.get('dialog.about.text'))], about,
                    'about is the one id whose effect is a modal: the table entry '
                    'calls QMessageBox.about on the window with the two localised '
                    'strings -- no entry, no dialog, and nothing else is red')

            checks = {
                ACTION_LIBRARY: check_library,
                ACTION_OPEN_FILE: lambda: self.assertEqual(
                    [str(Path(song).parent)], seen['scan'],
                    'open_file must emit scan_folder_requested once per click, with '
                    'the chooser result\'s parent directory'),
                ACTION_OPEN_FOLDER: lambda: self.assertEqual(
                    [folder], seen['scan'],
                    'open_folder must emit scan_folder_requested once per click, '
                    'with the chosen directory itself'),
                ACTION_REFRESH: lambda: self.assertEqual(
                    [current], seen['refresh'],
                    'refresh must emit refresh_library_requested once, for the '
                    'current library path'),
                ACTION_REFRESH_ALL: lambda: self.assertEqual(
                    [True], seen['refresh_all'],
                    'refresh_all must emit refresh_all_requested once per click'),
                ACTION_APPEARANCE: lambda: self.assertEqual(
                    [True], seen['appearance'],
                    'appearance must emit manage_appearance_requested once per click '
                    '(the presenter, not the window, opens the dialog)'),
                ACTION_ABOUT: check_about,
            }
            self.assertEqual(
                set(ACTION_IDS), set(checks),
                'the rail declares ids this test does not click -- every id has to '
                'be evidenced against the dispatch table, which is spec §1 '
                'criterion 4')

            with patch.object(QFileDialog, 'getOpenFileNames',
                              lambda *args, **kwargs: ([song], '')), \
                    patch.object(QFileDialog, 'getExistingDirectory',
                                 lambda *args, **kwargs: folder), \
                    patch.object(QMessageBox, 'about',
                                 lambda *args: about.append(args)):
                for action_id, assert_effect in checks.items():
                    with self.subTest(action_id=action_id):
                        for bucket in seen.values():
                            bucket.clear()
                        about.clear()
                        rail.button_for(action_id).click()
                        assert_effect()
                        # Exactly one *signal-level* effect per click, checked after
                        # each click rather than at the end, so a double connection on
                        # one button cannot be hidden by a missing one on another. The
                        # library entry is the one id with nothing to count: its window
                        # effect is the panel flag above, and it must not also fire a
                        # dispatch-table signal -- 1 for the six routed ids, 0 for it.
                        expected = 0 if action_id == ACTION_LIBRARY else 1
                        self.assertEqual(
                            expected,
                            sum(len(bucket) for bucket in seen.values()) + len(about),
                            f'{action_id} produced {expected} window effect(s) and '
                            'the click reached something else too (or nothing else): '
                            'the window must connect the rail signal once and nothing '
                            'on the buttons')

            # The toggle is a toggle: a second click closes what the first opened.
            rail.button_for(ACTION_LIBRARY).click()
            self.assertFalse(window.is_library_panel_open(),
                             'the library button must also close the panel')
        finally:
            window.deleteLater()

    def test_sidebar_selection_reaches_the_window_exactly_once(self):
        """Same rule on the panel side: one connection, one window emission.

        ``LibrarySidebar.library_selected`` already de-duplicates
        re-clicking the current row (Task 4); the window must not add a
        second consumer of the same signal.
        """
        from PyQt6.QtWidgets import QPushButton

        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        try:
            window.set_libraries([
                SimpleNamespace(name='Rock', path='/media/lib0'),
            ])
            rows = [
                row for row in window.findChildren(QPushButton, 'libraryRow')
                if row.property('library_path') is not None
            ]
            self.assertEqual(1, len(rows))
            emitted: list = []
            window.library_selected.connect(emitted.append)

            rows[0].click()

            self.assertEqual(['/media/lib0'], emitted,
                              'one row click must select the library exactly once')
            self.assertEqual('/media/lib0', window._current_library_path)
        finally:
            window.deleteLater()

    def test_sidebar_add_reaches_the_window_exactly_once(self):
        """Same rule on the panel side: one connection, one window emission.

        The footer's add entry, identified by its un-elided label because the two
        administration entries (add + manage) share ``#libraryRow`` and the absence
        of ``library_path`` no longer singles one out.

        This is the emitter proof the dead-signals census in
        ``tests/test_dead_code_removed.py`` points at: the signal survived
        Task 2 as unreachable and became live again when the shell put the
        panel -- with its add entry -- into the tree. The chooser is stubbed
        because the test pins the wiring, not the dialog.
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QFileDialog, QPushButton

        from core import i18n
        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        try:
            emitted: list = []
            window.add_library_requested.connect(emitted.append)
            footer = [
                row for row in window.findChildren(QPushButton, 'libraryRow')
                if row.property('library_path') is None
            ]
            self.assertEqual(2, len(footer),
                             'the footer owns both administration entries now')
            add = [row for row in footer if row.full_name == i18n.get('sidebar.add')]
            self.assertEqual(1, len(add), 'the footer add entry is the 添加媒体库 row')

            with patch.object(QFileDialog, 'getExistingDirectory',
                              lambda *args, **kwargs: '/media/new'):
                add[0].click()

            self.assertEqual(['/media/new'], emitted,
                              'one footer click with a chosen folder emits once')
        finally:
            window.deleteLater()

    def test_sidebar_manage_reaches_the_window_exactly_once(self):
        """The footer's second entry: ``manage_requested`` -> one window emission.

        ``MainWindow.manage_libraries_requested`` has had exactly one listener since
        Task 2 (the presenter's dialog opener) and no emitter since Task 7 deleted
        the menu bar -- spec §3.2's correction hands the emitter to this row, so a
        second connection on the window side would open two dialogs per click.
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QDialog, QPushButton

        from core import i18n
        from view.dialogs.library_dialog import LibraryManagementDialog
        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        try:
            emitted: list = []
            window.manage_libraries_requested.connect(lambda: emitted.append(True))
            manage = [
                row for row in window.findChildren(QPushButton, 'libraryRow')
                if row.full_name == i18n.get('sidebar.manage')
            ]
            self.assertEqual(1, len(manage))
            self.assertIsNone(manage[0].path,
                              'the management entry selects no library')

            with patch.object(LibraryManagementDialog, 'exec',
                              lambda dialog: QDialog.DialogCode.Accepted):
                manage[0].click()

            self.assertEqual([True], emitted,
                             'one footer click must ask for the dialog exactly once')
        finally:
            window.deleteLater()

    def test_unbounded_name_scales_with_the_data(self):
        """The ``UNBOUNDED_NAMES`` decision at its reason-for-existing size.

        Thirty libraries is spec §1 criterion 2's own number; the row count is
        libraries + 2 because the footer's two administration entries share
        ``#libraryRow`` (add + manage, spec §3.2's Task 8 correction). The same
        helper call must find no violation anywhere else in the tree.
        """
        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        try:
            window.set_libraries([
                SimpleNamespace(name=f'Lib{i}', path=f'/media/lib{i}')
                for i in range(30)
            ])
            counts = Counter(collect_names(window))
            self.assertEqual(32, counts['libraryRow'],
                             '30 rows plus the two shared-name footer entries')
            self.assertEqual([], multiplicity_failures(counts))
        finally:
            window.deleteLater()

    def test_unknown_repeated_name_still_trips_the_default(self):
        """The exemption must cover exactly ``UNBOUNDED_NAMES`` and nothing else.

        Synthetic on purpose: a live tree must *not* contain a doubled
        ``#progressSlider`` (that would already be the bug), so the only way to
        prove the default-1 rule stayed open is to feed the helper one.
        """
        failures = multiplicity_failures(
            Counter({'progressSlider': 2, 'playlistView': 1}))
        self.assertEqual(1, len(failures), failures)
        self.assertIn('progressSlider', failures[0])

    def test_toast_repositions_when_the_window_resizes(self):
        """Ledger constraint 7: ``Toast`` places itself at show time only.

        The shell owns the *trigger* to re-place (Task 6 left that to Task 7);
        without it a toast shown before a drag-shrink sits where the old,
        wider container centred it -- stale geometry exactly while the message
        is still on screen.
        """
        from PyQt6.QtWidgets import QFrame, QWidget

        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        try:
            window.resize(900, 600)
            window.show()
            self.app.processEvents()

            window.show_toast('kept alive across the resize')
            self.app.processEvents()
            toast = window.findChild(QFrame, 'toast')
            self.assertIsNotNone(toast, '#toast must live in the window tree')
            self.assertTrue(toast.isVisible())
            container = window.findChild(QWidget, 'playlistContainer')
            self.assertIsNotNone(container,
                                 '#playlistContainer must be the toast host')
            wide_centre = (container.width() - toast.width()) // 2
            self.assertEqual(wide_centre, toast.x(),
                             'a fresh toast is centred in its container')

            window.resize(500, 420)
            self.app.processEvents()
            self.assertEqual((container.width() - toast.width()) // 2, toast.x(),
                             'the toast followed the container: MainWindow must '
                             're-place it on parent resize')
            self.assertLessEqual(toast.x() + toast.width(), container.width())
        finally:
            window.close()
            window.deleteLater()


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class StyleSheetSelectorsHaveWearersTest(unittest.TestCase):
    """Review finding 3: the sheet's other direction -- sheet -> live tree.

    ``tests/test_theme_qss.py::test_declares_every_required_selector`` proves
    that every *registered* selector is styled, and
    :meth:`ViewStructureTest.test_every_required_object_name_exists` proves that
    every registered name is *present*. Neither one looks at what the generator
    emits beyond the registration, so after Task 9 deleted the five left-panel
    rules nothing at all stood between them and their return: re-emit
    ``#albumArt`` into the sheet and the suite stayed green (the report concedes
    this at §A.6). A rule no widget can wear is inert rather than wrong, but it is
    also invisible -- a reader cannot tell dead paint from live, and the render
    matrix cannot photograph a widget that does not exist.

    The rule this class enforces: every ``#name`` and every ``[prop="value"]``
    token of every selector member in the generated sheet must have a wearer in a
    constructed tree, or the member must be named by
    :data:`core.theme_qss.KNOWN_DEAD_SELECTORS`; and, since the batch-2 final
    review, every **bare class** a member names must have an instance in that tree
    or be a name of the recorded chrome exemption.

    That last clause is the one this class got wrong for a whole pass. Token-wise
    a bare rule has nothing to check -- ``QSplitter::handle`` carries no ``#name``
    and no ``[prop]``, so :func:`selector_offenders` answered ``[]`` and the two
    splitter rules the rail replaced (spec §3.3) sat emitted, un-worn and
    unreported. The exemption list the generator's own scope gate uses was the only
    thing standing between a dead rule and a green suite, and this guard never read
    it: a hole in exactly the mechanism built to stop dead rules lingering
    silently. ``test_every_emitted_bare_class_is_worn_or_exempted`` closes it,
    against the *same* list rather than a second competing one, and
    :meth:`test_the_zero_wearer_chrome_exemptions_are_the_recorded_three` pins
    which of those names really have no wearer so the macOS question cannot rot into
    an assumption.

    Two details the test has to get right, because a guard that fails for the
    wrong reason gets deleted:

    * **the tree must be driven, not just built.** ``[current="true"]`` and
      ``[running="true"]`` are *states* -- at rest every sidebar row says
      ``current="false"`` and no rail button spins -- so a tree of newly
      constructed widgets reports two live rules as dead. ``setUp`` therefore
      feeds two libraries, marks one current, and puts one button in flight.
    * **``#bgPathLabel`` is on the dialog, not the window**, exactly as
      :func:`make_appearance_dialog` documents: the union of the two trees is the
      live surface the sheet is allowed to select on.
    """

    def setUp(self):
        from view.main_window import MainWindow
        from view.widgets.action_rail import ACTION_REFRESH

        self.app = make_app()
        self.window = MainWindow(make_manager())
        self.dialog = make_appearance_dialog()
        self.window.set_libraries([
            SimpleNamespace(name='Rock', path='/media/rock'),
            SimpleNamespace(name='Jazz', path='/media/jazz'),
        ])
        self.window.set_current_library('/media/rock')
        self.window.set_action_progress(ACTION_REFRESH, True)
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.window.deleteLater)
        # Added last, so it runs first (cleanups are LIFO): the rail must not be
        # handed to the next test still spinning.
        self.addCleanup(self.window.set_action_progress, ACTION_REFRESH, False)

    def _sheets(self):
        """``(theme, qss)`` for both themes.

        The selector sets are theme-independent by contract, so a typo only DARK
        commits is still a typo, and it is caught by this pass.
        """
        from core.theme import DARK, LIGHT, AlphaSettings
        from core.theme_qss import build_qss

        for label in ('LIGHT', 'DARK'):
            tokens = LIGHT if label == 'LIGHT' else DARK
            yield label, build_qss(tokens, AlphaSettings())

    def _live_tokens(self):
        """The ``(names, properties)`` the driven trees wear."""
        names = set(collect_names(self.window)) | set(collect_names(self.dialog))
        return names, worn_properties(self.window, self.dialog)

    def _live_classes(self):
        """The Qt class names the driven trees instantiate -- bases included."""
        return worn_classes(self.window, self.dialog)

    def test_every_emitted_selector_has_a_wearer_or_is_listed(self):
        names, properties = self._live_tokens()

        offenders = []
        for label, qss in self._sheets():
            for member in _selector_members(qss):
                if member in KNOWN_DEAD_SELECTORS:
                    continue
                missing = selector_offenders(member, names, properties)
                if missing:
                    offenders.append(f'{label}: {member} selects {missing}')

        self.assertEqual(
            [], offenders,
            'the sheet styles widgets nobody can construct. Give the name a real '
            'widget, delete the rule, or -- only with a render-matrix decision '
            f'behind it -- list it in KNOWN_DEAD_SELECTORS: {offenders}',
        )

    def test_every_emitted_bare_class_is_worn_or_exempted(self):
        """A rule that names a whole class has an existence claim too.

        ``selector_offenders`` can only answer about tokens, so the class half of
        "does anything wear this?" went unasked: re-emit ``QSplitter::handle``
        after Task 7 deleted the splitter and this class stayed green. The claim is
        now made in the same shape as the token claim -- a wearer, or a name on the
        exemption -- and the exemption is the generator's own
        ``EXEMPT_CHROME_CLASSES``, not a second list that can disagree with the
        first. A bare class outside it fails here *and* in the scope gate, which is
        the point: the two guards read one record, so widening it is a decision with
        two witnesses rather than a pass through one blind spot. Requiring a
        recorded reason in ``EXEMPT_CHROME_DECISIONS`` as well is what stops the
        tuple from becoming a place to park a rule nobody will defend.
        """
        classes = self._live_classes()

        offenders = []
        for label, qss in self._sheets():
            for member, cls in _bare_class_selectors(qss):
                if cls in classes:
                    continue
                if cls in EXEMPT_CHROME_CLASSES and cls in EXEMPT_CHROME_DECISIONS:
                    continue
                why = ('is not on' if cls not in EXEMPT_CHROME_CLASSES
                       else 'is on the chrome exemption with no recorded reason in '
                            'EXEMPT_CHROME_DECISIONS, which is what makes the '
                            'exemption a decision instead of a parking space')
                offenders.append(
                    f'{label}: {member} styles {cls}, which no widget in the '
                    f'constructed tree is, and {why}')

        self.assertEqual(
            [], offenders,
            'the sheet styles a class nobody can construct and nobody recorded a '
            'decision for. Give it a wearer, delete the rule, or add the class to '
            'tests/test_theme_qss.py::EXEMPT_CHROME_CLASSES *with* a reason in '
            'EXEMPT_CHROME_DECISIONS -- both lists are pinned by name, so that is '
            f'a reviewed edit: {offenders}',
        )

    def test_the_zero_wearer_chrome_exemptions_are_the_recorded_three(self):
        """Exactly which exempted classes the offscreen tree cannot produce.

        The positive guard above tolerates an exemption; this one names its cost,
        which is the part that would otherwise be lost. Two of the three are the
        unresolved macOS question of spec §8 (batch 2 deleted ``menuBar()``; whether
        Qt still synthesises an application menu and its ``QMenu`` popups on macOS
        cannot be answered from this Windows host), and the third is Qt's on-demand
        tip popup. So the set is deliberately *not* derived from the exemption list
        -- it is written out, because a name sliding from "unworn but decided" to
        "worn again, nobody noticed" is the same silence this whole finding is about,
        only in the other direction: the real-machine check either lifts one of these
        out of the tuple on purpose or the suite says the tree changed under it.
        """
        classes = self._live_classes()

        for label, qss in self._sheets():
            bare = {cls for _member, cls in _bare_class_selectors(qss)}
            with self.subTest(theme=label):
                self.assertEqual(
                    ['QMenu', 'QMenuBar', 'QToolTip'], sorted(bare - classes),
                    'the set of bare chrome classes with no wearer moved. Every '
                    'name that left it needs the rule it now wears; every name that '
                    'joined it needs a reason in EXEMPT_CHROME_DECISIONS and a '
                    'decision about whether it is chrome or dead paint',
                )

    def test_the_dead_family_is_still_the_dead_family(self):
        """No listed selector may quietly regain a wearer.

        The other half of the allowlist: a chip-wearing widget coming back (the
        batch-4 column is the plausible candidate) turns this red, which is the
        point -- Task 10 has to remove the name on purpose, not discover it later
        in a matrix that photographs a chip nobody remembers deciding for.
        """
        names, properties = self._live_tokens()

        alive = [member for member in KNOWN_DEAD_SELECTORS
                 if not selector_offenders(member, names, properties)]
        self.assertEqual(
            [], alive,
            f'{alive} is listed as dead paint but every token of it is worn again '
            '-- remove it from KNOWN_DEAD_SELECTORS now that it has a wearer',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
