#!/usr/bin/env python3
"""
Playlist Context Menu - pure builder for the playlist right-click menu

Batch 3 Task 2, spec §3. The menu construction lives here rather than in
``PlaylistView`` because the view already carries the selection mode, the
display-index semantics and the event routing; the menu is a second job, and
pulling it out is what lets it be built and asserted with no window at all.

Contract:

* ``target_indices`` is the *resolved* target Task 3 works out with the
  Windows-Explorer rule of spec §4.3 (cursor row outside the selection acts on
  that row alone; inside it, acts on the whole selection). This function takes
  it as given: no selection model, no indices of its own.
* An empty target returns ``None``, not an empty ``QMenu``. "No menu over the
  blank area" (spec §4.3, Review Focus 5) is this function's job to express;
  an empty menu would still pop.
* Nothing is wired up here. The caller reads ``QAction.data()`` -- one of
  ``MENU_PLAY`` / ``MENU_REMOVE`` / ``MENU_CLEAR`` -- to decide what a trigger
  means, and emits the view's signals. Keeping the triggers out is what makes
  this testable without a presenter.

Ownership: the returned menu is parented to ``parent``, so it lives until that
widget dies. A caller that builds one per event must delete it when the popup
closes, or every right-click leaves another ``QMenu`` behind.

Copy goes through i18n (spec §7): the keys are the ``ctx.*`` block of
``locales/interface/main.{zh_CN,en_US}.properties`` -- ``ctx.`` rather than
``menu.`` per ruling R5, because ``menu.*`` is the menu-bar block batch 2
retired and mixing new copy into it would turn that cleanup into a per-key
audit. No English literal appears below for exactly that reason.
"""

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QMenu, QWidget

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import i18n

# Menu ids: the value each action carries in ``QAction.data()``. Task 3 routes
# on these, so they are the module's public vocabulary -- an action without one
# is an action nobody can dispatch.
MENU_PLAY = 'play'
MENU_REMOVE = 'remove'
MENU_CLEAR = 'clear'

MENU_IDS: tuple[str, ...] = (MENU_PLAY, MENU_REMOVE, MENU_CLEAR)

# Object name on every entry, so a test (or, later, a style) can pick the menu's
# items out of a widget tree without naming each one.
_ITEM_OBJECT_NAME = 'menuItem'


def _add_item(menu: QMenu, label: str, menu_id: str):
    """Append one entry carrying its id and the shared object name."""
    action = menu.addAction(label)
    action.setObjectName(_ITEM_OBJECT_NAME)
    action.setData(menu_id)
    return action


def build_playlist_menu(target_indices: list[int], target_is_playing: bool,
                        parent: QWidget) -> Optional[QMenu]:
    """Build the right-click menu for ``target_indices``.

    Args:
        target_indices: The display indices the menu acts on, already resolved
            by the caller (spec §4.3). Order is left as given; only the length
            matters here.
        target_is_playing: Whether the target is the currently playing row.
            The first entry is the play/pause toggle either way -- the label
            changes, the id (``MENU_PLAY``) does not, because it is one action
            in two states.
        parent: Ownership parent for the returned ``QMenu``.

    Returns:
        The menu, or ``None`` when there is no target and therefore no menu.
    """
    indices = list(target_indices)
    if not indices:
        return None

    menu = QMenu(parent)

    # 1. Play / pause.
    toggle_label = (i18n.get('ctx.pause') if target_is_playing
                    else i18n.get('ctx.play'))
    _add_item(menu, toggle_label, MENU_PLAY)

    # 2. Remove: the single-row copy for one row, the counted copy for a batch,
    # so a three-row target cannot read like it removes one track.
    count = len(indices)
    remove_label = (i18n.get('ctx.remove') if count == 1
                    else i18n.get('ctx.remove_count', count=count))
    _add_item(menu, remove_label, MENU_REMOVE)

    # 3. Clear, last and separated: it acts on the whole playlist, not on the
    # target, so it must not sit adjacent to the two target actions.
    menu.addSeparator()
    _add_item(menu, i18n.get('ctx.clear_playlist'), MENU_CLEAR)

    return menu
