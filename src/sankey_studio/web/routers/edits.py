"""Edits to the data of a graph: ``POST /edits/plan`` and ``POST /edits/write``.

``plan`` is a pure computation (it reads a file or counts documents, writes nothing), so like
``/preview`` it stays available in read-only remote mode. ``write`` persists: its router uses
``GuardedRoute``, so read-only mode answers 403 ``read_only_mode`` before the body is decoded; the
MongoDB branch also needs ``--allow-source-writes`` in remote mode. Both handlers are plain
``def`` (file and MongoDB I/O run in the worker pool) and share the app's graph cache.
"""

from __future__ import annotations

from fastapi import APIRouter

from sankey_studio.edits import plan_edit, write_edit
from sankey_studio.models import EditOutcome, EditRequest
from sankey_studio.web.deps import GuardedRoute, ResultCacheDep, ServicesDep

router = APIRouter(prefix="/api/v1/edits")
writes_router = APIRouter(prefix="/api/v1/edits", route_class=GuardedRoute)


@router.post("/plan")
def plan(body: EditRequest, services: ServicesDep, cache: ResultCacheDep) -> EditOutcome:
    """Where ``body.edit`` would go and what the person must agree to first (writes nothing)."""
    return plan_edit(services, body, cache)


@writes_router.post("/write")
def write(body: EditRequest, services: ServicesDep, cache: ResultCacheDep) -> EditOutcome:
    """Write ``body.edit`` to its file or collection (needs the saved consent for that target)."""
    return write_edit(services, body, cache)
