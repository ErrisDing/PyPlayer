#!/usr/bin/env python3
"""Render matrix: the theme layer and the batch-2 shell, as pixels.

Batch 1 built this harness for the theme layer (34 semantic tokens in
``core/theme.py``, one generated sheet in ``core/theme_qss.py``, a ``ThemeManager``
that follows the system theme, an SVG icon set). Batch 2 then replaced the shell
that wears it -- menu bar and left column out, 56 px ``ActionRail`` + full-width
playlist + floating ``LibrarySidebar`` + ``NowPlayingStrip`` + ``Toast`` in -- and
every one of those nine tasks was reviewed as code, never as a picture. Batch 1's
equivalent task is the one that found the main window background had never been
painted, a defect no static review had passed, so this file is the gate and not
the paperwork.

The matrix is **12** PNGs:

    light | dark  x  empty | populated | thirty-libraries  x  820x520 | 1100x720

plus opt-in frames, because the states below are not in the closed shell the
matrix loop walks:

* ``--sidebar-open``: three-library panel open, dark, 1100x720. The question this
  frame answers used to be batch 2's double offset -- ``_place_panel`` wrote
  ``x = RAIL_WIDTH`` *inside* ``content_stack``, which already begins right of
  the rail, so 56 px of playlist stayed visible between the two. Task 7 made the
  placement parent-relative (``x = 0``), so the shipped gap is **0** and the
  frame's job is now to prove that in pixels: :func:`measure` prints the gap from
  live rects and says ``FLUSH ON THE RAIL``, and the eye checks the one thing a
  rect cannot -- that the panel's fill starts exactly where the rail's ends.
  Dark is still the theme to look at, but for the opposite reason from the one
  this bullet used to give: the rail is painted ``surface_alt`` (``#2d2d30`` in
  DARK), which is also the alternating tint of every odd playlist row, so a
  leftover stripe there is *the rail's own colour* and no colour boundary marks
  it -- only the panel's left edge does. (In LIGHT the pair is ``#f5f5f5`` rail
  against a ``#ffffff`` even row and an identical ``#f5f5f5`` odd row, so half
  the stripe was invisible by construction either way.)
* ``--toast``: a live toast over the populated list, dark, 820x520 -- the narrow,
  low-contrast corner of checklist item 6. Its copy is ``status.refreshed_files``
  read through ``i18n``, so the frame photographs the real string with real
  numbers instead of a literal typed into a harness.
* ``--interaction``: the three batch-3 list states, **each in both themes**, at
  1100x720 -- six frames, one per theme x state. Tasks 1-7 shipped multi-select,
  hover and the right-click menu as code reviewed as code; these are the frames a
  human uses to decide whether the result is *visible*, which no test here can
  assert (a pixel equal to a token is not a pixel readable by an eye). Both
  themes, on purpose, because the alternating row tint is the ground that is hard
  and it is a different colour per theme -- measured off these very frames:
  ``hover_bg`` sits **0.3 luminance points below** ``surface_alt`` in DARK (a
  rounding-error darkening on an odd row) and 1.96 below it in LIGHT, while the
  same fills against the plain ground are +3.31 and -5.49; ``selection_bg`` is
  +2.42 over the alternating tint in DARK and -2.55 in LIGHT. One theme's
  "obviously visible" therefore says nothing about the other, and the numbers
  beside each frame are the ones an eye is asked to judge.
  * ``hover``: row 7, hovered by ``QTest.mouseMove`` -- the route a user takes,
    and the only one that works (measured: the viewport must carry ``WA_Hover``,
    which is why ``PlaylistView`` sets it). The guard demands
    ``State_MouseOver`` on that row *and on no other*, out of the delegate's own
    recorded option states, plus a before/after pixel delta -- a frame of an
    unhovered row is otherwise indistinguishable from a frame of a hovered one.
    **Offscreen only**: under the real ``windows`` QPA neither
    ``QTest.mouseMove`` nor ``QCursor.setPos`` sets ``underMouse()`` (measured;
    :func:`cursor_lands`), so the window run prints a skip line for these two
    frames rather than writing a PNG of a row nobody hovered.
  * ``multi-selected``: real Ctrl+clicks on rows 2, 3 and 5 -- non-contiguous on
    purpose, because a fill that ran past its own row is invisible when the batch
    is a range. Row 3 is the playing row, so one picture carries batch 3's
    priority chain: the two plain rows (one even, one odd) take ``selection_bg``,
    row 3 keeps ``playing_bg``, and row 4 sits between them untouched.
  * ``context-menu``: a genuine ``QContextMenuEvent`` aimed at the inner list
    viewport -- the route Task 3 measured necessary, because
    ``QTest.mouseClick(..., RightButton)`` delivers two mouse events and **no**
    context-menu event under ``offscreen``. The click lands *inside* the
    three-row batch, so the frame photographs Explorer's "inside the batch keeps
    the batch" branch and the counted copy (``移除 3 项`` / ``Remove 3 items``),
    where a leaked ``{count}`` would show.
    Not a live popup, in either capture mode: ``QMenu.exec()`` enters a nested
    event loop, so the view's ``_popup_menu`` seam is replaced and the menu the
    real handler really built is painted by ``menu.grab()`` **inside** that seam.
    Afterwards is too late, but not for the reason the first draft claimed: the
    handler's ``finally`` only *schedules* ``deleteLater()``, and a re-probe on this
    host showed ``processEvents`` alone leaves the menu alive -- what kills it is the
    explicit ``DeferredDelete`` flush ``pump()`` runs after each interaction (the
    same flush ``pump()`` exists for). So the grab has to happen inside the seam,
    before that pump. The
    ``grab()`` is then composited onto the window frame at the click point.
    Missing from any such composite: the popup's own native frame and shadow,
    Qt's edge-flipping, and pointer response -- so ``--capture window`` photographs
    the real *window* honestly and the *menu* still as a ``grab()``.

``thirty-libraries`` frames are rendered with the panel **open**: the floating
panel is the only surface in the shipped UI where a library count is visible at
all, so a closed-panel "30 libraries" frame would be pixel-identical to
``populated`` and the third column of the matrix would be decoration. The panel
opens after the window is laid out at the frame's size, not while the data loads
-- :func:`render_frame` explains why that order matters.

Nothing here judges. A stylesheet that parses is not a stylesheet that looks
right, and this script exists so a human eye is the gate -- with numbers beside
it, because three of batch 2's checklist items ("the list is window width minus
56", "the strip's lines do not clip out of their control", "the toast does not
cover the playing row") are geometry claims an eye cannot settle. The per-frame
measurement block and the colour census print next to each file, and ``--crops``
writes 2x crops of the rail, the panel, the strip, the toast, the bottom bar and
(the interaction frames) the affected rows and the composited menu, which is how
the icon-weight and text-legibility claims get *looked at* rather than assumed.

What the interaction frames do add is **guards, not judgements**: each one
insists that the state it is about to photograph is actually live (the cursor
landed, the selection reads back as the three rows clicked, the menu was really
built by the real handler) and stops the run with ``SystemExit`` otherwise. The
reason is the batch-1 shape this harness exists to catch: a frame of an unhovered
row looks exactly like a frame of a hovered one, and a silent fallback would let
a human certify a state that was never on screen. Nothing here decides whether a
contrast is *readable* -- that stays the eye's job.

Run it:

    QT_QPA_PLATFORM=offscreen python tests/tools/render_matrix.py --out /tmp/pyplayer-b2
    python tests/tools/render_matrix.py --out /tmp/pyplayer-b2-win --capture window
    python tests/tools/render_matrix.py --out /tmp/b3 --sidebar-open --toast --interaction --crops
    python tests/tools/render_matrix.py                        # temp dir, path printed

Two capture primitives, and the difference between them is why both exist:

* ``--capture grab`` (the default) calls ``QWidget.grab()``: it repaints the
  widget into an offscreen pixmap. **It composites every transparent region to
  white**, which is exactly how batch 1 Task 10 hid -- and then found -- the
  never-painted window background.
* ``--capture window`` shows the real window and asks the ``QScreen`` for the
  pixels on the desktop (``QScreen.grabWindow``), which composite against the
  real background. It needs a live platform, so run it with
  ``QT_QPA_PLATFORM=windows`` (or leave it unset), never offscreen. It is also
  the only capture that renders CJK: offscreen has no fontconfig-backed CJK
  fallback and draws hollow boxes, so the "correct Chinese" half of checklist
  items 4, 5 and 6 is a ``--capture window`` judgement and cannot be made from an
  offscreen frame at all.

What neither capture can show, and no reading of the PNGs makes verified:

* **A spontaneous pointer, and hover on a real desktop.** Measured on this host,
  Qt 6.11: under ``offscreen`` a ``QTest.mouseMove`` *does* drive both the
  delegate's row hover and the QSS ``:hover`` family (a ``#railButton`` grab goes
  from transparent to ``button_hover`` ``#f0f0f0``, and ``setFocus`` paints the
  focus ring) -- which is why the ``hover`` frame is buildable at all, and why
  this bullet used to read "cannot be photographed". Under the real ``windows``
  QPA the same call leaves ``underMouse()`` False, and so does ``QCursor.setPos``
  even though it visibly moves the pointer, because Qt takes that attribute from
  the window system's enter events rather than from synthetic ones. So the hover
  frame is an offscreen product, the ``--capture window`` run says so and skips
  it, and whether a real mouse's hover *reads* on a real panel at real gamma --
  and whether the tint clears when the pointer leaves -- is a human judgement.
* **HiDPI offscreen.** ``offscreen`` reports device pixel ratio 1, so the
  ``icon(..., dpr)`` 2x path only runs under ``--capture window`` on a scaled
  display.
* **A live popup.** See ``--interaction`` above: the menu half of that frame is a
  ``QMenu.grab()`` composited over the window in *both* capture modes, so nothing
  about the popup's native frame, its shadow, its edge-flipping or its pointer
  response is photographed here.
* **macOS chrome.** Whether Qt still synthesises an application menu once the
  ``QMenuBar`` is empty cannot be answered from a Windows host; see the batch
  report's "could not verify" section.

The matrix deliberately reuses :func:`tests.test_view_smoke.make_app`, so the
harness and the smoke test construct the application the same way and cannot
drift into "the test passes but the tool renders something else".
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List

# Headless before PyQt is imported: the QPA plugin is chosen when the first
# ``QApplication`` is constructed, so this has to run ahead of the imports below.
# ``setdefault``, not assignment -- ``--capture window`` is precisely the run that
# must NOT force offscreen, and an exported ``QT_QPA_PLATFORM=windows`` has to
# survive to reach Qt.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

THEMES = ('light', 'dark')
STATES = ('empty', 'populated', 'thirty-libraries')
SIZES = ((820, 520), (1100, 720))

#: The contract :func:`main` checks: 2 themes x 3 states x 2 sizes.
FRAME_COUNT = len(THEMES) * len(STATES) * len(SIZES)

# The one dedicated overlay frame per flag, chosen so the frame isolates the one
# thing it exists to photograph (see the module docstring). ``--sidebar-open``
# uses the three-library ``populated`` data with the panel opened by hand;
# ``--toast`` keeps the panel closed so the toast cannot hide the panel rows.
OPEN_FRAME = ('dark', 1100, 720)
TOAST_FRAME = ('dark', 820, 520)

#: The batch-3 states ``--interaction`` photographs, each in **both** themes: the
#: fills are pale against different grounds per theme, so one theme cannot settle
#: "is hover visible" for the other (see the module docstring).
INTERACTION_STATES = ('hover', 'multi-selected', 'context-menu')
INTERACTION_SIZE = (1100, 720)

#: The hovered row: odd (so the alternating tint is the ground under it), a plain
#: track row -- neither playing nor a folder, and inside the 720px frame the
#: fixture fits without scrolling. That combination is the worst case for "is the
#: hover fill visible at all", which is the only question this frame answers.
HOVER_ROW = 7

#: The Ctrl+clicked batch for the multi-select and menu frames. Row 3 is
#: ``PLAYING_INDEX``, so the three rows also carry batch 3's priority chain: the
#: two plain rows take ``selection_bg`` while the playing row keeps
#: ``playing_bg``, which a frame of three identical rows could not show. They are
#: deliberately **not** a contiguous range and deliberately one even row, the
#: playing row and one odd row: the odd row is the case a screenshot has to settle
#: (in DARK ``selection_bg`` ``#2f343a`` sits only ~2.4 luminance points over the
#: alternating tint ``#2d2d30``), and a row *between* two selected rows is where a
#: fill that ran past its own row would first be visible.
BATCH_ROWS = (2, 3, 5)

#: The right-click target of the menu frame: *inside* ``BATCH_ROWS``, i.e. the
#: spec §4.3 branch that keeps the batch -- and the only one whose menu copy is
#: parameterised ("Remove 3 items"), so a leaked ``{count}`` shows up here.
MENU_ROW = 3

# Sampled columns of a row, as offsets from its top/left/right edges: ``+3`` is
# one row-top pixel down (above the text band, off the bottom divider), ``12``
# clears the ``SPACE_2`` gutter and the 3px ``playing_bar`` on the left and the
# ``[relative_position]`` read-out on the right. Same geometry as the hover
# tests' band, so a pixel claim here reads the way a pixel claim there does: a hit
# is background, never ink.
BAND_TOP_OFFSET = 3
BAND_INSET = 12

# Three libraries -- the ordinary case. Short names, so this half of the panel is
# compared across sizes on geometry rather than on where its rows happened to
# elide.
LIBRARIES = (
    ('D:/fake/music', 'Music'),
    ('D:/fake/podcasts', 'Podcasts'),
    ('D:/fake/flac', 'FLAC'),
)

# --- the thirty-library fixture (spec §1 criterion 2's own number) ------------
# The 80-character name is the elision torture case: ``SIDEBAR_WIDTH`` 240 minus
# the row's gutters fits roughly 30 Latin characters, so it *must* elide, and the
# tail is where "elided" and "clipped" stop being the same picture.
LIB_NAME_80 = ('Night at the Rainbow, Birmingham - Extended Remastered Live '
               'Recording (1984) CD1')

# CJK + Latin in one name: the Latin half is what makes a clipped or tofu render
# obvious next to a correctly elided CJK tail. These two are readable only in the
# ``--capture window`` run -- offscreen draws the CJK as boxes.
LIB_NAME_MIXED = '古典与爵士 Classical Jazz 精选 2001'
LIB_NAME_CJK_HEAVY = '东京现场 Blue Note Tokyo 爵士四重奏录音全集 Vol.2'

# One name that *almost* fits. The row where elision begins is the row where a
# clip would first be mistaken for correct behaviour, so the fixture needs the
# borderline case and not only the two obvious ones.
LIB_NAME_MEDIUM = 'Chinese Pop 中文流行 2019-2024'

_GENRES = ('Rock', 'Electronic', 'Jazz', 'Classical', 'Podcasts', 'Audiobooks',
           'Soundtracks', 'Live Recordings', 'Vinyl Rips', 'Field Recording')

# Playback state for every populated half of the matrix. Index 3 is the playing
# row (below a folder row, so the playing bar has to survive next to a bold
# folder label), and 125.5/355.0 puts the progress handle at 35% -- far enough
# from both ends to compare the groove, the sub-page and the handle.
PLAYING_INDEX = 3
POSITION = 125.5
DURATION = 355.0
VOLUME = 0.6
LOOP_MODE = 'ALL'


def build_thirty_libraries() -> List:
    """Thirty ``LibraryConfig`` rows: the stress names plus deterministic filler.

    The count is checked rather than trusted: a fixture that quietly became 29 or
    31 libraries stops being the number spec §1 names, and the panel's scroll
    geometry depends on it overflowing.

    The short filler names are the other half of the point. An all-long fixture
    elides every row and therefore cannot show whether elision is *working* or
    merely always firing: the row that fits with room to spare is the control
    case, and ``LIB_NAME_MEDIUM`` sits on the boundary.
    """
    if len(LIB_NAME_80) != 80:
        raise SystemExit(f'LIB_NAME_80 is {len(LIB_NAME_80)} characters; the '
                         'fixture promises exactly 80')
    names = [LIB_NAME_80, LIB_NAME_MIXED, LIB_NAME_CJK_HEAVY, LIB_NAME_MEDIUM]
    names += [f'{_GENRES[i % len(_GENRES)]} {i:02d}' for i in range(4, 30)]
    if len(names) != 30:
        raise SystemExit(f'thirty-library fixture built {len(names)} names')
    return [make_library(f'D:/fake/lib/{index:02d}', name)
            for index, name in enumerate(names)]


def make_library(path: str, name: str):
    from core.config import LibraryConfig

    return LibraryConfig(path=path, name=name)


def build_entries() -> List:
    """Sixteen ``DisplayEntry`` rows: three folders plus thirteen tracks.

    Mirrors ``QueueService``'s real shape (a folder row, then its tracks indented
    by four spaces, each carrying a relative position), because the delegate
    paints ``[relative_position]`` on the right and elides the name on the left --
    two behaviours only a folder tree exercises. A couple of names are
    deliberately long so the 820px frames show the ellipsis instead of a collision
    with the position text.
    """
    from view.models import DisplayEntry

    rows = []

    def folder(node_idx: int, text: str, path: str) -> None:
        rows.append(DisplayEntry(
            display_text=text, node_idx=node_idx, is_folder=True, path=path,
        ))

    def track(node_idx: int, sub_idx: int, title: str, full_path: str,
              relative: str, folder_path: str) -> None:
        rows.append(DisplayEntry(
            display_text=f'    {title}', node_idx=node_idx, is_folder=False,
            path=folder_path, sub_index=sub_idx, full_path=full_path,
            relative_position=relative,
        ))

    folder(0, 'Rock', 'D:/fake/music/Rock')
    track(0, 0, 'Highway Star', 'D:/fake/music/Rock/01.flac',
          'Rock', 'D:/fake/music/Rock')
    track(0, 1, 'Smoke on the Water', 'D:/fake/music/Rock/02.flac',
          'Rock', 'D:/fake/music/Rock')
    track(0, 2, 'Lazy - Extended Remastered Live Recording at the '
                'Rainbow, Birmingham',
          'D:/fake/music/Rock/03.flac', 'Rock/Live', 'D:/fake/music/Rock')

    folder(1, 'Electronic', 'D:/fake/music/Electronic')
    track(1, 0, 'Aerodynamic', 'D:/fake/music/Electronic/01.mp3',
          'Electronic', 'D:/fake/music/Electronic')
    track(1, 1, 'Midnight City', 'D:/fake/music/Electronic/02.mp3',
          'Electronic/EPs', 'D:/fake/music/Electronic')
    track(1, 2, 'Teardrive (2016 Remaster)', 'D:/fake/music/Electronic/03.mp3',
          'Electronic/EPs', 'D:/fake/music/Electronic')
    track(1, 3, 'Tel Aviv - Original Long Mix', 'D:/fake/music/Electronic/04.mp3',
          'Electronic/Singles', 'D:/fake/music/Electronic')

    folder(2, 'Jazz', 'D:/fake/music/Jazz')
    track(2, 0, 'So What', 'D:/fake/music/Jazz/01.flac', 'Jazz',
          'D:/fake/music/Jazz')
    track(2, 1, 'Giant Steps', 'D:/fake/music/Jazz/02.flac', 'Jazz',
          'D:/fake/music/Jazz')
    track(2, 2, 'Naima', 'D:/fake/music/Jazz/03.flac', 'Jazz/Ballads',
          'D:/fake/music/Jazz')
    track(2, 3, 'Blue in Green', 'D:/fake/music/Jazz/04.flac',
          'Jazz/Ballads', 'D:/fake/music/Jazz')
    track(2, 4, 'Freight Train', 'D:/fake/music/Jazz/05.flac',
          'Jazz/Singles', 'D:/fake/music/Jazz')
    track(2, 5, 'My Funny Valentine', 'D:/fake/music/Jazz/06.flac',
          'Jazz/Singles', 'D:/fake/music/Jazz')
    track(2, 6, 'All Blues - Take 2', 'D:/fake/music/Jazz/07.flac',
          'Jazz/Takes', 'D:/fake/music/Jazz')

    # One short title flush against the library root, i.e. a non-indented row in
    # a tree that is otherwise all indentation.
    rows.insert(1, DisplayEntry(
        display_text='Ouverture', node_idx=3, is_folder=False,
        path='D:/fake/music/Ouverture.mp3', sub_index=0,
        full_path='D:/fake/music/Ouverture.mp3', relative_position='root',
    ))
    return rows


def pump(app, settle: float = 0.0) -> None:
    """Run the loop until the frame is settled *and* fully reaped.

    ``QCoreApplication.processEvents`` alone does NOT honour ``deleteLater``:
    deferred deletes are only sent when control returns to a running event
    loop, and ``LibrarySidebar._rebuild_rows`` retires the old rows with exactly
    that. A harness that swaps libraries between frames therefore keeps painting
    the previous set on top of the new one -- six chips in a three-library
    matrix, measured before Task 7 -- and every such frame is a lie. Flushing
    ``DeferredDelete`` explicitly is what the running app does for free.

    ``settle`` exists for the real-QPA run: a native window is composited by the
    desktop, so between two ``processEvents`` batches the pixels may still be the
    previous frame's. ``QWidget.grab()`` needs no such pause.
    """
    from PyQt6.QtCore import QEvent, QCoreApplication

    for _ in range(3):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if settle:
            time.sleep(settle)
    app.processEvents()


def empty(window) -> None:
    """The first-launch state: no libraries, no entries, no track."""
    window.set_libraries([])
    window.clear_playlist()
    window.clear_now_playing()
    window.reset_progress()
    window.set_playing_state(False)
    window.set_volume(VOLUME)
    window.set_loop_mode(LOOP_MODE)


def fill(window, libraries) -> None:
    """Drive a ``MainWindow`` into a populated half of the matrix.

    Goes through the public View API only -- the same calls the presenter makes
    -- so a harness that quietly bypassed a signal path could not hide a
    regression.
    """
    window.set_libraries(list(libraries))
    window.set_current_library(libraries[0].path)
    window.set_playlist_entries(build_entries())
    window.highlight_current_track(PLAYING_INDEX)
    window.update_track_info('Naima', 'Bill Evans', 'Kind of Blue')
    # No art bytes: the strip must fall back to ``resource/default_cover.png``,
    # which is exactly what checklist item 5 asks to see -- and never the English
    # ``now_playing.no_art`` string, which is only the last resort when that file
    # is missing from the install.
    window.update_album_art(None)
    window.set_playing_state(True)
    window.update_progress(POSITION, DURATION)
    window.set_volume(VOLUME)
    window.set_loop_mode(LOOP_MODE)


def apply_state(window, state: str) -> None:
    """Load one named matrix state (see :data:`STATES`) into the window.

    Overlays are put back to their closed baseline first, and *positively*: the
    panel is closed with ``hide_panel()`` and the toast with ``dismiss()``, never
    with the window's flag-driven ``toggle_library_panel()``. That matters because
    the matrix reuses one window for all twelve frames, and Qt restores a child's
    visibility when a hidden top-level is shown again -- so a frame that showed
    with the panel open leaves ``hideEvent`` having cleared ``_is_open`` while the
    widget itself is back on screen. A toggle starting from that state *opens* the
    panel, and every following frame photographs a floating panel its own state
    says is closed. Measured, and worth recording as a fact about the widget (see
    the batch report): the panel survives a hide/show round trip visually while
    ``is_panel_open()`` says it did not. The two overlay widgets' own idempotent
    hide methods are the honest route, and both are public.

    Opening an overlay is deliberately *not* this function's business: a floating
    widget positions itself against its parent, so the caller has to open it
    between :func:`present` and :func:`capture` -- once the parent is laid out at
    the frame's size -- or the frame photographs a snapshot of the previous size.
    """
    from view.widgets import LibrarySidebar, Toast

    window.findChild(LibrarySidebar).hide_panel()
    window.findChild(Toast).dismiss()

    if state == 'empty':
        empty(window)
        return
    fill(window, [make_library(path, name) for path, name in LIBRARIES]
         if state == 'populated' else build_thirty_libraries())


def build_app():
    """The ``QApplication``, configured exactly like ``main_qt``.

    ``Fusion`` and the 11pt base font are set before the theme manager pushes its
    palette and sheet, because both are read at polish time; leaving the style out
    would render a matrix that no real run can reproduce. ``make_app`` is reused
    from the smoke test on purpose -- see the module docstring.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from tests.test_view_smoke import make_app

    app = make_app()
    if not hasattr(app, '_render_matrix_configured'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app.setStyle('Fusion')
        font = app.font()
        font.setPointSize(11)
        app.setFont(font)
        app._render_matrix_configured = True
    return app


# === measurement =============================================================

def window_of(widget):
    """The top-level ``widget`` paints into -- the frame the pixmap shows."""
    return widget.window()


def rect_in_window(widget, top=None) -> tuple:
    """``widget``'s geometry in its top-level's coordinates: ``(x, y, w, h)``."""
    from PyQt6.QtCore import QPoint

    top = top if top is not None else window_of(widget)
    origin = widget.mapTo(top, QPoint(0, 0))
    return (origin.x(), origin.y(), widget.width(), widget.height())


def inside(outer: tuple, inner: tuple) -> bool:
    """Whether ``inner`` lies wholly within ``outer`` (both window-coordinate rects)."""
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh


def overlap(a: tuple, b: tuple) -> tuple:
    """Width and height of the intersection of two window-coordinate rects.

    Empty is ``(0, 0)``, not "one axis is zero": two rows that touch along an edge
    share a border pixel and no area, and reporting that as an overlap would make
    the rail's seven stacked buttons -- 40 px tall on a 44 px pitch -- read as
    twenty-one collisions instead of none.
    """
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    if w <= 0 or h <= 0:
        return (0, 0)
    return (w, h)


def parts(window) -> dict:
    """The named surfaces of the shell, by type so the Python class survives.

    ``findChild`` with the concrete widget class rather than ``QWidget`` because
    PyQt hands back a wrapper of the requested type: asked for a ``QWidget`` it
    gives one, and the accessors that make the measurements possible
    (``ActionRail.button_for``, ``LibraryRow.path``, ``LibraryRow.full_name``) are
    subclass methods that would be gone.
    """
    from PyQt6.QtWidgets import QLabel, QListView, QWidget
    from view.widgets import ActionRail, LibrarySidebar, PlaylistView, Toast

    rail = window.findChild(ActionRail)
    panel = window.findChild(LibrarySidebar)
    toast = window.findChild(Toast)
    view = window.findChild(QListView, 'playlistView')
    playlist = window.findChild(PlaylistView)
    container = window.findChild(QWidget, 'playlistContainer')
    bottom = window.findChild(QWidget, 'bottomPanel')
    strip = window.findChild(QWidget, 'nowPlayingStrip')
    for name, widget in (('actionRail', rail), ('librarySidebar', panel),
                         ('toast', toast), ('playlistView', view),
                         ('PlaylistView', playlist),
                         ('playlistContainer', container), ('bottomPanel', bottom),
                         ('nowPlayingStrip', strip)):
        if widget is None:
            raise SystemExit(f'#{name} is not in the MainWindow tree; the shell '
                             'this harness photographs has changed shape')
    return {
        'rail': rail, 'panel': panel, 'toast': toast, 'view': view,
        'playlist': playlist,
        'container': container, 'bottom': bottom, 'strip': strip,
        'header': window.findChild(QLabel, 'playlistHeader'),
    }


def measure(window) -> List[str]:
    """One line per claim the render checklist makes about geometry.

    Item 1 (list = window - 56), item 2 (rail glyph boxes), item 3 (the panel's
    ``x``), item 4 (panel scroll / elision / footer), item 5 (the strip's two
    lines) and item 6 (the toast) are all measured here rather than eyeballed,
    because "the list looks full width" is not evidence that it is *window width
    minus 56*, and an eye cannot tell a 56 px stripe of playlist between rail and
    panel from a panel that sits flush on the rail.
    """
    from core.theme import RAIL_WIDTH, ROW_HEIGHT, SIDEBAR_WIDTH
    from PyQt6.QtWidgets import QAbstractScrollArea, QLabel
    from view.widgets.action_rail import ACTION_IDS
    from view.widgets.library_sidebar import LibraryRow

    shell = parts(window)
    rail, panel, view = shell['rail'], shell['panel'], shell['view']
    toast, bottom = shell['toast'], shell['bottom']
    top = window_of(window)
    lines = []

    # -- item 1: the rail column and the full-width list ----------------------
    rail_rect, view_rect = rect_in_window(rail, top), rect_in_window(view, top)
    header_rect = rect_in_window(shell['header'], top)
    expected = window.width() - RAIL_WIDTH
    lines.append(
        f'rail x={rail_rect[0]} w={rail_rect[2]} (RAIL_WIDTH={RAIL_WIDTH})')
    lines.append(
        f'list x={view_rect[0]} y={view_rect[1]} w={view_rect[2]} h={view_rect[3]} '
        f'window-56={expected} '
        f'{"OK" if view_rect[2] == expected and view_rect[0] == rail_rect[2] else "MISMATCH"}')
    lines.append(
        f'header x={header_rect[0]} w={header_rect[2]} '
        f'{"OK" if header_rect[2] == expected else "MISMATCH"}')

    # -- item 2: seven glyph boxes, one per rail action -----------------------
    rects = [rect_in_window(rail.button_for(action_id), top)
             for action_id in ACTION_IDS]
    centres = sorted({x + w // 2 for x, _y, w, _h in rects})
    sizes = sorted({(w, h) for _x, _y, w, h in rects})
    touching = [
        f'{ACTION_IDS[i]}/{ACTION_IDS[i + offset]}'
        for i, row in enumerate(rects)
        for offset, other in enumerate(rects[i + 1:], 1)
        if overlap(row, other) != (0, 0)
    ]
    tops = sorted(y for _x, y, _w, _h in rects)
    pitches = [tops[i + 1] - tops[i] for i in range(len(tops) - 1)]
    lines.append(
        f'rail buttons n={len(rects)} sizes={sizes} centres={centres} '
        f'y-pitch={pitches} overlaps={touching or "none"}')

    # -- item 5: the strip's two lines must fit their own controls ------------
    for name in ('stripTitle', 'stripArtist'):
        label = shell['strip'].findChild(QLabel, name)
        shown, full = label.text(), label.toolTip()
        need = label.fontMetrics().horizontalAdvance(shown)
        lines.append(
            f'{name} x={label.x()} w={label.width()} shown_w={need} '
            f'elided={shown != full} '
            f'{"FITS" if need <= label.width() else "CLIPS OUT OF ITS CONTROL"} '
            f'shown={shown!r} full={full!r}')
    art = shell['strip'].findChild(QLabel, 'stripArt')
    lines.append(
        f'stripArt w={art.width()} h={art.height()} '
        f'pixmap={"yes" if (art.pixmap() and not art.pixmap().isNull()) else "NO -> text placeholder"} '
        f'text={art.text()!r}')

    # -- items 3 + 4: the floating panel, whenever it is showing --------------
    if panel.isVisible():
        prect = rect_in_window(panel, top)
        gap = prect[0] - (rail_rect[0] + rail_rect[2])
        lines.append(
            f'panel x={prect[0]} y={prect[1]} w={prect[2]} h={prect[3]} '
            f'(SIDEBAR_WIDTH={SIDEBAR_WIDTH}) rail_right_edge='
            f'{rail_rect[0] + rail_rect[2]} gap={gap} '
            f'{"FLUSH ON THE RAIL" if gap == 0 else f"{gap}px of LIST SHOWS BETWEEN RAIL AND PANEL"}')
        container_rect = rect_in_window(shell['container'], top)
        lines.append(
            f'panel inside content_stack='
            f'{"yes" if inside(container_rect, prect) else "NO"} '
            f'(container rect={container_rect}) '
            f'right_edge={prect[0] + prect[2]} window_w={window.width()} '
            f'{"OVERFLOWS WINDOW" if prect[0] + prect[2] > window.width() else "inside window"}')

        scroll = panel.findChild(QAbstractScrollArea)
        viewport_w = scroll.viewport().width()
        # ``widget().width()``, not ``sizeHint().width()``: the area is in
        # ``setWidgetResizable(True)`` mode, so the content is stretched to the
        # viewport and its size hint is what the layout *wanted* -- 240 for an
        # empty list inside a 198 px viewport -- which would be reported as an
        # overflow that cannot be scrolled to and does not exist on screen.
        content_w = scroll.widget().width()
        bar = scroll.verticalScrollBar()
        lines.append(
            f'panel scroll hbar={scroll.horizontalScrollBarPolicy().name} '
            f'vbar={bar.isVisible()} range={bar.minimum()}..{bar.maximum()} '
            f'content_w={content_w} viewport_w={viewport_w} '
            f'{"NO H-OVERFLOW" if content_w <= viewport_w else "H-OVERFLOW -> horizontal scrolling is the defect"}')
        if bar.maximum() <= 0:
            lines.append('panel does NOT scroll: every row is on screen or clipped')

        rows = panel.findChildren(LibraryRow)
        library_rows = [row for row in rows if row.path is not None]
        elided = [row.full_name for row in library_rows if row.text() != row.full_name]
        over = [
            (row.full_name, row.text(), row.width()) for row in library_rows
            if row.fontMetrics().horizontalAdvance(row.text()) > row.width()
        ]
        lines.append(
            f'panel rows total={len(rows)} libraries={len(library_rows)} '
            f'elided={len(elided)}/{len(library_rows)} text_wider_than_control={over or "none"}')
        for row in (library_rows[:1] + library_rows[-1:]):
            lines.append(
                f'  row w={row.width()} text_w='
                f'{row.fontMetrics().horizontalAdvance(row.text())} '
                f'chars={len(row.full_name)} text={row.text()!r} '
                f'tooltip_is_full={"yes" if row.toolTip() == row.full_name else "NO"}')
        footer = [row for row in rows if row.path is None]
        for row in footer:
            rrect = rect_in_window(row, top)
            text_w = row.fontMetrics().horizontalAdvance(row.text())
            lines.append(
                f'  footer {row.full_name!r} rect={rrect} h={row.height()} '
                f'(ROW_HEIGHT={ROW_HEIGHT}) text_w={text_w} '
                f'inside_panel={"yes" if inside(prect, rrect) else "NO"} '
                f'visible={"yes" if row.isVisible() else "NO"} '
                f'{"TEXT FITS" if text_w <= row.width() else "FOOTER TEXT DOES NOT FIT"}')

    # -- item 6: the toast ----------------------------------------------------
    if toast.isVisible():
        trect = rect_in_window(toast, top)
        brect = rect_in_window(bottom, top)
        label = toast.findChild(QLabel, 'toastText')
        lines.append(
            f'toast rect={trect} label_w={label.width()} '
            f'text={label.text()!r} '
            f'text_w={label.fontMetrics().horizontalAdvance(label.text())} '
            f'wrapped={label.height() > label.fontMetrics().height()}')
        lines.append(
            f'toast bottom={trect[1] + trect[3]} bottomPanel top={brect[1]} '
            f'{"ABOVE THE BAR" if trect[1] + trect[3] <= brect[1] else "OVERLAPS THE CONTROL BAR"}')
        model = view.model()
        if model is not None and model.rowCount() > PLAYING_INDEX:
            visual = view.visualRect(model.index(PLAYING_INDEX))
            origin = view.viewport().mapTo(top, visual.topLeft())
            playing = (origin.x(), origin.y(), visual.width(), visual.height())
            hit = overlap(trect, playing)
            lines.append(
                f'playing row rect={playing} toast_overlap={hit} '
                f'{"ROW IS CLEAR" if hit == (0, 0) else "TOAST COVERS THE PLAYING ROW"}')
        else:
            lines.append('playing row: no row at the playing index to collide with')

    return lines


def colour_census(pixmap, limit: int = 10) -> List[str]:
    """The ``limit`` most-covered colours of a frame, with coverage percentages.

    Item 8 ("no leftover white surfaces in dark, no black voids in light") is a
    coverage claim, so it is measured as coverage: a surface the theme never emits
    appears here with a percentage next to it, while glyph text of the same colour
    is a fraction of a percent and falls out of the list. Compare against
    ``core.theme.LIGHT`` / ``DARK`` -- anything in the answer that is not a token
    of the frame's own theme is a surface worth going and looking at.

    Sampled on a grid rather than every pixel: a 1100x720 frame is 792k pixels,
    and the census only has to be fine enough that a real surface clears the
    threshold. ``step`` keeps the sample near a quarter-million points.
    """
    from PyQt6.QtGui import QImage

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    width, height = image.width(), image.height()
    step = max(1, int((width * height / 250_000) ** 0.5))
    counts: dict = {}
    total = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            color = image.pixelColor(x, y)
            key = (color.red(), color.green(), color.blue())
            counts[key] = counts.get(key, 0) + 1
            total += 1
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [f'#{r:02x}{g:02x}{b:02x} {100.0 * n / total:.2f}%'
            for (r, g, b), n in top]


def write_crops(pixmap, window, path: Path, zoom: int = 2, extra: dict = None) -> List[Path]:
    """2x crops of the four surfaces whose defects are too small to see full-frame.

    Icon *weight* (item 2) cannot be judged at 1x inside a 1100 px frame: a 20 px
    glyph is a smudge, and "the rail icons match the transport glyphs" then turns
    into a guess. Same for the panel footer's two entries and the strip's 12 px
    artist line. Each crop is taken from the captured pixmap -- the pixels that
    were actually painted -- not from a fresh ``grab()``, so a ``--capture window``
    crop still shows the real composite.

    ``extra`` adds window-coordinate rects under their own names; the interaction
    frames use it for the affected rows and the composited menu, which are the
    parts of those frames whose whole subject is a few luminance points.
    """
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QPixmap

    top = window_of(window)
    dpr = pixmap.width() / max(1, window.width())
    shell = parts(window)
    crops = {}

    crops['rail'] = rect_in_window(shell['rail'], top)
    if shell['panel'].isVisible():
        crops['panel'] = rect_in_window(shell['panel'], top)
    crops['strip'] = rect_in_window(shell['strip'], top)
    crops['bottom'] = rect_in_window(shell['bottom'], top)
    if shell['toast'].isVisible():
        x, y, w, h = rect_in_window(shell['toast'], top)
        pad = 12
        crops['toast'] = (max(0, x - pad), max(0, y - pad), w + 2 * pad, h + 2 * pad)
    crops.update(extra or {})

    written = []
    directory = path.parent / 'crops'
    directory.mkdir(parents=True, exist_ok=True)
    for name, (x, y, w, h) in crops.items():
        source = QRect(int(x * dpr), int(y * dpr), int(w * dpr), int(h * dpr))
        source = source.intersected(pixmap.rect())
        piece = pixmap.copy(source).scaled(
            source.width() * zoom, source.height() * zoom,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation)
        crop_path = directory / f'{path.stem}__{name}.png'
        piece.save(str(crop_path))
        written.append(crop_path)
    return written


# === interaction frames =====================================================

def require(condition: bool, message: str) -> None:
    """Stop the run on a failed frame *precondition*.

    Deliberately not a print-and-continue: these three frames photograph states
    that are set by driving the widget, and a frame of the wrong state is
    indistinguishable from a frame of the right one by looking at it. So the
    harness checks the state it is about to save, loudly, and lets the eye judge
    only what those checks already established is on screen.
    """
    if not condition:
        raise SystemExit(f'interaction frame precondition failed: {message}')


def state_bits() -> dict:
    """The two ``QStyle.State`` bits a batch-3 row is judged on, as plain ints.

    Taken from the enum rather than hard-coded, the same reason
    ``tests/test_playlist_hover.py`` gives: a ``QStyle.StateFlag`` is an enum and
    mixing raw ints with one in a bitmask read is exactly what a future Qt change
    gets wrong silently.
    """
    from PyQt6.QtWidgets import QStyle

    return {
        'mouse_over': int(QStyle.StateFlag.State_MouseOver.value),
        'selected': int(QStyle.StateFlag.State_Selected.value),
    }


def row_rect(window, row: int) -> tuple:
    """Row ``row``'s rect in window coordinates, or a loud failure.

    Loud because two of the three frames sample pixels from this rect: a row that
    is scrolled out of the viewport still has a rect, and a frame that
    "measures" a row nobody can see is the exact lie the guard above exists to
    stop.
    """
    shell = parts(window)
    view = shell['view']
    visual = view.visualRect(view.model().index(row))
    origin = view.viewport().mapTo(window_of(window), visual.topLeft())
    viewport_rect = rect_in_window(view.viewport(), window_of(window))
    rect = (origin.x(), origin.y(), visual.width(), visual.height())
    require(inside(viewport_rect, rect) and visual.height() > 0,
            f'row {row} is not fully inside the list viewport ({rect} vs '
            f'{viewport_rect}); the frame would sample a row no eye can reach')
    return rect


def band_pixels(pixmap, rect: tuple, dpr: float) -> list:
    """Three background samples across a row band, read off ``pixmap``.

    ``BAND_TOP_OFFSET``/``BAND_INSET`` put every sample above the text band, off
    the bottom divider, clear of the ``SPACE_2`` gutter and the 3px playing bar on
    the left, and clear of the ``[relative_position]`` read-out on the right -- so
    a hit here is background and never ink (the same geometry
    ``tests/test_playlist_hover.py`` samples with, so a pixel claim here reads the
    way a pixel claim there does).
    """
    from PyQt6.QtGui import QImage

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    x, y, w, _h = rect
    ys = int(round((y + BAND_TOP_OFFSET) * dpr))
    return [image.pixelColor(int(round((x + off) * dpr)), ys).name().lower()
            for off in (BAND_INSET, w // 2, max(0, w - BAND_INSET))]


def painted_states(window) -> dict:
    """``{row: option.state}`` for every row the delegate actually paints.

    The row states are read out of ``PlaylistItemDelegate.paint`` itself rather
    than inferred from the colours, because a colour alone cannot tell "the row
    was hovered/selected and the fill is right" from "the state never reached the
    delegate" -- which is the failure batch 3 was warned about (Task 4's hover
    branch was unreachable dead code until ``WA_Hover`` went on the viewport).
    """
    from view.delegates.playlist_delegate import PlaylistItemDelegate

    view = parts(window)['view']
    states: dict = {}
    original = PlaylistItemDelegate.paint

    def recording(delegate, painter, option, index):
        states[index.row()] = int(option.state.value)
        return original(delegate, painter, option, index)

    PlaylistItemDelegate.paint = recording
    try:
        view.viewport().grab()
    finally:
        PlaylistItemDelegate.paint = original
    return states


def park_cursor(window, app) -> None:
    """Rest the platform cursor on the playing row, where it paints nothing extra.

    The hover frame needs a baseline in which no row carries the hover fill. The
    blank strip below the last row would be the obvious parking space, but the
    fixture is eighteen rows in a 720 px window and that strip is not guaranteed
    to exist at every frame size; the playing row is, and the delegate paints it
    from ``playing_bg`` whatever the hover bit says (spec §4.1's chain), so
    parking there cannot put a hover fill in the picture. The guards still read
    the recorded option states rather than trusting this paragraph.
    """
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    view = parts(window)['view']
    visual = view.visualRect(view.model().index(PLAYING_INDEX))
    QTest.mouseMove(view.viewport(), QPoint(visual.center().x(), visual.center().y()))
    app.processEvents()


def clear_selection(playlist, app) -> None:
    """Empty the selection and prove it is empty before a frame drives it.

    The matrix re-uses one window for every frame, and ``PlaylistModel`` answers a
    same-size ``update_entries`` without a model reset, so a selection from the
    previous frame can survive a data reload. Every batch-3 frame starts by
    clearing, and says so.
    """
    playlist._list_view.clearSelection()
    app.processEvents()
    require(playlist.selected_display_indices() == [],
            'the selection did not come back empty after clearSelection(); a frame '
            'that then clicks three rows cannot say which rows it clicked')


def select_batch(playlist, app, rows) -> None:
    """Build the batch with real Ctrl+clicks, then prove the result.

    Real clicks, not ``selectionModel().select``: the frame's claim is that the
    Explorer semantics Task 1 shipped are what a user's modifier-click produces,
    and a harness that set the selection itself would still pass if Qt's
    ``ExtendedSelection`` handling had regressed to single-select.
    """
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    view = playlist._list_view
    for row in rows:
        visual = view.visualRect(playlist._model.index(row))
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier,
                         QPoint(visual.center().x(), visual.center().y()))
        app.processEvents()
    require(playlist.selected_display_indices() == sorted(rows),
            f'Ctrl+clicking rows {list(rows)} gave selection '
            f'{playlist.selected_display_indices()}, and the frame is built on '
            'that selection')


def luminance(colour: str) -> float:
    """ITU-R BT.709 relative luminance of a ``#rrggbb`` string, 0..100.

    The interaction frames' whole subject is a few points of contrast, so the
    print next to the PNG has to carry a number, not "it looks subtle".
    """
    from PyQt6.QtGui import QColor

    color = QColor(colour)
    r, g, b, _alpha = (channel / 255.0 for channel in color.getRgb())
    return round(100.0 * (0.2126 * r + 0.7152 * g + 0.0722 * b), 2)


def hovered_rows(states: dict, bits: dict) -> list:
    """The rows whose recorded option carries ``State_MouseOver``."""
    return sorted(row for row, state in states.items() if state & bits['mouse_over'])


def selected_rows(states: dict, bits: dict) -> list:
    """The rows whose recorded option carries ``State_Selected``."""
    return sorted(row for row, state in states.items() if state & bits['selected'])


def parity(row: int) -> str:
    """How a row is grounded by ``QListView``'s alternating colours."""
    return 'odd/alternating' if row % 2 else 'even/plain'


def check_band(pixmap, rect, expected: str, dpr: float, label: str) -> list:
    """Sample a row band and insist it is filled with ``expected``, end to end.

    Three columns, not one: a fill that only reaches part of the row -- a delegate
    branch painting ``option.rect`` inside the text inset, say -- is exactly the
    thing a single centre sample would miss.
    """
    band = band_pixels(pixmap, rect, dpr)
    require(band == [expected.lower()] * 3,
            f'{label}: every band sample must be {expected}, got {band}')
    return [f'{label} band={band} == {expected} MATCH']


def rows_crop(window, first: int, last: int) -> tuple:
    """The window rect covering rows ``first`` to ``last``: the interaction crops.

    Full viewport width, because the claim these crops serve is a contrast one
    ("does the fill read across the row"), and a narrow crop cannot show a fill
    that stops halfway.
    """
    view = parts(window)['view']
    viewport = rect_in_window(view.viewport(), window_of(window))
    top_row = row_rect(window, first)
    bottom_row = row_rect(window, last)
    return (viewport[0], top_row[1], viewport[2],
            bottom_row[1] + bottom_row[3] - top_row[1])


def cursor_lands(app) -> bool:
    """Whether this platform lets the harness put the pointer on a widget.

    Measured on this host, Qt 6.11: under ``offscreen`` ``QTest.mouseMove`` does
    mark the target ``underMouse()`` and the delegate then sees
    ``State_MouseOver``; under the real ``windows`` QPA it does not -- and neither
    does ``QCursor.setPos``, which moves the *pointer* (``QCursor.pos()`` agrees)
    while ``underMouse()`` stays ``False``, because Qt updates that attribute from
    the window system's enter events, not from synthetic mouse events. So row
    hover is photographable offscreen and needs a human hand on a real desktop,
    and this function is the difference rather than a guess about it.
    """
    return app.platformName() == 'offscreen'


def drive_hover(window, app, tokens) -> dict:
    """Hover :data:`HOVER_ROW` and prove the fill is on it and nowhere else."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    shell = parts(window)
    view, playlist = shell['view'], shell['playlist']
    bits = state_bits()
    playing = playlist._model.get_playing_index()
    clear_selection(playlist, app)
    park_cursor(window, app)

    rect = row_rect(window, HOVER_ROW)
    baseline = window.grab()
    before = band_pixels(baseline, rect, baseline.width() / max(1, window.width()))
    states = painted_states(window)
    require(HOVER_ROW not in hovered_rows(states, bits),
            'the parked cursor already hovers the row this frame is about to '
            'hover, so the before/after delta would prove nothing')
    require(tokens.hover_bg.lower() not in before,
            f'row {HOVER_ROW} already reads as {tokens.hover_bg} before any mouse '
            'move; the frame would photograph a hover no input caused')
    require(HOVER_ROW != playing,
            f'row {HOVER_ROW} is the playing row ({playing}), and playing_bg '
            'outranks hover_bg, so this frame could not show the hover fill')
    require(not states.get(HOVER_ROW, 0) & bits['selected'],
            f'row {HOVER_ROW} is State_Selected in the baseline; selection_bg would '
            'paint over the branch this frame is about')

    visual = view.visualRect(playlist._model.index(HOVER_ROW))
    QTest.mouseMove(view.viewport(), QPoint(visual.center().x(), visual.center().y()))
    app.processEvents()
    if not view.viewport().underMouse():
        if not cursor_lands(app):
            # Not a product failure and not a frame: the platform will not put the
            # pointer anywhere, so there is nothing to photograph. Saying so is the
            # only honest output -- a PNG of an unhovered row labelled "hover" is
            # the lie every guard in this file exists to prevent.
            return {'skipped': (
                f'hover SKIPPED on the {app.platformName()!r} QPA: the pointer never '
                'landed (QTest.mouseMove leaves underMouse() False under a real '
                'platform, and QCursor.setPos moves the pointer without changing '
                'it), so row hover has to be judged with a real mouse on a real '
                'desktop -- see the batch report\'s requires-a-human checklist')}
        require(False,
                'the synthesized mouse move did not land on the list viewport even '
                'though this platform is supposed to let it: no row can be hovered, '
                'and tests/test_playlist_hover.py documents the same harness fact '
                '(a visible top-level stacked over this window swallows motion)')

    states = painted_states(window)
    hovered = hovered_rows(states, bits)
    require(hovered == [HOVER_ROW],
            f'exactly row {HOVER_ROW} must carry State_MouseOver, got {hovered}. An '
            'empty answer means the viewport lost Qt.WidgetAttribute.WA_Hover -- '
            'Task 4 measured that mouse motion then sets the bit on no row at all '
            'and the delegate\'s hover branch is dead code. A longer answer means '
            'hover is not the one-row state spec §4.1 claims.')
    require(not states[HOVER_ROW] & bits['selected'],
            f'row {HOVER_ROW} became State_Selected under the cursor, so its fill '
            'would be selection_bg and prove nothing about hover')

    ground = before[1]
    plain = band_pixels(baseline, row_rect(window, HOVER_ROW - 1),
                        baseline.width() / max(1, window.width()))[1]
    lines = [
        f'hover cursor row={HOVER_ROW} ({parity(HOVER_ROW)} ground) '
        f'hovered_rows={hovered} underMouse=yes baseline_band={before}',
        f'hover contrast, measured off this frame\'s own baseline: the alternating '
        f'ground {ground} (lum {luminance(ground)}) -> hover_bg {tokens.hover_bg} '
        f'(lum {luminance(tokens.hover_bg)}) step='
        f'{round(luminance(tokens.hover_bg) - luminance(ground), 2)}',
        f'hover contrast on the plain ground for comparison: {plain} '
        f'(lum {luminance(plain)}) -> {tokens.hover_bg} step='
        f'{round(luminance(tokens.hover_bg) - luminance(plain), 2)} '
        '(a NEGATIVE step means hovering reads as a DARKENING, which is the shape '
        'of hover_bg in both themes on an odd row; judge it, do not assume it)',
        'hover is delegate-painted, not QSS: no #playlistView::item rule exists, and '
        'tests/test_playlist_hover.py::test_no_item_qss_rule_was_added pins that',
    ]

    def expect(pixmap, dpr):
        after = band_pixels(pixmap, rect, dpr)
        lines = check_band(pixmap, rect, tokens.hover_bg.lower(), dpr,
                           f'hovered row {HOVER_ROW}')
        require(after != before,
                f'hovering row {HOVER_ROW} changed no pixel in the frame '
                f'(before={before} after={after}); the fill is invisible, not subtle')
        neighbours = [
            f'hover neighbours row{HOVER_ROW - 1}='
            f'{band_pixels(pixmap, row_rect(window, HOVER_ROW - 1), dpr)} '
            f'row{HOVER_ROW + 1}='
            f'{band_pixels(pixmap, row_rect(window, HOVER_ROW + 1), dpr)} '
            'neither carries hover_bg (hover is one row, not the view)',
            f'hover frame band={after} against the unhovered baseline {before}',
        ]
        return lines + neighbours

    return {'lines': lines, 'expect': expect,
            'crops': {'rows': rows_crop(window, HOVER_ROW - 2, HOVER_ROW + 2)}}


def unselected_neighbours(rows) -> list:
    """Rows that must **not** take the batch's fill: the gaps inside it and one on
    each side.

    The inside gap is the point. A fill that ran past its own row -- a range-style
    paint, or a delegate that trusted the selection model's range rather than its
    per-row ``State_Selected`` -- is invisible when the batch is contiguous, which
    is exactly why three Ctrl+clicked rows with a gap between them is the fixture.
    """
    return ([row for row in range(min(rows), max(rows) + 1) if row not in rows]
            + [min(rows) - 1, max(rows) + 1])


def drive_multi_selected(window, app, tokens) -> dict:
    """Ctrl+click :data:`BATCH_ROWS` and prove the batch is the batch, row by row."""
    shell = parts(window)
    playlist = shell['playlist']
    bits = state_bits()
    playing = playlist._model.get_playing_index()
    clear_selection(playlist, app)
    park_cursor(window, app)
    select_batch(playlist, app, BATCH_ROWS)

    states = painted_states(window)
    selected = selected_rows(states, bits)
    require(selected == sorted(BATCH_ROWS),
            f'Ctrl+clicks on {list(BATCH_ROWS)} must leave exactly those rows '
            f'carrying State_Selected, got {selected}')
    require(playing in BATCH_ROWS,
            f'the batch {list(BATCH_ROWS)} no longer holds the playing row '
            f'({playing}), so this frame loses the priority-chain claim it exists for')

    lines = [
        f'selection ctrl-clicked rows={list(BATCH_ROWS)} (non-contiguous by design) '
        f'selected_display_indices={playlist.selected_display_indices()} '
        f'state_selected_rows={selected} playing_row={playing}',
        f'selection tokens selection_bg={tokens.selection_bg} '
        f'playing_bg={tokens.playing_bg} (the grounds are measured from the frame, '
        'not from the palette: the sheet paints the list background translucent)',
        f'selection chain row {playing} is both State_Selected and the playing row: '
        'the frame must show playing_bg there, not selection_bg (spec §4.1)',
        'selection is delegate-painted: a #playlistView::item QSS rule would render '
        'zero pixels here, and tests/test_playlist_hover.py pins that none exists',
    ]

    def expect(pixmap, dpr):
        out = []
        for row in BATCH_ROWS:
            if row == playing:
                out += check_band(pixmap, row_rect(window, row),
                                  tokens.playing_bg.lower(), dpr,
                                  f'selected+playing row {row} keeps playing_bg')
            else:
                out += check_band(pixmap, row_rect(window, row),
                                  tokens.selection_bg.lower(), dpr,
                                  f'selected row {row} ({parity(row)})')
        grounds = {}
        for row in unselected_neighbours(BATCH_ROWS):
            band = band_pixels(pixmap, row_rect(window, row), dpr)
            require(tokens.selection_bg.lower() not in band,
                    f'row {row} is outside the batch but shows selection_bg {band}')
            grounds.setdefault(row % 2, band[1])
            out.append(f'selection neighbour row {row} ({parity(row)}) band={band} '
                       'untouched MATCH')
        # The step an eye is being asked to judge, measured against what the frame
        # actually paints underneath -- ``surface``/``surface_alt`` are the palette
        # answer, and the list background is composited through an alpha step.
        for odd, ground in sorted(grounds.items()):
            out.append(
                f'selection step over the measured '
                f'{"odd/alternating" if odd else "even/plain"} ground {ground}: '
                f'{round(luminance(tokens.selection_bg) - luminance(ground), 2)} '
                '(luminance points; NEGATIVE = the fill is a DARKENING on that row)')
        return out

    return {'lines': lines, 'expect': expect,
            'crops': {'rows': rows_crop(window, min(BATCH_ROWS) - 1,
                                         max(BATCH_ROWS) + 1)}}


def drive_context_menu(window, app, tokens) -> dict:
    """Right-click *inside* the batch and photograph the menu that opens.

    The route is the one Task 3 measured as necessary: a genuine
    ``QContextMenuEvent`` posted at the inner list viewport, which
    ``QAbstractItemView`` ignores and Qt then propagates up to ``PlaylistView``
    with ``pos()`` re-expressed. ``QTest.mouseClick(..., RightButton)`` produces
    two mouse events and no context-menu event at all under ``offscreen``, so a
    frame driven that way would photograph a menu nothing had asked for.
    """
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QContextMenuEvent

    from core import i18n
    from view.widgets.playlist_context_menu import MENU_IDS

    shell = parts(window)
    view, playlist = shell['view'], shell['playlist']
    playing = playlist._model.get_playing_index()
    clear_selection(playlist, app)
    park_cursor(window, app)
    select_batch(playlist, app, BATCH_ROWS)

    seen: dict = {'shown': 0}

    def seam(menu, global_pos):
        """Stand in for ``QMenu.exec()`` and photograph from inside it.

        The menu's pixels have to be taken *here*. The handler's ``finally`` runs
        ``deleteLater()``, which merely schedules the deletion -- re-probed on this
        host: ``processEvents`` leaves the object alive, while an explicit
        ``sendPostedEvents(None, DeferredDelete)`` or any real event loop destroys
        it (reading ``menu.actions()`` afterwards raises ``RuntimeError``). It is
        therefore ``pump()``'s deferred-delete flush, not ``processEvents``, that
        removes the menu between the seam and any later grab. The ``QPixmap`` itself
        survives, being ref-counted and independent of the widget.
        """
        entries = [action for action in menu.actions() if not action.isSeparator()]
        seen['shown'] += 1
        seen['ids'] = tuple(action.data() for action in entries)
        seen['labels'] = tuple(action.text() for action in entries)
        seen['separators'] = len(menu.actions()) - len(entries)
        seen['targets'] = playlist.selected_display_indices()
        seen['parent'] = menu.parent()
        seen['global_pos'] = global_pos
        grabbed = menu.grab()
        seen['pixmap'] = grabbed
        seen['image'] = grabbed.toImage()
        seen['bg'] = seen['image'].pixelColor(2, 2).name().lower()
        return None

    visual = view.visualRect(playlist._model.index(MENU_ROW))
    point = QPoint(visual.center().x(), visual.bottom() - 1)
    received = []

    def sink(index, event):
        received.append(index)

    playlist._popup_menu = seam
    playlist.context_menu_requested.connect(sink)
    try:
        event = QContextMenuEvent(QContextMenuEvent.Reason.Other, QPoint(point),
                                  QPoint(view.viewport().mapToGlobal(point)))
        app.sendEvent(view.viewport(), event)
        app.processEvents()
    finally:
        del playlist._popup_menu
        playlist.context_menu_requested.disconnect(sink)

    require(seen['shown'] == 1,
            f'the real handler must have popped exactly one menu, got {seen["shown"]}. '
            'Zero means the posted QContextMenuEvent never reached '
            'PlaylistView.contextMenuEvent, so the frame would carry no menu at all.')
    require(seen['targets'] == sorted(BATCH_ROWS),
            f'the menu was built for {seen["targets"]}, not the batch {list(BATCH_ROWS)}: '
            'a right-click inside the selection must keep it (spec §4.3), and an '
            'off-by-the-header-offset target lookup is what breaks that')
    require(playlist.selected_display_indices() == sorted(BATCH_ROWS),
            'the right-click collapsed the selection underneath the menu')
    require(received == [min(BATCH_ROWS)],
            f'context_menu_requested must fire once with targets[0], got {received}')
    require(seen['ids'] == MENU_IDS,
            f'the menu entries are {seen["ids"]}, not the builder\'s {MENU_IDS}')
    require(seen['separators'] == 1,
            f'one separator before the clear entry is the contract, got {seen["separators"]}')
    require(not seen['pixmap'].isNull() and seen['pixmap'].width() > 0
            and seen['pixmap'].height() > 0,
            f'menu.grab() gave {seen["pixmap"].width()}x{seen["pixmap"].height()} px; '
            'an empty grab means the menu was never laid out and the composite would '
            'paint nothing over the list')

    active = i18n.get_current_locale()
    other = 'en_US' if active == 'zh_CN' else 'zh_CN'
    count = len(BATCH_ROWS)
    copy = {active: seen['labels']}
    previous = i18n.get_current_locale()
    try:
        i18n.set_locale(other)
        copy[other] = (i18n.get('ctx.pause'),
                       i18n.get('ctx.remove_count', count=count),
                       i18n.get('ctx.clear_playlist'))
    finally:
        i18n.set_locale(previous)
    for locale, labels in copy.items():
        for label in labels:
            require('[MISSING' not in label,
                    f'{locale}: menu copy {label!r} is a missing-key marker')
            require('{' not in label and '}' not in label,
                    f'{locale}: menu copy {label!r} leaked a placeholder brace')
        require(str(count) in labels[1],
                f'{locale}: the batch copy {labels[1]!r} does not name the {count} '
                'targets it acts on')

    from dataclasses import fields

    token_values = {getattr(tokens, field.name).lower() for field in fields(tokens)
                    if isinstance(getattr(tokens, field.name), str)
                    and getattr(tokens, field.name).startswith('#')}
    require(seen['bg'] in token_values,
            f'the popup paints {seen["bg"]}, a colour no token of {theme_of(tokens)} '
            'emits (batch 1/2\'s defect class: a surface the theme does not know about)')

    at = view.viewport().mapTo(window_of(window), point)
    lines = [
        f'menu route real QContextMenuEvent -> PlaylistView.contextMenuEvent; '
        f'_popup_menu seam replaced, menu painted by QMenu.grab() INSIDE the seam '
        f'(no exec(), no nested loop) and composited at {at.x()},{at.y()}',
        f'menu targets={seen["targets"]} (right-click inside the batch keeps it) '
        f'selection_after={playlist.selected_display_indices()} shown={seen["shown"]} '
        f'context_menu_requested={received}',
        f'menu ids={list(seen["ids"])} separators={seen["separators"]} '
        f'parent={"PlaylistView" if seen["parent"] is playlist else seen["parent"]}',
        f'menu copy [{active}, photographed] '
        + ' | '.join(repr(label) for label in copy[active]),
        f'menu copy [{other}, printed not photographed] '
        + ' | '.join(repr(label) for label in copy[other]),
        f'menu grab={seen["pixmap"].width()}x{seen["pixmap"].height()} px '
        f'bg={seen["bg"]} is a {theme_of(tokens)} token; neither locale shows a '
        'marker or a brace',
    ]

    def expect(pixmap, dpr):
        """The rows under where the menu will land, checked before the composite.

        The frame's own claim is the menu, but the batch has to still be there for
        the menu to mean anything, so the two plain rows are checked against
        ``selection_bg`` and the playing row against ``playing_bg`` first -- and
        the popup is drawn only afterwards, because it covers exactly these rows.
        """
        out = []
        for row in BATCH_ROWS:
            if row == playing:
                out += check_band(pixmap, row_rect(window, row),
                                  tokens.playing_bg.lower(), dpr,
                                  f'menu frame playing row {row} under the batch')
            else:
                out += check_band(pixmap, row_rect(window, row),
                                  tokens.selection_bg.lower(), dpr,
                                  f'menu frame selected row {row} ({parity(row)})')
        return out

    def verify_composite(pixmap, dpr, menu_pixmap, rect):
        """Prove the menu's pixels are in the frame where the frame says they are.

        ``rect`` is the physical rect :func:`composite_menu` actually drew into, so
        the mapping holds whatever the two device pixel ratios turned out to be --
        the claim being checked is "this picture contains that grab", and it has to
        be checked against the drawing, not against a second arithmetic of it.
        """
        from PyQt6.QtGui import QImage

        x, y, width, height = rect
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
        source = menu_pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
        sx_ratio = width / max(1, menu_pixmap.width())
        sy_ratio = height / max(1, menu_pixmap.height())
        spots = [(2, 2), (menu_pixmap.width() // 2, 6),
                 (menu_pixmap.width() // 2, menu_pixmap.height() - 8)]
        out = []
        for sx, sy in spots:
            got = image.pixelColor(int(x + sx * sx_ratio),
                                   int(y + sy * sy_ratio)).name().lower()
            want = source.pixelColor(sx, sy).name().lower()
            require(got == want,
                    f'the composited menu pixel at {sx},{sy} reads {got} in the '
                    f'frame but {want} in the grab: the composite landed somewhere '
                    'else than it claims')
            out.append(f'menu composite pixel {sx},{sy} frame={got} grab={want} MATCH')
        return out

    menu_dpr = seen['pixmap'].devicePixelRatio() or 1.0
    return {'lines': lines, 'expect': expect, 'verify_composite': verify_composite,
            'menu': seen['pixmap'], 'menu_at': (at.x(), at.y()),
            # Window-logical rects, because that is what :func:`write_crops` scales.
            'crops': {
                'menu': (at.x(), at.y(),
                         seen['pixmap'].width() / menu_dpr,
                         seen['pixmap'].height() / menu_dpr),
                'rows': rows_crop(window, min(BATCH_ROWS) - 1,
                                  max(BATCH_ROWS) + 1)}}


def theme_of(tokens) -> str:
    """Which token set this frame wears, for a line that names it."""
    from core.theme import DARK, LIGHT

    return 'DARK' if tokens is DARK else ('LIGHT' if tokens is LIGHT else 'custom')


def composite_menu(pixmap, menu_pixmap, at, dpr: float) -> tuple:
    """Draw the grabbed popup onto the captured frame, top-left at ``at``.

    Physical pixels throughout, the same convention :func:`write_crops` reads with
    -- and the painter has to be told the frame is physical, because
    ``QWidget.grab()`` hands back a pixmap with the widget's device pixel ratio
    already set and a ``QPainter`` on it would scale twice.

    Fitting the menu inside the frame is a requirement rather than a nicety: a
    live popup that would not fit gets flipped by Qt, and a composite that quietly
    clipped instead would put a half-menu in front of a human and let them certify
    a shape the product never draws.
    """
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPainter

    menu_dpr = menu_pixmap.devicePixelRatio() or 1.0
    width = int(round(menu_pixmap.width() / menu_dpr * dpr))
    height = int(round(menu_pixmap.height() / menu_dpr * dpr))
    x, y = int(round(at[0] * dpr)), int(round(at[1] * dpr))
    require(x >= 0 and y >= 0 and x + width <= pixmap.width()
            and y + height <= pixmap.height(),
            f'the menu rect {(x, y, width, height)} does not fit the '
            f'{pixmap.width()}x{pixmap.height()} frame: a live popup would be moved '
            'to stay on screen and this composite would only be clipped, so the '
            'frame size or the clicked row has to change')

    pixmap.setDevicePixelRatio(1.0)
    painter = QPainter(pixmap)
    try:
        painter.drawPixmap(QRect(x, y, width, height), menu_pixmap,
                           QRect(0, 0, menu_pixmap.width(), menu_pixmap.height()))
    finally:
        painter.end()
    return (x, y, width, height)


#: Which driver builds which interaction frame.
DRIVERS = {
    'hover': drive_hover,
    'multi-selected': drive_multi_selected,
    'context-menu': drive_context_menu,
}


def render_interaction_frame(app, window, manager, theme: str, kind: str,
                             size: tuple, out_dir: Path, mode: str,
                             verbose: bool, crops: bool = False):
    """One interaction frame: data, state, capture, checks, then the save.

    The order is the function's claim to make. The state goes on **after**
    :func:`present`, because hover, the selection and the menu's resolved target
    are all facts about a laid-out live widget; ``facts['expect']`` then reads its
    pixels off the captured frame, so the picture a human is asked to judge is the
    same picture the guards already certified. A menu frame composites **after**
    those row checks: the popup is drawn over the rows it describes, so a band
    checked against a menu pixel would fail for the right reason and pass for none.

    Returns the path, or ``None`` when the platform made the state unreachable --
    see :func:`cursor_lands`. A frame is never written for a state that is not on
    screen, so a skipped state is reported as a skip and not as a picture.
    """
    manager.set_mode(theme)
    apply_state(window, 'populated')
    window.resize(*size)
    present(window, app, mode)
    facts = DRIVERS[kind](window, app, manager.tokens)
    if facts.get('skipped'):
        print(f'=== {theme}_{kind}: {facts["skipped"]}')
        return None
    pump(app, 0.0 if mode == 'grab' else 0.05)

    pixmap = capture(window, mode)
    dpr = pixmap.width() / max(1, window.width())
    frame_lines = facts['expect'](pixmap, dpr)

    if facts.get('menu') is not None:
        rect = composite_menu(pixmap, facts['menu'], facts['menu_at'], dpr)
        frame_lines += facts['verify_composite'](pixmap, dpr, facts['menu'], rect)
        frame_lines.append(
            f'menu composited physical rect={rect} (dpr {dpr:.2f}); the popup has no '
            'native frame, shadow or edge-flip in this composite')

    name = f'{theme}_{kind}_{size[0]}x{size[1]}.png'
    path = out_dir / name
    pixmap.save(str(path))
    if crops:
        write_crops(pixmap, window, path, extra=facts.get('crops'))

    if verbose:
        print(f'\n=== {name}  [{mode}]  {pixmap.width()}x{pixmap.height()} px ===')
        for line in measure(window):
            print(f'    {line}')
        for line in facts['lines'] + frame_lines:
            print(f'    {line}')
        print('    census  ' + '  '.join(colour_census(pixmap)))
        if window.devicePixelRatioF() != 1.0:
            print(f'    (dpr {window.devicePixelRatioF():.2f}; '
                  'measures above are logical px)')
    return path


# === capture =================================================================

#: Where the real-QPA run parks the window: fully inside the primary screen, so
#: ``grabWindow`` cannot catch a strip of the window off the edge.
FRAME_ORIGIN = (60, 60)


def present(window, app, mode: str) -> None:
    """Show the window at its current size and let the desktop catch up.

    Separate from :func:`capture` because the shell's two overlays position
    themselves against their parent at open time: a frame that opened the panel
    before the window was shown and laid out photographs a snapshot of the
    *previous* frame's parent size -- which is how the first run here measured a
    146 px panel holding thirty rows. So the caller presents, opens its overlays,
    presents again, and only then captures.

    ``settle`` exists for the real-QPA run: a native window is composited by the
    desktop, so the grabbed pixels can lag the repaint by a frame. ``grab()``
    repaints synchronously and needs no pause.
    """
    settle = 0.0 if mode == 'grab' else 0.05
    window.show()
    window.move(*FRAME_ORIGIN)
    window.raise_()
    window.activateWindow()
    pump(app, settle)
    for _ in range(4):
        if settle:
            time.sleep(settle)
        app.processEvents()


def capture(window, mode: str):
    """The frame as a pixmap, by the primitive ``mode`` names.

    ``grab`` is the batch-1 default and the one that composites transparency to
    white; ``window`` is ``QScreen.grabWindow`` on the real top-level, which is
    what batch 1 Task 10 had to fall back to in order to see the never-painted
    window background at all.
    """
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QApplication

    if mode == 'grab':
        return window.grab()

    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        raise SystemExit('--capture window needs a real screen: run it under the '
                         'platform QPA (windows/xcb), not offscreen')
    full = screen.grabWindow(int(window.winId()))
    if full.isNull():
        raise SystemExit('QScreen.grabWindow returned a null pixmap')

    # A native top-level's ``grabWindow`` *may* answer with the whole window frame
    # instead of the client area -- on this Qt 6.11/Windows host it does not, and
    # the first run here proved the difference is not academic: cropping
    # unconditionally by the frame margins threw away the real 31 px title bar and
    # shipped twelve frames with the rail's first button and the panel's title cut
    # off. So: sizes equal means the grab already is the client area, and only a
    # grab *larger* than the client area carries a frame worth cropping out.
    frame, geo = window.frameGeometry(), window.geometry()
    dpr = full.width() / max(1, frame.width())
    w, h = int(window.width() * dpr), int(window.height() * dpr)
    if (full.width(), full.height()) == (w, h) or full.width() < w or full.height() < h:
        return full
    x = int((geo.x() - frame.x()) * dpr)
    y = int((geo.y() - frame.y()) * dpr)
    crop = full.copy(QRect(x, y, min(w, full.width() - x), min(h, full.height() - y)))
    return crop if not crop.isNull() else full


def render_frame(app, window, manager, theme: str, state: str, size: tuple,
                 out_dir: Path, name: str, mode: str, verbose: bool,
                 crops: bool = False, open_panel: bool = False,
                 toast_copy: str = '') -> Path:
    """One frame: theme, data, size, show, overlays, capture.

    The order is the function's whole point. Both floating widgets compute their
    geometry from their parent, and that parent only has its final size after the
    layout has run at the new window size -- so the overlays go on *after* the
    first :func:`present`, then get one more settle pass, and only then is the
    frame photographed. Returns the frame path alone: crops belong to
    ``<out>/crops/`` and are not counted as frames.
    """
    manager.set_mode(theme)
    apply_state(window, state)
    window.resize(*size)
    present(window, app, mode)
    if open_panel:
        window.toggle_library_panel()
    if toast_copy:
        window.show_toast(toast_copy)
    if open_panel or toast_copy:
        present(window, app, mode)

    pixmap = capture(window, mode)
    path = out_dir / name
    pixmap.save(str(path))
    if crops:
        write_crops(pixmap, window, path)

    if verbose:
        print(f'\n=== {name}  [{mode}]  {pixmap.width()}x{pixmap.height()} px ===')
        for line in measure(window):
            print(f'    {line}')
        print('    census  ' + '  '.join(colour_census(pixmap)))
        if window.devicePixelRatioF() != 1.0:
            print(f'    (dpr {window.devicePixelRatioF():.2f}; '
                  'measures above are logical px)')
    return path

    written = [path]
    if crops:
        written += write_crops(pixmap, window, path)
    return written


def render_matrix(out_dir: Path, mode: str = 'grab', verbose: bool = True,
                  sidebar_open: bool = False, with_toast: bool = False,
                  interaction: bool = False, crops: bool = False):
    """Write the 12 matrix frames plus the opted-in overlay/interaction frames.

    One window and one manager are re-used for the whole matrix, and the theme is
    switched through ``ThemeManager.set_mode`` -- the live path a user takes from
    the appearance dialog -- rather than by rebuilding the app per theme. A theme
    that only renders correctly on a cold start is a real bug, and this is the
    harness that would catch it.

    Returns ``(matrix_paths, extra_paths)``: the 12 are the contract the exit code
    checks, the extras are the frames the flags asked for.

    The interaction frames go last on purpose. Each one moves the platform cursor
    and edits the selection, and the twelve matrix frames must not be photographed
    through any of that; running them after the matrix, and hiding the window
    between every frame, keeps each picture's own state its own.
    """
    from main import build_theme_manager
    from service.config_service import ConfigService
    from view.main_window import MainWindow

    app = build_app()
    out_dir.mkdir(parents=True, exist_ok=True)

    # A throwaway settings file: ConfigService writes, and a harness must not
    # touch the real ``~/.pyplayer/cache/settings.json``.
    with tempfile.TemporaryDirectory(prefix='pyplayer-render-matrix-') as tmp:
        config = ConfigService(config_file=str(Path(tmp) / 'settings.json'))
        # ``mode`` comes from the config here; the matrix overrides it per row
        # through ``set_mode``, which is the live path the appearance dialog uses.
        manager = build_theme_manager(app, config, mode=config.get_theme())
        window = MainWindow(manager)

        matrix: List[Path] = []
        for theme in THEMES:
            for state in STATES:
                for (width, height) in SIZES:
                    name = f'{theme}_{state}_{width}x{height}.png'
                    matrix.append(render_frame(
                        app, window, manager, theme, state, (width, height),
                        out_dir, name, mode, verbose, crops=crops,
                        # ``thirty-libraries`` is the state the panel-open frames
                        # belong to: the floating panel is the only surface where
                        # a library count is visible at all.
                        open_panel=(state == 'thirty-libraries')))
        window.hide()

        extras: List[Path] = []
        if sidebar_open:
            theme, width, height = OPEN_FRAME
            name = f'{theme}_sidebar-open_{width}x{height}.png'
            extras.append(render_frame(
                app, window, manager, theme, 'populated', (width, height),
                out_dir, name, mode, verbose, crops=crops, open_panel=True))
            window.hide()
        if with_toast:
            from core import i18n

            theme, width, height = TOAST_FRAME
            name = f'{theme}_toast_{width}x{height}.png'
            # The real string, with real numbers: ``status.refreshed_files`` is
            # the copy the presenter emits after a refresh-all, so this frame
            # photographs the toast the way a user reads it (and its length is
            # what makes the wrap-versus-clip question answerable).
            extras.append(render_frame(
                app, window, manager, theme, 'populated', (width, height),
                out_dir, name, mode, verbose, crops=crops,
                toast_copy=i18n.get('status.refreshed_files', count=128, libs=4)))
            window.hide()
        if interaction:
            for kind in INTERACTION_STATES:
                for theme in THEMES:
                    width, height = INTERACTION_SIZE
                    path = render_interaction_frame(
                        app, window, manager, theme, kind, (width, height),
                        out_dir, mode, verbose, crops=crops)
                    if path is not None:
                        extras.append(path)
                    window.hide()
        window.close()
    return matrix, extras


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='Render the 12-frame PyPlayer shell matrix (light|dark x '
                    'empty|populated|thirty-libraries x 820x520|1100x720), plus '
                    'the optional overlay frames.')
    parser.add_argument('--out', type=Path, default=None,
                        help='Directory for the PNGs. Defaults to a temp '
                             'directory, whose path is printed.')
    parser.add_argument('--capture', choices=('grab', 'window'), default='grab',
                        help='grab = QWidget.grab() (offscreen, composites '
                             'transparency to white); window = QScreen.grabWindow '
                             'on the real top-level (needs a live QPA, renders '
                             'CJK, shows the true composite).')
    parser.add_argument('--sidebar-open', action='store_true',
                        help='Add the dedicated frame with the floating library '
                             'panel open (three libraries, dark, 1100x720).')
    parser.add_argument('--toast', action='store_true',
                        help='Add the dedicated frame with a live toast over the '
                             'populated list (dark, 820x520).')
    parser.add_argument('--interaction', action='store_true',
                        help='Add the six batch-3 interaction frames: hover, '
                             'multi-selected and context-menu, each in light and '
                             'dark at 1100x720. Every one of them checks its own '
                             'precondition first and stops the run if the state is '
                             'not live (see the module docstring).')
    parser.add_argument('--crops', action='store_true',
                        help='Also write 2x crops (rail, panel, strip, toast, '
                             'bottom bar, and on the interaction frames the affected '
                             'rows and the menu) of every frame into <out>/crops/.')
    parser.add_argument('--quiet', action='store_true',
                        help='Do not print each rendered file and its measures.')
    args = parser.parse_args(argv)

    out_dir = args.out or Path(tempfile.mkdtemp(prefix='pyplayer-matrix-'))
    matrix, extras = render_matrix(
        out_dir, mode=args.capture, verbose=not args.quiet,
        sidebar_open=args.sidebar_open, with_toast=args.toast,
        interaction=args.interaction, crops=args.crops)

    if len(matrix) != FRAME_COUNT:
        print(f'Expected {FRAME_COUNT} matrix frames, wrote {len(matrix)}',
              file=sys.stderr)
        return 1
    frames = matrix + extras
    missing = [str(p) for p in frames if not p.is_file() or p.stat().st_size == 0]
    if missing:
        print('Empty or missing frames: ' + ', '.join(missing), file=sys.stderr)
        return 1
    if not args.out:
        print(f'\nout: {out_dir}')
    print(f'\n{len(matrix)} matrix frames'
          + (f' + {len(extras)} overlay/interaction frames' if extras else '')
          + f' in {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
