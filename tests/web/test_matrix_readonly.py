# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Remote read-only mode on the FULL app: every persisting route is 403, the pure ones work."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.web.deps import MSG_READ_ONLY
from tests.web.test_matrix_support import ENDPOINTS, SAFE, UNKNOWN_ID, UNSAFE, Endpoint, ids
from tests.web.test_routes_graphs_support import API, BUDGET, draft_json, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

#: SPEC section 4: what the read-only remote mode refuses (it would persist something).
PERSISTING: Final = {
    "PUT /api/v1/settings",
    "POST /api/v1/settings/storage/test",
    "POST /api/v1/settings/mongo/{name}/test",
    "POST /api/v1/sources/files",
    "DELETE /api/v1/sources/files/{name:path}",
    "POST /api/v1/graphs",
    "PUT /api/v1/graphs/{graph_id}",
    "DELETE /api/v1/graphs/{graph_id}",
    "POST /api/v1/graphs/{graph_id}/duplicate",
    "POST /api/v1/graphs/import",
    "POST /api/v1/graphs/move",
    "POST /api/v1/folders",
    "PUT /api/v1/folders/{folder_id}",
    "DELETE /api/v1/folders/{folder_id}",
    "POST /api/v1/edits/write",
}
#: Pure computations: they stay available.
PURE: Final = {
    "POST /api/v1/preview",
    "POST /api/v1/entries",
    "POST /api/v1/edits/plan",
    "POST /api/v1/export",
    "POST /api/v1/sources/detect",
}
JSON: Final = {"Content-Type": "application/json"}
BODIES: Final = [b"{}", b"", b'{"x": 1}', b"[1, 2]", b"null"]
REFUSED: Final = {"error": {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}}
PERSISTING_ENDPOINTS: Final = [e for e in UNSAFE if e.label in PERSISTING]
PURE_ENDPOINTS: Final = [e for e in UNSAFE if e.label in PURE]


def send(web: WebApp, endpoint: Endpoint, body: bytes) -> tuple[int, object]:
    """The same-origin client sends ``body`` as JSON to ``endpoint``."""
    response = web.client.request(endpoint.method, endpoint.path, content=body, headers=JSON)
    return response.status_code, response.json()


def test_every_unsafe_route_is_classified() -> None:
    assert PERSISTING.isdisjoint(PURE)
    assert {e.label for e in UNSAFE} == PERSISTING | PURE
    assert len(PERSISTING_ENDPOINTS) == 15
    assert len(PURE_ENDPOINTS) == 5


@pytest.mark.parametrize("endpoint", PERSISTING_ENDPOINTS, ids=ids(PERSISTING_ENDPOINTS))
@pytest.mark.parametrize("body", BODIES)
def test_a_persisting_route_answers_403_read_only_mode(
    remote_web: WebApp, endpoint: Endpoint, body: bytes
) -> None:
    assert send(remote_web, endpoint, body) == (403, REFUSED)


@pytest.mark.parametrize("endpoint", PERSISTING_ENDPOINTS, ids=ids(PERSISTING_ENDPOINTS))
@pytest.mark.parametrize("body", [b"{", b"not json", b"\xff\xfe"])
def test_an_undecodable_body_is_still_403_where_the_guard_runs_first(
    remote_web: WebApp, endpoint: Endpoint, body: bytes
) -> None:
    assert send(remote_web, endpoint, body) == (403, REFUSED)


def test_the_refused_requests_wrote_nothing(remote_web: WebApp) -> None:
    for endpoint in PERSISTING_ENDPOINTS:
        send(remote_web, endpoint, b"{}")
    assert remote_web.services.graphs().count() == 0
    assert remote_web.services.folders().list_folders() == []
    assert not remote_web.config.settings_file.exists()
    assert not remote_web.config.effective_sources_dir.exists()


def test_the_refusal_comes_after_the_csrf_check_not_instead_of_it(remote_web: WebApp) -> None:
    text = {"Content-Type": "text/plain"}
    forbidden = remote_web.bare.post(f"{API}/graphs", content=b"{}", headers=text)
    unsupported = remote_web.client.post(f"{API}/graphs", content=b"{}")
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "forbidden")
    assert (unsupported.status_code, unsupported.json()["error"]["code"]) == (
        415,
        "unsupported_media_type",
    )


def test_the_pure_computations_work_in_read_only_mode(remote_web: WebApp) -> None:
    draft = draft_json(*BUDGET)
    client = remote_web.client
    preview = client.post(f"{API}/preview", json=draft)
    entries = client.post(f"{API}/entries", json=draft)
    detect = client.post(f"{API}/sources/detect", json={"sample": "a,b,c\n1,2,3\n"})
    export = client.post(f"{API}/export", params={"format": "csv"}, json=draft)
    assert [r.status_code for r in (preview, entries, detect, export)] == [200, 200, 200, 200]
    assert preview.json()["stats"]["links"] == 4
    assert entries.json()["total"] == 4
    assert detect.json() == {"format": "csv"}
    assert export.headers["content-type"] == "text/csv; charset=utf-8"
    assert "Salary" in export.text


def test_every_read_is_available_in_read_only_mode(remote_web: WebApp) -> None:
    stored = save(remote_web, "Budget", *BUDGET)
    paths = [
        f"{API}/health",
        f"{API}/settings",
        f"{API}/graphs",
        f"{API}/graphs/{stored.id}",
        f"{API}/graphs/{stored.id}/render",
        f"{API}/graphs/{stored.id}/export?format=json",
        f"{API}/graphs/export?ids={stored.id}",
        f"{API}/compare/render?ids={stored.id}",
        f"{API}/tags",
        f"{API}/folders",
        f"{API}/sources/files",
        "/",
        f"/?folder={UNKNOWN_ID}",
        f"/graphs/{stored.id}",
        f"/graphs/{stored.id}/edit",
        f"/compare?ids={stored.id}",
        "/settings",
        "/graphs/new",
        "/static/vendor/plotly.min.js",
    ]
    statuses = {path: remote_web.client.get(path).status_code for path in paths}
    assert statuses == dict.fromkeys(paths, 200)


@pytest.mark.parametrize("endpoint", SAFE, ids=ids(SAFE))
def test_no_read_is_ever_a_403(remote_web: WebApp, endpoint: Endpoint) -> None:
    assert remote_web.client.get(endpoint.path).status_code != 403


@pytest.mark.parametrize("endpoint", PERSISTING_ENDPOINTS, ids=ids(PERSISTING_ENDPOINTS))
def test_with_remote_writes_the_persisting_routes_are_open(
    make_app: AppFactory, endpoint: Endpoint
) -> None:
    web = make_app(mode="remote_writes")
    status, body = send(web, endpoint, b"{}")
    assert status != 403
    assert body != REFUSED


def test_remote_writes_really_write(make_app: AppFactory) -> None:
    web = make_app(mode="remote_writes")
    created = web.client.post(f"{API}/graphs", json={"name": "Open", **draft_json(*BUDGET)})
    assert created.status_code == 201
    assert web.client.delete(f"{API}/graphs/{created.json()['id']}").status_code == 204
    assert web.client.put(f"{API}/settings", json={"theme": "dark"}).status_code == 200


def test_every_route_of_the_table_is_either_a_read_or_classified() -> None:
    reads = {e.label for e in ENDPOINTS} - {e.label for e in UNSAFE}
    assert all(label.startswith("GET ") for label in reads)
