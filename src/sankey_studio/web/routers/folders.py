# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The library folders ("collections" in the UI): a tree that groups saved graphs.

Every route here is under ``/api/v1``. The reads (``GET /folders``, ``GET /folders/{id}``) are
always available; ``POST``, ``PUT`` and ``DELETE`` persist, so ``GuardedRoute`` answers them 403
``read_only_mode`` (remote mode without ``--allow-remote-writes``) before the body is decoded. A
malformed id is a 404 like an unknown one (the repository checks it with ``check_folder_id``).

The rules (sibling names unique ignoring case, at most 8 levels, at most 1000 folders, no cycles)
live in ``storage.folder_tree``: a broken rule is 422 ``folder_rule``, a taken name 409
``folder_name_taken`` (not ``conflict``: that code means "stale revision, reload"). ``PUT`` is
optimistic like the graphs: a stale ``revision`` is 409 ``conflict`` with ``details``
``["revision=N", "updated_at=<iso>"]``. Deleting a folder never deletes a graph: its graphs and
sub-folders move up to its parent. ``POST /graphs/move`` (in ``graphs.py``) puts graphs in a
folder.
"""

from __future__ import annotations

from fastapi import APIRouter

from sankey_studio.models import FolderCreate, FolderDefinition, FolderUpdate
from sankey_studio.web.deps import GuardedRoute, ServicesDep
from sankey_studio.web.schemas import FolderList

router = APIRouter(prefix="/api/v1", route_class=GuardedRoute)


@router.get("/folders")
def list_folders(services: ServicesDep) -> FolderList:
    """Every folder with the number of graphs and sub-folders directly inside it."""
    return FolderList(items=services.folders().list_folders())


@router.post("/folders", status_code=201)
def create_folder(data: FolderCreate, services: ServicesDep) -> FolderDefinition:
    """Create a folder (revision 1) at the top level or below ``data.parent_id`` (404 if gone)."""
    return services.folders().create_folder(data)


@router.get("/folders/{folder_id}")
def get_folder(folder_id: str, services: ServicesDep) -> FolderDefinition:
    return services.folders().get_folder(folder_id)


@router.put("/folders/{folder_id}")
def update_folder(folder_id: str, data: FolderUpdate, services: ServicesDep) -> FolderDefinition:
    """Rename and/or move a folder; 409 ``conflict`` when ``data.revision`` is stale."""
    return services.folders().update_folder(folder_id, data)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, services: ServicesDep) -> None:
    """Delete a folder; its graphs and sub-folders move up to its parent (none is deleted)."""
    services.folders().delete_folder(folder_id)
