#!/usr/bin/env python3
"""
Playlist Item Delegate - Custom rendering for playlist items
Displays file name with relative position in gray on the right

Presentation lives here since Task 6: ``PlaylistModel`` answers data roles
only, and every colour is read from the theme manager's tokens at paint time,
so a live theme flip repaints without touching the model.
"""

from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QModelIndex, QRect, QPoint, QSize
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.theme import ROW_HEIGHT, SPACE_2
from view.models.playlist_model import PlaylistModel


# Width of the playing-row left marker (px). ``playing_bar`` is the accent-
# family token reserved for "this row is the one that sounds" -- 3px because a
# background tint alone (Task 6) was indistinguishable from the selection
# tint at a glance (audit A5).
PLAYING_BAR_WIDTH = 3


class PlaylistItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for playlist items.

    Paint order (Task 9, audit A5/D1), each layer in full:

    1. Background: ``playing_bg`` on the playing row, else ``selection_bg``
       when selected -- playing wins over selection so the playing row never
       looks merely selected.
    2. A 3px ``playing_bar`` strip down the left edge of the playing row.
    3. The file name, left-aligned: ``playing_text`` on the playing row,
       ``text_primary`` elsewhere; folder rows bold.
    4. ``[relative_position]`` on the right in ``text_muted``. The name's
       available width already excludes the position plus ``SPACE_2`` before
       eliding, so the two can never collide in a narrow window (and the
       muted text is the contrast-checked token, not the old
       ``QColor(136,136,136,160)``).

    Hover background is batch 3 (C2) and deliberately absent here.

    Row height comes from the shared ``ROW_HEIGHT`` token via ``sizeHint``.

    The manager is held by reference, never cached into colours: ``paint``
    reads ``self._manager.tokens`` every time, which is what makes
    ``ThemeManager.set_mode`` reach the list without a model reset.
    """

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        """One ``ROW_HEIGHT`` tall, full-width.

        The width is deliberately 0: ``QListView`` defaults to
        ``ResizeMode.Fixed``, so the item rect spans the viewport and only the
        height is taken from here. The generated sheet sets the item padding
        and divider but never ``height``, which is why the delegate has to.
        (Pinned by tests/test_theme_manager.py.)
        """
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        """Custom paint method for playlist items.

        Layers in the order the class docstring lists: backgrounds, playing
        bar, text, then the right-aligned position.
        """
        tokens = self._manager.tokens

        # Get data from model
        display_text = index.data(Qt.ItemDataRole.DisplayRole)
        relative_position = index.data(PlaylistModel.RelativePositionRole)
        is_folder = index.data(PlaylistModel.IsFolderRole)
        is_playing = index.data(PlaylistModel.IsPlayingRole)

        # Save painter state
        painter.save()

        # 1. Background: playing wins over selection, so a playing row that is
        # also selected still reads as "playing", not "just selected" (A5).
        if is_playing:
            painter.fillRect(option.rect, QColor(tokens.playing_bg))
        elif option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(tokens.selection_bg))

        # 2. Left 3px bar on the playing row only -- the second, orthogonal
        # cue for "playing", readable even where the tint washes out.
        if is_playing:
            bar = QRect(option.rect)
            bar.setWidth(PLAYING_BAR_WIDTH)
            painter.fillRect(bar, QColor(tokens.playing_bar))

        # Text rectangle: the row's existing 5px left padding already clears
        # the 3px bar, so the name never collides with the marker.
        text_rect = option.rect.adjusted(5, 0, -5, 0)

        # 3. Font and the row's own text colour (playing rows take
        # playing_text; folders stay text_primary but bold).
        font = QFont(option.font)
        if is_folder:
            font.setBold(True)
        painter.setFont(font)
        text_colour = tokens.playing_text if is_playing else tokens.text_primary

        # Folder rows and rows without a relative position: name only.
        if not relative_position or is_folder:
            painter.setPen(QColor(text_colour))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self._elide_text(display_text, font, text_rect.width()))
            painter.restore()
            return

        # 4. Position on the right, name on the left. The name's available
        # width is computed *before* eliding and already excludes the
        # position plus one SPACE_2 of breathing room, so a long name gets
        # an ellipsis instead of painting over the muted path (the old
        # overlay behaviour).
        metrics = QFontMetrics(font)
        position_text = f"[{relative_position}]"
        position_width = metrics.horizontalAdvance(position_text)

        available = max(0, text_rect.width() - position_width - SPACE_2)
        painter.setPen(QColor(text_colour))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self._elide_text(display_text, font, available))

        # ``text_muted`` replaces the old ``QColor(136,136,136,160)``: the
        # token is the one the 4.5:1 text guard in tests/test_theme.py
        # measured against playing_bg/selection_bg, and it is opaque.
        painter.setPen(QColor(tokens.text_muted))
        position_rect = QRect(text_rect)
        position_rect.setLeft(text_rect.right() - position_width)
        painter.drawText(position_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         position_text)

        # Restore painter state
        painter.restore()

    def _elide_text(self, text: str, font: QFont, max_width: int) -> str:
        """Elide text if it exceeds max_width."""
        if not text:
            return ""

        metrics = QFontMetrics(font)
        if metrics.horizontalAdvance(text) <= max_width:
            return text

        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_width)
