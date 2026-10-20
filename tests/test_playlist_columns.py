#!/usr/bin/env python3
"""Batch 4 Task 8: the delegate's three metadata columns, measured on pixels.

Everything here is an offscreen ``grab()`` of the list viewport plus the row
rectangles ``QListView`` hands back, because the claim Task 8 makes is a claim
about *where ink lands*. Nothing in this module writes an item QSS rule: the
delegate owns every pixel of the row (``#playlistView::item`` is shipped-dead --
see ``tests/test_theme_manager.py``), so a rule here would style nothing and
would make the test prove the sheet instead of the painting.

Four measurements, one per defect the batch is afraid of:

* **bands** -- each column's ink sits inside the band the tokens describe, in
  both themes, and the bands are disjoint. An un-elided artist string spills
  into the album band, and this is what sees it.
* **alignment** -- the duration is right-aligned and the two text columns are
  left-aligned, read off the ink's first and last column against the band's
  edges, so two swapped flags are a failure and not a nuance.
* **the three cell states** -- ``pending`` paints ``⋯``, ``unknown`` paints
  ``—``, ``known`` paints the value, and a folder row paints *nothing* in the
  data cells. The folder rule is keyed on ``is_folder``, never on the state: a
  folder header has no ``full_path`` to look a cached row up by, so its
  ``metadata_state`` is pinned at ``pending`` forever, and painting by state
  would give every folder a row of ``⋯``.
* **the overlong combination** (Review Focus 4) -- long name, long position,
  long artist/album: the name and the position each elide, the columns keep
  their widths, and no ink escapes the row's text rectangle.

Two host facts, measured on this machine before the assertions below were
written, and both of which shape them:

1. The offscreen font substitutes *every* glyph -- ``M``, ``x``, ``⋯``, ``—``
   alike -- with the same hollow box (probe: 28 exact-colour pixels, columns
   24..31, rows 8..15, and *identical pixel sets* for all four). A pixel scan
   can therefore tell *that* a cell painted and *how far its ink reaches*, but
   not one one-character mark from another. Distinguishability of ``⋯`` from
   ``—`` is pinned on the string the presentation function hands the painter
   (:meth:`MetadataCellRuleTest.test_the_two_marks_are_different_strings`),
   while the pixels pin that each cell paints *something*, in the mark token,
   on a ground that is neither ``playing_bg``, ``selection_bg`` nor ``hover_bg``
   and that clears WCAG AA against it -- which is why the two mark rows below
   are an even and an odd one, i.e. ``Base`` and ``AlternateBase``.
2. ``QFontMetrics`` at the playlist's own font (``Sans Serif`` 9pt) measures
   ``3:25`` at 48px, ``1:02:03`` at 84px, and both a CJK and a Latin glyph at
   12px of advance. ``COLUMN_DURATION_WIDTH`` 56 therefore holds ``MM:SS`` with
   8px of slack and elides anything longer, and ``COLUMN_TEXT_WIDTH`` 120 holds
   ten CJK glyphs. Those are the numbers the bands below are built from, and
   :meth:`ColumnTokenTest` re-measures them instead of trusting them.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from core import i18n
from core.theme import (
    COLUMN_DURATION_WIDTH,
    COLUMN_TEXT_WIDTH,
    ROW_HEIGHT,
    SPACE_2,
    THEMES,
)
from service.metadata_store import (
    RowMetadata,
    STATE_KNOWN,
    STATE_PENDING,
    STATE_UNKNOWN,
)
from service.queue_service import DisplayEntry
from tests.test_theme import ThemeContrastTest
from tests.test_view_smoke import QT_AVAILABLE, make_app, make_manager

# The two marks as escapes, so a failure message survives this host's GBK
# console. The locale files carry the same code points -- that is what
# :meth:`MetadataCellRuleTest.test_the_two_marks_are_the_recorded_code_points`
# ties down.
PENDING_MARK = '⋯'
UNKNOWN_MARK = '—'

#: The gutter between columns: ``SPACE_2``, the same inset the row already uses
#: on both of its edges, so the grid introduces no second spacing value.
COLUMN_GAP = SPACE_2

#: Wide enough for the whole data block *and* a title that still reads:
#: ``2 * SPACE_2`` of row inset + ``COLUMN_DURATION_WIDTH`` + two
#: ``COLUMN_TEXT_WIDTH`` + three gutters = 336, which leaves 300px for the name
#: at this width. Below the delegate's own floor the columns give the row back
#: to the title instead -- :meth:`ColumnFitTest`.
VIEW_WIDTH = 640
NARROW_VIEW_WIDTH = 300

#: The fixture rows, in display order: ``(name, position, folder, md, state)``.
#: Row 1 is even (``Base`` ground) and row 2 is odd (``AlternateBase``), which is
#: the "each mark on a different ground" the brief asks for: neither mark row can
#: be read as a state tint, and one of them cannot be read as the other mark.
FIXTURE_ROWS = (
    ('ArtistName', 'Rock', False,
     RowMetadata(artist='Aa', album='Bbb', duration=205.0), STATE_KNOWN),
    ('PendingOne', 'Rock', False, None, STATE_PENDING),
    ('UnknownOne', 'Rock', False, RowMetadata(), STATE_UNKNOWN),
    ('Folder header', 'Rock', True, None, STATE_PENDING),
    ('HalfKnown', 'Rock', False,
     RowMetadata(artist='Aa', duration=205.0), STATE_KNOWN),
)
KNOWN_ROW, PENDING_ROW, UNKNOWN_ROW, FOLDER_ROW, HALF_KNOWN_ROW = range(5)

OVERLONG_NAME = 'NeverGonnaGiveYouUpNeverGonnaLetYouDown.mp3'
OVERLONG_POSITION = 'Some/Very/Deep/Library/Branch/For/The/Elision/Check'
OVERLONG_ARTIST = 'ArtistNameThatGoesOnAndOnForever'
OVERLONG_ALBUM = 'AlbumNameThatGoesOnAndOnForeverToo'
OVERLONG_ROWS = (
    (OVERLONG_NAME, OVERLONG_POSITION, False,
     RowMetadata(artist=OVERLONG_ARTIST, album=OVERLONG_ALBUM, duration=205.0),
     STATE_KNOWN),
)

# The four inks a row can carry, so "no ink here at all" is a closed set rather
# than a list of the colours this file happens to remember.
_TEXT_TOKENS = ('text_primary', 'text_secondary', 'text_muted', 'playing_text')


def bands_for(rect):
    """The four column bands of one row rectangle, in viewport coordinates.

    Computed here from the theme tokens rather than imported from the delegate on
    purpose: the test has to own its own idea of where the columns belong, or a
    delegate that moved a band would move the expectation with it and every
    assertion below would be a tautology. Right-anchored, because 方案 P gives
    the row's right end to the data and only the name floats.
    """
    right = rect.right() - SPACE_2
    album_left = right - COLUMN_TEXT_WIDTH + 1
    artist_right = album_left - COLUMN_GAP - 1
    artist_left = artist_right - COLUMN_TEXT_WIDTH + 1
    duration_right = artist_left - COLUMN_GAP - 1
    duration_left = duration_right - COLUMN_DURATION_WIDTH + 1
    name_right = duration_left - COLUMN_GAP - 1
    return {
        'name': (rect.left() + SPACE_2, name_right),
        'duration': (duration_left, duration_right),
        'artist': (artist_left, artist_right),
        'album': (album_left, right),
    }


def make_entry(row, name, position='Rock', folder=False, **kwargs):
    """One display entry with a plausible file path behind it."""
    path = '/media/rock/Album/Track %02d.mp3' % row
    return DisplayEntry(display_text=name, node_idx=row, is_folder=folder,
                        path=path, sub_index=row, full_path=path,
                        relative_position=position, **kwargs)


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ColumnPixelHarness(unittest.TestCase):
    """Builds the painted playlist and reads ink out of it. Subclasses test."""

    def setUp(self):
        self.app = make_app()
        # Only the palette is put back -- the convention of every pixel test in
        # this suite, because each assertion reads the pixels of the theme it
        # applied, and the application sheet is the last thing written anyway.
        self._saved_palette = self.app.palette()
        self._widgets = []
        self._previous_locale = i18n.get_current_locale()
        # The fixture strings are Latin and the elision arithmetic below is in
        # Latin advances; the copy itself is Task 8's locale content and is
        # asserted under both locales in :class:`MetadataCellRuleTest`.
        i18n.set_locale('en_US')

    def tearDown(self):
        i18n.set_locale(self._previous_locale)
        for widget in self._widgets:
            widget.close()
            widget.deleteLater()
        self.app.setPalette(self._saved_palette)

    def _paint(self, mode, rows=FIXTURE_ROWS, width=VIEW_WIDTH):
        """``(image, row_rects, tokens, list_view)`` for ``rows`` in ``mode``."""
        from view.widgets.playlist_view import PlaylistView

        manager = make_manager(mode)
        manager.apply_to(self.app)
        view = PlaylistView(manager)
        self._widgets.append(view)
        view.set_entries([make_entry(index, name, position, folder)
                          for index, (name, position, folder, _md, _state)
                          in enumerate(rows)])
        # The metadata goes in through the targeted entry point, never through a
        # table re-push: Task 7 measured that ``set_entries`` /
        # ``set_playlist_entries`` repaints nothing for a row whose three columns
        # changed (``PlaylistModel.update_entries`` only compares display text
        # and the playing flag), so a re-push would leave every cell pending and
        # the band assertions below would be measuring an empty column.
        for index, (_name, _position, _folder, md, state) in enumerate(rows):
            view.update_row_metadata(index, md, state)

        view.resize(width, ROW_HEIGHT * len(rows) + 60)
        view.show()
        self.app.processEvents()

        list_view = view._list_view
        image = list_view.viewport().grab().toImage()
        rects = [list_view.visualRect(list_view.model().index(index))
                 for index in range(len(rows))]
        self.assertEqual(
            ROW_HEIGHT, rects[0].height(),
            'the row height is the shared token, so a band measured against a '
            'different row box is not the band the delegate painted')
        return image, rects, THEMES[mode], list_view

    @staticmethod
    def _ink(image, rect, band, tokens, names=_TEXT_TOKENS):
        """Columns of ``band`` carrying ink of the named theme tokens.

        The row's bottom pixel is excluded: that is the ``divider``, and counting
        it would make every band look full.
        """
        wanted = {getattr(tokens, name).lower() for name in names}
        left, right = band
        columns = []
        for x in range(left, right + 1):
            for y in range(rect.top(), rect.bottom()):
                if image.pixelColor(x, y).name().lower() in wanted:
                    columns.append(x)
                    break
        return columns

    def _band_ink(self, image, rect, band, tokens, token_name):
        """Columns of ``band`` carrying exactly ``tokens.<token_name>`` ink."""
        return self._ink(image, rect, band, tokens, names=(token_name,))

    def _ground(self, image, rect, band):
        """The colour the band is painted *on*, read from the image.

        Taken at the band's own first column, one row above the divider, in a
        fixture whose cells are blank at that height for the ground lookup...
        which is why this walks down until it finds a pixel that is not one of
        the inks: an alpha-composited playlist ground is not a token value the
        test could name, so it is measured.
        """
        inks = {getattr(THEMES['light'], name).lower() for name in _TEXT_TOKENS}
        inks |= {getattr(THEMES['dark'], name).lower() for name in _TEXT_TOKENS}
        left = band[0]
        for y in range(rect.top(), rect.bottom()):
            colour = image.pixelColor(left, y).name().lower()
            if colour not in inks:
                return colour
        self.fail(f'no non-ink pixel found in band {band} of {rect}')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PlaylistColumnTest(ColumnPixelHarness):
    """The three columns on pixels, in both themes."""

    def test_each_column_paints_inside_its_own_band_in_both_themes(self):
        from view.delegates.playlist_delegate import metadata_columns_fit

        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode)
                rect = rects[KNOWN_ROW]
                bands = bands_for(rect)
                self.assertTrue(
                    metadata_columns_fit(rect.width()),
                    f'the {rect.width()}px fixture row has no room for the '
                    f'columns, so this test is measuring a hidden grid')

                for column in ('duration', 'artist', 'album'):
                    left, right = bands[column]
                    ink = self._band_ink(image, rect, (left, right), tokens,
                                         'text_secondary')
                    self.assertTrue(
                        ink,
                        f'{column} painted no {tokens.text_secondary} ink in a '
                        f'known row: the column is not being painted at all')
                    self.assertLessEqual(
                        max(ink), right,
                        f'{column} ink escaped its band to x={max(ink)} while '
                        f'the band ends at x={right}')
                    self.assertGreaterEqual(
                        min(ink), left,
                        f'{column} ink started before its band at x={min(ink)}')

                # The bands are disjoint and in the mandated order, which is what
                # makes "the three columns were not squeezed into each other" a
                # measurement rather than a hope.
                order = [bands['name'], bands['duration'], bands['artist'],
                         bands['album']]
                for first, second in zip(order, order[1:]):
                    self.assertLess(
                        first[1], second[0],
                        f'bands {first} and {second} overlap')
                self.assertEqual(
                    COLUMN_DURATION_WIDTH,
                    bands['duration'][1] - bands['duration'][0] + 1)
                self.assertEqual(
                    COLUMN_TEXT_WIDTH,
                    bands['artist'][1] - bands['artist'][0] + 1)
                self.assertEqual(
                    COLUMN_TEXT_WIDTH,
                    bands['album'][1] - bands['album'][0] + 1)

    def test_duration_is_right_aligned_and_the_text_columns_are_left_aligned(self):
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode)
                rect = rects[KNOWN_ROW]
                bands = bands_for(rect)

                # ``3:25`` is 48px of advance against a 56px band, so a
                # right-aligned value leaves ~8px of empty band on its left and
                # ends on the band's right edge (the box glyph's side bearing is
                # a pixel or two, hence the tolerance).
                left, right = bands['duration']
                ink = self._band_ink(image, rect, (left, right), tokens,
                                     'text_secondary')
                self.assertGreaterEqual(
                    min(ink) - left, 4,
                    'the duration starts at the band\'s left edge: it is being '
                    'left-aligned, and the column would then be ragged on the '
                    'right, where every other row\'s digits are')
                self.assertGreaterEqual(
                    ink[-1], right - 5,
                    f'the duration\'s ink stops at x={ink[-1]} while the band '
                    f'ends at x={right}: it is not flush right')

                for column, value in (('artist', 'Aa'), ('album', 'Bbb')):
                    left, right = bands[column]
                    ink = self._band_ink(image, rect, (left, right), tokens,
                                         'text_secondary')
                    self.assertLessEqual(
                        min(ink), left + 2,
                        f'{column} ({value}) starts {min(ink) - left}px in: the '
                        f'text columns are left-aligned')
                    self.assertLess(
                        ink[-1], right - 20,
                        f'{column} ({value}) reaches the band\'s right edge, so '
                        f'its value is wider than the column and the left '
                        f'alignment cannot be told from the fill case')

    def test_pending_and_unknown_rows_paint_a_mark_in_every_data_cell(self):
        """``⋯`` on the pending row, ``—`` on the unknown row, in ``text_muted``.

        The two rows are an even and an odd one on purpose: their grounds are the
        view's ``Base`` and ``AlternateBase``, neither of which is ``playing_bg``,
        ``selection_bg`` or ``hover_bg`` -- so the ink cannot be a state tint
        misread as a mark, and the mark's own contrast is checked against the
        ground it actually sits on.
        """
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode)
                rows = (PENDING_ROW, UNKNOWN_ROW)
                bands = [bands_for(rects[row]) for row in rows]
                grounds = []
                for row, rect, band_row in zip(rows,
                                               [rects[r] for r in rows],
                                               bands):
                    inked = []
                    for column in ('duration', 'artist', 'album'):
                        ink = self._band_ink(image, rect, band_row[column],
                                             tokens, 'text_muted')
                        self.assertTrue(
                            ink,
                            f'row {row} ({FIXTURE_ROWS[row][0]}): {column} is '
                            f'blank, so the {FIXTURE_ROWS[row][4]} state paints '
                            f'no mark')
                        inked.append(ink)
                    self.assertEqual(
                        3, len({tuple(ink) for ink in inked}),
                        f'row {row}: the three cells are not three separate '
                        f'glyphs -- {inked}')

                    ground = self._ground(image, rect, band_row['album'])
                    grounds.append(ground)
                    state_tints = {getattr(tokens, name).lower() for name in
                                   ('playing_bg', 'selection_bg', 'hover_bg')}
                    self.assertNotIn(
                        ground, state_tints,
                        f'row {row}: the mark sits on a state tint, so this '
                        f'fixture cannot tell a mark from a selection fill')
                    self.assertGreaterEqual(
                        ThemeContrastTest.contrast(tokens.text_muted, ground),
                        4.5,
                        f'row {row}: {tokens.text_muted} on {ground} is below '
                        f'WCAG AA, so the mark is not legible there')

                # The two fixture grounds differ from each other: one even row,
                # one odd row, which is the "对照" that keeps a single background
                # from being the reason both marks looked fine.
                self.assertNotEqual(
                    grounds[0], grounds[1],
                    'the pending and the unknown row were painted on the same '
                    'ground, so this test is only proving one background')

    def test_folder_row_leaves_the_three_data_cells_empty(self):
        """A folder header shows its name and position and *nothing* else.

        The row carries ``metadata_state == 'pending'`` like any unfetched row
        (it has no path to be fetched *by*), so the only way this test can tell
        "empty" from "``⋯``" is the ink census -- and that is exactly the
        distinction the brief fixes before implementation: a folder must not
        wear a row of pending marks.
        """
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode)
                rect = rects[FOLDER_ROW]
                bands = bands_for(rect)

                for column in ('duration', 'artist', 'album'):
                    ink = self._ink(image, rect, bands[column], tokens)
                    self.assertEqual(
                        [], ink,
                        f'the folder row painted {ink} in the {column} band '
                        f'{bands[column]}: a folder header owns no metadata, so '
                        f'the cells must be blank, not marked')

                # And the row is not simply unpainted: its name puts ink inside
                # the name band. (A folder row keeps the shape it had before this
                # task -- bold name, no position read-out -- which is the
                # delegate's own folder branch, not something Task 8 changes.)
                name_ink = self._band_ink(image, rect, bands['name'], tokens,
                                          'text_primary')
                self.assertTrue(
                    name_ink,
                    'the folder row painted no title either: the blank cells '
                    'below would be an unpainted row, not a folder rule')

    def test_the_folder_census_has_teeth(self):
        """Step 5's mutation ②, flipped from the test side.

        Same mechanism as
        :meth:`OverlongRowTest.test_the_reservation_is_what_the_gap_measures`, and
        for the same reason: the harness will not let this file edit the delegate,
        and the instruction when that happens is to buy the falsifiability back
        from here rather than route around the refusal. ``paint`` looks
        ``metadata_cells`` up as a module global, so replacing it for one grab is
        the mutation -- folder cells painting the unknown mark, which is exactly
        what the brief fixes as wrong before implementation.

        The evidence is that the mutant leaves ink in all three bands, so
        :meth:`test_folder_row_leaves_the_three_data_cells_empty` is not reading a
        row that was blank either way: it is the census that separates "folder"
        from "every folder wears a row of marks".
        """
        from view.delegates import playlist_delegate

        real = playlist_delegate.metadata_cells
        self.addCleanup(setattr, playlist_delegate, 'metadata_cells', real)

        def mutant(**kwargs):
            if kwargs.get('is_folder'):
                # The shape Task 8 forbids: paint by state, ignore ``is_folder``.
                return (i18n.get('meta.unknown'),) * 3
            return real(**kwargs)

        playlist_delegate.metadata_cells = mutant
        image, rects, tokens, _view = self._paint('light')
        rect = rects[FOLDER_ROW]
        bands = bands_for(rect)
        for column in ('duration', 'artist', 'album'):
            self.assertTrue(
                self._ink(image, rect, bands[column], tokens),
                f'the mutant left the {column} band of the folder row blank, so '
                f'the shipped census cannot distinguish the two shapes and proves '
                f'nothing')

    def test_a_known_row_marks_only_the_cell_that_has_no_value(self):
        """The three cells are independent: a tag without an album is not a row without metadata.

        ``STATE_KNOWN`` with ``album is None`` is the extractor's answer "this
        file has no album tag", which is the same fact the ``unknown`` mark
        carries -- so that one cell takes the mark while the duration and the
        artist keep their values. A single "row is known, paint the row" flag
        would either blank the album cell (reading as "not fetched yet", the
        opposite lie) or mark all three.
        """
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode)
                rect = rects[HALF_KNOWN_ROW]
                bands = bands_for(rect)

                for column in ('duration', 'artist'):
                    value_ink = self._band_ink(image, rect, bands[column], tokens,
                                               'text_secondary')
                    mark_ink = self._band_ink(image, rect, bands[column], tokens,
                                              'text_muted')
                    self.assertTrue(
                        value_ink, f'{column} should carry the known value')
                    self.assertEqual(
                        [], mark_ink,
                        f'{column} painted a mark over its value')

                value_ink = self._band_ink(image, rect, bands['album'], tokens,
                                           'text_secondary')
                mark_ink = self._band_ink(image, rect, bands['album'], tokens,
                                          'text_muted')
                self.assertEqual([], value_ink,
                                 'the album cell painted a value it does not have')
                self.assertTrue(
                    mark_ink,
                    'the album cell of a known row with no album tag is blank, '
                    'which reads as "not fetched yet" -- it must carry the '
                    'unknown mark')

    def test_the_position_lives_after_the_name_and_not_at_the_row_end(self):
        """方案 P in one assertion: the row's right end belongs to the columns.

        Before this task ``[relative_position]`` was right-aligned against the
        *row*, which is the strip the three columns now own. The muted ink must
        therefore stop inside the name band -- and the data bands to its right
        hold no muted ink on a known row.
        """
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode)
                rect = rects[KNOWN_ROW]
                bands = bands_for(rect)
                muted = self._band_ink(image, rect, bands['name'], tokens,
                                       'text_muted')
                self.assertTrue(muted, 'no position text was painted')
                self.assertLessEqual(
                    max(muted), bands['name'][1],
                    'the position text reaches past the name band, so it is '
                    'still being drawn at the row end')
                for column in ('duration', 'artist', 'album'):
                    self.assertEqual(
                        [], self._band_ink(image, rect, bands[column], tokens,
                                           'text_muted'),
                        f'the {column} band carries muted ink on a known row')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class OverlongRowTest(ColumnPixelHarness):
    """Review Focus 4: the widest combination the grid can be handed."""

    def test_long_name_long_position_and_long_columns_fit_without_overflow(self):
        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, list_view = self._paint(
                    mode, rows=OVERLONG_ROWS)
                rect = rects[0]
                bands = bands_for(rect)
                font = list_view.font()
                from PyQt6.QtGui import QFontMetrics
                metrics = QFontMetrics(font)

                # The name and the position are both longer than the band they
                # share, so "each elides" is only provable against the advance
                # the *un-elided* strings would have needed.
                name_ink = self._band_ink(image, rect, bands['name'], tokens,
                                          'text_primary')
                muted = self._band_ink(image, rect, bands['name'], tokens,
                                       'text_muted')
                self.assertTrue(name_ink and muted,
                                'the overlong row painted no title or no position')
                band_left, band_right = bands['name']
                self.assertLessEqual(
                    max(name_ink), band_right,
                    'the title ink escaped the name band into the columns')
                self.assertLessEqual(
                    max(muted), band_right,
                    'the position ink escaped the name band into the columns')
                self.assertGreaterEqual(
                    min(name_ink), band_left,
                    'the title starts inside the row inset')
                self.assertGreater(
                    metrics.horizontalAdvance(OVERLONG_NAME),
                    name_ink[-1] - name_ink[0],
                    'the title was not elided: its ink spans as much ground as '
                    'the whole string needs')
                self.assertGreater(
                    metrics.horizontalAdvance(f'[{OVERLONG_POSITION}]'),
                    muted[-1] - muted[0],
                    'the long position text was not elided: it is eating the '
                    'title column instead of itself')

                # The reservation is the thing that keeps them apart: the title
                # stops at least one SPACE_2 before the position starts. Delete
                # "reserve the position first" from the delegate and the title
                # is elided against the whole band and runs into the muted text.
                self.assertGreaterEqual(
                    muted[0] - name_ink[-1], SPACE_2,
                    f'the title runs to x={name_ink[-1]} and the position starts '
                    f'at x={muted[0]}: they are colliding')

                # Neither data column is starved: a value wider than its band
                # fills it, so ink reaching the band's right edge is the proof
                # the column still has its width.
                for column in ('artist', 'album'):
                    left, right = bands[column]
                    ink = self._band_ink(image, rect, (left, right), tokens,
                                         'text_secondary')
                    self.assertTrue(ink, f'{column} painted nothing')
                    self.assertLessEqual(min(ink), left + 2,
                                         f'{column} lost its left edge')
                    self.assertGreaterEqual(
                        ink[-1], right - 12,
                        f'{column} ({right - left + 1}px band) only filled to '
                        f'x={ink[-1]}: the column was squeezed')
                duration_ink = self._band_ink(image, rect, bands['duration'],
                                              tokens, 'text_secondary')
                self.assertTrue(duration_ink, 'the duration column disappeared')
                self.assertGreaterEqual(
                    duration_ink[-1], bands['duration'][1] - 5,
                    'the duration column is no longer flush with the right edge '
                    'of its band')

                # And nothing at all escapes the row's text rectangle: the right
                # gutter from the album band's end to the row edge stays ink-free.
                overflow = [x for x in range(bands['album'][1] + 1, rect.right() + 1)
                            if any(image.pixelColor(x, y).name().lower()
                                   in {getattr(tokens, name).lower()
                                       for name in _TEXT_TOKENS}
                                   for y in range(rect.top(), rect.bottom()))]
                self.assertEqual(
                    [], overflow,
                    f'text ink at {overflow} sits right of the album band, so '
                    f'the row overflows its own rectangle')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ColumnFitTest(ColumnPixelHarness):
    """The grid gives way to the title instead of crushing it."""

    def test_a_narrow_row_gives_the_columns_back_to_the_title(self):
        from view.delegates.playlist_delegate import metadata_columns_fit

        for mode in ('light', 'dark'):
            with self.subTest(mode=mode):
                image, rects, tokens, _view = self._paint(mode, width=NARROW_VIEW_WIDTH)
                rect = rects[KNOWN_ROW]
                bands = bands_for(rect)
                self.assertFalse(
                    metadata_columns_fit(rect.width()),
                    f'the delegate keeps its {rect.width()}px row although the '
                    f'data block plus the title floor does not fit in it, so the '
                    f'assertions below are not testing the give-way rule')

                # The bands are *not* the probe here: at this width
                # ``bands_for`` degenerates (its right-anchored arithmetic puts
                # the duration band at negative x, over the title), so the claim
                # is made on ink colour instead. A known row paints its three
                # values in ``text_secondary`` -- see
                # :meth:`PlaylistColumnTest.test_each_column_paints_inside_its_own_band_in_both_themes`
                # -- so a row with no ``text_secondary`` ink at all is a row whose
                # grid was not drawn.
                self.assertEqual(
                    [], self._ink(image, rect, (rect.left(), rect.right()),
                                  tokens, names=('text_secondary',)),
                    'the narrow row painted its metadata values: the columns are '
                    'still drawn, crushing the title against them')

                title = self._band_ink(image, rect, (rect.left(), rect.right()),
                                       tokens, 'text_primary')
                self.assertTrue(title, 'the narrow row lost its title too')
                self.assertEqual(
                    title[0] - rect.left(), SPACE_2,
                    'the title no longer starts at the row inset: the name block '
                    'did not go back to the whole row')
                muted = self._band_ink(image, rect, (rect.left(), rect.right()),
                                       tokens, 'text_muted')
                self.assertTrue(muted, 'the narrow row lost its position text')
                # With the grid hidden the name block is the whole row again, so
                # the position ends inside the row's own ``SPACE_2`` inset -- one
                # glyph box (~4px) plus the inset, and no further.
                self.assertLessEqual(
                    rect.right() - muted[-1], SPACE_2 + 6,
                    f'the position ends at x={muted[-1]} on a row that runs to '
                    f'x={rect.right()}: it is not sitting in the right inset')
                self.assertLess(muted[-1], rect.right(),
                                'the position paints over the row edge')

    def test_the_reservation_is_what_the_gap_measures(self):
        """Step 5's mutation ①, flipped from the test side.

        The harness will not let this file edit
        ``view/delegates/playlist_delegate.py``, and the brief's rule for that is
        not to work around it -- so the single variable is flipped on the live
        module instead, for one grab, and put back by ``addCleanup``. ``paint``
        reads ``position_budget`` as a module global, so this is the mutation and
        not a simulation of it: the name is elided against the whole block, which
        is the shape Step 5 describes.

        The comparison is against the same row measured with the rule in place,
        which is what makes the control non-arbitrary: dropping the reservation
        hands the title the footnote's ground, so the title's ink moves right by
        more than a gutter and the read-out is gone (Qt elides the position to
        nothing at a 0-width budget, so the defect shows as a footnote that
        stopped existing -- the same collision the batch 1 reservation test caught
        in a 120px viewport, one width later).
        """
        from view.delegates import playlist_delegate

        def measure():
            image, rects, tokens, _view = self._paint('light', rows=OVERLONG_ROWS)
            rect = rects[0]
            bands = bands_for(rect)
            return (self._band_ink(image, rect, bands['name'], tokens,
                                   'text_primary'),
                    self._band_ink(image, rect, bands['name'], tokens,
                                   'text_muted'))

        shipped_name, shipped_muted = measure()
        self.assertTrue(shipped_name and shipped_muted,
                        'the shipped row lost one of the two texts')

        original = playlist_delegate.position_budget
        self.addCleanup(setattr, playlist_delegate, 'position_budget', original)
        playlist_delegate.position_budget = lambda block, advance: 0
        mutant_name, mutant_muted = measure()

        self.assertEqual(
            [], mutant_muted,
            'the mutant painted the position anyway, so nothing here can see the '
            'reservation being dropped -- the gap assertion would be decorative')
        self.assertGreater(
            mutant_name[-1], shipped_name[-1] + SPACE_2,
            f'the un-reserved title ended at x={mutant_name[-1]} against the '
            f'shipped {shipped_name[-1]}: the title did not take the ground the '
            f'footnote occupies, '
            'so the reservation is not what the gap assertion is measuring')

    def test_the_grid_width_is_the_sum_of_the_column_tokens(self):
        """One arithmetic statement for the block, so the tokens cannot half-migrate."""
        from view.delegates.playlist_delegate import DATA_COLUMNS_WIDTH

        self.assertEqual(
            COLUMN_DURATION_WIDTH + 2 * COLUMN_TEXT_WIDTH + 3 * COLUMN_GAP,
            DATA_COLUMNS_WIDTH,
            'the delegate counts a different block than the tokens describe')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class ColumnTokenTest(unittest.TestCase):
    """The two column tokens against this host's real font metrics."""

    def test_the_column_widths_hold_the_values_they_promise(self):
        from PyQt6.QtGui import QFontMetrics

        from view.widgets.playlist_view import PlaylistView

        app = make_app()
        view = PlaylistView(make_manager('light'))
        try:
            metrics = QFontMetrics(view._list_view.font())
            mm_ss = metrics.horizontalAdvance('3:25')
            self.assertGreaterEqual(
                COLUMN_DURATION_WIDTH, mm_ss,
                f'a MM:SS needs {mm_ss}px and the duration column is '
                f'{COLUMN_DURATION_WIDTH}px: every value would be elided')
            self.assertLess(
                COLUMN_DURATION_WIDTH, metrics.horizontalAdvance('1:02:03'),
                'the column is now wide enough for HH:MM:SS, so the delegate '
                'comment about the elided long value needs updating')
            # One CJK glyph is the widest thing an artist name averages; a column
            # narrower than eight of them cannot show a name at all.
            self.assertGreaterEqual(
                COLUMN_TEXT_WIDTH, 8 * metrics.horizontalAdvance('音'),
                'the text columns cannot hold eight CJK glyphs')
        finally:
            view.close()
            view.deleteLater()


class MetadataCellRuleTest(unittest.TestCase):
    """What each cell says -- the pure half of the delegate, no painter needed.

    These are the assertions the offscreen font cannot make on pixels (both marks
    rasterise to the same box on this host, see the module docstring), and they
    are the ones that carry the three rulings: the folder's blank cells, the
    state winning over a self-contradicting row (B4-R17), and the three cells
    being independent inside a known row.
    """

    def setUp(self):
        self._previous_locale = i18n.get_current_locale()

    def tearDown(self):
        # Every test here flips the locale to check both files, and i18n's
        # current locale is process-global state the rest of the suite reads.
        i18n.set_locale(self._previous_locale)

    def _cells(self, state, duration=None, artist=None, album=None, folder=False):
        from view.delegates.playlist_delegate import metadata_cells

        return metadata_cells(state=state, duration=duration, artist=artist,
                              album=album, is_folder=folder)

    def test_pending_paints_the_pending_mark_in_all_three_cells(self):
        for locale in ('zh_CN', 'en_US'):
            i18n.set_locale(locale)
            with self.subTest(locale=locale):
                self.assertEqual(
                    (PENDING_MARK,) * 3,
                    self._cells(STATE_PENDING, 205.0, 'Aa', 'Bbb'),
                    'a pending row paints something other than the pending mark')

    def test_unknown_paints_the_unknown_mark_in_all_three_cells(self):
        for locale in ('zh_CN', 'en_US'):
            i18n.set_locale(locale)
            with self.subTest(locale=locale):
                self.assertEqual(
                    (UNKNOWN_MARK,) * 3,
                    self._cells(STATE_UNKNOWN, 205.0, 'Aa', 'Bbb'))

    def test_known_paints_the_values_and_formats_the_duration(self):
        from view.time_format import format_time

        cells = self._cells(STATE_KNOWN, 205.0, 'Aa', 'Bbb')
        self.assertEqual(('3:25', 'Aa', 'Bbb'), cells)
        self.assertEqual(
            format_time(205.0), cells[0],
            'the duration cell is not the shared formatter\'s output')

    def test_a_known_row_marks_only_the_field_that_has_no_value(self):
        self.assertEqual(('3:25', 'Aa', UNKNOWN_MARK),
                         self._cells(STATE_KNOWN, 205.0, 'Aa', None))
        self.assertEqual((UNKNOWN_MARK, UNKNOWN_MARK, UNKNOWN_MARK),
                         self._cells(STATE_KNOWN))
        # ``duration=0.0`` and ``artist=''`` are answers, not absences (ruling
        # B4-R8), and the cell must show them rather than a mark.
        self.assertEqual(('0:00', '', UNKNOWN_MARK),
                         self._cells(STATE_KNOWN, 0.0, '', None))

    def test_the_state_wins_over_a_self_contradicting_row(self):
        """B4-R17: the queue can carry values with a state that denies them.

        ``apply_metadata`` writes both halves, but a row re-queued by a refresh
        keeps its values and goes back to ``pending`` -- and the display layer
        reads the state, never the values. Both directions are pinned: pending
        must not leak a value, and unknown must not leak one either.
        """
        self.assertEqual((PENDING_MARK,) * 3,
                         self._cells(STATE_PENDING, 205.0, 'Aa', 'Bbb'))
        self.assertEqual((UNKNOWN_MARK,) * 3,
                         self._cells(STATE_UNKNOWN, 205.0, 'Aa', 'Bbb'))

    def test_a_folder_row_owns_no_cells_at_all(self):
        """The state is ``pending`` here and *stays* pending -- so the rule is ``is_folder``.

        A folder header has no ``full_path`` for the store to answer about, so
        every folder would paint a row of ``⋯`` if this keyed on the state.
        ``None`` means "paint nothing", not "paint the unknown mark".
        """
        for state in (STATE_PENDING, STATE_UNKNOWN, STATE_KNOWN):
            with self.subTest(state=state):
                self.assertEqual(
                    (None, None, None),
                    self._cells(state, 205.0, 'Aa', 'Bbb', folder=True),
                    f'a folder row painted cells under state {state!r}')

    def test_an_unrecognised_state_word_paints_the_unknown_mark(self):
        """Never a blank: an empty cell is the folder's answer, not a fallback's."""
        self.assertEqual((UNKNOWN_MARK,) * 3, self._cells('what-is-this'))

    def test_the_two_marks_are_different_strings(self):
        """The pixel host cannot show this, so the string says it.

        Both marks are single characters, and this host's offscreen font gives
        every single character the same hollow box (measured -- ``M``, ``x``,
        ``⋯`` and ``—`` share one 28-pixel set), so a grab cannot separate them.
        The claim "a reader can tell pending from unknown" is therefore about
        the two glyphs being different glyphs, which is what fails if either
        locale file is edited into the same character.
        """
        for locale in ('zh_CN', 'en_US'):
            i18n.set_locale(locale)
            with self.subTest(locale=locale):
                pending = i18n.get('meta.pending')
                unknown = i18n.get('meta.unknown')
                self.assertNotIn('[MISSING', pending + unknown)
                self.assertTrue(pending and unknown)
                self.assertNotEqual(
                    pending, unknown,
                    f'{locale}: meta.pending and meta.unknown are both '
                    f'{ascii(pending)} -- the two states look identical')

    def test_the_two_marks_are_the_recorded_code_points(self):
        for locale in ('zh_CN', 'en_US'):
            i18n.set_locale(locale)
            with self.subTest(locale=locale):
                self.assertEqual(PENDING_MARK, i18n.get('meta.pending'))
                self.assertEqual(UNKNOWN_MARK, i18n.get('meta.unknown'))


class TimeFormatSharedTest(unittest.TestCase):
    """``format_time`` lives in ``view/time_format.py`` exactly once."""

    def test_format_time_formats_the_documented_shapes(self):
        from view.time_format import format_time

        for seconds, expected in ((-1, '0:00'), (0, '0:00'), (59.9, '0:59'),
                                  (65, '1:05'), (205, '3:25'),
                                  (3600, '1:00:00'), (3723, '1:02:03')):
            self.assertEqual(expected, format_time(seconds), f'{seconds}s')

    def test_there_is_only_one_implementation_in_the_tree(self):
        """The brief's "no two copies" rule, checked on the sources."""
        root = Path(__file__).resolve().parent.parent
        owners = sorted(
            str((root / relative).relative_to(root))
            for relative in ('view/time_format.py',
                             'view/widgets/bottom_panel.py',
                             'view/delegates/playlist_delegate.py')
            if 'def format_time' in (root / relative).read_text(encoding='utf-8')
        )
        self.assertEqual(
            [str(Path('view') / 'time_format.py')], owners,
            f'{owners} define format_time: the formatter has a second copy')

    def test_bottom_panel_and_the_delegate_import_the_one_copy(self):
        from view import time_format
        from view.delegates import playlist_delegate
        from view.widgets import bottom_panel

        self.assertIs(time_format.format_time, bottom_panel.format_time,
                      'bottom_panel no longer uses the shared formatter')
        self.assertIs(time_format.format_time, playlist_delegate.format_time,
                      'the delegate no longer uses the shared formatter')


@unittest.skipUnless(QT_AVAILABLE, 'PyQt6 not installed')
class PlaylistHeaderTest(unittest.TestCase):
    """The header band that took over the old ``#playlistHeader`` label.

    Two directions are checked here because the batch's own guard is bidirectional
    (``tests/test_view_structure.py`` / ``tests/test_theme_qss.py``): every new
    name must be styled *and* worn, and the name that left must be gone from the
    tree, the registration tuple and the sheet -- an unregistered leftover is what
    the brief forbids.
    """

    def setUp(self):
        self.app = make_app()
        self._saved_palette = self.app.palette()
        self._previous_locale = i18n.get_current_locale()
        self._widgets = []

    def tearDown(self):
        i18n.set_locale(self._previous_locale)
        for widget in self._widgets:
            widget.close()
            widget.deleteLater()
        self.app.setPalette(self._saved_palette)

    def _header(self, mode='light', locale='en_US', width=VIEW_WIDTH):
        """A shown ``PlaylistView``'s header row, with the sheet applied.

        ``apply_to`` is what makes the sheet's font reach the labels, so the
        "does the word fit its column" measurement below is measuring the shipped
        typography rather than the default font.
        """
        from view.widgets.playlist_view import PlaylistView

        i18n.set_locale(locale)
        manager = make_manager(mode)
        manager.apply_to(self.app)
        view = PlaylistView(manager)
        self._widgets.append(view)
        view.resize(width, 200)
        view.show()
        self.app.processEvents()
        header = view.findChild(QWidget, 'playlistHeaderRow')
        self.assertIsNotNone(header, '#playlistHeaderRow is not in the tree')
        return view, header

    def test_the_row_carries_the_four_column_labels_in_order(self):
        from PyQt6.QtWidgets import QLabel

        from core.theme_qss import REQUIRED_OBJECT_NAMES
        from view.widgets.playlist_view import HEADER_COLUMNS

        _view, header = self._header()
        names = [name for name, _key, _width, _align in HEADER_COLUMNS]
        self.assertEqual(
            ['colName', 'colDuration', 'colArtist', 'colAlbum'], names,
            'the header column table is the mandate, spelled in this order')
        for name in names:
            self.assertIn(name, REQUIRED_OBJECT_NAMES,
                          f'#{name} is worn but not registered')
            self.assertIsNotNone(
                header.findChild(QLabel, name),
                f'#{name} is not a label under the header row')

        # Left to right, no overlap: the band has to describe the grid it labels.
        labels = [header.findChild(QLabel, name) for name in names]
        rects = [label.geometry() for label in labels]
        for first, second in zip(rects, rects[1:]):
            self.assertLess(first.right(), second.left(),
                            f'{first} and {second} are not two columns')
        self.assertGreaterEqual(rects[0].left(), SPACE_2,
                                'the name heading ignores the row inset')

    def test_the_fixed_columns_are_the_column_tokens(self):
        from PyQt6.QtWidgets import QLabel

        _view, header = self._header()
        by_name = {name: header.findChild(QLabel, name)
                   for name in ('colName', 'colDuration', 'colArtist',
                                'colAlbum')}
        self.assertEqual(COLUMN_DURATION_WIDTH, by_name['colDuration'].width())
        self.assertEqual(COLUMN_TEXT_WIDTH, by_name['colArtist'].width())
        self.assertEqual(COLUMN_TEXT_WIDTH, by_name['colAlbum'].width())
        self.assertGreater(by_name['colName'].width(), COLUMN_TEXT_WIDTH,
                           'the name column is not taking the remainder')

        # Alignments mirror the delegate: duration flush right, text flush left.
        for name, flag in (('colDuration', 'AlignRight'),
                          ('colArtist', 'AlignLeft'),
                          ('colAlbum', 'AlignLeft'),
                          ('colName', 'AlignLeft')):
            self.assertTrue(
                int(by_name[name].alignment())
                & int(getattr(Qt.AlignmentFlag, flag)),
                f'#{name} is not {flag}: the heading sits over the wrong column')

    def test_every_heading_word_fits_its_own_column_in_both_locales(self):
        """The claim the 56px duration column is allowed to make at 13px type.

        A heading that does not fit its band is elided over its own column, which
        is the defect ``COLUMN_DURATION_WIDTH`` would otherwise hide: the value
        column is sized for ``MM:SS``, not for the word that names it.
        """
        for locale in ('en_US', 'zh_CN'):
            for mode in ('light', 'dark'):
                with self.subTest(locale=locale, mode=mode):
                    _view, header = self._header(mode=mode, locale=locale)
                    for name in ('colName', 'colDuration', 'colArtist',
                                 'colAlbum'):
                        label = header.findChild(QWidget, name)
                        self.assertLessEqual(
                            label.sizeHint().width(), label.width() + 1,
                            f'#{name} wants {label.sizeHint().width()}px of '
                            f'{ascii(label.text())} in a {label.width()}px column '
                            f'({locale}, {mode})')
                        self.assertFalse(
                            label.text().startswith('[MISSING'),
                            f'#{name} has no locale value under {locale}')

    def test_the_data_headings_hide_with_the_data_columns(self):
        """One question, asked once: the header never names a hidden grid."""
        from view.delegates.playlist_delegate import metadata_columns_fit

        for width in (VIEW_WIDTH, NARROW_VIEW_WIDTH):
            view, header = self._header(width=width)
            list_view = view._list_view
            fits = metadata_columns_fit(list_view.viewport().width())
            for name in ('colDuration', 'colArtist', 'colAlbum'):
                label = header.findChild(QWidget, name)
                self.assertEqual(
                    fits, label.isVisibleTo(header),
                    f'#{name} visible={label.isVisibleTo(header)} while the row '
                    f'grid fits={fits} at a {width}px view')
            self.assertTrue(
                header.findChild(QWidget, 'colName').isVisibleTo(header),
                'the name heading disappeared with the data headings')

    def test_the_old_single_label_left_no_unregistered_residue(self):
        """Tree, tuple and sheet all lost ``playlistHeader`` together."""
        from core.theme import AlphaSettings, DARK, LIGHT
        from core.theme_qss import REQUIRED_OBJECT_NAMES, build_qss
        from view.widgets.playlist_view import PlaylistView

        self.assertNotIn(
            'playlistHeader', REQUIRED_OBJECT_NAMES,
            'the tuple still registers the retired heading, which would make the '
            'tree-side guard demand a widget that no longer exists')

        view, _header = self._header()
        self.assertIsNone(
            view.findChild(QWidget, 'playlistHeader'),
            '#playlistHeader is still in the tree next to the new row: 方案 P '
            'moves the heading, it does not stack a second one')

        for label, tokens in (('LIGHT', LIGHT), ('DARK', DARK)):
            qss = build_qss(tokens, AlphaSettings())
            with self.subTest(theme=label):
                self.assertNotIn('#playlistHeader {', qss)
                self.assertNotIn('#playlistHeader,', qss)
                self.assertNotIn('#playlistHeader:', qss)
                self.assertIn('#playlistHeaderRow {', qss,
                              'the band lost its surface_header fill')


class HeaderLocaleKeyTest(unittest.TestCase):
    """The four column words exist, in both files, and name four different things."""

    def setUp(self):
        self._previous_locale = i18n.get_current_locale()

    def tearDown(self):
        i18n.set_locale(self._previous_locale)

    def test_the_column_keys_resolve_in_both_locales(self):
        for locale in ('zh_CN', 'en_US'):
            i18n.set_locale(locale)
            words = []
            for key in ('col.name', 'col.duration', 'col.artist', 'col.album'):
                value = i18n.get(key)
                self.assertNotIn('[MISSING', value,
                                 f'{key} missing from main.{locale}.properties')
                self.assertTrue(value, f'{key} is empty under {locale}')
                words.append(value)
            self.assertEqual(
                4, len(set(words)),
                f'{locale}: the four headings are not four words -- {words}')


class PositionReservationInvariantTest(unittest.TestCase):
    """The falsifiability mutation ① was meant to buy, bought back from the test side.

    Step 5 asks for two single-variable mutations. The harness refused the edit to
    :mod:`view.delegates.playlist_delegate` (a production file), and the brief's
    rule for that is explicit: do not retry, do not route around it. So the claim
    mutation ① would have made red -- "if the title stopped giving way to the
    position, the overlong row's ink would collide" -- is pinned here instead, as
    an invariant of the one function :meth:`PlaylistItemDelegate.paint` uses for
    that reservation. The mutant's shape is ``budget == 0``: the title is elided
    against the whole block and paints under the muted text, and both assertions
    below are what the shipped product keeps true and that shape breaks.

    :meth:`OverlongRowTest.test_long_name_long_position_and_long_columns_fit_without_overflow`
    is the pixel half of the same claim (it measures the gap between the two inks),
    and it is the reason this function exists as a function: inline in ``paint``
    the arithmetic could only be observed through a grab.
    """

    def test_the_pair_never_needs_more_room_than_the_block_has(self):
        """The one invariant the collision assertion rests on.

        Whatever the position's advance, the reserved footnote, the one ``SPACE_2``
        of gutter and the title's own room add up to no more than the block, and
        the title keeps its floor. A reservation that was deleted (Step 5's
        mutation ①) is the shape that breaks the second half of this pair, and
        :meth:`OverlongRowTest.test_the_reservation_is_what_the_gap_measures`
        shows the pixels breaking with it.
        """
        from view.delegates.playlist_delegate import (
            MIN_TITLE_WIDTH,
            position_budget,
        )

        for block in (96, 200, 302, 640):
            for advance in (0, 12, 72, 120, 4000):
                budget = position_budget(block, advance)
                name_avail = max(0, block - budget - SPACE_2)
                with self.subTest(block=block, advance=advance):
                    self.assertLessEqual(
                        budget + SPACE_2 + name_avail, block,
                        'the reservation lets the pair need more room than the '
                        'block has, which is the collision in the other direction')
                    self.assertGreaterEqual(
                        name_avail, min(MIN_TITLE_WIDTH, block - SPACE_2),
                        'the title lost its floor to the position text')

    def test_a_position_within_the_cap_is_reserved_in_full(self):
        """A footnote that fits is not shrunk, and a longer one only ever takes more."""
        from view.delegates.playlist_delegate import position_budget

        for block in (96, 200, 302, 640):
            cap = position_budget(block, 10_000)
            self.assertGreater(cap, 0, f'a {block}px block gives the footnote no '
                                      'room at all, so it is never painted')
            self.assertLessEqual(cap, block // 2,
                                 'the footnote took more than half the block')
            for advance in (0, 12, cap // 2, cap):
                with self.subTest(block=block, advance=advance):
                    self.assertEqual(
                        advance, position_budget(block, advance),
                        'a position inside its cap was not reserved in full: the '
                        'title is elided against ground the muted text will still '
                        'be painted on')
            self.assertLessEqual(position_budget(block, 12),
                                 position_budget(block, 120),
                                 'a longer position got less room')

    def test_a_position_too_long_for_the_block_elides_on_itself(self):
        from view.delegates.playlist_delegate import (
            MIN_TITLE_WIDTH,
            position_budget,
        )

        for block in (96, 200, 302, 640):
            budget = position_budget(block, 10_000)
            name_avail = max(0, block - budget - SPACE_2)
            with self.subTest(block=block):
                self.assertGreater(
                    budget, 0,
                    'a fifty-segment library path was given no room at all, so '
                    'the position text is not being painted either')
                self.assertGreaterEqual(
                    name_avail, min(MIN_TITLE_WIDTH, block - SPACE_2),
                    'the title lost its floor to the position text')
                self.assertLessEqual(
                    budget, block // 2,
                    'the footnote took more than half the block: the title is the '
                    'column a user scans, and an overlong path may not delete it')

    def test_the_folder_rule_has_one_author(self):
        """Mutation ②'s claim, likewise: the cells come from one function.

        ``grep`` is the tool for this and it is run here rather than in prose: the
        folder row's emptiness is decided in :func:`metadata_cells` and nowhere
        else, so no second branch can start painting ``—`` into a folder's cells
        while the rule still says ``None``. Task 8's paint path calls that one
        function and skips every ``None`` cell.
        """
        root = Path(__file__).resolve().parent.parent
        source = (root / 'view' / 'delegates' / 'playlist_delegate.py').read_text(
            encoding='utf-8')
        self.assertEqual(
            1, source.count('def metadata_cells'),
            'a second cell rule appeared in the delegate')
        self.assertEqual(
            1, source.count('is_folder: bool = False'),
            'the folder rule was forked into a second signature')
        self.assertIn('metadata_cells(state=state', source,
                      'paint no longer asks the one rule what the cells say')


if __name__ == '__main__':
    unittest.main(verbosity=2)
