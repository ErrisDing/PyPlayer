#!/usr/bin/env python3
"""presenter 状态反馈的三类分流（批次 2 Task 8）。

spec §5 splits the one ``set_status_message`` channel three ways, and the
presenter's fourteen call sites move with it:

* **progress** -> ``set_action_progress`` on the rail button that started the
  work, cleared when the work ends; ``status.refreshing`` / ``status.refresh_all``
  stop producing text at all (spec §5: 不产生文本);
* **result** -> ``show_toast``, through i18n keys with *real* parameters -- the
  four hardcoded English f-strings became keys and the site that passed no ``name=``
  finally substitutes;
* **error** -> stays a dialog, except ``status.theme_save_failed``, which joins
  the toast group (it was never a modal; see the §5 correction in the spec).

Three sites are **deleted**: ``status.playing``, ``status.paused`` and
``Now playing: {title}``. The transport button already carries play/pause and
``NowPlayingStrip`` already carries the title, so a third control repeating the
same fact is the defect spec §1 criterion 3 describes.

Harness: a **real** ``MainWindow`` and a **real** ``MainPresenter``; only the five
services are ``MagicMock``\\ s. Two consequences shape the helpers below:

* service *signals* cannot be ``emit``\\ ted on a mock, but ``connect`` on a mock
  records the receiver it was handed -- so :meth:`PresenterHarness._emit` calls
  precisely the slot the presenter registered. Delete a ``connect`` line and the
  event stops arriving, which is the failure this harness exists to catch; calling
  the presenter's slots directly would leave every connection untested.
* the status channels are wrapped, not replaced: :func:`_spied` records each call
  **and runs the real method**, so the toast really paints and the rail really
  spins -- an assertion about a call list cannot pass on a channel that was
  quietly rewired to nowhere.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_presenter_status -v
"""
import contextlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n
from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

ROCK = SimpleNamespace(name='Rock', path='/media/rock')
JAZZ = SimpleNamespace(name='Jazz', path='/media/jazz')
NEW_LIBRARY_PATH = '/media/new_library'

#: The keys whose copy the presenter is responsible for, in the order
#: :meth:`PresenterHarness._drive_every_status_path` fires them. Every one must
#: reach the user substituted and localised -- spec §1 criterion 5.
STATUS_KEYS = (
    'status.library_refreshed',
    'status.refreshed_files',
    'status.library_switched',
    'status.library_removed',
    'status.theme_save_failed',
    'status.background_set',
    'status.background_cleared',
    'status.completed',
    'status.tracks_loaded',
)

#: Copy Task 8 retires: play/pause/"now playing" duplicate the transport button
#: and the strip, and the two progress strings became a button state.
RETIRED_KEYS = ('status.playing', 'status.paused', 'status.now_playing',
                'status.refreshing', 'status.refresh_all')


def _media(count, prefix='/media/rock'):
    """``count`` MediaFile-shaped stand-ins (only ``.path``/``.title`` are read)."""
    return [SimpleNamespace(path=f'{prefix}/track{index}.mp3',
                            title=f'Track {index}')
            for index in range(count)]


@contextlib.contextmanager
def _spied(view, *names):
    """Record calls to ``view``'s status channels while still running them."""
    calls = {name: [] for name in names}

    def make(name, original):
        def spy(*args, **kwargs):
            calls[name].append(args)
            return original(*args, **kwargs)
        return spy

    for name in names:
        setattr(view, name, make(name, getattr(view, name)))
    try:
        yield calls
    finally:
        for name in names:
            delattr(view, name)


@contextlib.contextmanager
def _tiny_png():
    """One 16 px PNG on disk, for the background-image paths."""
    import tempfile

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'background.png'
        seed = QPixmap(16, 16)
        seed.fill(Qt.GlobalColor.darkBlue)
        if not seed.save(str(path), 'PNG'):
            raise unittest.SkipTest('the offscreen platform wrote no test PNG')
        yield path


def _flush_deferred_deletions():
    """Reap the widgets ``LibrarySidebar._rebuild_rows`` handed to ``deleteLater``.

    A row queued for deletion is still in the object tree until the deferred delete
    is delivered, and ``findChildren`` hands back whatever is left of it -- a plain
    ``QPushButton`` wrapper, because the ``LibraryRow`` Python object is already
    gone. Counting rows without this flush therefore counts libraries the
    presenter dropped two calls ago (measured: 5 rows where 3 were live).

    ``processEvents()`` is not enough and neither is a zero-timeout timer here:
    ``QEvent.DeferredDelete`` is only posted to the queue the event *loop* drains
    on entry, so the documented manual flush is what a test without a loop needs
    (``QCoreApplication.sendPostedEvents(nullptr, QEvent::DeferredDelete)``).
    Measured both ways: 3 -> 3 for ``processEvents``, 3 -> 1 for the call below.
    """
    from PyQt6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _footer_row(window, label: str):
    """The panel's footer entry whose *un-elided* text is ``label``, else ``None``.

    Matched on ``full_name`` and not ``text``: ``#libraryRow`` elides against its
    own width, so the visible string is not an identity. The footer entries are
    the only path-less rows, and the label is what tells them apart (Task 4's
    shared-objectName ruling, now with two entries).
    """
    from PyQt6.QtWidgets import QPushButton

    _flush_deferred_deletions()
    rows = [row for row in window.findChildren(QPushButton, 'libraryRow')
            if row.property('library_path') is None and row.full_name == label]
    return rows[0] if len(rows) == 1 else None


def _library_rows(window):
    from PyQt6.QtWidgets import QPushButton

    _flush_deferred_deletions()
    return [row for row in window.findChildren(QPushButton, 'libraryRow')
            if row.property('library_path') is not None]


class PresenterHarness:
    """Real window + real presenter + mocked services, shared by both classes."""

    def setUp(self):
        from PyQt6.QtWidgets import QWidget

        from presenter.main_presenter import MainPresenter
        from service.queue_service import PlaybackPosition
        from view.main_window import MainWindow

        self._previous_locale = i18n.get_current_locale()
        i18n.set_locale('zh_CN')
        self.app = make_app()

        self.view = MainWindow(make_manager())
        self.addCleanup(self.view.deleteLater)
        self.rail = self.view.findChild(QWidget, 'actionRail')
        self.toast = self.view.findChild(QWidget, 'toast')
        self.assertIsNotNone(self.rail, '#actionRail must be part of the shell')
        self.assertIsNotNone(self.toast, '#toast must be part of the shell')

        self.libraries = [ROCK, JAZZ]
        self.playback = mock.MagicMock(name='playback_service')
        self.playback.get_volume.return_value = 0.5
        self.playback.current_track = None
        self.queue = mock.MagicMock(name='queue_service')
        self.queue.get_current_position.return_value = PlaybackPosition()
        self.queue.get_loop_mode.return_value = 'OFF'
        self.queue.advance_to_next.return_value = None
        self.queue.is_empty.return_value = True
        self.library = mock.MagicMock(name='library_service')
        self.library.refresh_library.return_value = _media(2)
        # Three files across two libraries: the numbers the refresh copy has to
        # carry, chosen distinct so a swapped ``{count}``/``{libs}`` is visible.
        self.library.refresh_all_libraries.return_value = {
            ROCK.path: _media(2), JAZZ.path: _media(1)}
        self.library.get_files.return_value = _media(2)
        self.metadata = mock.MagicMock(name='metadata_service')
        self.config = mock.MagicMock(name='config_service')
        self.config.get_libraries.return_value = self.libraries
        self.config.get_background_image.return_value = None
        self.config.get_theme.return_value = 'light'
        self.config.get_overlay_alpha.return_value = 0.3
        self.config.get_playlist_alpha.return_value = 0.5
        self.config.get_controls_alpha.return_value = 0.6
        self.config.add_library.return_value = True
        self.config.remove_library.return_value = True
        self.config.set_theme.return_value = True

        self.presenter = MainPresenter(
            view=self.view,
            playback_service=self.playback,
            queue_service=self.queue,
            library_service=self.library,
            metadata_service=self.metadata,
            config_service=self.config,
        )
        self.view.set_current_library(ROCK.path)

    def tearDown(self):
        # The floating panel installs an *application-level* event filter while it
        # is open (Task 4). ``deleteLater`` does not run until the loop spins, so a
        # panel left open here would keep consuming mouse presses for the tests
        # that follow in the same process.
        if self.view.is_library_panel_open():
            self.view._sidebar.hide_panel()
        i18n.set_locale(self._previous_locale)

    # === driving the layers the way the application does ===

    def _emit(self, service, signal_name, *args):
        """Fire a service signal through the connection the presenter made."""
        signal = getattr(service, signal_name)
        receivers = [call.args[0] for call in signal.connect.call_args_list]
        self.assertTrue(
            receivers,
            f'nothing is connected to {signal_name}: the presenter lost the route',
        )
        for receiver in receivers:
            receiver(*args)

    def _click(self, action_id: str):
        """Press one rail button -- the route a user takes, shortcut included."""
        self.rail.button_for(action_id).click()

    def _open_appearance_dialog(self, *actions):
        """Reach the appearance dialog through the rail button, then act on it."""
        from PyQt6.QtWidgets import QDialog

        from view.dialogs.appearance_dialog import AppearanceDialog

        def fake_exec(dialog):
            for action in actions:
                action(dialog)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(AppearanceDialog, 'exec', fake_exec):
            # The button, never the window signal: a lost entry in
            # ``MainWindow._on_rail_action`` or a dropped presenter connect would
            # otherwise still open the dialog here.
            self._click('appearance')

    def _ensure_panel_open(self):
        if not self.view.is_library_panel_open():
            self.view.toggle_library_panel()

    def _open_manage_dialog(self, on_open=None):
        """Click the footer's 管理媒体库 entry; ``on_open`` runs inside ``exec``.

        Returns the dialog the presenter constructed, or ``None`` when nothing
        opened -- the emitter proof for spec §3.2's correction.
        """
        from PyQt6.QtWidgets import QDialog

        from view.dialogs.library_dialog import LibraryManagementDialog

        opened = []

        def fake_exec(dialog):
            opened.append(dialog)
            # Copied for assertions: ``_libraries`` is the dialog's own state, and
            # a later ``set_libraries`` during the same exec would rewrite it.
            dialog.opened_libraries = list(dialog._libraries)
            if on_open is not None:
                on_open(dialog)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(LibraryManagementDialog, 'exec', fake_exec):
            self._ensure_panel_open()
            row = _footer_row(self.view, i18n.get('sidebar.manage'))
            self.assertIsNotNone(
                row,
                'the floating panel has no 管理媒体库 footer entry, so media library '
                'management has no home (spec §3.2 correction)',
            )
            row.click()
        return opened[0] if opened else None

    def _delete_first_row(self, dialog):
        """Select the dialog's first library and press 删除 (the real buttons)."""
        dialog._list_widget.setCurrentRow(0)
        dialog._delete_button.click()

    def _remove_a_library_via_the_panel(self):
        """The only route to ``ConfigService.remove_library``: panel -> dialog -> 删除."""
        from PyQt6.QtWidgets import QMessageBox

        with mock.patch.object(QMessageBox, 'question',
                               lambda *args, **kwargs: QMessageBox.StandardButton.Yes):
            return self._open_manage_dialog(self._delete_first_row)

    def _click_add_row(self, chosen_path):
        """Click the footer's 添加媒体库 entry with the directory chooser stubbed."""
        from PyQt6.QtWidgets import QFileDialog

        row = _footer_row(self.view, i18n.get('sidebar.add'))
        self.assertIsNotNone(row, 'the floating panel lost its add entry')
        with mock.patch.object(QFileDialog, 'getExistingDirectory',
                               lambda *args, **kwargs: chosen_path):
            row.click()
        return row

    def _drive_every_status_path(self):
        """Fire every routed result path once under ``zh_CN``, in key order.

        Removal and the theme failure go through their real dialogs; the rest
        through the rail, the panel or a service signal. Nothing here calls a
        presenter slot the application does not call.
        """
        from PyQt6.QtWidgets import QFileDialog

        from core.library_manager import Track
        from core.player import PlayerState

        with _spied(self.view, 'show_toast') as calls, _tiny_png() as image:
            self._click('refresh')                      # library_refreshed
            self._click('refresh_all')                  # refreshed_files
            self.view.library_selected.emit(JAZZ.path)  # library_switched
            self._remove_a_library_via_the_panel()      # library_removed

            self.config.set_theme.return_value = False
            self._open_appearance_dialog(               # theme_save_failed
                lambda dialog: dialog._theme_buttons['dark'].click())
            self.config.set_theme.return_value = True

            with mock.patch.object(QFileDialog, 'getOpenFileName',
                                   return_value=(str(image), '')):
                self._open_appearance_dialog(           # background_set
                    lambda dialog: dialog._select_bg_btn.click())
            self._open_appearance_dialog(               # background_cleared
                lambda dialog: dialog._clear_bg_btn.click())

            self._emit(self.playback, 'track_ended')    # completed
            self._emit(self.library, 'library_loaded', ROCK.path,
                       _media(4))                       # tracks_loaded

            # And the two paths that must now say nothing at all.
            self._emit(self.playback, 'state_changed', PlayerState.PLAYING)
            self._emit(self.playback, 'track_changed',
                       Track(path='/media/rock/a.mp3', title='Song A'))

            messages = [args[0] for args in calls['show_toast']]
        return messages


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PresenterStatusTest(PresenterHarness, unittest.TestCase):
    """Where each of the fourteen status calls lands."""

    # === criterion 3: the window title is not a status channel ===

    def test_title_never_changes_across_states(self):
        """Review Focus 5 / spec §1 criterion 3, over every routed site."""
        from core.library_manager import Track
        from core.player import PlayerState

        expected = i18n.get('window.title')
        self.assertEqual(expected, self.view.windowTitle(),
                         'the shell must start on the frozen title')

        def check(step):
            with self.subTest(step=step):
                self.assertEqual(
                    expected, self.view.windowTitle(),
                    f'{step} rewrote the window title: the title is no longer a '
                    'status channel (spec §1 criterion 3)',
                )

        check('constructed')
        self._emit(self.playback, 'state_changed', PlayerState.PLAYING)
        check('playing')
        self._emit(self.playback, 'state_changed', PlayerState.PAUSED)
        check('paused')
        self._emit(self.playback, 'track_changed',
                   Track(path='/media/rock/a.mp3', title='Song A',
                         artist='Artist', album='Album'))
        check('track changed')
        self.view.library_selected.emit(JAZZ.path)
        check('library switched')
        self._click('refresh')
        check('refresh one')
        self._click('refresh_all')
        check('refresh all')
        self._emit(self.library, 'library_loaded', ROCK.path, _media(3))
        check('library loaded')
        self._emit(self.playback, 'track_ended')
        check('queue completed')
        self._emit(self.playback, 'state_changed', PlayerState.IDLE)
        check('idle')
        self.assertEqual(expected, self.view.windowTitle())

    # === progress ===

    def test_refresh_progress_round_trips(self):
        """``set_action_progress(id, True)`` before the work, ``False`` after.

        Asserted on the rail as well as on the call list: the presenter can report
        a state the widget refuses to enter, and only the rail knows. The running
        state is probed *from inside* the service call, because a spinner raised
        and cleared around a synchronous scan only means something while the scan
        is running.
        """
        running_during_work = []

        def refresh(library_path):
            running_during_work.append(self.rail.is_running('refresh'))
            return _media(2)

        self.library.refresh_library.side_effect = refresh

        with _spied(self.view, 'set_action_progress', 'show_toast') as calls:
            self._click('refresh')
            self.assertEqual(
                [('refresh', True), ('refresh', False)], calls['set_action_progress'],
                'refreshing one library must put its own button in flight and take '
                'it out again, with no third state',
            )
            self.assertEqual([True], running_during_work,
                             'the button was not in flight while the scan ran')
            self.assertFalse(self.rail.is_running('refresh'),
                             'a finished refresh must not leave a spinner behind')
            # One toast: the result. The progress copy itself never becomes text.
            self.assertEqual(1, len(calls['show_toast']), calls['show_toast'])

        with _spied(self.view, 'set_action_progress') as calls:
            self._click('refresh_all')
            self.assertEqual(
                [('refresh_all', True), ('refresh_all', False)],
                calls['set_action_progress'],
                'refresh-all reports on its own button, not on refresh',
            )
            self.assertFalse(self.rail.is_running('refresh_all'),
                             'the finished scan-all must release both entries')
            self.assertTrue(self.rail.button_for('refresh').isEnabled(),
                            'refresh-all left refresh blocked')

    def test_progress_copy_never_becomes_a_message(self):
        """spec §5: the progress class produces no text at all.

        ``status.refreshing`` / ``status.refresh_all`` stay in the properties files
        for the census, so a call site that still routes them to the toast would be
        invisible to every other test here.
        """
        for key, action_id in (('status.refreshing', 'refresh'),
                               ('status.refresh_all', 'refresh_all')):
            with self.subTest(key=key):
                copy = i18n.get(key)
                with _spied(self.view, 'show_toast') as calls:
                    self._click(action_id)
                self.assertNotIn(copy, [args[0] for args in calls['show_toast']],
                                 f'{key} still renders as a message')

    def test_progress_state_survives_a_failing_scan(self):
        """A raising scan must still clear the button, or the rail dies.

        ``_BLOCKED_PAIR`` disables *both* refresh entries while one runs, so a
        stuck state does not only leave a spinner: it takes the other entry down
        with it, permanently.

        Driven on the handler rather than the rail button for one environment
        reason: since PyQt 5.5 an exception that escapes a slot invoked *from C++*
        calls ``qFatal`` and aborts the process (measured here -- the same call
        through ``click()`` killed the run mid-suite). A Python-level call keeps
        the exception catchable; the rail, the state and the finally-path under
        test are the real ones either way.
        """
        self.library.refresh_library.side_effect = RuntimeError('disk gone')

        with _spied(self.view, 'set_action_progress') as calls:
            with self.assertRaises(RuntimeError):
                self.presenter._on_refresh_library(ROCK.path)

        self.assertEqual([('refresh', True), ('refresh', False)],
                         calls['set_action_progress'],
                         'the failed scan left its own progress report unbalanced')
        self.assertFalse(self.rail.is_running('refresh'))
        self.assertFalse(self.rail.is_running('refresh_all'),
                         'the failed refresh left its partner blocked')
        self.assertTrue(self.rail.button_for('refresh').isEnabled(),
                        'a failed scan must not disable the retry')

    # === result feedback ===

    def test_refresh_result_is_a_toast(self):
        """One toast, real numbers, no braces (spec §1 criterion 5)."""
        with _spied(self.view, 'show_toast') as calls:
            self._click('refresh_all')

        self.assertEqual(1, len(calls['show_toast']),
                         f'expected exactly one result toast, got {calls["show_toast"]}')
        message = calls['show_toast'][0][0]
        self.assertNotIn('{', message, message)
        self.assertIn('3', message, f'the file count did not reach the copy: {message}')
        self.assertIn('2', message, f'the library count did not reach the copy: {message}')
        self.assertEqual(message, self.toast.current_message(),
                         'the message must reach the widget, not only the API call')
        self.assertTrue(self.toast.isVisibleTo(self.view),
                        'a result reported into an invisible toast is not shown')

    def test_refresh_one_and_switch_library_report_by_name(self):
        """``status.library_refreshed`` / ``status.library_switched`` carry the
        library's *name*: both keys take ``{name}``, and the old code handed one a
        raw path and handed the other nothing but a hardcoded English sentence."""
        with _spied(self.view, 'show_toast') as calls:
            self._click('refresh')
            self.view.library_selected.emit(JAZZ.path)

        messages = [args[0] for args in calls['show_toast']]
        self.assertEqual(2, len(messages), messages)
        for message, name in zip(messages, ('Rock', 'Jazz')):
            with self.subTest(message=message):
                self.assertNotIn('{', message, message)
                self.assertIn(name, message,
                              f'the {{name}} parameter should have produced '
                              f'{name}: {message}')
                self.assertNotIn('/media/', message,
                                 f'a raw path reached user-visible copy: {message}')

    def test_theme_save_failure_is_toasted(self):
        """§5 correction: ``status.theme_save_failed`` is feedback, not a modal."""
        self.config.set_theme.return_value = False

        with _spied(self.view, 'show_toast', 'show_error') as calls:
            self._open_appearance_dialog(
                lambda dialog: dialog._theme_buttons['dark'].click())

        self.assertEqual(1, len(calls['show_toast']), calls['show_toast'])
        self.assertNotIn('{', calls['show_toast'][0][0])
        self.assertEqual([], calls['show_error'],
                         'a failed settings write escalated to a modal interruption; '
                         'spec §5 rules it feedback (toast)')

    def test_theme_save_success_is_silent(self):
        """The same click with a write that worked has nothing to report.

        Driven on ``dark`` against a ``light`` configuration so the dialog really
        emits: clicking the already-selected mode would prove nothing about the
        presenter's silence.
        """
        self.config.set_theme.return_value = True

        with _spied(self.view, 'show_toast', 'set_action_progress') as calls:
            self._open_appearance_dialog(
                lambda dialog: dialog._theme_buttons['dark'].click())

        self.config.set_theme.assert_called_once_with('dark')
        self.assertEqual([], calls['show_toast'], calls['show_toast'])

    def test_background_change_is_toasted(self):
        """``status.background_set`` / ``_cleared``: toasts, and no English
        ``default=`` copy riding next to a key that exists in both locales."""
        from PyQt6.QtWidgets import QFileDialog

        with _tiny_png() as image, _spied(self.view, 'show_toast') as calls, \
                mock.patch.object(QFileDialog, 'getOpenFileName',
                                  return_value=(str(image), '')):
            self._open_appearance_dialog(
                lambda dialog: dialog._select_bg_btn.click())
            self.assertIsNotNone(self.view._background_pixmap,
                                 'the set path no longer reaches the view paint')
            self._open_appearance_dialog(
                lambda dialog: dialog._clear_bg_btn.click())
            self.assertIsNone(self.view._background_pixmap,
                              'the clear path no longer restores the default background')

        messages = [args[0] for args in calls['show_toast']]
        self.assertEqual(2, len(messages), messages)
        for message in messages:
            with self.subTest(message=message):
                self.assertNotIn('{', message)
                self.assertNotIn('[MISSING', message)
                self.assertNotIn(str(image), message,
                                 'the fallback copy replaced the i18n key')

    def test_completed_and_tracks_loaded_report_as_toasts(self):
        """The last two result strings: end of queue, and a freshly loaded library."""
        from core.player import PlayerState

        with _spied(self.view, 'show_toast') as calls:
            self._emit(self.playback, 'state_changed', PlayerState.PLAYING)
            self._emit(self.playback, 'track_ended')
            self._emit(self.library, 'library_loaded', ROCK.path, _media(4))

        messages = [args[0] for args in calls['show_toast']]
        self.assertEqual(2, len(messages), messages)
        for message in messages:
            with self.subTest(message=message):
                self.assertNotIn('{', message)
                self.assertNotIn('[MISSING', message)
        self.assertIn('4', messages[1],
                      f'the track count did not reach the copy: {messages[1]}')

    # === the three deleted sites ===

    def test_playing_paused_status_removed(self):
        """Play/pause reach the transport button and *nothing else*."""
        from core.player import PlayerState

        with _spied(self.view, 'show_toast', 'set_action_progress') as calls:
            self._emit(self.playback, 'state_changed', PlayerState.PLAYING)
            self.assertTrue(self.view._bottom_panel._is_playing,
                            'the transport button is where this state lives now')
            self._emit(self.playback, 'state_changed', PlayerState.PAUSED)
            self.assertFalse(self.view._bottom_panel._is_playing)

        self.assertEqual([], calls['show_toast'],
                         'playing/paused must not be reported as text anywhere')
        self.assertEqual([], calls['set_action_progress'],
                         'a transport state is not a rail action in flight')

    def test_now_playing_copy_reaches_the_strip_only(self):
        """``Now playing: {title}`` is deleted; the strip is the only place it shows."""
        from PyQt6.QtWidgets import QWidget

        from core.library_manager import Track

        strip = self.view.findChild(QWidget, 'nowPlayingStrip')
        self.assertIsNotNone(strip, '#nowPlayingStrip must be in the shell')

        with _spied(self.view, 'show_toast') as calls:
            self._emit(self.playback, 'track_changed',
                       Track(path='/media/rock/a.mp3', title='Song A',
                             artist='Artist', album='Album'))

        self.assertEqual([], calls['show_toast'],
                         'the title line duplicates NowPlayingStrip (spec §5)')
        self.assertEqual('Song A', strip._title_text, strip._title_text)

        # An unknown title still falls back, and the fallback still belongs to the
        # view (batch 1 review finding 1).
        with _spied(self.view, 'show_toast') as calls:
            self._emit(self.playback, 'track_changed',
                       Track(path='/media/rock/b.mp3', title=''))
        self.assertEqual([], calls['show_toast'])
        self.assertEqual(i18n.get('metadata.unknown_title'), strip._title_text)

    # === the old channel is gone ===

    def test_no_status_message_calls_left(self):
        """No ``set_status_message`` anywhere in ``presenter/`` or ``view/``.

        The scan covers comments and docstrings on purpose: Task 7 left the
        forwarder behind with a note that Task 8 deletes it, and a channel that
        survives as prose is one ``git revert`` away from surviving as code.
        """
        hits = []
        for directory in ('presenter', 'view'):
            for source in sorted((ROOT / directory).rglob('*.py')):
                for number, line in enumerate(
                        source.read_text(encoding='utf-8').splitlines(), 1):
                    if 'set_status_message' in line:
                        hits.append(f'{source.relative_to(ROOT)}:{number}')
        self.assertEqual([], hits, f'the status channel still exists at {hits}')

        from view.main_window import MainWindow

        self.assertIs(
            hasattr(MainWindow, 'set_status_message'), False,
            'MainWindow.set_status_message must be deleted, not merely unused '
            '(spec §9 反向回归: the View interface lost it)',
        )

    def test_presenter_builds_no_status_copy_in_code(self):
        """The structural half of the no-hardcoded-English guard.

        The runtime tests can only see the paths this suite happens to drive, and a
        literal passed straight to ``show_toast`` stops being translatable the
        moment it is written -- which is how four of the fourteen sites got there.
        """
        source = (ROOT / 'presenter' / 'main_presenter.py').read_text(encoding='utf-8')
        offenders = []
        for number, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for marker in ('show_toast(f"', "show_toast(f'", 'show_toast("',
                           "show_toast('"):
                if marker in line:
                    offenders.append(f'presenter/main_presenter.py:{number}: {stripped}')
        self.assertEqual([], offenders,
                         'user-visible status copy must come from a key lookup that '
                         'substitutes its parameters')

        for number, line in enumerate(source.splitlines(), 1):
            if 'i18n.get(' in line and 'status.' in line and 'default=' in line:
                self.fail(
                    f'presenter/main_presenter.py:{number}: a status key with a '
                    'hardcoded default -- every status key ships in both locales')

    def test_retired_keys_have_no_lookup_left(self):
        """The deleted copy must not be resurrected by another call site.

        Scanned as *lookups* (a line that asks i18n for the key), not as mentions:
        this task's own docstrings name the retired strings to explain why they are
        gone, and silencing that prose would make the guard worse, not stricter.
        """
        for directory in ('presenter', 'view'):
            for source in sorted((ROOT / directory).rglob('*.py')):
                for number, line in enumerate(
                        source.read_text(encoding='utf-8').splitlines(), 1):
                    if 'i18n.get(' not in line and 'i18n.interface(' not in line:
                        continue
                    for key in RETIRED_KEYS:
                        self.assertNotIn(
                            key, line,
                            f'{source.relative_to(ROOT)}:{number} still looks up '
                            f'{key}: spec §5 deleted this copy (it duplicates the '
                            'transport button or the strip, or it is progress that '
                            'is now a button state)',
                        )

    # === every string, in both locales ===

    def test_every_status_message_is_localised_and_substituted(self):
        """No braces, no missing keys, no bare-ASCII English under ``zh_CN``.

        spec §1 criterion 5 on the whole channel at once: four of the fourteen
        sites were hardcoded English and one substituted nothing, and all five are
        invisible to a test that only checks that *a* toast appeared.
        """
        messages = self._drive_every_status_path()

        self.assertEqual(
            len(STATUS_KEYS), len(messages),
            f'expected {len(STATUS_KEYS)} messages in key order, got {messages}',
        )
        for key, message in zip(STATUS_KEYS, messages):
            with self.subTest(key=key, message=message):
                self.assertNotIn('{', message,
                                 f'{key} reached the user with an unsubstituted '
                                 'placeholder (spec §1 criterion 5)')
                self.assertNotIn('}', message, message)
                self.assertNotIn('[MISSING', message,
                                 f'{key} is not in main.zh_CN.properties')
                self.assertTrue(
                    any(ord(char) > 0x2E7F for char in message),
                    f'{key} rendered as bare ASCII English under zh_CN: {message!r}',
                )

    def test_every_status_key_exists_in_both_locales(self):
        """A key added to one locale only silently degrades on the other."""
        for locale_str in ('zh_CN', 'en_US'):
            i18n.set_locale(locale_str)
            for key in STATUS_KEYS + ('sidebar.manage',):
                value = i18n.get(key)
                with self.subTest(locale=locale_str, key=key):
                    self.assertNotIn('[MISSING', value,
                                     f'{key} is missing from main.{locale_str}.properties')
                    self.assertNotEqual(key, value)
        i18n.set_locale('zh_CN')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class LibraryAdministrationReachabilityTest(PresenterHarness, unittest.TestCase):
    """Task 7's review finding: 增库与删库都必须从浮层端到端可达（spec §3.2 订正）.

    Every test here starts at a click on one of the floating panel's footer
    entries, because "the signal is declared" was never the defect. The defect had
    two halves: ``manage_libraries_requested`` lost its emitter when the menu bar
    went (leaving the presenter's connect dangling), and the panel's
    ``add_library_requested`` gained an emitter and no consumer.
    """

    def setUp(self):
        super().setUp()
        self.view.toggle_library_panel()
        self.assertTrue(self.view.is_library_panel_open(),
                        'the harness opened the floating panel')

    def test_footer_owns_add_and_manage(self):
        """Two path-less rows, named by the spec §3.2 ruling: 添加 + 管理."""
        self.assertIsNotNone(_footer_row(self.view, i18n.get('sidebar.add')))
        self.assertIsNotNone(
            _footer_row(self.view, i18n.get('sidebar.manage')),
            'the panel footer must host 管理媒体库: the rail is frozen at seven '
            'actions and management is not one of them (spec §6)',
        )
        self.assertNotEqual(i18n.get('sidebar.add'), i18n.get('sidebar.manage'))
        self.assertNotIn('[MISSING', i18n.get('sidebar.manage'))

    def test_manage_row_reaches_the_presenter_dialog(self):
        """footer click -> ``manage_requested`` -> window -> the presenter's handler."""
        dialog = self._open_manage_dialog()
        self.assertIsNotNone(
            dialog,
            'nothing opened LibraryManagementDialog: manage_libraries_requested is '
            'still a dangling connection (Task 7 review, Important)',
        )
        self.assertEqual([ROCK.path, JAZZ.path],
                         [library.path for library in dialog.opened_libraries],
                         'the dialog opened without the configured libraries')

    def test_manage_row_closes_the_panel(self):
        """The dialog is modal and the panel floats over the list: one must give."""
        self._open_manage_dialog()
        self.assertFalse(
            self.view.is_library_panel_open(),
            'the panel is still floating over the list behind a modal dialog',
        )

    def test_window_forwards_the_footer_to_the_presenter_signal(self):
        """``LibrarySidebar.manage_requested`` re-exports as ``manage_libraries_requested``."""
        emitted = []
        self.view.manage_libraries_requested.connect(lambda: emitted.append(True))
        from PyQt6.QtWidgets import QDialog
        from view.dialogs.library_dialog import LibraryManagementDialog

        with mock.patch.object(LibraryManagementDialog, 'exec',
                               lambda dialog: QDialog.DialogCode.Accepted):
            _footer_row(self.view, i18n.get('sidebar.manage')).click()

        self.assertEqual([True], emitted,
                         'MainWindow no longer forwards the panel footer to the '
                         'signal the presenter listens on')

    def test_remove_from_the_footer_dialog_reaches_config_and_view(self):
        """Delete a library through the dialog the footer opened, end to end."""
        def remove_library(path):
            self.libraries[:] = [lib for lib in self.libraries
                                 if lib.path != path]
            return True

        self.config.remove_library.side_effect = remove_library

        with _spied(self.view, 'show_toast') as calls:
            self._remove_a_library_via_the_panel()

        self.config.remove_library.assert_called_once_with(ROCK.path)
        self.assertEqual([JAZZ.path],
                         [row.path for row in _library_rows(self.view)],
                         'the panel still lists the library that was just removed')
        self.assertEqual(1, len(calls['show_toast']), calls['show_toast'])
        message = calls['show_toast'][0][0]
        self.assertNotIn('{', message,
                         f'status.library_removed still substitutes nothing: {message}')
        self.assertIn('rock', message.lower(), message)
        self.assertNotIn('[MISSING', message)

    def test_add_from_the_footer_reaches_config_and_view(self):
        """footer -> ``add_library_requested`` -> presenter -> ``ConfigService``.

        ``MainWindow.add_library_requested`` was revived by Task 7 with a live
        producer and *no consumer*. A click here has to write the config, start the
        scan and put the new row in the panel the user is still looking at.
        """
        def add_library(path, name=None):
            self.libraries[:] = self.libraries + [
                SimpleNamespace(name=Path(path).name, path=path)]
            return True

        self.config.add_library.side_effect = add_library

        self._click_add_row(NEW_LIBRARY_PATH)

        self.config.add_library.assert_called_once_with(NEW_LIBRARY_PATH)
        self.assertTrue(
            self.library.load_library.called,
            'the new library was configured but never scanned: the panel would '
            'list an empty library',
        )
        self.assertEqual(NEW_LIBRARY_PATH, self.library.load_library.call_args.args[0])
        self.assertEqual([ROCK.path, JAZZ.path, NEW_LIBRARY_PATH],
                         [row.path for row in _library_rows(self.view)],
                         'the new library never reached the floating panel')
        self.assertTrue(
            self.view.is_library_panel_open(),
            'adding a library must keep the panel open -- the row the user asked '
            'for is why it is open (Task 4)',
        )

    def test_a_cancelled_chooser_adds_nothing(self):
        """An empty path would add a library rooted at the current directory."""
        self._click_add_row('')
        self.config.add_library.assert_not_called()
        self.assertEqual(2, len(_library_rows(self.view)))

    def test_dialog_add_and_footer_add_share_one_sink(self):
        """Both add routes write through the same presenter path.

        The dialog stayed reachable for reorder and removal; if its add button and
        the footer diverged, one of the two would silently stop scanning.
        """
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QFileDialog

        from view.dialogs.library_dialog import LibraryManagementDialog

        def add_library(path, name=None):
            self.libraries[:] = self.libraries + [
                SimpleNamespace(name=Path(path).name, path=path)]
            return True

        self.config.add_library.side_effect = add_library

        def fill_then_add(dialog):
            with mock.patch.object(QFileDialog, 'getExistingDirectory',
                                   lambda *args, **kwargs: NEW_LIBRARY_PATH):
                dialog._add_button.click()
            self.assertEqual(
                [ROCK.path, JAZZ.path, NEW_LIBRARY_PATH],
                [dialog._list_widget.item(index).data(Qt.ItemDataRole.UserRole)
                 for index in range(dialog._list_widget.count())],
                'the dialog did not re-list the library its own button added')

        self._open_manage_dialog(fill_then_add)

        self.config.add_library.assert_called_once_with(NEW_LIBRARY_PATH)
        self.assertEqual(3, len(_library_rows(self.view)),
                         'the dialog-side add never reached the window')


if __name__ == '__main__':
    unittest.main(verbosity=2)
