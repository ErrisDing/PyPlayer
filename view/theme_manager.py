#!/usr/bin/env python3
"""
PyPlayer Theme Manager

The single consumer of the theme layer and the only place in the app allowed
to push an application-wide style sheet and palette. Before this
module, styling came from three sources at once -- the global
``view/resources/styles.qss``, per-widget inline sheets, and colours
hardcoded in the playlist delegate/model -- which is why the progress slider
and the volume slider rendered differently side by side (A1) and why macOS dark
mode was half-light (A2). Both old sources are gone; this manager is the
replacement:

    main.py -> ThemeManager(mode, alphas).apply_to(app) -> widgets read tokens

``apply_to`` emits :func:`core.theme_qss.build_qss` for the widget tree *and*
installs a ``QPalette`` built from the same tokens. The palette is not
optional: Fusion reads it for the parts QSS cannot reach (menu arrows,
scrollbar slots, dialog chrome, item-view text when a rule sets no colour),
so sheet-only theming is exactly the half-light failure this layer exists to
close.

Modes are ``'auto'`` / ``'light'`` / ``'dark'`` and resolution lives in
:func:`core.theme.resolve`, so an unrecognised preference raises ``ValueError``
by design rather than silently rendering the wrong theme. That makes startup a
contract point: ``main.py`` catches it at the seam and falls back to ``'auto'``
(see ``build_theme_manager``).

Signal flow for a live theme change:

    set_mode / set_alpha / system flip
        -> palette + QSS re-pushed to the application
        -> ``theme_changed(tokens)``
        -> ``MainWindow.recolor`` -> bottom-panel icons + playlist repaint + scrim

The three alphas are the user's appearance sliders. ``playlist`` and
``controls`` are colours in the sheet, so they need a rebuild; ``overlay`` is
the scrim the main window paints itself, so it only needs a repaint (see
:meth:`ThemeManager.set_alpha`).
"""

from dataclasses import replace
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPalette

from core.theme import AlphaSettings, ThemeTokens, resolve
from core.theme_qss import build_qss

# ``QStyleHints.colorScheme().name`` values ``resolve`` understands. Anything
# else -- a future Qt enum member, a platform that reports something odd -- is
# treated as ``'Unknown'`` (which ``resolve`` maps to LIGHT) so a scheme name
# can never become a startup exception.
_KNOWN_SCHEMES = frozenset({'Dark', 'Light', 'Unknown'})


def _clamp_unit(value: float) -> float:
    """Squeeze a 0.0-1.0 setting into 0.0-1.0; never raise on a bad config."""
    return min(1.0, max(0.0, float(value)))


class ThemeManager(QObject):
    """Owns the application palette and stylesheet for one theme mode.

    Args:
        mode: ``'auto'``, ``'light'`` or ``'dark'``. Resolved eagerly, so a
            bad value raises here (at the ``main.py`` seam) instead of on the
            first paint.
        alphas: The user's transparency settings; defaults to
            :class:`core.theme.AlphaSettings` (i.e. ``AppearanceDefaults``).
    """

    # Emitted with the new ``ThemeTokens`` after every palette/stylesheet push
    # and after every alpha change. ``MainWindow.recolor`` is the subscriber.
    theme_changed = pyqtSignal(object)

    #: The alpha keys the manager accepts: exactly the three fields of
    #: :class:`core.theme.AlphaSettings`, i.e. the three appearance sliders.
    ALPHA_KEYS = ('overlay', 'playlist', 'controls')

    def __init__(
        self,
        mode: str = 'auto',
        alphas: Optional[AlphaSettings] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._alphas = alphas if alphas is not None else AlphaSettings()
        self._app = None
        self._system_scheme = 'Unknown'
        self._watched_hints = None
        # Fail fast: ``main.py`` catches ValueError here and falls back to auto.
        self._tokens = resolve(mode, self._system_scheme)

    # === Public API ===

    @property
    def tokens(self) -> ThemeTokens:
        """The ``LIGHT``/``DARK`` token set currently in force."""
        return self._tokens

    @property
    def alphas(self) -> AlphaSettings:
        """Current transparency settings (an immutable snapshot)."""
        return self._alphas

    @property
    def mode(self) -> str:
        """``'auto'``, ``'light'`` or ``'dark'`` as configured."""
        return self._mode

    def apply_to(self, app) -> None:
        """Install the palette and the generated stylesheet on ``app``.

        Also subscribes to ``QStyleHints.colorSchemeChanged`` when the platform
        provides it, which is what makes ``'auto'`` follow a live OS flip.
        Idempotent: calling it twice re-pushes the style without double-
        connecting the system-scheme slot.
        """
        self._app = app
        self._system_scheme = self._system_scheme_of(app)
        self._tokens = resolve(self._mode, self._system_scheme)
        self._push_palette()
        self._push_stylesheet()
        self._watch_system_scheme(app)
        self.theme_changed.emit(self._tokens)

    def set_mode(self, mode: str) -> None:
        """Switch theme mode; ``ValueError`` for anything but auto/light/dark.

        Resolution happens before any state is written, so a rejected mode
        leaves the running theme untouched.
        """
        tokens = resolve(mode, self._system_scheme)
        self._mode = mode
        self._tokens = tokens
        self._push_palette()
        self._push_stylesheet()
        self.theme_changed.emit(self._tokens)

    def set_alpha(self, which: str, value: float) -> None:
        """Update one transparency setting and re-style.

        ``ValueError`` for an unknown ``which``, matching
        :func:`core.theme.resolve` (deviation from the brief's ``KeyError``,
        per controller ruling R2 -- ``dataclasses.replace`` would have raised
        ``TypeError`` instead, which is neither). Values are clamped to
        0.0-1.0 rather than raised on: a bad ``settings.json`` entry must not
        be able to produce an invalid colour or an unstartable app.
        """
        if which not in self.ALPHA_KEYS:
            raise ValueError(
                f'Unknown alpha key: {which!r} '
                f'(expected one of {", ".join(self.ALPHA_KEYS)})'
            )
        self._alphas = replace(self._alphas, **{which: _clamp_unit(value)})
        if which != 'overlay':
            # overlay is the scrim the main window paints, not a sheet colour,
            # so the sheet does not have to be rebuilt for it.
            self._push_stylesheet()
        self.theme_changed.emit(self._tokens)

    # === System scheme ===

    def _on_system_scheme_changed(self, scheme) -> None:
        """React to an OS light/dark flip, but only while in ``'auto'``."""
        if self._mode != 'auto':
            return
        name = getattr(scheme, 'name', None) or str(scheme)
        if name not in _KNOWN_SCHEMES:
            name = 'Unknown'
        if name == self._system_scheme:
            return
        self._system_scheme = name
        self._tokens = resolve(self._mode, name)
        self._push_palette()
        self._push_stylesheet()
        self.theme_changed.emit(self._tokens)

    @staticmethod
    def _system_scheme_of(app) -> str:
        """``QColorScheme.name`` of the running platform, or ``'Unknown'``.

        ``QStyleHints.colorScheme`` is Qt 6.5+ and is not implemented by every
        QPA plugin (offscreen reports ``Unknown``), so an absent or failing
        accessor is a normal path, not an error.
        """
        try:
            name = app.styleHints().colorScheme().name
        except (AttributeError, TypeError):
            return 'Unknown'
        return name if name in _KNOWN_SCHEMES else 'Unknown'

    def _watch_system_scheme(self, app) -> None:
        """Connect ``colorSchemeChanged`` when the platform has it."""
        hints = app.styleHints()
        if not hasattr(hints, 'colorSchemeChanged'):
            self._watched_hints = None
            return
        if hints is self._watched_hints:
            return        # already watching this QStyleHints
        hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self._watched_hints = hints

    # === Style push ===

    def _push_palette(self) -> None:
        if self._app is not None:
            self._app.setPalette(self._build_palette(self._tokens))

    def _push_stylesheet(self) -> None:
        if self._app is not None:
            # The one stylesheet call site in the product (asserted by
            # tests/test_theme_manager.py and the grep step of the task).
            self._app.setStyleSheet(build_qss(self._tokens, self._alphas))

    @staticmethod
    def _build_palette(tokens: ThemeTokens) -> QPalette:
        """Map the semantic tokens onto the ``QPalette`` roles Fusion reads.

        Every colour comes from ``tokens``; nothing here is a literal. Roles
        are set for all colour groups first (``setColor`` with a role only
        touches Active/Inactive/Disabled alike), then the ``Disabled`` group is
        overridden with the ``button_disabled_*`` pair, so disabled items in
        the list views and menus grey out to the palette instead of to the
        platform default.
        """
        palette = QPalette()

        def set_all(role: QPalette.ColorRole, hex_color: str) -> None:
            palette.setColor(role, QColor(hex_color))

        set_all(QPalette.ColorRole.Window, tokens.window_bg)
        set_all(QPalette.ColorRole.WindowText, tokens.text_primary)
        set_all(QPalette.ColorRole.Base, tokens.surface)
        set_all(QPalette.ColorRole.AlternateBase, tokens.surface_alt)
        set_all(QPalette.ColorRole.Text, tokens.text_primary)
        set_all(QPalette.ColorRole.Button, tokens.button_bg)
        set_all(QPalette.ColorRole.ButtonText, tokens.text_primary)
        set_all(QPalette.ColorRole.Highlight, tokens.accent)
        set_all(QPalette.ColorRole.HighlightedText, tokens.text_on_accent)
        set_all(QPalette.ColorRole.ToolTipBase, tokens.tooltip_bg)
        set_all(QPalette.ColorRole.ToolTipText, tokens.tooltip_text)
        set_all(QPalette.ColorRole.PlaceholderText, tokens.text_muted)
        # ``Link`` is the one role with no dedicated token: ``accent`` is the
        # only colour in the set with a checked ``surface`` background (4.60:1
        # LIGHT / 6.91:1 DARK), and the old darwin-only palette used a plain
        # blue here too.
        set_all(QPalette.ColorRole.Link, tokens.accent)

        disabled = QPalette.ColorGroup.Disabled
        palette.setColor(disabled, QPalette.ColorRole.Window,
                         QColor(tokens.button_disabled_bg))
        palette.setColor(disabled, QPalette.ColorRole.WindowText,
                         QColor(tokens.button_disabled_text))
        palette.setColor(disabled, QPalette.ColorRole.Base,
                         QColor(tokens.button_disabled_bg))
        palette.setColor(disabled, QPalette.ColorRole.AlternateBase,
                         QColor(tokens.button_disabled_bg))
        palette.setColor(disabled, QPalette.ColorRole.Text,
                         QColor(tokens.button_disabled_text))
        palette.setColor(disabled, QPalette.ColorRole.Button,
                         QColor(tokens.button_disabled_bg))
        palette.setColor(disabled, QPalette.ColorRole.ButtonText,
                         QColor(tokens.button_disabled_text))
        palette.setColor(disabled, QPalette.ColorRole.Highlight,
                         QColor(tokens.button_disabled_bg))
        palette.setColor(disabled, QPalette.ColorRole.HighlightedText,
                         QColor(tokens.button_disabled_text))
        return palette
