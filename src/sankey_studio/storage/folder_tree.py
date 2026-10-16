# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The rules of the library folder tree ("collections" in the UI), as pure functions.

Both backends call these on the list of ALL folders, so a rule lives in exactly one place:
sibling names are unique (NFC + case-folded), a path is at most ``FOLDER_DEPTH_MAX`` levels deep,
there are at most ``FOLDERS_MAX`` folders and a folder never ends up below itself.

Nothing here does I/O. Every walk carries a visited set, so data that was edited by hand (or that
two racing writers left behind: A below B and B below A are each valid on their own) can never
loop: a folder in a cycle, or whose parent is missing, is listed as-is and read as a top-level one.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sankey_studio.errors import FolderNameTakenError, FolderRuleError, NotFoundError
from sankey_studio.models import FOLDER_DEPTH_MAX, FOLDERS_MAX, FolderDefinition, FolderSummary

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from collections.abc import Set as AbstractSet

MSG_NOT_FOUND = "Folder not found"
MSG_CYCLE = "A collection cannot be moved into itself or into one of its own collections"
MSG_DEPTH = f"Collections can be nested at most {FOLDER_DEPTH_MAX} levels deep"
MSG_COUNT = f"At most {FOLDERS_MAX} collections are allowed"
MSG_NAME_TAKEN = "A collection with this name already exists in the same place"


def name_key(name: str) -> str:
    """The form in which sibling names are compared: NFC, then case-folded."""
    return unicodedata.normalize("NFC", name).casefold()


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a folder is going: ``folder_id`` is ``None`` while it is being created."""

    folder_id: str | None
    parent_id: str | None
    name: str


def _by_id(items: Sequence[FolderDefinition]) -> dict[str, FolderDefinition]:
    return {item.id: item for item in items}


def _chain(by_id: Mapping[str, FolderDefinition], folder_id: str | None) -> list[FolderDefinition]:
    """``folder_id`` and its ancestors, nearest first; stops at a missing parent or a cycle."""
    chain: list[FolderDefinition] = []
    seen: set[str] = set()
    current = folder_id
    while current is not None and current in by_id and current not in seen:
        seen.add(current)
        chain.append(by_id[current])
        current = by_id[current].parent_id
    return chain


def depth_of(by_id: Mapping[str, FolderDefinition], folder_id: str | None) -> int:
    """Levels from the top down to ``folder_id`` itself: 0 for the top level, 1 for a top folder.

    Capped at ``FOLDER_DEPTH_MAX + 1``, so a cycle still answers "too deep".
    """
    return min(len(_chain(by_id, folder_id)), FOLDER_DEPTH_MAX + 1)


def path_of(items: Sequence[FolderDefinition], folder_id: str | None) -> list[FolderDefinition]:
    """The folders from the top down to ``folder_id`` (itself last); empty for an unknown id."""
    return _chain(_by_id(items), folder_id)[::-1]


def _levels(items: Sequence[FolderDefinition], folder_id: str) -> list[list[str]]:
    """Breadth-first levels of the subtree below ``folder_id``; level 0 is ``[folder_id]``."""
    children: dict[str, list[str]] = {}
    for item in items:
        if item.parent_id is not None:
            children.setdefault(item.parent_id, []).append(item.id)
    seen = {folder_id}
    levels = [[folder_id]]
    while True:
        below = [kid for fid in levels[-1] for kid in children.get(fid, ()) if kid not in seen]
        if not below:
            return levels
        seen.update(below)
        levels.append(below)


def subtree_height(items: Sequence[FolderDefinition], folder_id: str) -> int:
    """Levels of the subtree rooted at ``folder_id``: 1 for a folder without sub-folders."""
    return len(_levels(items, folder_id))


def descendants(items: Sequence[FolderDefinition], folder_id: str) -> set[str]:
    """Every folder below ``folder_id`` (not itself), at any depth."""
    return {fid for level in _levels(items, folder_id)[1:] for fid in level}


def _check_parent(by_id: Mapping[str, FolderDefinition], parent_id: str | None) -> None:
    if parent_id is not None and parent_id not in by_id:
        raise NotFoundError(MSG_NOT_FOUND)


def _check_cycle(items: Sequence[FolderDefinition], place: Placement) -> None:
    if place.folder_id is None or place.parent_id is None:
        return
    if place.parent_id == place.folder_id or place.parent_id in descendants(items, place.folder_id):
        raise FolderRuleError(MSG_CYCLE)


def _check_depth(items: Sequence[FolderDefinition], place: Placement) -> None:
    by_id = _by_id(items)
    own = 1 if place.folder_id not in by_id else subtree_height(items, place.folder_id)
    if depth_of(by_id, place.parent_id) + own > FOLDER_DEPTH_MAX:
        raise FolderRuleError(MSG_DEPTH)


def check_name_free(
    items: Sequence[FolderDefinition], parent_id: str | None, name: str, own_id: str | None
) -> None:
    """``FolderNameTakenError`` when ANOTHER folder of ``parent_id`` has the same name key.

    Siblings are compared by their EFFECTIVE parent: a folder whose parent is missing sits at the
    top level, so it clashes with a top-level name (and the other way round).
    """
    key = name_key(name)
    known = {item.id for item in items}
    where = effective(parent_id, known)
    for item in items:
        if item.id == own_id or name_key(item.name) != key:
            continue
        if effective(item.parent_id, known) == where:
            raise FolderNameTakenError(MSG_NAME_TAKEN)


def requested_parent(
    items: Sequence[FolderDefinition], current: FolderDefinition, parent_id: str | None
) -> str | None:
    """The parent an update really asks for.

    A folder whose stored parent is missing reads as a top-level one. When an update repeats that
    missing parent (a rename that sends the listed ``parent_id`` back), it is healed to the top
    level instead of failing with "not found"; moving to a different missing parent still fails.
    """
    dangling = parent_id is not None and parent_id == current.parent_id
    if dangling and all(item.id != parent_id for item in items):
        return None
    return parent_id


def validate_placement(items: Sequence[FolderDefinition], place: Placement) -> None:
    """The parent exists, no cycle, not too deep, the name is free: checked in that order."""
    _check_parent(_by_id(items), place.parent_id)
    _check_cycle(items, place)
    _check_depth(items, place)
    check_name_free(items, place.parent_id, place.name, place.folder_id)


def validate_new_count(items: Sequence[FolderDefinition]) -> None:
    """Refuse a new folder when the store already holds ``FOLDERS_MAX``."""
    if len(items) >= FOLDERS_MAX:
        raise FolderRuleError(MSG_COUNT)


def reparent_plan(
    items: Sequence[FolderDefinition], folder_id: str
) -> list[tuple[str, str | None]]:
    """``(child id, new parent)`` for each sub-folder of ``folder_id`` once it is deleted.

    The children move to the parent of the deleted folder. ``FolderNameTakenError`` when one of
    them has the name of a folder that already sits there.
    """
    by_id = _by_id(items)
    target = by_id[folder_id].parent_id if folder_id in by_id else None
    taken = {
        name_key(item.name) for item in items if item.parent_id == target and item.id != folder_id
    }
    plan: list[tuple[str, str | None]] = []
    for item in items:
        if item.parent_id != folder_id:
            continue
        if name_key(item.name) in taken:
            raise FolderNameTakenError(MSG_NAME_TAKEN)
        plan.append((item.id, target))
    return plan


def effective(folder_id: str | None, known: AbstractSet[str]) -> str | None:
    """Where a graph really sits: a ``folder_id`` that names no folder reads as the top level."""
    return folder_id if folder_id in known else None


def with_counts(
    items: Sequence[FolderDefinition], graph_counts: Mapping[str | None, int]
) -> list[FolderSummary]:
    """One ``FolderSummary`` per folder in ``(name key, id)`` order.

    ``graph_counts`` maps an EFFECTIVE folder id (``None`` = top level) to its number of graphs.
    """
    children: dict[str, int] = {}
    for item in items:
        if item.parent_id is not None:
            children[item.parent_id] = children.get(item.parent_id, 0) + 1
    ordered = sorted(items, key=lambda item: (name_key(item.name), item.id))
    return [
        FolderSummary(
            id=item.id,
            name=item.name,
            parent_id=item.parent_id,
            revision=item.revision,
            updated_at=item.updated_at,
            graph_count=graph_counts.get(item.id, 0),
            child_count=children.get(item.id, 0),
        )
        for item in ordered
    ]


def order_parents_first(items: Sequence[FolderDefinition]) -> list[FolderDefinition]:
    """``items`` so that every folder comes after its parent (stable; cycle members come last).

    A folder whose parent is not in ``items`` counts as a top-level one.
    """
    ids = {item.id for item in items}
    placed: dict[str, FolderDefinition] = {}
    pending = list(items)
    while pending:
        ready = [
            item
            for item in pending
            if item.parent_id is None or item.parent_id not in ids or item.parent_id in placed
        ]
        if not ready:
            break
        placed.update((item.id, item) for item in ready)
        pending = [item for item in pending if item.id not in placed]
    return [*placed.values(), *pending]


def closure(items: Sequence[FolderDefinition], wanted: Collection[str]) -> list[FolderDefinition]:
    """The folders named in ``wanted`` plus all their ancestors, parents first (bundle export)."""
    by_id = _by_id(items)
    keep = {item.id for fid in wanted for item in _chain(by_id, fid)}
    return order_parents_first([item for item in items if item.id in keep])
