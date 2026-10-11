"""Read-only MongoDB inspection for the editor's Mongo form (prefix ``/api/v1/mongo``).

* ``GET /{name}/databases`` -> ``["db", ...]`` (``admin``, ``local`` and ``config`` are never
  listed).
* ``GET /{name}/collections?database=`` -> ``["coll", ...]`` (``system.*`` are never listed).
* ``GET /{name}/sample?database=&collection=&n=`` -> ``{"documents": [...], "suggested": {...}}``:
  up to ``n`` (1..20) bounded, JSON-safe documents and the field paths the editor pre-selects
  (``source``, ``target``, ``value``, ``category`` or ``null``).

``name`` is a configured connection (unknown: 404 ``source_not_found``); ``database`` and
``collection`` go straight to ``sources.mongo_inspect``, which validates them with
``mongo_safety`` before a client exists (``admin``/``local``/``config`` and ``system.*`` answer
400 ``unsafe_source``). ``mongo_inspect`` runs each call inside ``clients.slot(name)`` and maps
driver failures to a message with the connection NAME and the exception class only. These are
GET routes: they stay available in remote read-only mode. The handlers are plain ``def`` (blocking
driver calls run in Starlette's worker thread pool).

They take ``MongoContextDep``, not ``services.source_context()``: a Mongo call never reads a
source file, so an unusable sources directory must not turn them into a 503.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from sankey_studio.sources.mongo_inspect import (
    CollectionRef,
    FieldSuggestion,
    list_collections,
    list_databases,
    sample_documents,
    suggest_fields,
)
from sankey_studio.web.deps import MongoContextDep
from sankey_studio.web.schemas import CollectionsQuery, SampleQuery

__all__ = ["SampleOut", "router"]

router = APIRouter(prefix="/api/v1/mongo", tags=["mongo"])


class SampleOut(BaseModel):
    """Sample documents (JSON-safe) and the suggested field mapping."""

    model_config = ConfigDict(extra="forbid")

    documents: list[dict[str, Any]]
    suggested: FieldSuggestion


@router.get("/{name}/databases")
def databases(name: str, ctx: MongoContextDep) -> list[str]:
    return list_databases(ctx, name)


@router.get("/{name}/collections")
def collections(
    name: str, query: Annotated[CollectionsQuery, Query()], ctx: MongoContextDep
) -> list[str]:
    return list_collections(ctx, name, query.database)


@router.get("/{name}/sample")
def sample(name: str, query: Annotated[SampleQuery, Query()], ctx: MongoContextDep) -> SampleOut:
    target = CollectionRef(name, query.database, query.collection)
    documents = sample_documents(ctx, target, query.n)
    return SampleOut(documents=documents, suggested=suggest_fields(documents))
