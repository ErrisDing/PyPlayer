#!/usr/bin/env python3
"""
PyPlayer Icon Pipeline

Turns the hand-authored SVG set in ``resource/icons`` into theme-coloured
``QIcon`` objects. Before this module the transport glyphs were five
``draw_*_icon`` QPainter polygon functions plus a rasteriser living in
``view/widgets/bottom_panel.py``, the loop and volume indicators were *text
characters* (``↺``, ``♪♪♪``) whose glyphs are not guaranteed on every platform,
and neither could be recoloured from the theme tokens -- so a dark mode could
keep a light-grey glyph (spec
``docs/superpowers/specs/2026-10-16-ui-batch1-theme-tokens-design.md`` §4.5).

Two pieces make the pipeline work:

* every SVG is authored on a ``viewBox="0 0 24 24"`` box with
  ``fill="currentColor"`` and no external references;
* :func:`icon` reads the file, substitutes ``currentColor`` with the caller's
  colour and rasterises the result at ``size * dpr``.

The substitution is why no icon can drift off-palette: the only colour in the
resources is a placeholder, so a glyph is as light/dark-correct as the token the
caller passed. The cost is that a theme flip has to reach the caller:
``ThemeManager.theme_changed`` -> ``BottomPanel.recolor`` and, since batch 2,
``ActionRail.recolor`` are the places those calls live.

Rendering goes through ``QSvgRenderer`` rather than ``QIcon(path)``: Qt's own
SVG icon engine has no colour hook, and a ``QIcon`` built from a file path would
therefore ignore the theme.
"""

from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from core.resource_utils import get_resource_path

# Batch 1's twelve transport glyphs: the play/pause/prev/next/stop row, the
# three loop states and the four volume levels -- every name
# ``view/widgets/bottom_panel.py`` asks for. This is *not* the shipped
# inventory, and says so rather than implying one: ``resource/icons`` holds 19
# files since batch 2 Task 3 added the seven rail glyphs (``file``, ``folder``,
# ``refresh``, ``refresh_all``, ``settings``, ``info``, ``add``), six of which
# the rail calls and none of which is listed here. Batch 2 authorises no
# further files -- Task 4 reuses ``add`` for its panel footer.
#
# Kept as the transport set (rather than extended to 19) because that is what it
# lists, because ``tests/test_icons.py`` carries its own literals on purpose
# (deriving them would make its comparison true by construction), and because an
# extended copy of the directory here would have nothing keeping it in sync --
# which is how this comment went stale in the first place. The inventory with a
# guard behind it is the directory itself:
# ``tests/test_icons.py::test_icon_names_are_the_shipped_files`` pins the disk
# against the union of both batches. Nothing in the product reads this constant;
# Tasks 4 and 7 should glob ``_ICON_SUBDIR`` if they need every name.
ICON_NAMES: tuple[str, ...] = (
    'play', 'pause', 'prev', 'next', 'stop',
    'loop_off', 'loop_all', 'loop_one',
    'volume_mute', 'volume_low', 'volume_mid', 'volume_high',
)

# Resource-relative location of one glyph. Resolved by ``get_resource_path``,
# the same helper that finds ``resource/default_cover.png``, so a frozen bundle
# (``.build/pyplayer.spec`` ships the whole ``resource`` directory) resolves the
# new subdirectory exactly like the existing resource does.
_ICON_SUBDIR = 'resource/icons'

# (name, colour, size, dpr) -> QIcon. The key has to carry every input: an icon
# cached without the colour in its key would hand a light glyph to a dark theme,
# which is the exact failure this pipeline exists to close.
_cache: dict[tuple[str, str, int, float], QIcon] = {}


def _icon_path(name: str) -> Path:
    """Absolute path of one glyph's SVG, dev or bundled."""
    return get_resource_path(f'{_ICON_SUBDIR}/{name}.svg')


def clear_cache() -> None:
    """Drop every cached ``QIcon``.

    Exposed for tests (a theme flip has to be observable as a *new* glyph, and a
    warm cache would hide that) and for a future screen-DPR change, where the
    1x sheets in the cache are the wrong resolution.
    """
    _cache.clear()


def icon(name: str, color: str, size: int, dpr: float = 1.0) -> QIcon:
    """Rasterise ``name`` in ``color`` at ``size`` logical pixels (``dpr`` scale).

    Args:
        name: stem of a file in ``resource/icons`` -- ``'play'`` for
            ``play.svg``. The directory, not :data:`ICON_NAMES`, is the
            inventory: that tuple lists batch 1's twelve transport glyphs, and
            the rail (batch 2 Task 3) calls six names it does not contain. An
            unknown stem takes the same downgrade as a missing file.
        color: ``#rrggbb`` -- a ``core.theme.ThemeTokens`` field, never a
            literal at the call site.
        size: logical (device-independent) pixels.
        dpr: device pixel ratio of the target screen; the sheet is rasterised at
            ``size * dpr`` and tagged, so a HiDPI display gets a sharp glyph
            instead of an upscaled 1x one.

    Returns:
        A cached ``QIcon`` holding one ``size * dpr`` sheet. A missing or
        unparseable resource returns ``QIcon()`` (``isNull()``) after one warning
        line on stdout: an icon set that stops drawing must not take the player
        down with it, but it must not be silent either.
    """
    size = max(1, int(size))
    dpr = float(dpr) if dpr and dpr > 0 else 1.0
    key = (name, color, size, dpr)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    rendered = _render(name, color, size, dpr)
    _cache[key] = rendered
    return rendered


def _render(name: str, color: str, size: int, dpr: float) -> QIcon:
    """Read, recolour and rasterise one glyph; ``QIcon()`` on any failure."""
    path = _icon_path(name)
    if not path.is_file():
        print(f'Warning: icon resource not found: {path}')
        return QIcon()

    try:
        svg = path.read_text(encoding='utf-8')
    except OSError as error:      # unreadable file == missing file, same downgrade
        print(f'Warning: icon {name} could not be read from {path}: {error}')
        return QIcon()

    if 'currentColor' not in svg:
        # An authored icon that hardcoded a colour would otherwise render
        # *correctly* forever and silently ignore every theme flip.
        print(f'Warning: icon {name} has no currentColor placeholder; '
              f'theme colours cannot reach it')

    renderer = QSvgRenderer(
        QByteArray(svg.replace('currentColor', color).encode('utf-8')))
    if not renderer.isValid():
        print(f'Warning: icon {name} is not valid SVG ({path}); '
              f'degrading to an empty icon')
        return QIcon()

    sheet = max(1, int(round(size * dpr)))
    pixmap = QPixmap(sheet, sheet)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # The target rect is in device pixels, and it has to stay explicit. A
        # rect in *logical* pixels paints the glyph into the top-left quarter of
        # a HiDPI sheet; omitting the rect is a no-op on Qt 6.11 -- QSvgRenderer
        # scales to the painter's viewport, measured 0 px of difference against
        # the explicit rect -- which is why ``tests/test_icons.py`` pins this call
        # site as well as the pixels it produces. ``render``'s return value is not
        # usable either: PyQt6 drops the C++ bool (verified on Qt 6.11, it is
        # always None), so ``isValid()`` above is the failure gate, as the brief
        # specifies.
        renderer.render(painter, QRectF(0, 0, sheet, sheet))
    finally:
        painter.end()

    # Tag after painting, not before: a painter on a DPR-tagged pixmap works in
    # logical coordinates, so the glyph lands offset and clipped against the edge
    # of the canvas instead of filling it (measured on Qt 6.11: at dpr 2 the ink
    # starts at 16 units and runs off 23.5).
    pixmap.setDevicePixelRatio(dpr)

    result = QIcon()
    result.addPixmap(pixmap)
    return result
