# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Library folders ("collections" in the UI) inside a graph bundle.

A v2 bundle lists its folders after the graphs, parents first. An export carries the folders the
exported graphs sit in plus their ancestors (every folder, empty ones too, when the whole library
is exported). An import places them before the graphs:

* ``new_ids``: every folder gets a new id, but a sibling with the same name (NFC + case-folded)
  under the same new parent is REUSED, so importing the same bundle twice never doubles the tree.
  The returned map says where the graphs of each bundle folder land.
* ``keep_ids``: each folder is stored with its own id (``put_folder``); an id the store already has
  is reused. A parent that was refused is replaced by the nearest folder stored above it.

A folder that cannot be stored (a bad record, the count or depth limit, a name clash, a parent
chain that never reaches the top) is reported by its position in the bundle and never blocks the
others: its graphs land in the nearest folder that was stored above it, else at the top level.
Messages never echo the input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from sankey_studio.errors import (
    BundleError,
    ConflictError,
    FolderNameTakenError,
    FolderRuleError,
    NotFoundError,
    StorageError,
)
from sankey_studio.models import FOLDERS_MAX, FolderCreate, FolderDefinition
from sankey_studio.storage.base import upgrade_doc
from sankey_studio.storage.common import validation_lines
from sankey_studio.storage.folder_tree import closure, name_key, order_parents_first

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from sankey_studio.storage.folders_base import FolderRepository

__all__ = [
    "FOLDER_ROOT",
    "MSG_CYCLE",
    "FolderImport",
    "export_folders",
    "folder_items",
    "import_folders",
    "select_folders",
]

#: Location label of an error that belongs to a bundle folder as a whole (the UI word).
FOLDER_ROOT: Final = "collection"
MSG_CYCLE: Final = "its parent chain never reaches the top level"
#: What a store refuses on purpose when a folder is created: the parent vanished, the depth or
#: count limit, or a sibling took the name between the check and the write.
_REFUSED: Final = (FolderRuleError, FolderNameTakenError, NotFoundError)


@dataclass(slots=True)
class FolderImport:
    """What an import of the folders did.

    ``placed`` maps a bundle folder id to the id its graphs land in (``None`` is the top level,
    and is also the answer for an id the bundle does not hold); ``created`` counts the folders
    that did not exist before; ``failures`` are ``(position in the bundle, reason)``.
    """

    placed: dict[str | None, str | None] = field(default_factory=lambda: {None: None})
    created: int = 0
    failures: list[tuple[int, str]] = field(default_factory=list)


# --------------------------------------------------------------------------- export


def select_folders(
    items: Sequence[FolderDefinition], used: Collection[str | None] | None
) -> list[FolderDefinition]:
    """The folders an export carries, parents first.

    ``used=None`` is the whole library (empty folders too). Otherwise the folders named in
    ``used`` plus all their ancestors; ``None`` (top level) and ids that name no folder add none.
    """
    if used is None:
        return order_parents_first(items)
    return closure(items, {folder_id for folder_id in used if folder_id is not None})


def export_folders(
    repo: FolderRepository | None, used: Collection[str | None] | None
) -> list[dict[str, Any]]:
    """``select_folders`` of ``repo`` as JSON dumps; no repository means no folders."""
    if repo is None:
        return []
    return [f.model_dump(mode="json") for f in select_folders(repo.list_definitions(), used)]


# --------------------------------------------------------------------------- import


def folder_items(bundle: dict[str, Any]) -> list[object]:
    """The ``folders`` list of a bundle (an absent key is an empty list); ``BundleError`` else."""
    folders = bundle.get("folders", [])
    if not isinstance(folders, list):
        raise BundleError("The bundle has no list of collections")
    if len(folders) > FOLDERS_MAX:
        raise BundleError(f"A bundle may hold at most {FOLDERS_MAX} collections")
    return folders


def _parse(item: object) -> FolderDefinition | str:
    """The folder, or the reason it cannot be used (never the input itself)."""
    if not isinstance(item, dict):
        return "not an object"
    try:
        return FolderDefinition.model_validate(upgrade_doc(item, "folder"))
    except StorageError as exc:  # an unusable schema_version
        return exc.message
    except ValidationError as exc:
        lines = validation_lines(exc, FOLDER_ROOT)
        more = f" (+{len(lines) - 1} more)" if len(lines) > 1 else ""
        return lines[0] + more


def _reachable(ordered: Sequence[FolderDefinition]) -> set[str]:
    """The ids whose parent chain ends at the top level (``ordered`` is parents first).

    A parent the bundle does not hold counts as the top level; members of a cycle, and everything
    below them, are left out.
    """
    held = {folder.id for folder in ordered}
    reached: set[str] = set()
    for folder in ordered:
        if folder.parent_id is None or folder.parent_id not in held or folder.parent_id in reached:
            reached.add(folder.id)
    return reached


class _Placer:
    """Stores the folders of a bundle one by one and remembers where each one landed."""

    def __init__(self, repo: FolderRepository, *, keep_ids: bool) -> None:
        self._repo = repo
        self._keep_ids = keep_ids
        self.out = FolderImport()
        # (parent, name key) -> id of the folder already there; only a new_ids import reuses them
        self._siblings: dict[tuple[str | None, str], str] = {}
        if not keep_ids:
            for stored in repo.list_definitions():
                self._siblings[stored.parent_id, name_key(stored.name)] = stored.id

    def place(self, folder: FolderDefinition) -> None:
        """Store ``folder``. When the store refuses it, its graphs fall back to its parent's place
        and the refusal (``_REFUSED``) propagates to the caller."""
        parent = self.out.placed.get(folder.parent_id)
        self.out.placed[folder.id] = parent
        landed = self._put(folder) if self._keep_ids else self._create(folder, parent)
        self.out.placed[folder.id] = landed

    def _put(self, folder: FolderDefinition) -> str:
        parent = self.out.placed.get(folder.parent_id, folder.parent_id)
        if parent != folder.parent_id:  # the parent was refused: sit where its graphs landed
            folder = FolderDefinition.model_validate({**folder.model_dump(), "parent_id": parent})
        try:
            self._repo.put_folder(folder)
        except ConflictError:  # the id is already there: use that folder
            return folder.id
        self.out.created += 1
        return folder.id

    def _create(self, folder: FolderDefinition, parent: str | None) -> str:
        key = (parent, name_key(folder.name))
        if key in self._siblings:  # the same folder is already here (an earlier import)
            return self._siblings[key]
        made = self._repo.create_folder(FolderCreate(name=folder.name, parent_id=parent))
        self._siblings[key] = made.id
        self.out.created += 1
        return made.id


def import_folders(
    repo: FolderRepository, items: Sequence[object], *, keep_ids: bool
) -> FolderImport:
    """Store the valid folders of ``items`` (parents first) and report where each landed.

    A backend failure (``StorageError``) aborts the import; everything else a folder can run into
    is a ``FolderImport.failures`` entry.
    """
    placer = _Placer(repo, keep_ids=keep_ids)
    out = placer.out
    parsed: dict[str, tuple[int, FolderDefinition]] = {}
    for position, item in enumerate(items, start=1):
        folder = _parse(item)
        if isinstance(folder, str):
            out.failures.append((position, folder))
        else:
            parsed.setdefault(folder.id, (position, folder))
    ordered = order_parents_first([folder for _, folder in parsed.values()])
    reachable = _reachable(ordered)
    for folder in ordered:
        position = parsed[folder.id][0]
        if folder.id not in reachable:
            out.failures.append((position, MSG_CYCLE))
            continue
        try:
            placer.place(folder)
        except _REFUSED as exc:
            out.failures.append((position, exc.message))
    out.failures.sort(key=lambda failure: failure[0])
    return out
