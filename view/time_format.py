#!/usr/bin/env python3
"""The one ``MM:SS`` / ``HH:MM:SS`` formatter the view layer owns.

Batch 4 Task 8 lifted this out of :mod:`view.widgets.bottom_panel` because the
playlist's duration column needs the same spelling of a length, and two copies
of a time formatter is exactly the logic-block duplication this batch forbids:
the progress row would say ``1:05`` and the playlist ``01:05`` for the same
number, and nothing would notice until a user did.

``bottom_panel`` keeps re-exporting the name (``from view.time_format import
format_time``), so the import path it has always had still resolves -- and
``tests/test_playlist_columns.py::TimeFormatSharedTest`` pins both halves of
that: exactly one ``def format_time`` in the tree, and both consumers bound to
the same function object.

Pure Python, no Qt: like :mod:`core.theme`, this is a value formatter, so it can
be tested without a display.
"""


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS.

    A negative value is "nothing has played yet", not a sign to print, so it
    reads as ``0:00``. Sub-second input is truncated, not rounded: ``59.9`` is
    still ``0:59``, which is what a progress row that has not reached the minute
    has always said.
    """
    if seconds < 0:
        return "0:00"

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
