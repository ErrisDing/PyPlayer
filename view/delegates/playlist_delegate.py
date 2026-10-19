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

    This method, not ``QStyle``, owns every pixel of the row, so the sheet has
    no ``#playlistView::item`` rule at all (see the note in
    ``core/theme_qss.py``): anything written there would be parsed and then
    thrown away. The row's own geometry tokens -- ``ROW_HEIGHT``, ``SPACE_2``
    and ``divider`` -- are therefore consumed here.

    Paint order (Task 9, audit A5/D1, plus the row divider), each layer in full:

    1. Background: ``playing_bg`` on the playing row, else ``selection_bg``
       when selected, else ``hover_bg`` when the cursor is on this row --
       playing wins over selection so the playing row never looks merely
       selected, and both win over hover (batch 3, C2, spec §4.1). The three
       are an ``elif`` chain, never painted on top of each other.
    2. 1px ``divider`` along the bottom edge of the row: the only thing that
       separates two rows that are neither selected nor playing.
    3. A 3px ``playing_bar`` strip down the left edge of the playing row, drawn
       *over* the divider so the marker stays unbroken where the two meet.
    4. The file name, left-aligned at ``SPACE_2`` from the row edge:
       ``playing_text`` on the playing row, ``text_primary`` elsewhere; folder
       rows bold.
    5. ``[relative_position]`` on the right in ``text_muted``, at ``SPACE_2``
       from the right edge. The name's available width already excludes the
       position plus one ``SPACE_2`` before eliding, so the two can never
       collide in a narrow window (and the muted text is the contrast-checked
       token, not the old ``QColor(136,136,136,160)``).

    The hover fill is layer 1's third branch and lives here because nothing else
    can paint it: a ``#playlistView::item:hover`` rule in the sheet is parsed and
    discarded for a view whose delegate overrides ``paint()`` (the batch 2 audit
    finding this batch is not allowed to repeat). The alternating row tint, by
    contrast, is *not* painted by this class: ``PlaylistView`` asks ``QListView``
    for alternating rows and the view fills them from the palette's
    ``AlternateBase`` (mapped to ``surface_alt`` by ``ThemeManager``, measured
    ``#f5f5f5`` on odd rows in the render matrix), which is why the layers below
    are drawn over a band that is already tinted -- and why a hovered odd row
    reads as ``hover_bg`` laid over that tint, not as a blend of the two.

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
        height is taken from here. The delegate owns the row and the sheet sets
        no ``::item`` rule (not even ``height``), so this is the only place the
        row height exists.
        (Pinned by tests/test_theme_manager.py.)
        """
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        """Custom paint method for playlist items.

        Layers in the order the class docstring lists: background, divider,
        playing bar, text, then the right-aligned position.
        """
        tokens = self._manager.tokens

        # Get data from model
        display_text = index.data(Qt.ItemDataRole.DisplayRole)
        relative_position = index.data(PlaylistModel.RelativePositionRole)
        is_folder = index.data(PlaylistModel.IsFolderRole)
        is_playing = index.data(PlaylistModel.IsPlayingRole)

        # Save painter state
        painter.save()

        # 1. Background: playing wins over selection, and selection wins over
        # hover (spec §4.1). A playing row that is also selected still reads as
        # "playing", not "just selected" (A5); a hovered row that is playing or
        # selected keeps *its* tint, because hover is the weakest of the three
        # states and they must never stack. ``State_MouseOver`` reaches this
        # branch only because ``PlaylistView`` gives the list view's viewport
        # ``Qt.WidgetAttribute.WA_Hover`` -- measured on this host, without that
        # attribute ``QListView`` never sets the bit for any row, and the branch
        # below would be dead code (the same shape as batch 2's dead ``::item``
        # rule, which is why the hover test asserts the bit as well as the pixel).
        if is_playing:
            painter.fillRect(option.rect, QColor(tokens.playing_bg))
        elif option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(tokens.selection_bg))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(tokens.hover_bg))

        # 2. Row divider: the bottom pixel of the row in ``divider``. This is
        # the layer that makes the "separates two rows that are neither selected
        # nor playing" claim above true -- and it has to be painted here because
        # a ``::item`` border-bottom in the sheet is never drawn for a view whose
        # delegate overrides ``paint()`` (whole-branch review finding 4: 0 pixels
        # of ``divider`` in a live ``#playlistView`` viewport, against 956 in the
        # delegate-less library list).
        divider = QRect(option.rect)
        divider.setTop(divider.bottom())
        painter.fillRect(divider, QColor(tokens.divider))

        # 3. Left 3px bar on the playing row only -- the second, orthogonal
        # cue for "playing", readable even where the tint washes out. Painted
        # after the divider so the marker is not notched by it at the row's
        # bottom edge.
        if is_playing:
            bar = QRect(option.rect)
            bar.setWidth(PLAYING_BAR_WIDTH)
            painter.fillRect(bar, QColor(tokens.playing_bar))

        # Text rectangle: ``SPACE_2`` in from each edge -- the inset the sheet's
        # deleted ``::item`` padding used to claim, now actually applied. It
        # clears the 3px bar, so the name never collides with the marker, and it
        # keeps the right-hand position read-out off the viewport border.
        text_rect = option.rect.adjusted(SPACE_2, 0, -SPACE_2, 0)

        # 4. Font and the row's own text colour (playing rows take
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

        # 5. Position on the right, name on the left. The name's available
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
