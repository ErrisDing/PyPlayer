#!/usr/bin/env python3
"""
Playlist Item Delegate - Custom rendering for playlist items
Displays file name with relative position in gray on the right
"""

from typing import Optional
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QModelIndex, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from view.models.playlist_model import PlaylistModel


class PlaylistItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for playlist items.

    Renders:
    - File name on the left (normal color)
    - Relative position on the right (gray, semi-transparent)
    - File name overlays position when space is limited
    """

    # Colors - semi-transparent gray for position
    GRAY_COLOR = QColor(136, 136, 136, 160)  # #888888 with alpha

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        """Custom paint method for playlist items."""
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
            painter.fillRect(option.rect, PlaylistModel.PLAYING_BG_COLOR)
        elif option.state & QStyle.StateFlag.State_Selected:
            # Selected item background
            painter.fillRect(option.rect, QColor(227, 242, 253))  # #e3f2fd

        # Calculate text rectangle (with padding)
        text_rect = option.rect.adjusted(5, 0, -5, 0)

        # Set font
        font = QFont(option.font)
        if is_folder:
            font.setBold(True)
        painter.setFont(font)

        # Set text color
        if is_folder:
            painter.setPen(PlaylistModel.FOLDER_COLOR)
        else:
            painter.setPen(option.palette.text().color())

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

        # Draw relative position first (in gray, semi-transparent) - on the right
        painter.setPen(self.GRAY_COLOR)
        position_rect = QRect(text_rect)
        position_rect.setLeft(text_rect.right() - position_width)
        painter.drawText(position_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, position_text)

        # Draw file name on top (may overlay the position if needed)
        # Reset text color for file name
        painter.setPen(option.palette.text().color())

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
