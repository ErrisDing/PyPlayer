#!/usr/bin/env python3
"""
PyPlayer Now Playing Strip

The control bar's cover-plus-two-lines read-out (batch 2 spec §2, §3.2): the
48 px thumbnail and the title/artist pair that used to occupy the 200 px box at
the top of the left panel, now at the left end of the bottom bar because the left
panel is gone.

**The cover pipeline is a move, not a rewrite.** :meth:`update_album_art`,
:meth:`_clear_art` and :meth:`_load_default_cover` were copied verbatim out of
the batch-1 left-panel file -- which batch 2 Task 9 then deleted, so this is the
only copy left -- the substitution being only the size they scale to
(``self.ART_SIZE`` -> :data:`core.theme.STRIP_ART_SIZE`). That block is
batch-1-tested code: PIL first with a LANCZOS thumbnail, an explicit ``QImage``
construction per colour mode (RGBA/RGB, everything else converted to RGB), a
Qt-only fallback when Pillow is missing, and *any* exception landing on the
default cover. Re-deriving it would have quietly dropped the colour-mode handling
and the ``devicePixelRatio`` behaviour it already has, which is why it was
duplicated rather than rewritten for the one task the two files coexisted.

Two deliberate differences from the panel this replaced:

* **One line, so no album.** ``album`` stays in :meth:`update_track_info`'s
  signature because the presenter already passes three arguments and spec §4
  promises not to change that call site, but the strip does not render it. The bar
  is one row taller than the transport buttons: a third line of text would either
  grow the bar past the control row or squeeze the title into two lines, and album
  is a *column* in batch 4's list structure, where it can be sorted and compared.
  Dropping the argument here is the cheaper half of that decision; the copy
  (``metadata.unknown_album``) stays unused for the same batch-1 reason the artist
  placeholder does.
* **Eliding is the widget's job.** A ``QLabel`` with word wrap off reports its full
  text as the minimum size hint, so an 80-character title would have taken the
  window's minimum width with it. Both labels therefore size-policy ``Ignored``
  horizontally and re-elide against their own width on every resize, keeping the
  whole string in the tooltip.
"""

import io
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from core import i18n
from core.resource_utils import get_resource_path
from core.theme import SPACE_1, SPACE_2, STRIP_ART_SIZE

DEFAULT_COVER_PATH = get_resource_path("resource/default_cover.png")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class NowPlayingStrip(QWidget):
    """Cover thumbnail plus title and artist, in one row of the control bar.

    Unlike :class:`view.widgets.action_rail.ActionRail` this widget draws no
    token-coloured glyph, so it needs no theme manager: every colour it can wear
    is emitted by ``core/theme_qss.py`` under
    ``#nowPlayingStrip`` / ``#stripArt`` / ``#stripTitle`` / ``#stripArtist``.

    Args:
        parent: Standard Qt parent. Task 7 puts the strip at the left end of
            :class:`view.widgets.bottom_panel.BottomPanel`.
    """

    # Class-level cache for default cover
    _default_pixmap: Optional[QPixmap] = None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title_text = ''
        self._artist_text = ''
        self._load_default_cover()
        self._setup_ui()

    @classmethod
    def _load_default_cover(cls) -> None:
        """Load and cache the default cover image."""
        if cls._default_pixmap is not None:
            return

        if DEFAULT_COVER_PATH.exists():
            cls._default_pixmap = QPixmap(str(DEFAULT_COVER_PATH))
            if cls._default_pixmap.isNull():
                cls._default_pixmap = None
                print(f"Warning: Failed to load default cover from {DEFAULT_COVER_PATH}")
        else:
            print(f"Warning: Default cover not found at {DEFAULT_COVER_PATH}")

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        # The strip is transparent so the control bar's own composited fill shows
        # through it -- ``core/theme_qss.py`` gives it no background token, and
        # ``tests/test_theme_qss.py::MainWindowFillTest`` pins that.
        self.setObjectName("nowPlayingStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_2)

        self._art_label = QLabel()
        self._art_label.setObjectName("stripArt")
        self._art_label.setFixedSize(STRIP_ART_SIZE, STRIP_ART_SIZE)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A7, verbatim from the panel: the initial state goes through the same
        # path ``clear()`` does, so first launch and stopped playback match.
        self._clear_art()
        layout.addWidget(self._art_label)

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(SPACE_1)

        self._title_label = QLabel(i18n.get('metadata.no_track'))
        self._title_label.setObjectName("stripTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter |
                                       Qt.AlignmentFlag.AlignLeft)
        self._ignore_width(self._title_label)
        info_layout.addWidget(self._title_label)

        self._artist_label = QLabel("")
        self._artist_label.setObjectName("stripArtist")
        self._artist_label.setAlignment(Qt.AlignmentFlag.AlignVCenter |
                                        Qt.AlignmentFlag.AlignLeft)
        self._ignore_width(self._artist_label)
        info_layout.addWidget(self._artist_label)

        layout.addLayout(info_layout, 1)

    @staticmethod
    def _ignore_width(label: QLabel) -> None:
        """Let a label be narrower than its text, so elision is possible at all.

        ``QSizePolicy.Ignored`` is what makes ``minimumSizeHint`` stop reporting the
        full string: without it a 80-character title would push the bar's minimum
        width past the window, and the window -- not the label -- would do the
        clipping.
        """
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setWordWrap(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        """Re-fit both lines to the space the strip actually has."""
        if self.width() <= 0:
            return
        margins = self.layout().contentsMargins()
        available = (self.width() - margins.left() - margins.right()
                     - STRIP_ART_SIZE - self.layout().spacing())
        if available <= 0:
            return
        for label, text in ((self._title_label, self._title_text),
                            (self._artist_label, self._artist_text)):
            elided = label.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, available)
            if elided != label.text():
                # Guard, not tidiness: setText invalidates the layout, which can
                # resize the strip and land straight back here.
                label.setText(elided)

    def update_track_info(self, title: str, artist: str = "", album: str = "") -> None:
        """Update the track information display.

        Args:
            title: Track title; an empty one falls back to ``metadata.unknown_title``
                exactly as the panel did.
            artist: Artist name. Empty stays empty -- batch 1 ruled that
                ``metadata.unknown_artist`` would be new behaviour §4.6 never asked
                for, and a bottom bar has even less room for a guess than the panel
                had.
            album: Accepted and **not rendered**. One row of 48 px holds two lines
                of ``FONT_SIZE_SM``/``FONT_SIZE_MD`` text; a third would either
                grow the control bar past the transport row or wrap the title. Album
                belongs in batch 4's playlist columns, where it can be compared with
                other albums instead of being read one track at a time. The argument
                stays because spec §4 keeps ``MainWindow.update_track_info``'s call
                site unchanged.

        The tooltip carries the un-elided strings for both lines, which is what
        makes an elided title "elided, not clipped".
        """
        self._title_text = title if title else i18n.get('metadata.unknown_title')
        self._artist_text = artist if artist else ""
        self._title_label.setToolTip(self._title_text)
        self._artist_label.setToolTip(self._artist_text)
        self._apply_elision()

    def update_album_art(self, art_data: Optional[bytes]) -> None:
        """
        Update album art from raw image data.

        Args:
            art_data: Raw image bytes (PNG, JPEG, etc.) or None for placeholder
        """
        if not art_data:
            self._clear_art()
            return

        try:
            # Use PIL for better image handling
            if PIL_AVAILABLE:
                image = Image.open(io.BytesIO(art_data))
                # Resize to fit while maintaining aspect ratio
                image.thumbnail((STRIP_ART_SIZE, STRIP_ART_SIZE), Image.Resampling.LANCZOS)

                # Convert to Qt format
                if image.mode == 'RGBA':
                    data = image.tobytes('raw', 'RGBA')
                    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888)
                elif image.mode == 'RGB':
                    data = image.tobytes('raw', 'RGB')
                    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGB888)
                else:
                    image = image.convert('RGB')
                    data = image.tobytes('raw', 'RGB')
                    qimage = QImage(data, image.width, image.height, QImage.Format.Format_RGB888)

                pixmap = QPixmap.fromImage(qimage)
            else:
                # Fallback to Qt-only
                pixmap = QPixmap()
                pixmap.loadFromData(art_data)

                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        STRIP_ART_SIZE, STRIP_ART_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )

            if not pixmap.isNull():
                self._art_label.setPixmap(pixmap)
            else:
                self._clear_art()

        except Exception as e:
            print(f"Error loading album art: {e}")
            self._clear_art()

    def _clear_art(self) -> None:
        """Clear album art and show default cover or placeholder."""
        if self._default_pixmap and not self._default_pixmap.isNull():
            # Scale the default cover to fit
            scaled = self._default_pixmap.scaled(
                STRIP_ART_SIZE, STRIP_ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._art_label.setPixmap(scaled)
        else:
            # No default cover on disk: the *text* placeholder is the last
            # resort, and it comes from i18n like everything else. #stripArt's
            # sheet rule paints the box, so no stylesheet is re-applied here.
            self._art_label.clear()
            self._art_label.setText(i18n.get('now_playing.no_art'))

    def clear(self) -> None:
        """Clear all display -- same path as the initial state (A7)."""
        self.update_track_info(i18n.get('metadata.no_track'), "", "")
        self._clear_art()

    def recolor(self, tokens) -> None:
        """Forward hook for ``MainWindow.recolor`` (Task 7).

        The strip re-rasterises nothing: the cover is a file on disk or bytes from
        the metadata service, and both labels and the box are coloured by the
        application sheet. ``tokens`` is therefore unread here -- the method exists
        so Task 7 can forward ``theme_changed`` to every batch-2 widget with one
        call shape (``ActionRail.recolor``, ``LibrarySidebar.recolor``), and the
        repaint keeps that uniform even if the strip starts drawing a token colour
        of its own.
        """
        self._art_label.update()
