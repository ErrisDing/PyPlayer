#!/usr/bin/env python3
"""Render matrix: the whole theme layer, as pixels.

Tasks 1-9 replaced every styling source in the app (34 semantic tokens in
``core/theme.py``, one generated sheet in ``core/theme_qss.py``, a
``ThemeManager`` that follows the system theme, an SVG icon set) without ever
looking at the result. This is the harness that looks: it builds the real
``MainWindow``, pumps it full of fake data, and saves

    light | dark  x  empty | populated  x  820x520 | 1100x720  =  8 PNGs

Nothing is asserted here. A stylesheet that parses is not a stylesheet that
looks right -- the two-slivers-identical bug (A1), the dark-grey playlist header
(A3) and the half-light macOS dark mode (A2) were all defects that unit tests
could only describe, never see. This script exists so a human eye is the gate.

Run it (headless is fine, ``QT_QPA_PLATFORM`` is forced to ``offscreen``):

    QT_QPA_PLATFORM=offscreen python tests/tools/render_matrix.py --out /tmp/pyplayer-ui
    python tests/tools/render_matrix.py            # temp dir, path printed

Two things this harness *cannot* show, and no reading of the PNGs makes them
verified:

* **CJK text.** The offscreen platform has no fontconfig-backed CJK fallback,
  so Chinese copy renders as empty boxes here. The pixel files are for
  geometry, colour and chrome; ``python main.py`` on a real desktop is the
  only way to check the words. See spec section 6's own caveat.
* **HiDPI.** Offscreen reports device pixel ratio 1. A 2x display exercises
  the ``icon(..., dpr)`` path this run does not.
* **Hover states.** Nothing here paints ``:hover``. Neither ``WA_UnderMouse``
  nor a synthetic ``QMouseEvent`` drives QSS's ``State_MouseOver``, so the chip
  and list-item hover rules need a real pointer over a real window.

The matrix deliberately reuses :func:`tests.test_view_smoke.make_app`, so the
harness and the smoke test construct the application the same way and cannot
drift into "the test passes but the tool renders something else".
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import List

# Headless before PyQt is imported: the QPA plugin is chosen when the first
# ``QApplication`` is constructed, so this has to run ahead of the imports below.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

THEMES = ('light', 'dark')
STATES = ('empty', 'populated')
SIZES = ((820, 520), (1100, 720))

# Three libraries: the media-library chip row has to show at least one selected
# chip and two resting ones in every populated frame, and the short names keep
# the row from wrapping at 820px so the chips stay comparable across the matrix.
LIBRARIES = (
    ('D:/fake/music', 'Music'),
    ('D:/fake/podcasts', 'Podcasts'),
    ('D:/fake/flac', 'FLAC'),
)
CURRENT_LIBRARY = LIBRARIES[0][0]

# Playback state for the populated half of the matrix. Index 3 is the playing
# row (below a folder row, so the playing bar has to survive next to a bold
# folder label), and 125.5/355.0 puts the progress handle at 35% -- far enough
# from both ends to compare the groove, the sub-page and the handle.
PLAYING_INDEX = 3
POSITION = 125.5
DURATION = 355.0
VOLUME = 0.6
LOOP_MODE = 'ALL'


def build_entries() -> List:
    """Sixteen ``DisplayEntry`` rows: three folders plus thirteen tracks.

    Mirrors ``QueueService``'s real shape (a folder row, then its tracks
    indented by four spaces, each carrying a relative position), because the
    delegate paints ``[relative_position]`` on the right and elides the name on
    the left -- two behaviours only a folder tree exercises. A couple of names
    are deliberately long so the 820px frames show the ellipsis instead of a
    collision with the position text.
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
    # Long enough to overrun the row at 820px but not at 1100px, so the small
    # frames of the matrix show the delegate's elide path (name truncated with
    # an ellipsis, ``[relative_position]`` still fully visible on the right) and
    # the large frames show the same row uncut. A name that fits everywhere
    # leaves the collision the eliding exists to prevent untested.
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


def pump(app) -> None:
    """Run the loop until the frame is settled *and* fully reaped.

    ``QCoreApplication.processEvents`` alone does NOT honour ``deleteLater``:
    deferred deletes are only sent when control returns to a running event
    loop, and ``LibrarySelector._rebuild_buttons`` uses exactly that to retire
    the old chips. A harness that swaps libraries between frames therefore
    keeps painting the previous set on top of the new one -- six chips in a
    three-library matrix -- and every chip frame it produces is a lie. Flushing
    ``DeferredDelete`` explicitly is what the running app does for free.
    """
    from PyQt6.QtCore import QEvent, QCoreApplication

    for _ in range(3):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def populate(window) -> None:
    """Drive a ``MainWindow`` into the populated half of the matrix.

    Goes through the public View API only -- the same calls the presenter makes
    -- so a harness that quietly bypassed a signal path could not hide a
    regression.
    """
    window.set_libraries([_library(path, name) for path, name in LIBRARIES])
    window.set_current_library(CURRENT_LIBRARY)
    window.set_playlist_entries(build_entries())
    window.highlight_current_track(PLAYING_INDEX)
    window.update_track_info('Naima', 'Bill Evans', 'Kind of Blue')
    # No art bytes: the panel must fall back to ``resource/default_cover.png``,
    # which is exactly what checklist item 9 asks to see.
    window.update_album_art(None)
    window.set_playing_state(True)
    window.update_progress(POSITION, DURATION)
    window.set_volume(VOLUME)
    window.set_loop_mode(LOOP_MODE)


def _library(path: str, name: str):
    from core.config import LibraryConfig

    return LibraryConfig(path=path, name=name)


def empty(window) -> None:
    """The first-launch state: no libraries, no entries, no track."""
    window.set_libraries([])
    window.clear_playlist()
    window.clear_now_playing()
    window.reset_progress()
    window.set_playing_state(False)
    window.set_volume(VOLUME)
    window.set_loop_mode(LOOP_MODE)


def build_app():
    """The offscreen ``QApplication``, configured exactly like ``main_qt``.

    ``Fusion`` and the 11pt base font are set before the theme manager pushes
    its palette and sheet, because both are read at polish time; leaving the
    style out would render a matrix that no real run can reproduce.
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


def render_matrix(out_dir: Path, verbose: bool = True) -> List[Path]:
    """Write the eight PNGs into ``out_dir`` and return their paths.

    One window and one manager are re-used for the whole matrix, and the theme
    is switched through ``ThemeManager.set_mode`` -- the live path a user takes
    from the appearance dialog -- rather than by rebuilding the app per theme.
    A theme that only renders correctly on a cold start is a real bug, and this
    is the harness that would catch it.
    """
    from core.config import DEFAULT_THEME_MODE
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

        written: List[Path] = []
        for theme in THEMES:
            manager.set_mode(theme)
            for state in STATES:
                (populate if state == 'populated' else empty)(window)
                for (width, height) in SIZES:
                    window.resize(width, height)
                    window.show()
                    pump(app)
                    path = out_dir / f'{theme}_{state}_{width}x{height}.png'
                    window.grab().save(str(path))
                    written.append(path)
                    if verbose:
                        print(f'rendered {path}')
            window.hide()
        window.close()
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='Render the 8-frame PyPlayer theme matrix (light|dark x '
                    'empty|populated x 820x520|1100x720).')
    parser.add_argument('--out', type=Path, default=None,
                        help='Directory for the PNGs. Defaults to a temp '
                             'directory, whose path is printed.')
    parser.add_argument('--quiet', action='store_true',
                        help='Do not print each rendered file.')
    args = parser.parse_args(argv)

    out_dir = args.out or Path(tempfile.mkdtemp(prefix='pyplayer-matrix-'))
    written = render_matrix(out_dir, verbose=not args.quiet)
    if len(written) != len(THEMES) * len(STATES) * len(SIZES):
        print(f'Expected {len(THEMES) * len(STATES) * len(SIZES)} frames, '
              f'wrote {len(written)}', file=sys.stderr)
        return 1
    missing = [str(p) for p in written if not p.is_file() or p.stat().st_size == 0]
    if missing:
        print('Empty or missing frames: ' + ', '.join(missing), file=sys.stderr)
        return 1
    if not args.out:
        print(f'\nout: {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
