"""The library of saved graphs: CRUD, duplicate, JSON bundle import/export, tags and the render.

Order matters: ``/graphs/export`` and ``/graphs/import`` are declared BEFORE ``/graphs/{graph_id}``
so the static paths are never read as an id. A malformed id is a 404 (the repository checks it
with ``check_graph_id``), an unknown valid id too. Every route with an unsafe method persists
something, and ``GuardedRoute`` answers it 403 ``read_only_mode`` (remote mode without
``--allow-remote-writes``) before FastAPI decodes the body, so a malformed body is a 403 there
too; the reads, the bundle export and the render are always available.

The bundle export refuses a document the import would refuse: ``IMPORT_BODY_BYTES`` is the one cap
(422 ``bundle_error``, "export fewer graphs"), so an exported file always imports again. Both
count UTF-8 bytes, and the export is written one graph at a time, aborting at the first graph that
would cross the cap, so a request for 200 huge graphs never holds more than the cap plus one graph.

``PUT`` is optimistic: a stale ``revision`` answers 409 with ``details`` ``["revision=N",
"updated_at=<iso>"]`` (the repository's ``ConflictError``), and the UI then reloads or saves a copy
with ``POST /graphs/{id}/duplicate``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import APIRouter, Body, Query, Response
from pydantic import BaseModel, ConfigDict

from sankey_studio.bundle import RenderBundle
from sankey_studio.errors import BundleError
from sankey_studio.models import (
    NAME_MAX,
    GraphCreate,
    GraphDefinition,
    GraphDraft,
    GraphSummary,
    GraphUpdate,
)
from sankey_studio.pipeline import BundleOptions, render_bundle
from sankey_studio.storage.bundle import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    ImportReport,
    import_bundle,
)
from sankey_studio.web.deps import GuardedRoute, ResultCacheDep, ServicesDep
from sankey_studio.web.schemas import IdsQuery, ListQuery, RenderQuery
from sankey_studio.web.security import IMPORT_BODY_BYTES, Download, download_response

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

COPY_SUFFIX = " (copy)"
BUNDLE_FILE_NAME = "sankey-studio-graphs"
BUNDLE_MEDIA_TYPE = "application/json"
MSG_EXPORT_TOO_LARGE = "The export is larger than a bundle import accepts; export fewer graphs"
#: ``json.dumps(bundle, indent=2)`` around the graphs: each graph is one chunk in between.
BUNDLE_HEAD: Final = (
    f'{{\n  "format": "{BUNDLE_FORMAT}",\n  "version": {BUNDLE_VERSION},\n  "graphs": ['
).encode()
BUNDLE_TAIL: Final = b"\n  ]\n}"
_GRAPH_INDENT = "    "
#: ``json.dumps(graph, indent=2, ensure_ascii=False)`` as an object: non-ASCII text stays as it
#: is (an emoji is 4 bytes, not the 12 of two ``\uXXXX`` escapes), so the size counted is the UTF-8
#: served.
_GRAPH_ENCODER: Final = json.JSONEncoder(indent=2, ensure_ascii=False)


router = APIRouter(prefix="/api/v1", route_class=GuardedRoute)


class GraphPage(BaseModel):
    """One page of the library: ``total`` counts every match, not only this page."""

    model_config = ConfigDict(extra="forbid")

    items: list[GraphSummary]
    total: int
    limit: int
    offset: int


def draft_of(definition: GraphDefinition) -> GraphDraft:
    """The drawable part of a saved graph (what the render and export pipeline takes)."""
    return GraphDraft(
        source=definition.source, transform=definition.transform, style=definition.style
    )


def copy_of(definition: GraphDefinition) -> GraphCreate:
    """A new graph like ``definition`` whose name ends in ``(copy)`` and still fits ``NAME_MAX``."""
    return GraphCreate(
        name=definition.name[: NAME_MAX - len(COPY_SUFFIX)] + COPY_SUFFIX,
        description=definition.description,
        tags=definition.tags,
        source=definition.source,
        transform=definition.transform,
        style=definition.style,
    )


def _graph_chunk(graph: GraphDefinition, *, first: bool) -> bytes:
    """One graph of the bundle as UTF-8, indented and separated to sit in the ``graphs`` list."""
    text = _GRAPH_ENCODER.encode(graph.model_dump(mode="json"))
    nested = text.replace("\n", "\n" + _GRAPH_INDENT)  # a newline inside a string is escaped
    return f"{'' if first else ','}\n{_GRAPH_INDENT}{nested}".encode()


def encode_bundle(load: Callable[[str], GraphDefinition], ids: Iterable[str], limit: int) -> bytes:
    """The bundle of the graphs ``ids`` (given order, repeats dropped) as UTF-8 JSON bytes.

    The bytes are those of ``json.dumps(bundle, indent=2)`` (non-ASCII text stays as it is). Graphs
    are loaded and encoded one by one while the running size is counted, so the document is
    refused (422 ``bundle_error``) at the first graph that takes it above ``limit`` bytes and the
    rest of the request is never loaded.
    """
    chunks = [BUNDLE_HEAD]
    size = len(BUNDLE_HEAD) + len(BUNDLE_TAIL)
    for graph_id in dict.fromkeys(ids):
        chunk = _graph_chunk(load(graph_id), first=len(chunks) == 1)
        size += len(chunk)
        if size > limit:
            raise BundleError(MSG_EXPORT_TOO_LARGE, details=[f"limit_bytes={limit}"])
        chunks.append(chunk)
    chunks.append(BUNDLE_TAIL)
    return b"".join(chunks)


@router.get("/graphs")
def list_graphs(query: Annotated[ListQuery, Query()], services: ServicesDep) -> GraphPage:
    """Search the library (``q`` over name, description and tags; exact ``tag``), newest first."""
    repo = services.graphs()
    return GraphPage(
        items=repo.list_graphs(
            query=query.q, tag=query.tag, limit=query.limit, offset=query.offset
        ),
        total=repo.count(query=query.q, tag=query.tag),
        limit=query.limit,
        offset=query.offset,
    )


@router.get("/graphs/export")
def export_graphs(query: Annotated[IdsQuery, Query()], services: ServicesDep) -> Response:
    """The listed graphs (1..200 ids) as one JSON bundle download.

    422 ``bundle_error`` when the document is larger than ``IMPORT_BODY_BYTES``: the import
    would answer 413 to it, so a file the UI hands out must never be one it cannot take back.
    """
    body = encode_bundle(services.graphs().get, query.ids, IMPORT_BODY_BYTES)
    return download_response(Download(body, BUNDLE_MEDIA_TYPE, BUNDLE_FILE_NAME, "json"))


@router.get("/tags")
def list_tags(services: ServicesDep) -> list[str]:
    """Every tag in use, sorted."""
    return services.graphs().all_tags()


@router.get("/graphs/{graph_id}")
def get_graph(graph_id: str, services: ServicesDep) -> GraphDefinition:
    return services.graphs().get(graph_id)


@router.get("/graphs/{graph_id}/render")
def render_graph(
    graph_id: str,
    query: Annotated[RenderQuery, Query()],
    services: ServicesDep,
    cache: ResultCacheDep,
) -> RenderBundle:
    """Load the saved graph's source and draw it (``query`` may switch labels on or off)."""
    draft = draft_of(services.graphs().get(graph_id))
    options = BundleOptions(theme=query.theme, style=query.styled(draft.style))
    return render_bundle(services, draft, options, cache)


@router.post("/graphs", status_code=201)
def create_graph(data: GraphCreate, services: ServicesDep) -> GraphDefinition:
    """Save a new graph (revision 1)."""
    return services.graphs().create(data)


@router.post("/graphs/import")
def import_graphs(bundle: Annotated[object, Body()], services: ServicesDep) -> ImportReport:
    """Store every valid graph of a bundle under a fresh id; the report lists the failures."""
    return import_bundle(services.graphs(), bundle)


@router.put("/graphs/{graph_id}")
def update_graph(graph_id: str, data: GraphUpdate, services: ServicesDep) -> GraphDefinition:
    """Replace a graph; 409 when ``data.revision`` is not the stored revision."""
    return services.graphs().update(graph_id, data)


@router.delete("/graphs/{graph_id}", status_code=204)
def delete_graph(graph_id: str, services: ServicesDep) -> None:
    services.graphs().delete(graph_id)


@router.post("/graphs/{graph_id}/duplicate", status_code=201)
def duplicate_graph(graph_id: str, services: ServicesDep) -> GraphDefinition:
    """Save the stored graph again as ``<name> (copy)`` (new id, revision 1)."""
    repo = services.graphs()
    return repo.create(copy_of(repo.get(graph_id)))
