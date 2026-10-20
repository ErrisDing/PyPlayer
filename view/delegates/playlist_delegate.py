#!/usr/bin/env python3
"""
Playlist Item Delegate - Custom rendering for playlist items
Displays file name with relative position, then the three metadata columns

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

from core import i18n
from core.theme import (
    COLUMN_DURATION_WIDTH,
    COLUMN_TEXT_WIDTH,
    ROW_HEIGHT,
    SPACE_2,
    SPACE_3,
)
from service.metadata_store import STATE_KNOWN, STATE_PENDING, STATE_UNKNOWN
from view.models.playlist_model import PlaylistModel
from view.time_format import format_time


# Width of the playing-row left marker (px). ``playing_bar`` is the accent-
# family token reserved for "this row is the one that sounds" -- 3px because a
# background tint alone (Task 6) was indistinguishable from the selection
# tint at a glance (audit A5).
PLAYING_BAR_WIDTH = 3

#: Gutter between the grid's columns: ``SPACE_2``, the same inset the row
#: already keeps on its two edges, so the grid adds no second spacing value.
COLUMN_GAP = SPACE_2

#: The width of the whole right-hand block, gutters included. One arithmetic
#: statement so the delegate, the header and the test all describe the same
#: strip (``tests/test_playlist_columns.py`` re-derives it from the tokens).
DATA_COLUMNS_WIDTH = (COLUMN_DURATION_WIDTH + 2 * COLUMN_TEXT_WIDTH
                      + 3 * COLUMN_GAP)

#: The narrowest the name block may be while the columns are shown. Below it the
#: three columns give the row back to the title instead of crushing it to zero
#: glyphs: the title is the column a user scans, and a playlist squeezed that
#: thin is showing nothing readable either way. ``96`` is eight glyph boxes at
#: the measured 12px advance -- enough for an elided "Name…" -- and it is what
#: keeps ``tests/test_i18n_coverage.py::DelegateStatePixelsTest`` (a 120px
#: viewport) on the title-only path it was written for.
MIN_NAME_BLOCK_WIDTH = 96

#: The narrowest the title may be kept at while the position text is elided.
#: Without it a pathological library path -- a folder 50 segments deep -- would
#: take the whole block and leave the title no ink at all, which is the same
#: defect in the other direction. Three glyph boxes.
MIN_TITLE_WIDTH = SPACE_3 * 3


def position_budget(block_width: int, position_advance: int) -> int:
    """How much of the name block the ``[relative_position]`` read-out gets.

    The reservation the name is elided *against*: the title is laid out in
    ``block_width - position_budget(...) - SPACE_2``, so the two can never put ink
    in each other's columns. Three cases, all of them the point of this one line:

    * a position that fits takes exactly its own advance, so the title gives it
      room and no more;
    * a longer one is capped at half the block, and at the block minus
      :data:`MIN_TITLE_WIDTH` minus one gutter, whichever is smaller: the
      footnote gives way to the name, never the other way round, and a
      fifty-segment library path elides on itself instead of leaving the title
      two glyphs (the decision the brief asks to be written down, and the reason
      this is a named function rather than an inline ``min``);
    * an empty or near-empty block hands back 0, so the arithmetic upstream never
      sees negative room to elide against.
    """
    cap = min(max(0, block_width - SPACE_2 - MIN_TITLE_WIDTH),
              block_width // 2)
    return min(position_advance, cap)


def metadata_columns_fit(row_width: int) -> bool:
    """Whether a row (or the header) of ``row_width`` px shows the three columns.

    Both the delegate and ``PlaylistView``'s header ask this one question, so the
    labels on top can never describe columns the rows are not drawing. The
    ``2 * SPACE_2`` is the delegate's own side inset, which the header mirrors
    through its layout margins.
    """
    return row_width - 2 * SPACE_2 >= DATA_COLUMNS_WIDTH + MIN_NAME_BLOCK_WIDTH


def column_rects(rect: QRect) -> tuple:
    """``(name_block, duration, artist, album)`` rectangles for one row rect.

    Right-anchored: the data block is pinned to the row's right inset and only
    the name block floats, which is 方案 P -- the row's right end belongs to the
    columns and the position read-out moved off it (see :meth:`paint`).
    """
    text = rect.adjusted(SPACE_2, 0, -SPACE_2, 0)
    top, height = text.top(), text.height()
    album = QRect(text.right() - COLUMN_TEXT_WIDTH + 1, top,
                  COLUMN_TEXT_WIDTH, height)
    artist = QRect(album.left() - COLUMN_GAP - COLUMN_TEXT_WIDTH, top,
                   COLUMN_TEXT_WIDTH, height)
    duration = QRect(artist.left() - COLUMN_GAP - COLUMN_DURATION_WIDTH, top,
                     COLUMN_DURATION_WIDTH, height)
    name = QRect(text.left(), top, duration.left() - COLUMN_GAP - text.left(),
                 height)
    return name, duration, artist, album


def metadata_cells(state, duration=None, artist=None, album=None,
                   is_folder: bool = False) -> tuple:
    """What the three data cells of one row say, in ``(duration, artist, album)``.

    ``None`` means "paint nothing in this cell", and it is the folder row's
    answer to all three. The rules, in the order they are checked:

    * **``is_folder`` wins over everything, including the state.** A folder
      header owns no file, so it has no ``full_path`` for the metadata store to
      answer about, and its ``metadata_state`` is therefore pinned at
      ``STATE_PENDING`` for ever. Keying this branch on the state instead would
      paint a row of ``⋯`` on every folder in the library -- measured in the
      Task 7 review, and the reason the parameter exists.
    * **the state decides the cell, not the values** (ruling B4-R17). The queue
      can hold a self-contradicting row: ``QueueService`` keeps the values a row
      already had when a refresh puts it back to ``pending``. The display layer
      reads the state word and nothing else, so ``pending`` paints the pending
      mark even next to a real artist string. ``STATE_PENDING`` /
      ``STATE_UNKNOWN`` are imported from the store rather than re-typed here
      (ruling B4-R5): the delegate and the cache cannot drift into two spellings.
    * **inside a ``known`` row each cell stands on its own.** ``STATE_KNOWN``
      with ``album is None`` is the extractor's answer "this file has no album
      tag", which is the same fact the ``unknown`` mark carries, so *that* cell
      takes the mark while the duration and the artist keep their values. A
      blank there would read as "not fetched yet" -- the opposite lie -- and a
      row-wide flag would mark all three.
    * an unrecognised state word paints the unknown mark, never a blank: a blank
      is the folder's answer, and a fallback must not impersonate it.

    ``duration=0.0`` and ``artist=''`` are values, not absences (ruling B4-R8),
    and they are tested for with ``is not None`` for that reason.

    A value that happens to equal one of the two mark strings would be painted
    like a mark; that costs a colour on a row whose artist is literally named
    ``—``, and nothing else.
    """
    if is_folder:
        return (None, None, None)

    pending_mark = i18n.get('meta.pending')
    unknown_mark = i18n.get('meta.unknown')

    if state == STATE_PENDING:
        return (pending_mark, pending_mark, pending_mark)
    if state == STATE_UNKNOWN:
        return (unknown_mark, unknown_mark, unknown_mark)
    if state != STATE_KNOWN:
        return (unknown_mark, unknown_mark, unknown_mark)

    return (
        format_time(duration) if duration is not None else unknown_mark,
        artist if artist is not None else unknown_mark,
        album if album is not None else unknown_mark,
    )


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
    5. ``[relative_position]`` in ``text_muted``, right-aligned inside the *name
       block* -- the strip left of the grid, not the row's right edge (Task 8,
       方案 P). The name's available width is computed *before* eliding and
       already excludes the position plus one ``SPACE_2``, so the two can never
       collide, and a position too long for its share elides on itself instead
       of eating the title.
    6. The three metadata columns -- duration (right-aligned), artist and album
       (left-aligned) -- in the bands :func:`column_rects` describes, over the
       row's right inset. What each cell says is
       :func:`metadata_cells`; a folder row has nothing to say and paints
       nothing. Below :data:`MIN_NAME_BLOCK_WIDTH` of room for the title the
       columns are not drawn at all.

    The hover fill is layer 1's third branch and lives here because nothing else
    can paint it: a ``#playlistView::item:hover`` rule in the sheet is parsed and
    discarded for a view whose delegate overrides ``paint()`` (the batch 2 audit
    finding this batch is not allowed to repeat). The alternating row tint, by
    contrast, is *not* painted by this class: ``PlaylistView`` asks ``QListView``
    for alternating rows and the view fills them from the palette's
    ``AlternateBase`` (mapped to ``surface_alt`` by ``ThemeManager``, measured
    ``#f5f5f5`` on odd rows in the render matrix), which is why the layers below
    are drawn over a band that is already tinted -- and why a hovered odd row
    reads as ``hover_bg`` laid over that tint, not as a blend of the two. The
    fill is opaque, so it covers whatever ground it is handed; which tint that
    ground is under the shipped sheet is the render matrix's claim to make
    (Task 7), not this class's -- the hover tests skip ``apply_to`` and so run
    against Qt's default ``AlternateBase``.

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
        playing bar, then the name and position in the name block, then the
        three data columns.
        """
        tokens = self._manager.tokens

        # Get data from model
        display_text = index.data(Qt.ItemDataRole.DisplayRole)
        relative_position = index.data(PlaylistModel.RelativePositionRole)
        is_folder = index.data(PlaylistModel.IsFolderRole)
        is_playing = index.data(PlaylistModel.IsPlayingRole)
        state = index.data(PlaylistModel.MetadataStateRole)
        duration = index.data(PlaylistModel.DurationRole)
        artist = index.data(PlaylistModel.ArtistRole)
        album = index.data(PlaylistModel.AlbumRole)

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
        # keeps the right-hand columns off the viewport border.
        text_rect = option.rect.adjusted(SPACE_2, 0, -SPACE_2, 0)

        # 4. Font and the row's own text colour (playing rows take
        # playing_text; folders stay text_primary but bold).
        font = QFont(option.font)
        if is_folder:
            font.setBold(True)
        painter.setFont(font)
        text_colour = tokens.playing_text if is_playing else tokens.text_primary

        # 6. The grid, or its absence. ``metadata_columns_fit`` is the delegate's
        # answer *and* the header's, so a row that hides the columns never faces
        # a header that still names them. Drawn before the title even though the
        # class docstring lists it last: the bands are disjoint, so nothing here
        # can be overpainted, and the numbering is by meaning, not by z-order.
        columns = (column_rects(option.rect)
                   if metadata_columns_fit(option.rect.width()) else None)
        name_rect = columns[0] if columns else text_rect

        if columns:
            self._paint_cells(painter, font, columns,
                              metadata_cells(state=state, duration=duration,
                                             artist=artist, album=album,
                                             is_folder=bool(is_folder)),
                              tokens)

        # Folder rows and rows without a relative position: name only, and the
        # name owns the whole block. A folder header's position is deliberately
        # not drawn -- the shape it has had since before this batch, and Task 8
        # moves the position, it does not re-decide who gets one.
        if not relative_position or is_folder:
            painter.setPen(QColor(text_colour))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self._elide_text(display_text, font, name_rect.width()))
            painter.restore()
            return

        # 5. Name on the left, position on the right -- both *inside the name
        # block*, whose right edge is the duration column's neighbour. This is
        # the move Task 8 exists to make: the read-out used to be right-aligned
        # against the row, and the row's right end is now the columns' (the two
        # are not both painted).
        #
        # The position's width is taken off the block *before* the name is
        # elided, so a long name gets an ellipsis instead of painting under the
        # muted text -- the old overlay behaviour, and the reason the reservation
        # is the first thing here. :func:`position_budget` owns how much that is
        # (and caps the footnote itself, so a 50-segment library path elides on its
        # own text rather than deleting the title); the shape of dropping it is
        # what ``tests/test_playlist_columns.py::OverlongRowTest`` flips on the test
        # side and measures.
        metrics = QFontMetrics(font)
        position_text = f"[{relative_position}]"
        budget = position_budget(name_rect.width(),
                                 metrics.horizontalAdvance(position_text))
        available = max(0, name_rect.width() - budget - SPACE_2)
        painter.setPen(QColor(text_colour))
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self._elide_text(display_text, font, available))

        # ``text_muted`` replaces the old ``QColor(136,136,136,160)``: the
        # token is the one the 4.5:1 text guard in tests/test_theme.py
        # measured against playing_bg/selection_bg, and it is opaque.
        painter.setPen(QColor(tokens.text_muted))
        position_rect = QRect(name_rect)
        position_rect.setLeft(name_rect.left())
        painter.drawText(position_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         metrics.elidedText(position_text,
                                           Qt.TextElideMode.ElideRight,
                                           budget))

        # Restore painter state
        painter.restore()

    @staticmethod
    def _paint_cells(painter: QPainter, font: QFont, columns: tuple,
                     cells: tuple, tokens) -> None:
        """Draw the three data cells of one row inside their bands.

        ``cells`` comes straight from :func:`metadata_cells`, so every rule about
        what a cell *says* -- the folder's silence, the state's priority, the
        per-field unknown inside a known row -- has one author, and this is only
        the geometry half. A ``None`` cell is skipped rather than painted: that
        is what "the folder row's data cells are empty" looks like on pixels.

        Duration is right-aligned so the digits line up column-wise (a list of
        three- and four-character times is unreadable left-aligned); the two text
        columns are left-aligned, which is how names are scanned. Every cell is
        elided to its own band, so a long artist stops at the album column
        instead of painting over it.
        """
        _name_rect, duration_rect, artist_rect, album_rect = columns
        marks = {i18n.get('meta.pending'), i18n.get('meta.unknown')}
        for rect, text, align in ((duration_rect, cells[0],
                                   Qt.AlignmentFlag.AlignRight),
                                  (artist_rect, cells[1],
                                   Qt.AlignmentFlag.AlignLeft),
                                  (album_rect, cells[2],
                                   Qt.AlignmentFlag.AlignLeft)):
            if text is None:
                continue
            # A cell that says "nothing here yet" paints quieter than a cell that
            # says something. Comparing on the mark strings keeps that choice
            # with the content rule instead of repeating it per state branch.
            painter.setPen(QColor(tokens.text_muted if text in marks
                                  else tokens.text_secondary))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | align,
                             text)

    def _elide_text(self, text: str, font: QFont, max_width: int) -> str:
        """Elide text if it exceeds max_width."""
        if not text:
            return ""

        metrics = QFontMetrics(font)
        if metrics.horizontalAdvance(text) <= max_width:
            return text

        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_width)
