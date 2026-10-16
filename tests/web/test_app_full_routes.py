# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The route table of the FULL app: every route of SPEC section 4, nothing else, static first."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from fastapi import APIRouter
from fastapi.routing import iter_route_contexts
from starlette.routing import Mount

from sankey_studio.web.app import STATIC_DIR
from tests.web.test_matrix_support import (
    ENDPOINTS,
    UNSAFE,
    Endpoint,
    api_contexts,
    endpoints_of,
)

if TYPE_CHECKING:
    from starlette.routing import BaseRoute

    from tests.web.conftest import WebApp

#: SPEC section 4, one entry per method.
SPEC_ROUTES: Final = [
    "GET /api/v1/health",
    "GET /api/v1/settings",
    "PUT /api/v1/settings",
    "POST /api/v1/settings/mongo/{name}/test",
    "POST /api/v1/settings/storage/test",
    "GET /api/v1/mongo/{name}/databases",
    "GET /api/v1/mongo/{name}/collections",
    "GET /api/v1/mongo/{name}/sample",
    "GET /api/v1/sources/files",
    "POST /api/v1/sources/files",
    "DELETE /api/v1/sources/files/{name:path}",
    "GET /api/v1/sources/files/{name:path}/preview",
    "POST /api/v1/sources/detect",
    "POST /api/v1/preview",
    "POST /api/v1/entries",
    "POST /api/v1/edits/plan",
    "POST /api/v1/edits/write",
    "GET /api/v1/graphs",
    "POST /api/v1/graphs",
    "GET /api/v1/graphs/export",
    "POST /api/v1/graphs/import",
    "POST /api/v1/graphs/move",
    "GET /api/v1/graphs/{graph_id}",
    "PUT /api/v1/graphs/{graph_id}",
    "DELETE /api/v1/graphs/{graph_id}",
    "POST /api/v1/graphs/{graph_id}/duplicate",
    "GET /api/v1/graphs/{graph_id}/render",
    "GET /api/v1/folders",
    "POST /api/v1/folders",
    "GET /api/v1/folders/{folder_id}",
    "PUT /api/v1/folders/{folder_id}",
    "DELETE /api/v1/folders/{folder_id}",
    "GET /api/v1/compare/render",
    "GET /api/v1/tags",
    "GET /api/v1/graphs/{graph_id}/export",
    "POST /api/v1/export",
    "GET /",
    "GET /graphs/new",
    "GET /graphs/{graph_id}",
    "GET /graphs/{graph_id}/edit",
    "GET /compare",
    "GET /settings",
    "GET /static/vendor/plotly.min.js",
]


def app_endpoints(web: WebApp) -> list[Endpoint]:
    return endpoints_of(web.app.routes)


def shadowed(routes: list[BaseRoute]) -> list[tuple[str, str]]:
    """``(static path, earlier dynamic path)`` pairs where the earlier route would answer."""
    found: list[tuple[str, str]] = []
    api = api_contexts(routes)
    for index, route in enumerate(api):
        if "{" in str(route.path):
            continue
        found.extend(
            (str(route.path), str(earlier.path))
            for earlier in api[:index]
            if (earlier.methods or set()) & (route.methods or set())
            and earlier.path_regex.fullmatch(route.path)
        )
    return found


def test_the_app_serves_exactly_the_routes_of_the_spec(web: WebApp) -> None:
    actual = [endpoint.label for endpoint in app_endpoints(web)]
    assert sorted(actual) == sorted(SPEC_ROUTES)
    assert len(actual) == len(set(actual)) == 43


def test_the_registry_and_the_app_agree(web: WebApp) -> None:
    assert [e.label for e in app_endpoints(web)] == [e.label for e in ENDPOINTS]
    assert {e.label for e in UNSAFE} == {
        label for label in SPEC_ROUTES if label.split()[0] != "GET"
    }
    assert len(UNSAFE) == 20


def test_the_static_mount_is_registered_after_every_route(web: WebApp) -> None:
    contexts = list(iter_route_contexts(web.app.routes))
    *others, last = (context.original_route for context in contexts)
    assert isinstance(last, Mount)
    assert (last.path, last.name) == ("/static", "static")
    assert len(others) == len(api_contexts(web.app.routes)) == 43
    assert STATIC_DIR.is_dir()
    assert not web.app.docs_url
    assert not web.app.redoc_url
    assert not web.app.openapi_url


def test_no_static_route_is_shadowed_by_an_earlier_dynamic_one(web: WebApp) -> None:
    assert shadowed(web.app.routes) == []


def _view() -> None:
    return None


def test_the_shadow_check_sees_a_dynamic_route_registered_first() -> None:
    router = APIRouter()
    router.add_api_route("/graphs/{graph_id}", _view, methods=["GET"])
    router.add_api_route("/graphs/new", _view, methods=["GET"])
    router.add_api_route("/graphs/new", _view, methods=["POST"])  # another method: not shadowed
    router.add_api_route("/graphs/other/{x}", _view, methods=["GET"])
    assert shadowed(router.routes) == [("/graphs/new", "/graphs/{graph_id}")]


def test_the_shadow_check_accepts_the_static_route_first() -> None:
    router = APIRouter()
    router.add_api_route("/graphs/new", _view, methods=["GET"])
    router.add_api_route("/graphs/{graph_id}", _view, methods=["GET"])
    assert shadowed(router.routes) == []


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("GET /api/v1/graphs/export", "GET /api/v1/graphs/{graph_id}"),
        ("POST /api/v1/graphs/import", "POST /api/v1/graphs/{graph_id}/duplicate"),
        ("GET /graphs/new", "GET /graphs/{graph_id}"),
        ("GET /api/v1/graphs/export", "GET /graphs/{graph_id}"),
        ("POST /api/v1/graphs/move", "POST /api/v1/graphs/{graph_id}/duplicate"),
    ],
)
def test_static_paths_are_declared_before_their_dynamic_siblings(
    web: WebApp, first: str, second: str
) -> None:
    labels = [endpoint.label for endpoint in app_endpoints(web)]
    assert labels.index(first) < labels.index(second)


def test_the_static_graph_routes_answer_instead_of_the_id_routes(web: WebApp) -> None:
    export = web.client.get("/api/v1/graphs/export")
    imported = web.client.post("/api/v1/graphs/import", json={"graphs": []})
    page = web.client.get("/graphs/new")
    assert (export.status_code, export.json()["error"]["code"]) == (422, "validation_error")
    assert imported.json()["error"]["code"] == "bundle_error"
    assert page.status_code == 200
    assert 'data-page="new"' in page.text


def test_every_api_route_lives_under_the_versioned_prefix(web: WebApp) -> None:
    pages = {"/", "/graphs/new", "/graphs/{graph_id}", "/graphs/{graph_id}/edit", "/compare"}
    pages |= {"/settings", "/static/vendor/plotly.min.js"}
    for endpoint in app_endpoints(web):
        assert endpoint.template.startswith("/api/v1/") or endpoint.template in pages
        assert endpoint.method in {"GET", "POST", "PUT", "DELETE"}
