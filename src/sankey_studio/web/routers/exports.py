"""Downloads of one chart: ``GET /graphs/{id}/export`` (saved) and ``POST /export`` (a draft).

``chart`` is ``sankey`` or ``donut``, ``format`` is ``svg``, ``png``, ``html``, ``json`` or ``csv``.
No endpoint takes figure JSON (a figure with ``layout.images[].source`` would make Chrome fetch an
arbitrary URL): the figure is always built here from a saved id or a ``GraphDraft``.

Errors come from the domain: 422 ``no_categories`` (donut without categories), 422
``export_too_large`` (pixel or graph-size cap), 503 ``export_busy``, 501 ``export_unavailable``
(no Chrome), 502 ``export_failed``, 504 ``export_timeout``. The browser then falls back to
Plotly's client-side download. Both routes are pure computations, so they stay available in
read-only remote mode. Every answer is an attachment (``download_response``).

The Sankey figure is drawn like on screen (at most ``max_drawn_links`` links, with its note); the
CSV holds every link.

File names: the Sankey files are named after the graph (``<name>.svg``), the donut files add
``-donut`` before the extension (``<name>-donut.svg``, also ``.png``, ``.html``, ``.json`` and
``.csv``), so the two charts of one graph never share a file name. The suffix survives the cut of a
long name to ``FALLBACK_NAME_MAX`` characters (the name is shortened, not the suffix).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Final

from fastapi import APIRouter, Query, Response

from sankey_studio.models import GraphDraft
from sankey_studio.pipeline import build_graph_from_draft
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.export import export_csv, export_html, export_image, export_json
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.sankey import build_figure
from sankey_studio.web.deps import ResultCacheDep, ResultCacheLike, ServicesDep
from sankey_studio.web.routers.graphs import draft_of
from sankey_studio.web.schemas import ExportQuery
from sankey_studio.web.security import (
    FALLBACK_NAME,
    FALLBACK_NAME_MAX,
    Download,
    download_response,
)

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph
    from sankey_studio.services import Services

router = APIRouter(prefix="/api/v1")

#: Inserted before the extension of every donut file (see the module doc).
DONUT_SUFFIX: Final = "-donut"

#: ``text/*`` types get ``; charset=utf-8`` from the response class.
MEDIA_TYPES: Final = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "html": "text/html",
    "json": "application/json",
    "csv": "text/csv",
}


@dataclass(frozen=True, slots=True)
class ExportJob:
    """A draft to export, the name it is served under (also the HTML title) and the request."""

    draft: GraphDraft
    title: str
    query: ExportQuery


def file_stem(job: ExportJob) -> str:
    """The download name without extension: the title, plus ``-donut`` for the donut chart."""
    if job.query.chart != "donut":
        return job.title
    return job.title[: FALLBACK_NAME_MAX - len(DONUT_SUFFIX)] + DONUT_SUFFIX


def _figure(graph: SankeyGraph, job: ExportJob, services: Services) -> dict[str, Any]:
    style, theme = job.draft.style, job.query.theme
    if job.query.chart == "donut":
        return build_donut_figure(graph, style, theme)
    options = FigureOptions(max_links=services.settings().max_drawn_links)
    return build_figure(graph, style, theme, options)


def _encode_figure(figure: dict[str, Any], job: ExportJob) -> bytes | str:
    query = job.query
    match query.format:
        case "svg" | "png" as fmt:
            return export_image(figure, fmt, query.image_options())
        case "html":
            return export_html(figure, title=job.title, theme=query.theme)
        case _:
            return export_json(figure)


def serve_export(job: ExportJob, services: Services, cache: ResultCacheLike) -> Response:
    """Build the graph of ``job``, render it in the requested format and wrap it as a download."""
    graph = build_graph_from_draft(services, job.draft, cache)
    query = job.query
    if query.format == "csv":
        body: bytes | str = export_csv(graph, chart=query.chart, basis=job.draft.style.donut.basis)
    else:
        body = _encode_figure(_figure(graph, job, services), job)
    ext = query.format
    return download_response(Download(body, MEDIA_TYPES[ext], file_stem(job), ext))


@router.get("/graphs/{graph_id}/export")
def export_saved_graph(
    graph_id: str,
    query: Annotated[ExportQuery, Query()],
    services: ServicesDep,
    cache: ResultCacheDep,
) -> Response:
    """Export a saved graph; the file is named after the graph."""
    definition = services.graphs().get(graph_id)
    job = ExportJob(draft_of(definition), definition.name, query)
    return serve_export(job, services, cache)


@router.post("/export")
def export_draft(
    query: Annotated[ExportQuery, Query()],
    draft: GraphDraft,
    services: ServicesDep,
    cache: ResultCacheDep,
) -> Response:
    """Export an unsaved draft; the file is named after its title (``graph`` without one)."""
    job = ExportJob(draft, draft.style.title or FALLBACK_NAME, query)
    return serve_export(job, services, cache)
