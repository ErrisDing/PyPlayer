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

from core.theme import ROW_HEIGHT
from view.models.playlist_model import PlaylistModel


class PlaylistItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for playlist items.

    Renders:
    - File name on the left (normal color)
    - Relative position on the right (gray, semi-transparent)
    - File name overlays position when space is limited
    - Row height from the shared ``ROW_HEIGHT`` token

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
        """Custom paint method for playlist items."""
        tokens = self._manager.tokens

        # Get data from model
        display_text = index.data(Qt.ItemDataRole.DisplayRole)
        relative_position = index.data(PlaylistModel.RelativePositionRole)
        is_folder = index.data(PlaylistModel.IsFolderRole)
        is_playing = index.data(PlaylistModel.IsPlayingRole)

        # Save painter state
        painter.save()

        # Draw background
        if is_playing:
            # Playing track background
            painter.fillRect(option.rect, QColor(tokens.playing_bg))
        elif option.state & QStyle.StateFlag.State_Selected:
            # Selected item background
            painter.fillRect(option.rect, QColor(tokens.selection_bg))

        # Calculate text rectangle (with padding)
        text_rect = option.rect.adjusted(5, 0, -5, 0)

        # Set font
        font = QFont(option.font)
        if is_folder:
            font.setBold(True)
        painter.setFont(font)

        # Set text color
        painter.setPen(QColor(tokens.text_primary))

        # If no relative position, just draw the display text
        if not relative_position or is_folder:
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           self._elide_text(display_text, font, text_rect.width()))
            painter.restore()
            return

        # Calculate widths
        metrics = QFontMetrics(font)

        # Format position text with square brackets
        position_text = f"[{relative_position}]"
        position_width = metrics.horizontalAdvance(position_text)
        file_name_width = metrics.horizontalAdvance(display_text)

        # Space between file name and position
        spacing = 8
        total_width = text_rect.width()

        # Draw relative position first (muted, on the right) - the token is the
        # contrast-checked one, so it stays legible on playing_bg too.
        painter.setPen(QColor(tokens.text_muted))
        position_rect = QRect(text_rect)
        position_rect.setLeft(text_rect.right() - position_width)
        painter.drawText(position_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, position_text)

        # Draw file name on top (may overlay the position if needed)
        # Reset text color for file name
        painter.setPen(QColor(tokens.text_primary))

        if file_name_width + position_width + spacing <= total_width:
            # Everything fits - draw full file name
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, display_text)
        else:
            # Not enough space - file name overlays position (no truncation on position)
            # Elide file name to fit total width
            file_name = self._elide_text(display_text, font, total_width)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, file_name)

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
