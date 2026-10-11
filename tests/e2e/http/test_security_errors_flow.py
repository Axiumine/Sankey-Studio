"""E2E.md A.8, part 3: what the server says when something goes wrong.

404 and 500 bodies hold no stack trace, source file name or file-system path; an error body never
echoes what the caller sent (a pasted password, a pipeline, a file name, a query value); an
oversize body is a 413 whatever the route and however the bytes arrive, and it stores nothing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import graph_create, graph_draft, unique_name
from tests.e2e.support.clients import json_of, make_client, seed_graph, upload_source
from tests.e2e.support.http_b_security import API, assert_no_internals, assert_security_headers
from tests.e2e.support.http_b_tape import attach
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

HTML = {"Accept": "text/html"}
MARK = "ZZMARK7F3A"
MIB = 2**20
JSON = {"Content-Type": "application/json"}
INTERNAL_ERROR = {
    "error": {"code": "internal_error", "message": "Internal server error", "details": []}
}


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


# ------------------------------------------------------------------------------ 404


@pytest.mark.parametrize(
    ("path", "accept"),
    [
        ("/api/v1/nope", "application/json"),
        ("/api/v1/graphs/zz", "application/json"),
        (f"/api/v1/graphs/{'0' * 32}/render", "application/json"),
        ("/no/such/page", "application/json"),
        ("/static/nope.css", "text/css"),
        ("/api/v1/nope", "text/html"),
    ],
)
def test_a_json_404_is_the_envelope_and_nothing_else(
    live_server: LiveServer, api: httpx.Client, path: str, accept: str
) -> None:
    response = api.get(path, headers={"Accept": accept})
    assert response.status_code == 404
    error = response.json()["error"]
    assert (error["code"], error["details"]) == ("not_found", [])
    assert_no_internals(response.text, live_server)


@pytest.mark.parametrize(
    ("path", "hidden"),
    [
        ("/zz-marker-9f2c/zz-other", "zz-marker"),
        (f"/graphs/{'0' * 32}", "0" * 32),
        (f"/graphs/{'0' * 32}/edit", "0" * 32),
        ("/graphs/zz-marker-9f2c", "zz-marker"),
    ],
)
def test_a_browser_gets_an_html_404_page_without_internals_or_the_address(
    live_server: LiveServer, api: httpx.Client, path: str, hidden: str
) -> None:
    response = api.get(path, headers=HTML)
    assert response.status_code == 404
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert_no_internals(response.text, live_server)
    assert hidden not in response.text


# ------------------------------------------------------------------------------ 500


@pytest.fixture
def broken_server(make_server: ServerFactory, monkeypatch: pytest.MonkeyPatch) -> LiveServer:
    """A server whose graph store raises an unexpected error carrying a path."""
    server = make_server()

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"disk exploded at {server.data_dir}/internal-detail")

    monkeypatch.setattr(server.services, "graphs", boom)
    return server


FAILING_CALLS = (
    pytest.param(("GET", "/api/v1/graphs", "application/json"), id="api-list"),
    pytest.param(("POST", "/api/v1/graphs", "application/json"), id="api-create"),
    pytest.param(("GET", "/", "text/html"), id="library-page"),
    pytest.param(("GET", f"/graphs/{'0' * 32}", "text/html"), id="viewer-page"),
)


@pytest.mark.parametrize("call", FAILING_CALLS)
def test_an_unexpected_failure_is_a_generic_500_with_no_detail(
    broken_server: LiveServer, caplog: pytest.LogCaptureFixture, call: tuple[str, str, str]
) -> None:
    method, path, accept = call
    caplog.set_level(logging.ERROR)
    payload = graph_create("x") if method == "POST" else None
    # the server drops the connection after an unhandled error: one client per request
    with make_client(broken_server) as client:
        headers = {"Accept": accept, "Connection": "close"}
        response = client.request(method, path, headers=headers, json=payload)
    assert response.status_code == 500
    if accept == "text/html":  # a browser navigation gets the app-shell page, never the envelope
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Something went wrong" in response.text
        assert '{"error"' not in response.text
        assert "internal_error" not in response.text
    else:
        assert response.json() == INTERNAL_ERROR
    assert_no_internals(response.text, broken_server)
    assert_security_headers(response, no_store=True)
    # it is in the server log (written just after the answer went out), not in the answer
    wait_until(lambda: "disk exploded" in caplog.text, what="the server to log the failure")
    with make_client(broken_server) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}  # still serving


# ------------------------------------------------------------------------------ no echo


def put_connection(client: httpx.Client, uri: str) -> httpx.Response:
    """``PUT /settings`` with one connection named ``x`` that has ``uri``."""
    settings = json_of(client.get(f"{API}/settings"))
    settings.pop("bootstrap")
    return client.put(
        f"{API}/settings", json={**settings, "mongo_connections": [{"name": "x", "uri": uri}]}
    )


def unsafe_preview(client: httpx.Client) -> httpx.Response:
    source = {"type": "mongo", "connection": "x", "collection": "c", "filter": {"$where": MARK}}
    return client.post(f"{API}/preview", json={"source": source})


#: label -> (request carrying ``MARK`` in a place a caller can put text, expected status)
HOSTILE: dict[str, tuple[Callable[[httpx.Client], httpx.Response], int]] = {
    "invalid-body": (lambda c: c.post(f"{API}/graphs", json={"name": MARK, "tags": MARK}), 422),
    "bad-json": (
        lambda c: c.post(f"{API}/graphs", content=f'{{"name": "{MARK}', headers=JSON),
        422,
    ),
    "bad-enum": (
        lambda c: c.post(f"{API}/preview", json={**graph_draft(), "style": {"color_mode": MARK}}),
        422,
    ),
    "bad-query-value": (lambda c: c.get(f"{API}/graphs", params={"limit": MARK}), 422),
    "unknown-graph": (lambda c: c.get(f"{API}/graphs/{MARK}"), 404),
    "unknown-page": (lambda c: c.get(f"/{MARK}/{MARK}", headers=HTML), 404),
    "bad-media-type": (
        lambda c: c.post(
            f"{API}/graphs", content="{}", headers={"Content-Type": f"application/{MARK}"}
        ),
        415,
    ),
    "unsafe-filter": (unsafe_preview, 422),
    "unknown-connection": (lambda c: c.get(f"{API}/mongo/{MARK} !/databases"), 404),
    "unsafe-uri": (
        lambda c: put_connection(c, f"mongodb://user:{MARK}pw@host/?tlsCAFile=/etc/{MARK}"),
        422,
    ),
    "garbage-uri": (lambda c: put_connection(c, f"{MARK}pw"), 422),
    "upload-path": (
        lambda c: c.post(
            f"{API}/sources/files", files={"file": (f"{MARK}/../x.csv", b"a,b,1", "text/csv")}
        ),
        400,
    ),
    "source-path": (lambda c: c.get(f"{API}/sources/files/{MARK}%2F..%2F..%2Fx/preview"), 400),
    "bad-detect": (
        lambda c: c.post(f"{API}/sources/detect", json={"sample": MARK, "extra": 1}),
        422,
    ),
    "bad-source-tag": (
        lambda c: c.post(f"{API}/graphs", json={**graph_create("x"), "source": {"type": MARK}}),
        422,
    ),
}


@pytest.mark.parametrize("label", list(HOSTILE))
def test_error_bodies_never_echo_what_the_caller_sent(
    live_server: LiveServer, api: httpx.Client, label: str
) -> None:
    send, status = HOSTILE[label]
    tape = attach(api)
    response = send(api)
    assert response.status_code == status
    tape.assert_clean([MARK, f"{MARK}pw"])
    assert_no_internals(response.text, live_server)


# ------------------------------------------------------------------------------ 413


def padded(size: int) -> bytes:
    """A JSON document of exactly ``size`` bytes (valid JSON followed by spaces)."""
    return b"{}" + b" " * (size - 2)


def test_a_json_body_over_8_mib_is_a_413_whatever_the_route(api: httpx.Client) -> None:
    routes = ("/preview", "/entries", "/graphs", "/settings", "/sources/detect")
    for route in routes:
        response = api.request(
            "PUT" if route == "/settings" else "POST",
            API + route,
            content=padded(8 * MIB + 1),
            headers=JSON,
        )
        assert response.status_code == 413, route
        assert response.json()["error"] == {
            "code": "payload_too_large",
            "message": "The request body is too large",
            "details": ["limit_bytes=8388608"],
        }
        assert_security_headers(response, no_store=True)
    assert api.get(f"{API}/health").status_code == 200  # the connection and the server are fine


def test_the_limit_counts_bytes_as_they_arrive_not_the_declared_length(api: httpx.Client) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"{}"
        for _ in range(9):
            yield b" " * MIB

    response = api.post(f"{API}/preview", content=chunks(), headers=JSON)  # chunked: no length
    assert response.status_code == 413
    assert response.json()["error"]["details"] == ["limit_bytes=8388608"]


def test_a_body_at_the_cap_is_read_and_judged_on_its_content(api: httpx.Client) -> None:
    response = api.post(f"{API}/preview", content=padded(8 * MIB), headers=JSON)
    assert response.status_code == 422  # {} is no draft: the size was fine


def test_the_bundle_import_cap_is_twice_the_json_cap(api: httpx.Client) -> None:
    allowed = api.post(f"{API}/graphs/import", content=padded(9 * MIB), headers=JSON)
    assert allowed.status_code != 413
    refused = api.post(f"{API}/graphs/import", content=padded(16 * MIB + 1), headers=JSON)
    assert refused.status_code == 413
    assert refused.json()["error"]["details"] == ["limit_bytes=16777216"]


def test_an_oversize_body_stores_nothing(make_server: ServerFactory) -> None:
    server = make_server(settings={"max_upload_mb": 1})
    huge = {**graph_create("huge"), "description": "x" * (8 * MIB)}
    with make_client(server) as api:
        assert api.post(f"{API}/graphs", json=huge).status_code == 413
        assert json_of(api.get(f"{API}/graphs"))["total"] == 0
        parts = {"file": ("big.csv", b"a,b,1\n" * (500_000), "text/csv")}  # 3 MB > 1 MiB + 1 MiB
        assert api.post(f"{API}/sources/files", files=parts).status_code == 413
        assert json_of(api.get(f"{API}/sources/files")) == []
    assert not list(server.graphs_dir.glob("*.json"))


def test_the_upload_cap_follows_the_setting_and_applies_at_once(make_server: ServerFactory) -> None:
    server = make_server(settings={"max_upload_mb": 1})
    row = b"a,b,1\n"
    with make_client(server) as api:
        small = upload_source(api, "small.csv", row * 100_000)  # 600 KB
        mid = upload_source(api, "mid.csv", row * 200_000)  # 1.2 MB: over the file cap
        assert (small.status_code, mid.status_code) == (201, 413)
        assert mid.json()["error"]["code"] == "payload_too_large"
        settings = json_of(api.get(f"{API}/settings"))
        settings.pop("bootstrap")
        assert api.put(f"{API}/settings", json={**settings, "max_upload_mb": 2}).status_code == 200
        assert upload_source(api, "mid.csv", row * 200_000).status_code == 201
        assert sorted(f["name"] for f in json_of(api.get(f"{API}/sources/files"))) == [
            "mid.csv",
            "small.csv",
        ]


def test_a_draft_just_under_the_cap_is_still_drawn(api: httpx.Client) -> None:
    draft = graph_draft()
    draft["source"]["content"] = draft["source"]["content"] + "# " + "x" * 100 + "\n"
    name = unique_name("under")
    assert seed_graph(api, name, draft)["name"] == name
