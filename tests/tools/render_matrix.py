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

plus two opt-in overlay frames, because the shell's two floating widgets are the
parts a closed shell cannot photograph:

* ``--sidebar-open``: three-library panel open, dark, 1100x720. Dark and wide on
  purpose: the question this frame answers is Task 7's D7 note -- the panel's
  ``x`` is ``RAIL_WIDTH`` *inside* ``content_stack``, which already begins right
  of the rail, so a 56 px stripe of the playlist can show between the rail and
  the panel. In LIGHT that stripe is ``#f5f5f5`` rail against a ``#ffffff`` list,
  i.e. invisible, so a "looks fine" there would be worthless; in DARK it is
  ``#2d2d30`` against ``#252526`` and the frame shows what is actually there.
* ``--toast``: a live toast over the populated list, dark, 820x520 -- the narrow,
  low-contrast corner of checklist item 6. Its copy is ``status.refreshed_files``
  read through ``i18n``, so the frame photographs the real string with real
  numbers instead of a literal typed into a harness.

``thirty-libraries`` frames are rendered with the panel **open**: the floating
panel is the only surface in the shipped UI where a library count is visible at
all, so a closed-panel "30 libraries" frame would be pixel-identical to
``populated`` and the third column of the matrix would be decoration. The panel
opens after the window is laid out at the frame's size, not while the data loads
-- :func:`render_frame` explains why that order matters.

Nothing here asserts. A stylesheet that parses is not a stylesheet that looks
right, and this script exists so a human eye is the gate -- with numbers beside
it, because three of batch 2's checklist items ("the list is window width minus
56", "the strip's lines do not clip out of their control", "the toast does not
cover the playing row") are geometry claims an eye cannot settle. The per-frame
measurement block and the colour census print next to each file, and ``--crops``
writes 2x crops of the rail, the panel, the strip and the toast, which is how the
icon-weight and text-legibility claims get *looked at* rather than assumed.

Run it:

    QT_QPA_PLATFORM=offscreen python tests/tools/render_matrix.py --out /tmp/pyplayer-b2
    python tests/tools/render_matrix.py --out /tmp/pyplayer-b2-win --capture window
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

* **Hover and focus states.** Neither ``WA_UnderMouse`` nor a synthetic
  ``QMouseEvent`` drives QSS's ``State_MouseOver``, and this host's cursor sits on
  a virtual display that will not hold ``QCursor.setPos``. The rail and row
  ``:hover``/``:focus`` rules need a real pointer over a real window.
* **HiDPI offscreen.** ``offscreen`` reports device pixel ratio 1, so the
  ``icon(..., dpr)`` 2x path only runs under ``--capture window`` on a scaled
  display.
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
    from view.widgets import ActionRail, LibrarySidebar, Toast

    rail = window.findChild(ActionRail)
    panel = window.findChild(LibrarySidebar)
    toast = window.findChild(Toast)
    view = window.findChild(QListView, 'playlistView')
    container = window.findChild(QWidget, 'playlistContainer')
    bottom = window.findChild(QWidget, 'bottomPanel')
    strip = window.findChild(QWidget, 'nowPlayingStrip')
    for name, widget in (('actionRail', rail), ('librarySidebar', panel),
                         ('toast', toast), ('playlistView', view),
                         ('playlistContainer', container), ('bottomPanel', bottom),
                         ('nowPlayingStrip', strip)):
        if widget is None:
            raise SystemExit(f'#{name} is not in the MainWindow tree; the shell '
                             'this harness photographs has changed shape')
    return {
        'rail': rail, 'panel': panel, 'toast': toast, 'view': view,
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


def write_crops(pixmap, window, path: Path, zoom: int = 2) -> List[Path]:
    """2x crops of the four surfaces whose defects are too small to see full-frame.

    Icon *weight* (item 2) cannot be judged at 1x inside a 1100 px frame: a 20 px
    glyph is a smudge, and "the rail icons match the transport glyphs" then turns
    into a guess. Same for the panel footer's two entries and the strip's 12 px
    artist line. Each crop is taken from the captured pixmap -- the pixels that
    were actually painted -- not from a fresh ``grab()``, so a ``--capture window``
    crop still shows the real composite.
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
                  crops: bool = False):
    """Write the 12 matrix frames plus the opted-in overlay frames.

    One window and one manager are re-used for the whole matrix, and the theme is
    switched through ``ThemeManager.set_mode`` -- the live path a user takes from
    the appearance dialog -- rather than by rebuilding the app per theme. A theme
    that only renders correctly on a cold start is a real bug, and this is the
    harness that would catch it.

    Returns ``(matrix_paths, extra_paths)``: the 12 are the contract the exit code
    checks, the extras are the two overlay frames.
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
    parser.add_argument('--crops', action='store_true',
                        help='Also write 2x crops (rail, panel, strip, toast, '
                             'bottom bar) of every frame into <out>/crops/.')
    parser.add_argument('--quiet', action='store_true',
                        help='Do not print each rendered file and its measures.')
    args = parser.parse_args(argv)

    out_dir = args.out or Path(tempfile.mkdtemp(prefix='pyplayer-matrix-'))
    matrix, extras = render_matrix(
        out_dir, mode=args.capture, verbose=not args.quiet,
        sidebar_open=args.sidebar_open, with_toast=args.toast, crops=args.crops)

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
          + (f' + {len(extras)} overlay frames' if extras else '')
          + f' in {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
