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
caller passed, and ``ThemeManager.theme_changed`` -> ``BottomPanel.recolor`` is
the one place those calls live.

Rendering goes through ``QSvgRenderer`` rather than ``QIcon(path)``: Qt's own
SVG icon engine has no colour hook, and a ``QIcon`` built from a file path would
therefore ignore the theme.
"""

from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from core.resource_utils import get_resource_path

# The set, as the brief pins it. Kept here for callers that want to enumerate
# the glyphs (``tests/test_icons.py`` deliberately carries its own literal, so a
# rename on either side fails a test instead of following itself).
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
        name: one of :data:`ICON_NAMES`.
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
        # The target rect is in device pixels: passing None would paint the
        # renderer's own 24 px default into the corner of a larger sheet and
        # leave the rest transparent. ``render``'s return value is not usable --
        # PyQt6 drops the C++ bool (verified on Qt 6.11: it is always None), so
        # ``isValid()`` above is the failure gate, as the brief specifies.
        renderer.render(painter, QRectF(0, 0, sheet, sheet))
    finally:
        painter.end()

    # Tag after painting, not before: a painter on a DPR-tagged pixmap works in
    # logical coordinates, which would fill only the top-left quarter of the
    # sheet.
    pixmap.setDevicePixelRatio(dpr)

    result = QIcon()
    result.addPixmap(pixmap)
    return result
