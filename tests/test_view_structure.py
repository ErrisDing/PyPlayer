#!/usr/bin/env python3
"""Widget-tree structure tests for the theme layer's scoping contract.

``core/theme_qss.py`` emits rules scoped only by ``#objectName`` and
``[prop="value"]`` selectors, and it declares which ones it uses in
:data:`REQUIRED_OBJECT_NAMES` / :data:`REQUIRED_DYN_PROPERTIES`. Those two
tuples are the contract; this module is the widget side of it, so a rename on
either end fails a test instead of silently dropping a rule onto Fusion
defaults.

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
import sys
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

# Make the project root importable no matter how the test is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

from core.theme_qss import REQUIRED_DYN_PROPERTIES, REQUIRED_OBJECT_NAMES

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
        shrink to zero buttons to check. ``('chip', 'true')`` is the one pair no
        live widget wears since Task 9 deleted the chip row: the floating
        sidebar uses ``#libraryRow`` + ``[current="true"]`` instead, and the chip
        rule, its registration and Task 4's contrast pin are left standing for
        Task 10 to rule on with a render matrix in hand -- this test therefore
        pins the *declaration*, not the wearing, for that one pair.
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
        """Ledger constraint 3: connect only ``ActionRail.action_triggered``.

        A rail click already routes ``clicked -> action.trigger() ->
        triggered``, and the rail itself connects only the action (Task 3's
        critical fix) -- so a window that *also* wired the button or the action
        would deliver every click twice. ``click()`` drives the real route.
        The appearance entry doubles as the dispatch-table check: it is the
        only rail action whose effect is a window signal rather than a handler.
        """
        from unittest.mock import patch

        from PyQt6.QtWidgets import QFileDialog, QWidget

        from view.main_window import MainWindow

        song = str(Path('C:/media/song.mp3'))
        with patch.object(QFileDialog, 'getOpenFileNames',
                          lambda *args, **kwargs: ([song], '')):
            window = MainWindow(make_manager())
            try:
                rail = window.findChild(QWidget, 'actionRail')
                self.assertIsNotNone(rail, '#actionRail must live in the window tree')
                scans: list = []
                appearances: list = []
                window.scan_folder_requested.connect(scans.append)
                window.manage_appearance_requested.connect(lambda: appearances.append(True))

                rail.button_for('open_file').click()
                rail.button_for('appearance').click()

                self.assertEqual(1, len(scans),
                                 'open_file must emit scan_folder_requested once per click')
                self.assertEqual(1, len(appearances),
                                 'appearance must emit manage_appearance_requested once per click')
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
