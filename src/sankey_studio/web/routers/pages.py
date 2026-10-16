# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The HTML pages, the vendored plotly.js and the health probe.

Pages (``GET``, always HTML):

* ``/`` library, ``/graphs/new`` and ``/graphs/{id}/edit`` editor, ``/graphs/{id}`` viewer,
  ``/compare?ids=`` compare, ``/settings``. ``/graphs/new`` is declared BEFORE ``/graphs/{id}``.
* ``/?folder=<id>`` is the library inside one folder ("collection"), ``/graphs/new?folder=<id>`` the
  editor for a graph that will be saved in it. The value is lenient: an invalid or unknown id (or
  another parameter) is ignored and the page shows the top level, never an error.
* Every page renders ONE template (``page.html``) and embeds its data only as
  ``{{ boot|tojson }}`` inside ``<script type="application/json" id="page-data">``; user text
  (graph names, tags) reaches the page through Jinja's autoescape or through that block, never
  through ``Markup`` or ``|safe``. The environment is built here with ``autoescape=True`` for
  every template, whatever its extension.
* A malformed or unknown graph id is a 404 (``NotFoundError``). ``/compare`` takes 0..12 ids
  (``ComparePageQuery``): none is the empty compare page, an unknown id stays in ``ids`` and is
  also listed in ``missing`` (the page then draws a "no longer exists" card), a malformed id or
  more than 12 ids is a 422.
* A browser (``GET`` with ``Accept: text/html``, outside ``/api/`` and ``/static/``) gets HTML for
  every error of a page, never the JSON envelope: ``error.html`` in the same shell with the status
  of the error. A 404 or a 422 is headed "Graph not found" (a graph page whose graph is gone) or
  "Page not found" (anything else), status 404; an unreachable graph store (503 ``storage_error``)
  says so, naming the MongoDB database or the graphs folder after the stored backend; any other
  error is headed "Something went wrong". The page offers the library, Settings and a plain
  "Reload" link (``href=""``, no script). It never contains the requested URL, id or any other
  request text, nor the text of the exception. Every other client keeps the JSON envelope
  (``web/errors.py`` decides, ``error_page`` renders). ``/graphs/new`` (unless it names a folder)
  and ``/settings`` never touch the graph store, so they open while it is down.
* Every HTML answer carries ``Cache-Control: no-store``: Back/Forward must never show a page that
  was rendered before the graph changed or went away.
* The pages are plain ``def`` routes: reading the library is file or Mongo I/O, which Starlette
  runs in its worker thread pool.

Bidirectional controls (U+202A-U+202E, U+2066-U+2069) and control characters are removed from the
heading and the link labels before they reach the template: a graph named with a right-to-left
override must not reverse the words around it (``static/js/core/text.js`` does the same for text
built in the browser). A name that is empty after that is shown as "Untitled graph". The ``boot``
data keeps the names exactly as stored.

The page theme: the stored ``theme`` of the settings (``system`` when the file cannot be read) is
rendered as ``<html data-theme>`` and sits in ``boot["theme"]``, so a browser that never visited
before paints in the saved theme at once. ``theme_source`` is ``server`` when this server persists
the theme (writes allowed: the stored value always wins) and ``device`` when it does not
(read-only remote mode: the choice of this browser, cached locally, wins over the stored value).

The shell is ``templates/page.html`` (extends ``base.html``): header navigation, theme switch,
banners from ``remote_mode``/``writes_allowed``, toast region, then ``static/js/core/shell.js`` and
the module of the page, ``static/js/pages/<page>.js`` with ``new`` and ``edit`` both mapped to
``editor.js`` (the mapping lives in the template, next to the style sheet of the same name).

The wave-3 frontend replaces ``templates/`` and ``static/`` and keeps the boot data contract:
``{"page", "remote_mode", "writes_allowed", ...}`` plus ``graphs``/``total`` (library), ``graph``
(a ``GraphSummary``: editor of an existing graph and viewer, ``null`` for a new one) and
``ids``/``graphs`` (compare). Everything else the page needs it fetches from ``/api/v1``.

``support_router`` holds the two non-page routes of the assembly: ``GET /api/v1/health`` and
``GET /static/vendor/plotly.min.js``, which is the ``plotly.min.js`` of the installed plotly
package (no CDN). It is a router route, registered before the ``/static`` mount, so the mount
never answers that path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal

from fastapi import APIRouter, Query, Request, Response
from jinja2 import Environment, FileSystemLoader
from plotly.offline import get_plotlyjs
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from starlette.templating import Jinja2Templates

from sankey_studio.errors import NotFoundError, SettingsError
from sankey_studio.models import GraphId
from sankey_studio.storage.common import summary_of
from sankey_studio.storage.folder_tree import effective
from sankey_studio.storage.folders_base import ROOT_SCOPE
from sankey_studio.web.assets import static_url
from sankey_studio.web.deps import ConfigDep, ServicesDep, get_config, get_services
from sankey_studio.web.schemas.queries import (
    COMPARE_IDS_MAX,
    LIST_LIMIT_MAX,
    ScopeQuery,
    split_ids,
)

if TYPE_CHECKING:
    from sankey_studio.config import BootstrapConfig
    from sankey_studio.models import FolderSummary, GraphSummary
    from sankey_studio.services import Services

__all__ = [
    "ERROR_TEMPLATE",
    "NO_STORE",
    "PAGE_TEMPLATE",
    "PLOTLY_PATH",
    "TEMPLATES_DIR",
    "UNTITLED",
    "ComparePageQuery",
    "HealthOut",
    "PageLink",
    "PageView",
    "error_page",
    "not_found_page",
    "plotly_js",
    "render_page",
    "router",
    "storage_kind",
    "support_router",
]

TEMPLATES_DIR: Final = Path(__file__).resolve().parent.parent / "templates"
PAGE_TEMPLATE: Final = "page.html"
#: The error pages (not found, store unreachable, server error): ``page.html`` with a static body
#: (no page module, no page style sheet).
ERROR_TEMPLATE: Final = "error.html"
#: HTML is never cached: Back/Forward must ask the server again.
NO_STORE: Final = "no-store"
#: The headers of every HTML answer (a constant: ``Cache-Control`` is spelled once, read-only).
_NO_STORE_HEADERS: Final = MappingProxyType({"Cache-Control": NO_STORE})
#: What a graph with no visible name is called in headings, titles and link labels.
UNTITLED: Final = "Untitled graph"
#: The same for a folder ("collection" in the UI).
UNTITLED_FOLDER: Final = "Untitled collection"
#: Heading (``<h1>`` and title) of each error page; the key is the ``kind`` of the boot data.
HEADINGS: Final = {
    "page": "Page not found",
    "graph": "Graph not found",
    "database": "Graph database unavailable",
    "folder": "Graphs folder unavailable",
    "server": "Something went wrong",
}
#: The kinds that are a 404: they keep the page name ``notfound`` (the others are ``error``).
NOT_FOUND_KINDS: Final = frozenset({"page", "graph"})
PLOTLY_PATH: Final = "/static/vendor/plotly.min.js"
HEALTH_PATH: Final = "/api/v1/health"
#: ``text/*`` types get ``; charset=utf-8`` from the response class.
JS_MEDIA_TYPE: Final = "text/javascript"
#: Never stored either: no browser keeps a plotly.js across a server restart or an upgrade.
VENDOR_CACHE: Final = NO_STORE

#: Embeddings and overrides (U+202A-U+202E) and isolates (U+2066-U+2069): invisible characters that
#: change how the text around them is drawn. Control characters (NUL, bell, escape, DEL and the C1
#: block) have no glyph and show as empty boxes; tab, line feed and carriage return stay, like
#: ``static/js/core/text.js`` (same set). ``str.translate`` deletes the keys mapped to None.
_UNSEEN_CONTROLS: Final = dict.fromkeys(
    [
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
        *range(0x09),  # NUL..BS
        *range(0x0B, 0x0D),
        *range(0x0E, 0x20),
        *range(0x7F, 0xA0),
    ]
)
DEFAULT_THEME: Final = "system"

PageName = Literal["library", "new", "edit", "viewer", "compare", "settings", "notfound", "error"]

#: ``autoescape=True`` (not ``select_autoescape``): every template is escaped, whatever its name.
TEMPLATES: Final = Jinja2Templates(
    env=Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
)
#: Every ``/static`` link of a template goes through it (``/static/v-<digest>/``, web/assets.py).
TEMPLATES.env.globals["static_url"] = static_url

router = APIRouter(tags=["pages"])
support_router = APIRouter()


@dataclass(frozen=True, slots=True)
class PageLink:
    """One entry of the page's link list (a path of this app and its label)."""

    href: str
    label: str


NAV: Final = (
    PageLink("/", "Library"),
    PageLink("/graphs/new", "New graph"),
    PageLink("/settings", "Settings"),
)


@dataclass(frozen=True, slots=True)
class PageView:
    """What a page shows: its name, heading, links and the data embedded as JSON.

    ``template`` and ``status_code`` are the page's own, ``page.html`` and 200 unless it says so.
    """

    name: PageName
    heading: str
    links: tuple[PageLink, ...] = NAV
    data: dict[str, Any] = field(default_factory=dict)
    template: str = PAGE_TEMPLATE
    status_code: int = 200


class HealthOut(BaseModel):
    """The liveness answer: the process serves requests (it does not touch storage)."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


def _plain(text: str) -> str:
    """``text`` without bidirectional controls and without control characters (tab/LF/CR stay)."""
    return text.translate(_UNSEEN_CONTROLS)


def _graph_title(name: str) -> str:
    """A graph name for a heading or a link: plain, ``UNTITLED`` when nothing visible is left."""
    return _plain(name).strip() or UNTITLED


def _stored_theme(request: Request) -> str:
    """The saved colour theme; ``system`` when the settings cannot be read (the page must load)."""
    try:
        return get_services(request).settings().theme
    except SettingsError:
        return DEFAULT_THEME


def storage_kind(request: Request) -> str:
    """``database`` when graphs live in MongoDB, ``folder`` for the file store (or no settings)."""
    try:
        backend = get_services(request).settings().storage_backend
    except SettingsError:
        return "folder"
    return "database" if backend == "mongo" else "folder"


def render_page(request: Request, config: BootstrapConfig, view: PageView) -> Response:
    """Render ``view`` with the common boot data (page name, remote mode, writes allowed, theme).

    The answer is ``text/html`` with ``Cache-Control: no-store``.
    """
    theme = _stored_theme(request)
    boot: dict[str, Any] = {
        "page": view.name,
        "remote_mode": config.remote_mode,
        "writes_allowed": config.privileged_writes_allowed,
        "theme": theme,
        **view.data,
    }
    links = tuple(PageLink(link.href, _plain(link.label)) for link in view.links)
    context = {
        "page": view.name,
        "heading": _plain(view.heading),
        "links": links,
        "boot": boot,
        "theme": theme,
        "theme_source": "server" if config.privileged_writes_allowed else "device",
    }
    return TEMPLATES.TemplateResponse(
        request, view.template, context, view.status_code, _NO_STORE_HEADERS
    )


def error_page(request: Request, kind: str, status_code: int) -> Response:
    """An error in the app shell: a heading, one sentence and the ways out (see ``error.html``).

    ``kind`` is a key of ``HEADINGS``; ``status_code`` is kept. Nothing of the request (URL, id,
    query) and nothing of the error (message, details) reaches the template.
    """
    name: PageName = "notfound" if kind in NOT_FOUND_KINDS else "error"
    data = {"kind": kind}
    heading = HEADINGS[kind]
    view = PageView(name, heading, data=data, template=ERROR_TEMPLATE, status_code=status_code)
    return render_page(request, get_config(request), view)


def not_found_page(request: Request, *, graph: bool = False) -> Response:
    """The 404 page: "Graph not found" for a graph that is gone, "Page not found" otherwise."""
    return error_page(request, "graph" if graph else "page", 404)


def _dump(graphs: list[GraphSummary]) -> list[dict[str, Any]]:
    return [graph.model_dump(mode="json") for graph in graphs]


def _graph_links(graphs: list[GraphSummary]) -> tuple[PageLink, ...]:
    return tuple(PageLink(f"/graphs/{graph.id}", _graph_title(graph.name)) for graph in graphs)


def _folder_links(folders: list[FolderSummary]) -> tuple[PageLink, ...]:
    return tuple(
        PageLink(f"/?folder={folder.id}", f"Collection: {_folder_title(folder.name)}")
        for folder in folders
    )


def _folder_title(name: str) -> str:
    """A folder name for a link: plain, ``UNTITLED_FOLDER`` when nothing visible is left."""
    return _plain(name).strip() or UNTITLED_FOLDER


@router.get("/")
def library_page(
    query: Annotated[ScopeQuery, Query()],
    request: Request,
    services: ServicesDep,
    config: ConfigDep,
) -> Response:
    """The library: the first page of the newest graphs directly in the folder ``?folder=`` names.

    No folder, or one that is invalid or unknown, is the top level. ``folders`` is every folder
    (the page builds the breadcrumb and the cards from it); a folder whose parent no longer
    exists is listed at the top level. The page asks the API for more graphs.
    """
    repository = services.folders()
    folders = repository.list_folders()
    known = {folder.id for folder in folders}
    scope = effective(query.folder, known)
    graphs = repository.list_in(scope or ROOT_SCOPE, limit=LIST_LIMIT_MAX, offset=0)
    inside = [f for f in folders if effective(f.parent_id, known) == scope]
    data = {
        "graphs": _dump(graphs),
        "total": repository.count_in(scope or ROOT_SCOPE),
        "folders": [folder.model_dump(mode="json") for folder in folders],
        "folder": scope,
    }
    links = (*NAV, *_folder_links(inside), *_graph_links(graphs))
    return render_page(request, config, PageView("library", "Graphs", links, data))


def _existing_folder(folder_id: str, services: Services) -> str | None:
    """``folder_id`` if a folder with that id exists, else ``None`` (malformed ids included)."""
    try:
        return services.folders().get_folder(folder_id).id
    except NotFoundError:
        return None


@router.get("/graphs/new")
def new_page(
    query: Annotated[ScopeQuery, Query()],
    request: Request,
    services: ServicesDep,
    config: ConfigDep,
) -> Response:
    """The editor for a graph that does not exist yet (declared before ``/graphs/{id}``).

    ``folder_id`` of the boot data is the existing folder ``?folder=`` names, else ``null``. The
    store is only asked when a folder is named, so the page opens without one while it is down.
    """
    folder_id = _existing_folder(query.folder, services) if query.folder else None
    data = {"graph": None, "folder_id": folder_id}
    return render_page(request, config, PageView("new", "New graph", data=data))


def _graph_view(name: Literal["edit", "viewer"], graph_id: str, services: Services) -> PageView:
    """The view of a stored graph; ``NotFoundError`` (404) for an unknown or malformed id."""
    summary = summary_of(services.graphs().get(graph_id))
    data = {"graph": summary.model_dump(mode="json")}
    title = _graph_title(summary.name)
    if name == "edit":
        other = PageLink(f"/graphs/{graph_id}", "View")
        return PageView(name, f"Edit {title}", (*NAV, other), data)
    other = PageLink(f"/graphs/{graph_id}/edit", "Edit")
    return PageView(name, title, (*NAV, other), data)


@router.get("/graphs/{graph_id}")
def viewer_page(
    graph_id: str, request: Request, services: ServicesDep, config: ConfigDep
) -> Response:
    """The viewer of a saved graph."""
    return render_page(request, config, _graph_view("viewer", graph_id, services))


@router.get("/graphs/{graph_id}/edit")
def edit_page(
    graph_id: str, request: Request, services: ServicesDep, config: ConfigDep
) -> Response:
    """The editor of a saved graph."""
    return render_page(request, config, _graph_view("edit", graph_id, services))


def _page_ids(value: object) -> object:
    """``split_ids`` for a page: blank pieces are dropped, so ``?ids=`` is the same as no ids."""
    ids = split_ids(value)
    return [item for item in ids if item] if isinstance(ids, list) else ids


class ComparePageQuery(BaseModel):
    """``?ids=`` of ``GET /compare``: 0..12 distinct graph ids (none = the empty compare page)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    ids: Annotated[list[GraphId], BeforeValidator(_page_ids), Field(max_length=COMPARE_IDS_MAX)] = (
        Field(default_factory=list)
    )


@router.get("/compare")
def compare_page(
    query: Annotated[ComparePageQuery, Query()],
    request: Request,
    services: ServicesDep,
    config: ConfigDep,
) -> Response:
    """The compare view of up to 12 saved graphs, in the order of ``ids``.

    ``graphs`` holds the ones that exist; an id with no graph stays in ``ids`` and is listed in
    ``missing``, so the page can say so instead of failing.
    """
    repo = services.graphs()
    graphs: list[GraphSummary] = []
    missing: list[str] = []
    for graph_id in query.ids:
        try:
            graphs.append(summary_of(repo.get(graph_id)))
        except NotFoundError:
            missing.append(graph_id)
    data = {"ids": query.ids, "graphs": _dump(graphs), "missing": missing}
    view = PageView("compare", "Compare graphs", (*NAV, *_graph_links(graphs)), data)
    return render_page(request, config, view)


@router.get("/settings")
def settings_page(request: Request, config: ConfigDep) -> Response:
    """The settings page (it reads and saves through ``/api/v1/settings``)."""
    return render_page(request, config, PageView("settings", "Settings"))


@cache
def plotly_js() -> bytes:
    """``plotly.min.js`` of the installed plotly package, UTF-8 encoded once per process."""
    text: str = get_plotlyjs()
    return text.encode()


@support_router.get(PLOTLY_PATH)
def vendor_plotly() -> Response:
    """The plotly.js the pages load; served from the package, never from a CDN."""
    return Response(plotly_js(), media_type=JS_MEDIA_TYPE, headers={"Cache-Control": VENDOR_CACHE})


@support_router.get(HEALTH_PATH)
def health() -> HealthOut:
    """Liveness probe for launchers and tests: the app is up and routing."""
    return HealthOut()
