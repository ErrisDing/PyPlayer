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
services are ``MagicMock``\\ s. Three consequences shape the helpers below:

* service *signals* cannot be ``emit``\\ ted on a mock, but ``connect`` on a mock
  records the receiver it was handed -- so :meth:`PresenterHarness._emit` calls
  precisely the slot the presenter registered. Delete a ``connect`` line and the
  event stops arriving, which is the failure this harness exists to catch; calling
  the presenter's slots directly would leave every connection untested.
* the status channels are wrapped, not replaced: :func:`_spied` records each call
  **and runs the real method**, so the toast really paints and the rail really
  spins -- an assertion about a call list cannot pass on a channel that was
  quietly rewired to nowhere.

A third consequence of the mocked services is a fixture rule, and batch 4's controller
finding is what made it explicit: ``refresh_all_libraries`` is a mock, so it fires no
``library_loaded`` at all, and a scanned file list is fed to the presenter by
:meth:`PresenterHarness._walk` rather than by the service. Since Task 7 the scan's other
half -- collect each library's plan, merge it, start one sweep -- runs *through* a
``try/except Exception`` whose handler prints and returns. A file list whose shape is not
``MediaFile``\ 's therefore leaves every one of these tests by that error exit while
staying green; :func:`_media` builds the real DTO for that reason, and
:func:`_captured_stdout` is what lets a test see the exit taken at all.
``MetadataPlanTest`` pins the merged plan and the one-library failure under exactly this
assembly.

The two structural guards read the modules' **AST**, not their lines
(:func:`status_channel_violations`). They have to: four of the nine routed toast
sites are written as ``show_toast(`` + newline + ``i18n.get(...)``, so a line-based
marker scan is satisfied by the very style the file it guards is written in, and a
retired key looked up across the same line break resurrected deleted copy with the
suite green (batch-2 review findings 1 and 2).

The progress guard asks about the **whitelist**, not the vocabulary
(:func:`_progressable_action_ids`): the rail lets only ``PROGRESSABLE_IDS`` -- the
two library scans -- into running state, and it raises ``ValueError`` for anything
else. Because the presenter calls it from a Qt slot, that exception is not a
traceback the user can walk away from: Qt calls ``qFatal`` and the process dies. So
``set_action_progress('appearance', True)`` is not a spinner on the wrong button, it
is a crash-on-touch, and the guard that admitted it (the batch-2 final review's
finding 2) was checking the wrong set -- all seven ids instead of the two allowed
ones. It reads the rail's own declaration, resolves the ``ACTION_*`` symbols the
presenter actually writes as well as string literals, and reports an unresolvable
whitelist instead of trusting an empty one.

Run with an offscreen Qt platform:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_presenter_status -v
"""
import ast
import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Make the project root importable no matter how the test is invoked.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n
from core.library_manager import MediaFile
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

#: The i18n entry points a user-visible string may come from. Anything else that
#: reaches :func:`show_toast` is copy built in code.
I18N_LOOKUP_ATTRS = ('get', 'interface')

#: The violation kinds :func:`status_channel_violations` reports. The two source
#: guards below ask for different subsets of one shared pass, which is why the
#: kind travels with every finding instead of living in two separate scanners.
COPY_CONCERNS = ('hardcoded-copy', 'progress-text', 'status-default')
RETIREMENT_CONCERNS = ('retired-key',)


def _call_name(node: ast.Call) -> str:
    """The method/function name a call node is invoking (``''`` when dynamic)."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ''


def _is_i18n_lookup(node) -> bool:
    """``i18n.get(...)`` / ``i18n.interface(...)`` -- the only legal copy source."""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in I18N_LOOKUP_ATTRS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == 'i18n')


def _string_literals(node) -> list:
    """Every string constant under ``node``, f-string fragments included."""
    return [child.value for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)]


def _lookup_key(node: ast.Call) -> str:
    """The looked-up key as far as it is *literal* text; ``''`` when computed.

    ``f'status.{name}'`` contributes the ``'status.'`` prefix, which is all the
    ``status-default`` rule needs; it can never name a whole retired key, which is
    what the ``retired-key`` rule reads the literals for.
    """
    argument = node.args[0] if node.args else next(
        (kw.value for kw in node.keywords if kw.arg in ('keyword', 'key')), None)
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    if isinstance(argument, ast.JoinedStr):
        return ''.join(value.value for value in argument.values
                       if isinstance(value, ast.Constant)
                       and isinstance(value.value, str))
    return ''


_RAIL_SOURCE = ROOT / 'view' / 'widgets' / 'action_rail.py'


def _rail_declared_names() -> tuple:
    """``(literals, {tuple_name: ids})`` declared at the top of the rail module.

    Read by **parsing**, not importing: this file guards *source*, and importing
    the rail to learn a fact written in plain text would tie the non-Qt half of the
    suite to PyQt6 for nothing. ``literals`` maps a constant name to its string
    value (``ACTION_REFRESH -> 'refresh'``); ``tuples`` resolves the id groups whose
    elements are those names (``PROGRESSABLE_IDS -> ('refresh', 'refresh_all')``).
    ``ACTION_IDS`` and ``PROGRESSABLE_IDS`` are annotated assignments, so both
    ``Assign`` and ``AnnAssign`` are read -- missing the latter is how a guard ends
    up with an empty whitelist it silently ignores.
    """
    tree = ast.parse(_RAIL_SOURCE.read_text(encoding='utf-8'))
    literals, groups = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if len(targets) != 1 or not isinstance(targets[0], ast.Name) or value is None:
            continue
        name = targets[0].id
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            literals[name] = value.value
        elif isinstance(value, (ast.Tuple, ast.List)) and value.elts:
            ids = [literals.get(elts.id) if isinstance(elts, ast.Name) else None
                   for elts in value.elts]
            if all(identifier is not None for identifier in ids):
                groups[name] = tuple(ids)
    return literals, groups


def _progressable_action_ids() -> tuple:
    """The ids ``set_action_progress`` may address -- ``PROGRESSABLE_IDS``, not ``ACTION_IDS``.

    Batch-2 final-review finding 2: this guard asked the wrong question. "Is this a
    rail action?" is *not* the rule -- spec §5's Task 8 ruling is that only the two
    library scans can show progress, and the whitelist lives in the rail itself as
    :data:`view.widgets.action_rail.PROGRESSABLE_IDS`, enforced in
    :meth:`ActionRail.set_progress` by ``raise ValueError``. The presenter reaches
    that method from a Qt slot, so the exception does not surface as a traceback:
    Qt prints it and calls ``qFatal``, and **the process dies**. A guard that
    admitted ``set_action_progress('appearance', True)`` therefore admitted a
    crash-on-touch, which is the one thing a source guard has to be worth.
    """
    return _rail_declared_names()[1].get('PROGRESSABLE_IDS', ())


def _known_action_ids() -> tuple:
    """Every rail id, for the message that distinguishes a typo from a refusal."""
    return _rail_declared_names()[1].get('ACTION_IDS', ())


def _progress_target(node) -> tuple:
    """``(shape, id_value)`` for the first argument of a progress call.

    Three shapes, because the presenter writes the id as a *symbol*
    (``ACTION_REFRESH``) and a guard that only understands string literals checks
    four call sites it cannot see. A name the rail declares is resolved to its
    value, so ``ACTION_APPEARANCE`` fails exactly like ``'appearance'`` would; a
    name it does not (a variable, an attribute of something else, any computed
    expression) is ``'opaque'`` -- which this module has always called a finding
    ("a computed value means a call site the ruling never covered"), the old code
    simply waved ``Name``/``Attribute`` through on the way to enforcing it.
    """
    literals = _rail_declared_names()[0]
    if isinstance(node, ast.Constant):
        return ('literal', node.value if isinstance(node.value, str) else None)
    names = ([node.id] if isinstance(node, ast.Name)
             else [node.attr] if isinstance(node, ast.Attribute) else [])
    for name in names:
        if name in literals:
            return ('rail constant', literals[name])
    return ('opaque', None)


def _show_toast_violations(node: ast.Call, where: str) -> list:
    """Every shape of ``show_toast`` call that builds copy in code."""
    message = node.args[0] if node.args else next(
        (kw.value for kw in node.keywords if kw.arg == 'message'), None)
    if message is None:
        return [('hardcoded-copy', f'{where}: show_toast() carries no message')]
    if _is_i18n_lookup(message):
        # ``show_toast(i18n.get('k'), 'and some more copy')`` -- the second
        # positional slot is the *duration*, so a string here is copy with nowhere
        # to be translated.
        smuggled = [literal for extra in node.args[1:]
                    for literal in _string_literals(extra)]
        if smuggled:
            return [('hardcoded-copy',
                     f'{where}: show_toast() passes copy beside its key lookup: '
                     f'{smuggled}')]
        return []
    return [('hardcoded-copy',
             f'{where}: show_toast() is handed {type(message).__name__}, not an '
             'i18n key lookup -- user-visible copy has to come from a key that '
             'substitutes its parameters')]


def _progress_violations(node: ast.Call, where: str) -> list:
    """``set_action_progress`` is a state channel: ``(progressable id, bool)``.

    spec §5's progress row produces **no text**, so every shape that smuggles some
    in -- a third argument, a keyword, a message where the bool belongs -- is one
    defect: a spinner that also carries a sentence. And ``running`` is reported at
    the start of a ``try`` and cleared in its ``finally``, so a computed value
    rather than a literal means a call site the ruling never covered.

    The id half of that check asks the *whitelist* question, not the *vocabulary*
    question: ``PROGRESSABLE_IDS`` (the two library scans), not ``ACTION_IDS`` (all
    seven). See :func:`_progressable_action_ids` for what the difference costs -- a
    known id with no running state is a ``ValueError`` raised inside a Qt slot, and
    Qt answers that with ``qFatal``, so the defect is a dead process rather than a
    spinner that never spins.
    """
    if len(node.args) != 2 or node.keywords:
        return [('progress-text',
                 f'{where}: set_action_progress() must be called as '
                 f'(action id, True/False) -- got '
                 f'{ast.unparse(node)}[{len(node.args)} positional, '
                 f'{len(node.keywords)} keyword(s)]')]
    action, running = node.args
    failures = []
    progressable = _progressable_action_ids()
    known = _known_action_ids()
    shape, action_id = _progress_target(action)
    if not progressable:
        # An unresolvable whitelist reads as "no restriction", which is the failure
        # mode this whole finding is: a guard that admits everything is a guard that
        # is green. Say so at every call site rather than trust the empty tuple.
        failures.append(
            f'{where}: PROGRESSABLE_IDS could not be read from '
            'view/widgets/action_rail.py -- a whitelist that resolves to nothing '
            'admits every progress call, so the empty read is reported instead of '
            'believed')
    elif shape == 'opaque':
        failures.append(
            f'{where}: the progress channel is addressed by {ast.unparse(action)}, '
            'which is neither one of the rail\'s ACTION_* ids nor a string literal '
            f'-- a computed id is a call site this ruling cannot check, and the rail '
            f'raises on the wrong one (only {", ".join(progressable)} are '
            'progressable)')
    elif action_id is None:
        failures.append(
            f'{where}: the progress id must be a string, got '
            f'{ast.unparse(action)}')
    elif action_id not in progressable:
        verdict = (
            'is not a rail action at all -- a typo'
            if action_id not in known else
            'is a rail action with **no running state**: progress is the library '
            'scan made visible, so a spinner here promises work this button does '
            'not do (spec §5)')
        failures.append(
            f'{where}: set_action_progress({action_id!r}) is refused by the rail -- '
            f'it {verdict}. Only {", ".join(progressable)} may enter progress, and '
            f'{action_id!r} raises ValueError inside the Qt slot that called it, '
            'which Qt turns into qFatal: the process dies. Fix the call site; '
            'widening PROGRESSABLE_IDS is a spec decision, not a test edit')
    if not (isinstance(running, ast.Constant)
            and isinstance(running.value, bool)):
        failures.append(
            f'{where}: the running state must be a bool literal, got '
            f'{ast.dump(running)[:60]} -- progress carries state, spec §5, never text')
    return [('progress-text', text) for text in failures]


def _lookup_violations(node: ast.Call, where: str) -> list:
    """The two invariants of one ``i18n`` lookup in the status channels."""
    failures = []
    key = _lookup_key(node)
    if key.startswith('status.') and any(kw.arg == 'default' for kw in node.keywords):
        failures.append(('status-default',
                         f'{where}: {key} looked up with a hardcoded default -- '
                         'every status key ships in both locales'))
    # Every string the lookup is handed, exactly as the line scan read the whole
    # line: the key, its parameters, and any fallback.
    literals = _string_literals(node)
    for literal in literals:
        for retired in RETIRED_KEYS:
            if retired in literal:
                failures.append(('retired-key',
                                 f'{where}: {retired} is looked up again -- spec §5 '
                                 'deleted this copy (it duplicates the transport '
                                 'button or the strip, or it is progress that is now '
                                 'a button state)'))
    return failures


def status_channel_violations(*paths: Path) -> list:
    """One AST pass per source file over every ``ast.Call`` node it contains.

    Returns ``(kind, message)`` pairs; see ``COPY_CONCERNS`` / ``RETIREMENT_CONCERNS``
    for the kinds. Both structural guards in this module consume this, so the two
    concerns cannot drift apart into two scanners with two blind spots.

    Why it parses instead of scanning lines (batch-2 review findings 1 and 2): four
    of the nine toast sites Task 8 shipped in *this very file* are written as
    ``show_toast(\\n    i18n.get(...))``. A marker that has to share a line with its
    opening parenthesis is therefore satisfied by the dominant style of the file it
    guards -- ``show_toast(\\n    f"Refreshed {n}")`` passed it, and so did a
    ``default=`` on the call's second line. The retired-key scan had the identical
    hole, which is the revival path it exists to close: ``i18n.get(\\n`` plus
    ``    'status.playing')`` resurrected deleted copy with the suite green. The
    four ``set_action_progress`` sites happen to fit on one line today, which is
    precisely the accident a guard must not rest on. Reading ``ast.Call`` nodes
    takes the line boundary out of the question -- a call is a call however it is
    wrapped, and its arguments have shapes.
    """
    violations = []
    for path in paths:
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            # A source the scanner was *handed* by a test of the scanner itself
            # (``PresenterStatusTest._scan`` writes throwaway modules to a temp
            # directory). The guard has to be testable with code the repository does
            # not contain -- otherwise the only way to prove it bites is to commit
            # the bad call, which for the progress channel means committing a crash.
            relative = path
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            where = f'{relative}:{node.lineno}'
            name = _call_name(node)
            if name == 'show_toast':
                violations += _show_toast_violations(node, where)
            elif name == 'set_action_progress':
                violations += _progress_violations(node, where)
            if _is_i18n_lookup(node):
                violations += _lookup_violations(node, where)
    return violations


def _source_guard(paths, concerns) -> list:
    """The violations of one concern set, as ``kind: where`` lines for the message."""
    return sorted(f'{kind}: {text}' for kind, text in
                  status_channel_violations(*paths) if kind in concerns)


def _media(count, prefix='/media/rock'):
    """``count`` scanned files -- the **real** DTO, because a stub of our own shape lied.

    Batch-4 controller finding. This helper used to hand back ``SimpleNamespace``s with
    ``path`` and ``title`` and a docstring claiming "only ``.path``/``.title`` are read".
    Since Task 7 that is false: the scan's collection path also reads ``size_bytes`` and
    ``modified_time`` -- :meth:`MainPresenter._metadata_plan` for the fingerprints and
    ``LibraryMetadataStore.validate`` for the ``(path, size, mtime)`` triples -- and it
    does so inside a ``try`` whose ``except Exception`` answers with a ``print`` and a
    ``return``. Every library of every scan in this file therefore left through that error
    exit: six ``was not collected`` lines on each full run, and -- the part four reviews
    missed -- the behaviour those tests were driving was never executed by any of them.

    So the fixture *is* :class:`core.library_manager.MediaFile` now, and cannot drift from
    the DTO again. The rule for any media stand-in this module builds: its field set has
    to match ``MediaFile``'s (``path``/``title``/``file_type``/``extension``/
    ``size_bytes``/``modified_time``), or the presenter's collection path silently goes
    back through ``except`` and a green suite means nothing.

    No disk dependency comes with it. ``MediaFile.__post_init__`` stats the path and keeps
    the *handed* ``size_bytes``/``modified_time`` when that stat raises (the ``except
    OSError: pass`` half of ``core/library_manager.py``), and ``/media/...`` is not a path
    this host has -- the same controlled fingerprint ``tests/test_metadata_store.py`` and
    ``tests/test_queue_metadata.py`` already rely on for this class.
    """
    return [MediaFile(path=f'{prefix}/track{index}.mp3',
                      title=f'Track {index}',
                      file_type='audio',
                      extension='.mp3',
                      size_bytes=1000 + index,
                      modified_time=100.0 + index)
            for index in range(count)]


@contextlib.contextmanager
def _captured_stdout():
    """Everything printed while the block runs, handed back as a ``StringIO``.

    The metadata guards report a refused library with ``print`` -- on **stdout**, not as
    an exception and not on stderr -- so a test that only counts toasts and rail states
    cannot tell "collected" from "swallowed", which is exactly the blind spot the stub
    above fell into. Yielding the buffer is what lets the assertions below *read* the
    error exit: the positive cases demand it stay empty, the boundary case demands it
    name exactly one library.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield buffer


def _noise(buffer) -> list:
    """The refused-library lines in captured output (one ``print`` is one line)."""
    return [line for line in buffer.getvalue().splitlines()
            if 'was not collected' in line]


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

    def _walk(self, *libraries):
        """Drive 刷新全部 over these ``(library path, files)`` pairs, one signal each.

        The mock answers ``refresh_all_libraries`` with a value, and a value is not a
        walk: the real service fires ``library_loaded`` once per library, and those
        emissions are the only thing that feeds the joint plan. So the side effect emits
        through :meth:`_emit` -- the connection the presenter itself made, never a slot
        called by hand -- and returns the mapping ``_on_refresh_all`` counts into the
        result toast. Without this helper the metadata half of a refresh-all would collect
        nothing and the plan under test would not exist.
        """
        def walk():
            results = {}
            for library_path, files in libraries:
                results[library_path] = files
                self._emit(self.library, 'library_loaded', library_path, files)
            return results

        self.library.refresh_all_libraries.side_effect = walk

    def _record_metadata_pushes(self):
        """A snapshot of every table the scan hands the queue, in call order.

        Taken through the mock's ``side_effect`` rather than read back off
        ``call_args_list``: :meth:`MainPresenter._metadata_collect` pushes **its live
        accumulator**, so a mock records one object that keeps growing and every call
        looks like the final one. Copying at the moment of the call is what makes "each
        push carried the union so far" -- the rule that stops the second library blanking
        the first -- readable at all.
        """
        pushed = []
        self.queue.set_metadata.side_effect = (
            lambda mapping: pushed.append(dict(mapping)))
        return pushed

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

        Both channels are checked, because both can carry copy: a toast whose
        message is not a key lookup, a progress call that grew a third argument or
        a keyword (spec §5: the progress row produces no text), and a ``status.*``
        lookup with a ``default=`` -- a fallback is English sitting in code with a
        key file next to it. See :func:`status_channel_violations` for why this
        reads ``ast.Call`` nodes instead of scanning lines.
        """
        violations = _source_guard(
            (ROOT / 'presenter' / 'main_presenter.py',), COPY_CONCERNS)
        self.assertEqual(
            [], violations,
            'user-visible status copy must come from a key lookup that substitutes '
            'its parameters, and the progress channel must stay (id, bool)',
        )

    def _scan(self, *statements: str) -> list:
        """Run the copy/progress source guard over a throwaway module.

        The only honest way to test a guard whose subject is a crash: the progress
        defect this guards against kills the process from inside a Qt slot, so
        "prove it bites" cannot mean "run it". The statements are written into a
        temp file and read back by the same AST pass the real presenter is scanned
        with, so what is under test is the guard, not a copy of its logic.
        """
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix='status-guard-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / 'synthetic_presenter.py'
        path.write_text(
            'class Presenter:\n    def _run(self):\n'
            + ''.join(f'        {line}\n' for line in statements),
            encoding='utf-8')
        return _source_guard([path], COPY_CONCERNS)

    def test_the_progress_guard_refuses_an_id_the_rail_will_refuse(self):
        """Final-review finding 2, permanently: the whitelist, not the vocabulary.

        Every one of these calls is a ``ValueError`` inside a Qt slot at runtime,
        and Qt's answer to an unhandled exception in a slot is ``qFatal`` -- the
        process ends. The first three are the shapes that used to pass: ``'appearance'``
        because it *is* a rail action, ``ACTION_APPEARANCE`` for the same reason
        written as the symbol the presenter actually uses (the old check only looked
        at string literals, so it saw nothing to check), and a bare variable because
        ``Name`` was waved through on the way to rejecting computed values. The last
        two are the legal calls, kept here so the guard is shown not to be a blanket
        refusal -- a guard that fails everything is deleted, not trusted.
        """
        refused = (
            "self._view.set_action_progress('appearance', True)",
            'self._view.set_action_progress(ACTION_APPEARANCE, True)',
            "self._view.set_action_progress('library', True)",
            "self._view.set_action_progress('nonsense', True)",
            'self._view.set_action_progress(action_id, True)',
            "self._view.set_action_progress('refresh', 'working')",
        )
        for statement in refused:
            with self.subTest(statement=statement):
                self.assertTrue(
                    self._scan(statement),
                    f'{statement} reaches the rail and aborts the process, but the '
                    'source guard let it through')

        allowed = (
            "self._view.set_action_progress('refresh', True)",
            "self._view.set_action_progress('refresh_all', False)",
            'self._view.set_action_progress(ACTION_REFRESH, True)',
            'self._view.set_action_progress(ACTION_REFRESH_ALL, False)',
        )
        for statement in allowed:
            with self.subTest(statement=statement):
                self.assertEqual(
                    [], self._scan(statement),
                    f'{statement} is a legal progress call and the guard has to say '
                    'so, or the next person disables it')

    def test_the_progress_whitelist_is_read_not_assumed(self):
        """The guard's input is the rail's own declaration, and empty is a failure.

        Two halves. First: ``PROGRESSABLE_IDS`` is read from the rail's source and
        must still name exactly the two library scans -- if the rail's whitelist is
        ever re-shaped (a computed tuple, a different name), the resolver stops
        resolving, and that is red here rather than a silently unguarded channel.
        Second: the empty read is *reported* at every call site -- see
        :func:`_progress_violations` -- because a whitelist that resolves to nothing
        admits everything, which is this whole finding wearing a different hat.
        """
        literals, groups = _rail_declared_names()
        self.assertEqual(
            ('refresh', 'refresh_all'), _progressable_action_ids(),
            f'PROGRESSABLE_IDS resolved to {_progressable_action_ids()!r} out of '
            f'{sorted(groups)} -- the guard and the rail now disagree about what may '
            'spin, and the rail is the one that raises')
        self.assertEqual(
            7, len(_known_action_ids()),
            'the rail declares a different number of action ids than spec §6 fixes '
            '(7); the guard separates "typo" from "no running state" using this, so '
            'a broken read degrades every message')
        self.assertEqual(
            {'ACTION_REFRESH': 'refresh', 'ACTION_REFRESH_ALL': 'refresh_all',
             'ACTION_APPEARANCE': 'appearance', 'ACTION_ABOUT': 'about',
             'ACTION_LIBRARY': 'library', 'ACTION_OPEN_FILE': 'open_file',
             'ACTION_OPEN_FOLDER': 'open_folder'},
            {name: value for name, value in literals.items()
             if name.startswith('ACTION_')},
            'the ACTION_* symbols the presenter writes did not resolve to the ids '
            'the rail compares against -- the symbol-shaped call sites are the ones '
            'this guard used to be blind to')

        # And the loud-empty branch, by taking the whitelist away.
        with mock.patch(
                f'{__name__}._progressable_action_ids',
                lambda: ()):
            violations = self._scan(
                "self._view.set_action_progress('refresh', True)")
        self.assertTrue(
            violations,
            'an unresolvable PROGRESSABLE_IDS must fail every progress call site: '
            'a guard whose whitelist reads empty is a guard that admits everything, '
            'and it must not be green while doing that')

    def test_retired_keys_have_no_lookup_left(self):
        """The deleted copy must not be resurrected by another call site.

        Scanned as *lookups* (a call that asks i18n for the key), not as mentions:
        this task's own docstrings name the retired strings to explain why they are
        gone, and silencing that prose would make the guard worse, not stricter.

        The scope is every module the status channels live in -- ``presenter/`` and
        ``view/`` -- and the scan is the same AST pass as the guard above, because
        the revival path this test exists to close is a *call*, and a call that
        wraps onto a second line is still a call: ``i18n.get(\\n    'status.playing')``
        satisfied the old line scan (review finding 2) while doing exactly the thing
        the test forbids.
        """
        paths = (sorted((ROOT / 'presenter').rglob('*.py'))
                 + sorted((ROOT / 'view').rglob('*.py')))
        violations = _source_guard(paths, RETIREMENT_CONCERNS)
        self.assertEqual(
            [], violations,
            'spec §5 deleted this copy -- it duplicates the transport button or the '
            'strip, or it is progress that is now a button state',
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


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class MetadataPlanTest(PresenterHarness, unittest.TestCase):
    """批次 4 补漏：扫描的元数据正路要真的被执行，也要真的被看见。

    Four reviews read ``test_presenter_status.py`` and saw scan tests passing. They were
    not passing on the metadata route -- they were *skipping* it: :func:`_media` handed
    the presenter a stand-in with no ``size_bytes``, the collection path raised
    ``AttributeError`` inside :meth:`MainPresenter._metadata_collect`, its
    ``except Exception`` printed one line to stdout and returned, and every test carried
    on asserting toasts and rail states it could assert either way. The dense pins for
    this route live in ``tests/test_metadata_wiring.py``, with real services and a real
    sweep; what was missing is the **shape under this file's own assembly**, because the
    assembly is where the drift hid. These three cases use nothing but the mocks
    :class:`PresenterHarness` already builds.

    All three read :func:`_captured_stdout`. That is the part that makes the fix
    permanent rather than incidental: "no library was refused" is an observable fact here,
    so a stub that loses a field again fails on the *positive* case instead of quietly
    routing it through the guard.
    """

    def setUp(self):
        super().setUp()
        # Cold libraries, spelled out rather than left to a mock's empty iterator: every
        # row below is pending, so a plan that came back empty is a plan that was not
        # built and not a library that had nothing to ask for.
        self.library.get_cache_entries.return_value = []

    def test_a_scan_starts_one_sweep_that_carries_every_library_of_the_walk(self):
        """Two libraries walked -> one plan, both to-do lists, one owner per row.

        The claim is ruling B4-R21b seen from the presenter's side and without a
        thread in the room: ``start_sweep`` is asked **once** for the whole window (each
        extra call retires the plan before it, which is how k-1 libraries used to be left
        at ``⋯``), the merged targets are exactly the union of what each library listed
        with none of them listed twice for the same library, each row is owned by the
        library that listed it, the per-library flush domain names both libraries, and the
        table pushed to the queue is the union so far rather than the last library alone
        (spec §10 risk 1 seen from the producer's side).
        """
        rock_files = _media(2)
        jazz_files = _media(1, prefix=JAZZ.path)
        self.assertEqual([], self.queue.set_metadata.call_args_list,
                         'the harness started a plan before the walk did')

        self._walk((ROCK.path, rock_files), (JAZZ.path, jazz_files))
        pushed = self._record_metadata_pushes()
        with _captured_stdout() as out:
            self._click('refresh_all')

        self.assertEqual(
            [], _noise(out),
            'the walk left through the guard, not through the plan: nothing below can '
            'tell a merged two-library plan from a window that collected nothing at all')

        self.metadata.start_sweep.assert_called_once()
        targets, callback = self.metadata.start_sweep.call_args.args
        self.assertEqual(
            self.presenter._on_metadata_row, callback,
            'the plan was handed to a callback the presenter does not own, so no answer '
            'could ever be recorded into the stores that asked for it')

        paths = [triple[0] for triple in targets]
        self.assertEqual(
            sorted(media.path for media in rock_files + jazz_files), sorted(paths),
            f'the joint plan did not carry both libraries\' to-do lists: {paths}')
        self.assertEqual(3, len(set(paths)),
                         f'a path was planned twice over: {paths}')
        for _full_path, size, mtime in targets:
            self.assertIsInstance(size, int, 'the plan carried a size that is not an int')
            self.assertIsInstance(
                mtime, float,
                'the plan carried an mtime that is not a float -- start_sweep refuses '
                'the whole list for one such row (ruling B4-R16), so this payload would '
                'have cost both libraries their columns')

        self.assertEqual(
            {**{media.path: (ROCK.path,) for media in rock_files},
             **{media.path: (JAZZ.path,) for media in jazz_files}},
            self.presenter._metadata_owners,
            'a row is not owned by the library that listed it, so an answer would be '
            'recorded into the wrong store and written into the wrong cache file')
        self.assertEqual(
            set(paths), set(self.presenter._metadata_fingerprints),
            'the fingerprints the plan carries are not the rows the plan asks for: a '
            'write-back re-check would compare one row against another file\'s numbers')
        self.assertEqual({ROCK.path, JAZZ.path},
                         set(self.presenter._metadata_since_flush),
                         'the plan\'s flush domain does not name both libraries: one '
                         'library\'s answers could only ever be written by the other '
                         '(ruling B4-R23)')

        self.assertEqual(
            [{media.path for media in rock_files},
             {media.path for media in rock_files + jazz_files}],
            [set(mapping) for mapping in pushed],
            'the queue was not fed the union so far at each push: ``set_metadata`` '
            'replaces the whole table, so a second library pushing only its own paths '
            'blanks the first one\'s rows (spec §10 risk 1)')
        for index, mapping in enumerate(pushed):
            with self.subTest(push=index):
                self.assertEqual(
                    {None}, set(mapping.values()),
                    'a cold library was pushed as if it had already been answered: an '
                    'empty cache means pending, and pending is what the plan below is '
                    'there to clear')
        self.assertIsNone(self.presenter._metadata_join,
                          'the window stayed open after the walk launched its plan')

    def test_a_path_two_libraries_share_is_planned_once_per_library_and_owned_by_both(self):
        """A library inside a library: one row per asking library, one owner list each.

        ``scan_directory`` walks recursively, so two configured libraries really can list
        the same absolute file, and the plan is deliberately **not** deduplicated across
        them: it counts one delivery per target, and the answer lands in every store that
        asked (ruling B4-R21b). The half that must not repeat is the *owners* list -- two
        entries for one library would double-record and double-write that row. Neither
        shape is visible to the tests above, and neither was reachable at all while the
        stub was leaving through the guard.
        """
        rock_files = _media(2)
        shared = rock_files[1]
        jazz_files = [shared] + _media(1, prefix=JAZZ.path)

        self._walk((ROCK.path, rock_files), (JAZZ.path, jazz_files))
        pushed = self._record_metadata_pushes()
        with _captured_stdout() as out:
            self._click('refresh_all')

        self.assertEqual([], _noise(out), 'the overlapping walk never reached the plan')
        self.metadata.start_sweep.assert_called_once()
        targets = self.metadata.start_sweep.call_args.args[0]
        paths = [triple[0] for triple in targets]

        self.assertEqual(
            sorted([media.path for media in rock_files]
                   + [media.path for media in jazz_files]), sorted(paths),
            f'the shared path was dropped from one library\'s half: {paths}')
        self.assertEqual(2, paths.count(shared.path),
                         'a path two libraries ask for is one target per library that '
                         f'asked, not one in total: {paths}')
        self.assertEqual(3, len(set(paths)))

        owners = self.presenter._metadata_owners
        self.assertEqual((ROCK.path, JAZZ.path), owners[shared.path],
                         'the shared row lost one of its two owners, so one library\'s '
                         'cache file can never be answered')
        for full_path, asked in owners.items():
            with self.subTest(path=full_path):
                self.assertEqual(
                    len(set(asked)), len(asked),
                    f'{full_path} is owned twice by the same library: the answer would '
                    'be recorded and flushed twice for one request')
        self.assertEqual(
            [{media.path for media in rock_files},
             {media.path for media in rock_files + jazz_files}],
            [set(mapping) for mapping in pushed],
            'the shared path was either dropped from the table the queue was handed or '
            'counted twice in it: one row of the display is one file, whichever of the '
            'two libraries listed it')

    def test_one_library_that_fails_to_collect_leaves_the_others_planned_and_reported(self):
        """The guard is a boundary, so its boundary has to be observable.

        ``_metadata_collect``'s ``except Exception`` stays wide on purpose (its own
        comment says why: every caller is a Qt slot, and on this host an escape is the
        process, not a traceback). A deliberate guard with no test is a guard nobody can
        tell apart from the bug it hides, so this is the other side of the same window:
        one library's cache read raises, and what has to be true is -- the failure is
        reported *for that library alone*, the library collected before it keeps its
        targets and its owner entry, the launch still happens, the walk is not
        interrupted, and the progress pair and the result toast still close.
        """
        rock_files = _media(2)
        jazz_files = _media(1, prefix=JAZZ.path)

        def cache_entries(library_path):
            if library_path == JAZZ.path:
                raise OSError('the cache document is unreadable')
            return []

        self.library.get_cache_entries.side_effect = cache_entries
        self._walk((ROCK.path, rock_files), (JAZZ.path, jazz_files))
        pushed = self._record_metadata_pushes()

        with _spied(self.view, 'set_action_progress', 'show_toast') as calls, \
                _captured_stdout() as out:
            self._click('refresh_all')

        noise = _noise(out)
        self.assertEqual(1, len(noise), f'a refused library is not a silent one: {noise}')
        self.assertIn(JAZZ.path, noise[0])
        self.assertNotIn(ROCK.path, noise[0],
                         'the report blamed the library that worked: ' + noise[0])
        self.assertIn('unreadable', noise[0],
                      'the cause did not travel with the line: ' + noise[0])

        self.metadata.start_sweep.assert_called_once()
        survived = [triple[0] for triple in self.metadata.start_sweep.call_args.args[0]]
        self.assertEqual([media.path for media in rock_files], survived,
                         'a refused library took the surviving one\'s plan down with it')
        self.assertEqual({media.path: (ROCK.path,) for media in rock_files},
                         self.presenter._metadata_owners,
                         'the refused library left an owner entry behind, or took a '
                         'surviving row\'s with it')
        self.assertEqual([{media.path for media in rock_files}],
                         [set(mapping) for mapping in pushed],
                         'the refused library either pushed a table of its own (rows it '
                         'never planned) or took the surviving library\'s push with it')
        self.assertEqual({ROCK.path}, set(self.presenter._metadata_since_flush),
                         'the refused library entered the plan\'s flush domain, so a '
                         'store it never built would be visited for every closing write')

        self.assertEqual([('refresh_all', True), ('refresh_all', False)],
                         calls['set_action_progress'],
                         'the refused library left its own scan unbalanced')
        self.assertFalse(self.rail.is_running('refresh_all'))
        self.assertIsNone(self.presenter._metadata_join,
                         'a refused library left the collection window open')
        self.assertIn(i18n.get('status.refreshed_files', count=3, libs=2),
                      [args[0] for args in calls['show_toast']],
                      'one library\'s metadata failed, so the whole refresh stopped '
                      'short of its report -- the scan succeeded and has to say so')


class SelfReferentialPatchTest(unittest.TestCase):
    """No test may patch its own module by dotted name.

    ``unittest discover -s tests`` imports these files as top-level modules
    (``test_presenter_status``), while ``python -m unittest tests.test_x``
    imports them as package members (``tests.test_presenter_status``). They are
    two distinct module objects in ``sys.modules``. A patch written as
    ``mock.patch('tests.test_me._thing', ...)`` therefore rebinds an attribute
    on a module the running test's globals do not come from: the patch silently
    does nothing, and the assertion below it passes or fails depending on which
    invocation the author happened to use. That is exactly how
    :meth:`PresenterStatusTest.test_the_progress_whitelist_is_read_not_assumed`
    came to pass alone and fail in the full suite.

    Use ``f'{__name__}._thing'`` or ``mock.patch.object`` instead.
    """

    def test_no_test_patches_its_own_module_by_dotted_name(self):
        offenders = []
        for path in sorted((ROOT / 'tests').glob('test_*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and getattr(node.func, 'attr', '') == 'patch'):
                    continue
                if not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    target = first.value
                elif isinstance(first, ast.JoinedStr):
                    continue
                else:
                    continue
                if target.split('.')[0] == 'tests':
                    offenders.append(f'{path.name}:{node.lineno}: {target}')
        self.assertEqual(
            [], offenders,
            'a mock.patch target rooted at the `tests` package binds a module '
            'object the running test may not share; use f\'{__name__}.attr\' or '
            'mock.patch.object (see this test\'s docstring)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
