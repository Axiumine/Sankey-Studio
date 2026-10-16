# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``FileFolderRepository``: library folders in ``<graphs dir>/folders.json``.

Shares the lock, the listing index and the directory of the ``FileGraphRepository`` of the same
directory (``locks.py``), so a folder change and a graph write exclude each other. Every
read-modify-write of the folders file runs inside ``with self._state.lock:``; the lock is NOT
re-entrant, so no locking public method is called from inside.

Deleting a folder moves its graphs up FIRST (one lock hold per graph) and drops the record
afterwards: a crash leaves a consistent tree and some graphs already moved up (a retry finishes),
while the reverse order would leave graphs pointing at a folder that is gone, which read as top
level, the wrong place. Locking is per process, so run ONE uvicorn worker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.errors import NotFoundError, StorageError
from sankey_studio.models import FolderDefinition, MoveReport
from sankey_studio.storage.atomic import check_writable, os_reason
from sankey_studio.storage.base import check_graph_id
from sankey_studio.storage.common import Clock, clamp_page, utc_now
from sankey_studio.storage.files import folder_members as members
from sankey_studio.storage.files.locks import open_state
from sankey_studio.storage.folder_tree import (
    MSG_NOT_FOUND,
    Placement,
    check_name_free,
    name_key,
    reparent_plan,
    requested_parent,
    validate_new_count,
    validate_placement,
    with_counts,
)
from sankey_studio.storage.folders_base import (
    check_folder_id,
    exists_error,
    new_folder_id,
    scope_id,
    stale_error,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sankey_studio.models import FolderCreate, FolderSummary, FolderUpdate, GraphSummary
    from sankey_studio.storage.files.locks import DirState


def _find(items: Sequence[FolderDefinition], folder_id: str) -> FolderDefinition:
    for item in items:
        if item.id == folder_id:
            return item
    raise NotFoundError(MSG_NOT_FOUND)


def _replaced(
    items: Sequence[FolderDefinition], folder: FolderDefinition
) -> list[FolderDefinition]:
    """``items`` with ``folder`` in place of the record of the same id."""
    return [folder if item.id == folder.id else item for item in items]


def _with(folder: FolderDefinition, **changes: object) -> FolderDefinition:
    """A folder is a value: rebuild it with the changed fields instead of mutating it."""
    return FolderDefinition.model_validate({**folder.model_dump(), **changes})


class FileFolderRepository:
    def __init__(self, graphs_dir: Path, *, clock: Clock = utc_now) -> None:
        self._state: DirState = open_state(graphs_dir)
        self._dir = self._state.directory
        self._clock = clock

    # ------------------------------------------------------------------ reads

    def list_folders(self) -> list[FolderSummary]:
        folders, rows = members.snapshot(self._state)
        return with_counts(folders, members.graph_counts(folders, rows))

    def list_definitions(self) -> list[FolderDefinition]:
        with self._state.lock:
            items = self._state.tree.read()
        return sorted(items, key=lambda item: (name_key(item.name), item.id))

    def get_folder(self, folder_id: str) -> FolderDefinition:
        key = check_folder_id(folder_id)
        with self._state.lock:
            return _find(self._state.tree.read(), key)

    def list_in(self, scope: str, *, limit: int = 200, offset: int = 0) -> list[GraphSummary]:
        target = scope_id(scope)
        size, start = clamp_page(limit, offset)
        folders, rows = members.snapshot(self._state)
        return members.graphs_in(folders, rows, target)[start : start + size]

    def count_in(self, scope: str) -> int:
        target = scope_id(scope)
        folders, rows = members.snapshot(self._state)
        return len(members.graphs_in(folders, rows, target))

    # ------------------------------------------------------------------ writes

    def create_folder(self, data: FolderCreate) -> FolderDefinition:
        with self._state.lock:
            items = self._state.tree.read_for_write()
            validate_new_count(items)
            validate_placement(items, Placement(None, data.parent_id, data.name))
            now = self._clock()
            folder = FolderDefinition(
                id=new_folder_id(),
                name=data.name,
                parent_id=data.parent_id,
                created_at=now,
                updated_at=now,
            )
            self._state.tree.save([*items, folder])
        return folder

    def update_folder(self, folder_id: str, data: FolderUpdate) -> FolderDefinition:
        key = check_folder_id(folder_id)
        with self._state.lock:
            items = self._state.tree.read_for_write()
            current = _find(items, key)
            if current.revision != data.revision:
                raise stale_error(current.revision, current.updated_at)
            parent = requested_parent(items, current, data.parent_id)
            validate_placement(items, Placement(key, parent, data.name))
            folder = _with(
                current,
                name=data.name,
                parent_id=parent,
                revision=current.revision + 1,
                updated_at=self._clock(),
            )
            self._state.tree.save(_replaced(items, folder))
        return folder

    def delete_folder(self, folder_id: str) -> None:
        key = check_folder_id(folder_id)
        with self._state.lock:
            items = self._state.tree.read_for_write()
            parent = _find(items, key).parent_id
            reparent_plan(items, key)  # refuse a name clash before any graph is moved
        for graph_id in members.ids_in(self._state, key):
            members.move_up(self._state, graph_id, key, parent)
        with self._state.lock:
            self._drop(key)

    def _drop(self, folder_id: str) -> None:
        """Remove the record and move its sub-folders up. The caller holds the lock."""
        items = self._state.tree.read_for_write()
        parent = _find(items, folder_id).parent_id
        moving = {child for child, _ in reparent_plan(items, folder_id)}
        now = self._clock()
        self._state.tree.save(
            [
                _with(item, parent_id=parent, revision=item.revision + 1, updated_at=now)
                if item.id in moving
                else item
                for item in items
                if item.id != folder_id
            ]
        )

    def put_folder(self, folder: FolderDefinition, *, overwrite: bool = False) -> FolderDefinition:
        with self._state.lock:
            items = self._state.tree.read_for_write()
            existing = next((item for item in items if item.id == folder.id), None)
            if existing is not None and not overwrite:
                raise exists_error(existing.revision, existing.updated_at)
            if existing is None:
                validate_new_count(items)
            check_name_free(items, folder.parent_id, folder.name, folder.id)
            kept = _replaced(items, folder) if existing else [*items, folder]
            self._state.tree.save(kept)
        return folder

    def move_graphs(self, ids: Sequence[str], folder_id: str | None) -> MoveReport:
        wanted = list(dict.fromkeys(check_graph_id(graph_id) for graph_id in ids))
        if folder_id is not None:
            with self._state.lock:
                _find(self._state.tree.read(), check_folder_id(folder_id))
        moved = 0
        missing: list[str] = []
        for graph_id in wanted:
            if members.assign(self._state, graph_id, folder_id):
                moved += 1
            else:
                missing.append(graph_id)
        return MoveReport(moved=moved, missing=missing)

    def ping(self) -> None:
        try:
            check_writable(self._dir)
        except OSError as exc:
            raise StorageError(f"The graphs directory is not writable: {os_reason(exc)}") from exc
