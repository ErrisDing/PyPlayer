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
MULTIPLICITY = {'timeLabel': 2}

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

    def test_transport_and_chip_properties(self):
        from view.main_window import MainWindow

        # The literals below are the contract Task 4 declared; assert that first
        # so an edit to the tuple fails here rather than in an `in` test that
        # would silently shrink to zero buttons to check.
        self.assertIn(('role', 'transport'), REQUIRED_DYN_PROPERTIES)
        self.assertIn(('chip', 'true'), REQUIRED_DYN_PROPERTIES)

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
            chips = [
                button for button in window.findChildren(QPushButton)
                if button.property('chip') == 'true'
            ]
            self.assertEqual(len(chips), 2, 'One chip button per media library')

            # ``QPushButton[chip="true"][selected="true"]`` is written against
            # strings, and strings are the contract this test enforces. (Qt's
            # attribute selector does special-case QMetaType::Bool and would
            # match a Python bool as "true"/"false" -- but the sheet's own text
            # is what a reader greps, so the widgets declare strings.)
            for chip in chips:
                selected = chip.property('selected')
                self.assertIsInstance(
                    selected, str,
                    f'chip {chip.text()!r} sets selected as {type(selected).__name__}, '
                    'but the sheet is written against the strings "true"/"false"',
                )
                self.assertIn(selected, ('true', 'false'))

            window.set_current_library('/lib/jazz')
            self.assertEqual(
                [chip.text() for chip in chips if chip.property('selected') == 'true'],
                ['Jazz'],
            )
        finally:
            window.deleteLater()

    def test_object_names_are_unique_per_scope(self):
        from view.main_window import MainWindow

        window = MainWindow(make_manager())
        dialog = make_appearance_dialog()
        try:
            counts = Counter(collect_names(window) + collect_names(dialog))
            expected = set(REQUIRED_OBJECT_NAMES) | set(DIALOG_SLIDER_NAMES)
            for name in sorted(expected):
                limit = MULTIPLICITY.get(name, 1)
                self.assertLessEqual(
                    counts[name], limit,
                    f'#{name} appears {counts[name]} times, the sheet assumes at most {limit}',
                )
            self.assertEqual(
                counts['timeLabel'], 2,
                '#timeLabel must sit on both the elapsed and the total-duration label',
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
