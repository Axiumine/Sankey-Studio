"""The body caps and the CSRF guard in front of the real graph, preview and export routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.web.routers import exports, graphs, preview
from sankey_studio.web.security import IMPORT_BODY_BYTES, IMPORT_PATH, JSON_BODY_BYTES
from tests.web.test_routes_exports_support import FakeRender, install_render
from tests.web.test_routes_graphs_support import API, BUDGET, UNKNOWN_ID, code, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router, preview.router, exports.router])


def padded(size: int) -> str:
    """A JSON object of exactly ``size`` bytes: a ``pad`` field and nothing else."""
    head, tail = '{"pad":"', '"}'
    return head + "x" * (size - len(head) - len(tail)) + tail


class Route(NamedTuple):
    method: str
    path: str
    status: int  # of a body that is within the cap but not a valid request


JSON_ROUTES = [
    Route("POST", "/graphs", 422),
    Route("PUT", f"/graphs/{UNKNOWN_ID}", 422),
    Route("POST", "/preview", 422),
    Route("POST", "/entries", 422),
    Route("POST", "/export", 422),
]


@pytest.mark.parametrize(
    "route", JSON_ROUTES, ids=lambda route: f"{route.method} {route.path[:12]}"
)
def test_a_json_body_may_be_8_mib_and_not_a_byte_more(web: WebApp, route: Route) -> None:
    url = API + route.path
    at_cap = web.client.request(
        route.method, url, content=padded(JSON_BODY_BYTES), headers=JSON_HEADERS
    )
    assert at_cap.status_code == route.status
    assert code(at_cap) == "validation_error"
    over = web.client.request(
        route.method, url, content=padded(JSON_BODY_BYTES + 1), headers=JSON_HEADERS
    )
    assert over.status_code == 413
    assert code(over) == "payload_too_large"


def test_the_import_route_is_the_one_the_body_limit_knows() -> None:
    paths = {route.path for route in graphs.router.routes if hasattr(route, "path")}
    assert IMPORT_PATH in paths


def test_an_import_may_exceed_the_json_cap_up_to_16_mib(web: WebApp) -> None:
    bundle = '{"format":"sankey-studio/graphs","version":2,"graphs":[],"pad":"%s"}'
    fixed = len(bundle % "")
    at_json_cap_plus = bundle % ("x" * (JSON_BODY_BYTES + 1 - fixed))
    ok = web.client.post(IMPORT_PATH, content=at_json_cap_plus, headers=JSON_HEADERS)
    assert ok.status_code == 200
    assert ok.json()["imported"] == 0
    at_cap = bundle % ("x" * (IMPORT_BODY_BYTES - fixed))
    assert web.client.post(IMPORT_PATH, content=at_cap, headers=JSON_HEADERS).status_code == 200
    over = bundle % ("x" * (IMPORT_BODY_BYTES + 1 - fixed))
    response = web.client.post(IMPORT_PATH, content=over, headers=JSON_HEADERS)
    assert response.status_code == 413
    assert code(response) == "payload_too_large"


def test_a_cross_site_export_never_starts_chrome(
    monkeypatch: pytest.MonkeyPatch, web: WebApp
) -> None:
    render: FakeRender = install_render(monkeypatch)
    stored = save(web, "Household", *BUDGET)
    response = web.client.get(
        f"{API}/graphs/{stored.id}/export?format=png", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert code(response) == "forbidden"
    assert render.calls == []


def test_an_export_post_needs_the_json_content_type(
    monkeypatch: pytest.MonkeyPatch, web: WebApp
) -> None:
    render = install_render(monkeypatch)
    response = web.bare.post(f"{API}/export", content="{}", headers={"Content-Type": "text/plain"})
    assert response.status_code == 403
    assert render.calls == []
