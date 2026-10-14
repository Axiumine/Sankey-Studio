"""What the pages router DECLARES: paths, order, status, response model, tags, public names.

mutmut skips decorated functions, and every route handler is one, so a moved router, a changed
path or a dropped tag would otherwise pass the suite when no behaviour test happens to look at
it. The tables below pin them: the exact route set of ``router`` (the six pages, with
``/graphs/new`` declared BEFORE ``/graphs/{graph_id}``) and of ``support_router`` (the vendored
plotly.js and the health probe), the success status, the response model FastAPI filters the
answer with, the absence of a write guard (pages are read-only GETs), the tags and the public
names of the module, and the order of ``ALL_ROUTERS`` (support first, pages last).
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi.routing import APIRoute

from sankey_studio.web.routers import (
    ALL_ROUTERS,
    compare,
    edits,
    exports,
    folders,
    graphs,
    mongo,
    pages,
    preview,
    settings,
    sources,
)

if TYPE_CHECKING:
    from fastapi import APIRouter

PLOTLY = "/static/vendor/plotly.min.js"
HEALTH = "/api/v1/health"


class Declared(NamedTuple):
    """One route: its router, where it lives and what it answers on success."""

    router: APIRouter
    path: str
    response: object


DECLARED = [
    Declared(pages.router, "/", None),
    Declared(pages.router, "/graphs/new", None),
    Declared(pages.router, "/graphs/{graph_id}", None),
    Declared(pages.router, "/graphs/{graph_id}/edit", None),
    Declared(pages.router, "/compare", None),
    Declared(pages.router, "/settings", None),
    Declared(pages.support_router, PLOTLY, None),
    Declared(pages.support_router, HEALTH, pages.HealthOut),
]


def api_routes(router: APIRouter) -> list[APIRoute]:
    """The routes of ``router`` in declaration order (every route here is an ``APIRoute``)."""
    found = [route for route in router.routes if isinstance(route, APIRoute)]
    assert len(found) == len(router.routes)
    return found


@pytest.mark.parametrize("case", DECLARED, ids=[c.path for c in DECLARED])
def test_each_route_is_a_get_with_its_status_response_model_and_no_guard(case: Declared) -> None:
    (route,) = [r for r in api_routes(case.router) if r.path == case.path]
    assert route.methods == {"GET"}
    assert (route.status_code or 200) == 200
    assert route.response_model == case.response
    assert route.dependencies == []
    assert route.include_in_schema is True
    # plain ``def``: file or Mongo I/O must run in Starlette's worker thread pool
    assert not inspect.iscoroutinefunction(route.endpoint)


def test_the_pages_router_serves_the_six_pages_with_the_static_path_first() -> None:
    paths = [route.path for route in api_routes(pages.router)]
    assert paths == [
        "/",
        "/graphs/new",
        "/graphs/{graph_id}",
        "/graphs/{graph_id}/edit",
        "/compare",
        "/settings",
    ]


def test_the_support_router_serves_exactly_plotly_and_health() -> None:
    paths = [route.path for route in api_routes(pages.support_router)]
    assert paths == [PLOTLY, HEALTH]


def test_the_page_routes_carry_the_pages_tag_and_the_support_routes_none() -> None:
    assert pages.router.tags == ["pages"]
    assert pages.router.prefix == ""
    assert all(route.tags == ["pages"] for route in api_routes(pages.router))
    assert pages.support_router.tags == []
    assert pages.support_router.prefix == ""
    assert all(route.tags == [] for route in api_routes(pages.support_router))


def test_the_public_names_of_the_pages_module() -> None:
    public = [
        "ERROR_TEMPLATE",
        "NO_STORE",
        "UNTITLED",
        "ComparePageQuery",
        "HealthOut",
        "PAGE_TEMPLATE",
        "PLOTLY_PATH",
        "PageLink",
        "PageView",
        "TEMPLATES_DIR",
        "error_page",
        "not_found_page",
        "plotly_js",
        "render_page",
        "router",
        "storage_kind",
        "support_router",
    ]
    assert sorted(pages.__all__) == sorted(public)
    assert len(pages.__all__) == len(set(pages.__all__))
    assert all(hasattr(pages, name) for name in public)


def test_all_routers_is_the_registration_order_support_first_and_pages_last() -> None:
    expected = (
        pages.support_router,
        settings.router,
        sources.router,
        mongo.router,
        preview.router,
        edits.router,
        edits.writes_router,
        graphs.router,
        folders.router,
        compare.router,
        exports.router,
        pages.router,
    )
    assert expected == ALL_ROUTERS
    assert len(ALL_ROUTERS) == len({id(router) for router in ALL_ROUTERS}) == 12
