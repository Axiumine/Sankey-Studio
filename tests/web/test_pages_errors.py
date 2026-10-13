"""The HTML error pages: a browser never gets the JSON envelope for a page that failed.

A browser navigation (``GET`` with ``Accept: text/html`` outside ``/api/`` and ``/static/``) gets
the app-shell page ``error.html`` for EVERY error of a page, with the status of the error and
``Cache-Control: no-store``: an unreachable graph store (503 ``storage_error``) says so, naming
MongoDB or the graphs folder after the stored backend; any other domain, HTTP or unexpected error
is "Something went wrong". Nothing of the request or of the error text is ever in the page. API
paths and clients that do not ask for HTML keep the envelope. ``/graphs/new`` and ``/settings``
never touch the store and open while it is down. The 404 pages are in ``test_pages_notfound.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, NamedTuple

import pytest
from fastapi import APIRouter, HTTPException

from sankey_studio import errors as domain
from sankey_studio.models import AppSettings
from sankey_studio.web import errors as web_errors
from tests.web.conftest import SAME_ORIGIN, new_client
from tests.web.test_pages_notfound import BROWSER, HOSTILE, HTML, heading_of
from tests.web.test_pages_support import DATA_ID, JSON_TYPE, parse, unversioned
from tests.web.test_routes_graphs_support import PLAIN, UNKNOWN_ID, code, save

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import AppFactory, WebApp

#: Text of the exception: it carries a secret and a path, and must never reach the page.
LEAK: Final = "mongodb://u:hunter2@db.invalid/ in /srv/app/store.py"
DATABASE: Final = (
    "The graph database is not reachable right now. Check that MongoDB is running, then reload."
)
FOLDER: Final = (
    "The graphs folder cannot be read right now. Check that it exists and that you can read it, "
    "then reload."
)
GENERIC: Final = "The server could not show this page. Reload it, or go back to the library."
STORAGE_JSON: Final = {"error": {"code": "storage_error", "message": LEAK, "details": []}}


class Variant(NamedTuple):
    """What an error page must say: status, heading, sentence and the boot ``kind``."""

    status: int
    heading: str
    text: str
    kind: str


DATABASE_PAGE: Final = Variant(503, "Graph database unavailable", DATABASE, "database")
FOLDER_PAGE: Final = Variant(503, "Graphs folder unavailable", FOLDER, "folder")
GENERIC_PAGE: Final = Variant(500, "Something went wrong", GENERIC, "server")


def down_paths(graph_id: str) -> list[str]:
    return ["/", f"/graphs/{graph_id}", f"/graphs/{graph_id}/edit", f"/compare?ids={graph_id}"]


def store_down(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read of the graph store fails with a ``StorageError`` that carries ``LEAK``."""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise domain.StorageError(LEAK)

    repo = type(web.services.graphs())
    for method in ("list_graphs", "count", "get", "create"):
        monkeypatch.setattr(repo, method, boom)


def mongo_settings(app_settings: AppSettings) -> AppSettings:
    return app_settings.model_copy(
        update={"storage_backend": "mongo", "storage_connection": "test"}
    )


def assert_error_page(response: Response, expected: Variant) -> None:
    status, heading, text, kind = expected
    page = parse(response)
    assert response.status_code == status
    assert response.headers["content-type"] == HTML
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("<!doctype html>")
    assert heading_of(response) == heading
    assert f"<title>{heading} - Sankey Studio</title>" in response.text
    assert text in response.text
    assert 'data-page="error"' in response.text
    assert page.data()["kind"] == kind
    assert page.find("div", data_testid="state-error", role="alert")
    assert not page.find("div", data_testid="state-empty")
    assert page.find("main", data_testid="app-root")
    assert page.find("div", data_testid="theme-switch")
    assert '{"error"' not in response.text


def actions_of(response: Response) -> list[tuple[str, str]]:
    """``(href, text)`` of the links of the card, from Reload on."""
    links = [link for link in parse(response).links if link.area == "page"]
    start = next(index for index, link in enumerate(links) if link.testid == "state-retry")
    return [(link.href, link.text) for link in links[start:]]


# ---------------------------------------------------------------------- the store is down


@pytest.mark.parametrize("index", range(4))
def test_a_page_with_the_graph_database_down_is_the_database_page(
    make_app: AppFactory,
    app_settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
    index: int,
) -> None:
    web = make_app(settings=mongo_settings(app_settings))
    stored = save(web, "Stored before the outage", *PLAIN)
    path = down_paths(stored.id)[index]
    store_down(web, monkeypatch)
    response = web.client.get(path, headers=BROWSER)
    assert_error_page(response, DATABASE_PAGE)
    assert actions_of(response) == [
        ("", "Reload"),
        ("/", "Back to the library"),
        ("/settings", "Open Settings"),
    ]
    assert LEAK not in response.text
    assert "hunter2" not in response.text
    assert stored.id not in response.text


@pytest.mark.parametrize("index", range(4))
def test_a_page_with_the_graphs_folder_unusable_is_the_folder_page(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    stored = save(web, "Stored before the outage", *PLAIN)
    path = down_paths(stored.id)[index]
    store_down(web, monkeypatch)
    response = web.client.get(path, headers=BROWSER)
    assert_error_page(response, FOLDER_PAGE)
    assert "MongoDB" not in response.text
    assert LEAK not in response.text


def test_the_folder_page_is_the_answer_when_the_settings_cannot_be_read(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise domain.StorageError(LEAK)

    monkeypatch.setattr(type(web.services), "graphs", boom)
    web.config.data_dir.mkdir(parents=True, exist_ok=True)
    web.config.settings_file.write_text("{ not json", encoding="utf-8")
    response = web.client.get("/", headers=BROWSER)
    assert_error_page(response, FOLDER_PAGE)
    assert parse(response).data()["theme"] == "system"


def test_unreadable_settings_are_a_generic_page_with_their_own_status(web: WebApp) -> None:
    web.config.data_dir.mkdir(parents=True, exist_ok=True)
    web.config.settings_file.write_text("{ not json", encoding="utf-8")
    assert_error_page(web.client.get("/", headers=BROWSER), GENERIC_PAGE._replace(status=422))


def test_reload_is_a_plain_link_to_the_document_itself(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_down(web, monkeypatch)
    response = web.client.get(f"/compare?ids={UNKNOWN_ID}", headers=BROWSER)
    page = parse(response)
    (reload_link,) = page.find("a", data_testid="state-retry")
    assert reload_link["href"] == ""  # same path and query, written nowhere in the page
    assert UNKNOWN_ID not in response.text
    assert "ids=" not in response.text
    assert [script.attrs.get("type") for script in page.scripts if not script.attrs.get("src")] == [
        JSON_TYPE
    ]
    assert page.find("button", data_testid="state-retry") == []


def test_the_page_loads_only_the_shell_script_and_its_data_block(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_down(web, monkeypatch)
    page = parse(web.client.get("/", headers=BROWSER))
    data = [script for script in page.scripts if script.attrs.get("type") == JSON_TYPE]
    assert [script.attrs["id"] for script in data] == [DATA_ID]
    sources = [script.attrs.get("src") for script in page.scripts if script not in data]
    assert [unversioned(src or "") for src in sources] == [
        "/static/js/core/theme-init.js",
        "/static/js/core/shell.js",
    ]
    assert page.data() == {
        "page": "error",
        "kind": "folder",
        "remote_mode": False,
        "writes_allowed": True,
        "theme": "system",
    }


@pytest.mark.parametrize("suffix", ["", "/edit"])
def test_nothing_of_the_request_or_of_the_error_is_in_the_page(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    store_down(web, monkeypatch)
    paths = [f"/graphs/{HOSTILE}{suffix}", f"/compare?ids={HOSTILE}", f"/?q={HOSTILE}"]
    for path in paths:
        response = web.client.get(path, headers=BROWSER)
        assert response.status_code in {404, 422, 503}, path
        for leaked in ("ZQXmark", "alert(1)", "hunter2", "db.invalid", "/srv/app"):
            assert leaked not in response.text, path


def test_the_page_keeps_the_banners_and_the_stored_theme(
    make_app: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    web = make_app(mode="remote_read_only", settings=AppSettings(theme="dark"))
    store_down(web, monkeypatch)
    page = parse(web.client.get("/", headers=BROWSER))
    assert page.find("html")[0]["data-theme"] == "dark"
    assert page.find("div", data_testid="remote-banner")
    assert page.find("div", data_testid="read-only-banner")
    assert (page.data()["remote_mode"], page.data()["writes_allowed"]) == (True, False)


def test_the_page_carries_the_security_headers(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_down(web, monkeypatch)
    response = web.client.get("/", headers=BROWSER)
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"


def test_the_pages_that_never_touch_the_store_open_while_it_is_down(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_down(web, monkeypatch)
    for path in ("/graphs/new", "/settings"):
        response = web.client.get(path, headers=BROWSER)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store"
        assert parse(response).data()["page"] in {"new", "settings"}


@pytest.mark.parametrize("accept", ["*/*", "application/json", "text/plain", ""])
def test_a_client_that_does_not_ask_for_html_keeps_the_json_envelope(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, accept: str
) -> None:
    store_down(web, monkeypatch)
    for path in down_paths(UNKNOWN_ID):
        response = web.client.get(path, headers={"Accept": accept})
        assert (response.status_code, response.json()) == (503, STORAGE_JSON), path
        assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "path", ["/api/v1/graphs", f"/api/v1/graphs/{UNKNOWN_ID}", "/static/nope.js"]
)
def test_api_and_static_paths_stay_json_for_a_browser(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    store_down(web, monkeypatch)
    response = web.client.get(path, headers=BROWSER)
    assert response.headers["content-type"] == "application/json"
    assert code(response) in {"storage_error", "not_found"}


def test_only_get_gets_the_page(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> None:
    store_down(web, monkeypatch)
    body = {"name": "x", "source": {"type": "manual", "links": []}}
    response = web.client.post("/api/v1/graphs", headers=BROWSER, json=body)
    assert response.headers["content-type"] == "application/json"
    assert (response.status_code, code(response)) == (503, "storage_error")


# ---------------------------------------------------------------------- any other error

probe = APIRouter()
DOMAIN_ERRORS = {
    "busy": domain.BusyError(LEAK),
    "conflict": domain.ConflictError(LEAK, current_revision=2),
    "source": domain.SourceError(LEAK),
    "failed": domain.ExportFailedError(LEAK),
    "plain": domain.SankeyError(LEAK, details=[LEAK]),
}


@probe.get("/probe/domain/{name}")
def _domain(name: str) -> None:
    raise DOMAIN_ERRORS[name]


@probe.get("/probe/http/{status}")
def _http(status: int) -> None:
    raise HTTPException(status_code=status, detail=LEAK, headers={"X-Extra": "1"})


@probe.get("/probe/boom")
def _boom() -> None:
    raise RuntimeError(LEAK)


class Failure(NamedTuple):
    name: str
    status: int


DOMAIN_CASES = [
    Failure("busy", 503),
    Failure("conflict", 409),
    Failure("source", 422),
    Failure("failed", 502),
    Failure("plain", 400),
]


@pytest.mark.parametrize("case", DOMAIN_CASES, ids=lambda c: c.name)
def test_any_domain_error_of_a_page_is_the_generic_page_with_its_status(
    make_app: AppFactory, case: Failure
) -> None:
    web = make_app([probe])
    response = web.client.get(f"/probe/domain/{case.name}", headers=BROWSER)
    assert_error_page(response, GENERIC_PAGE._replace(status=case.status))
    assert actions_of(response)[0] == ("", "Reload")
    assert "hunter2" not in response.text
    assert "/srv/app" not in response.text
    json_answer = web.client.get(f"/probe/domain/{case.name}")
    assert json_answer.status_code == case.status
    assert json_answer.headers["content-type"] == "application/json"


@pytest.mark.parametrize("status", [400, 403, 405, 418, 500, 502])
def test_any_http_error_of_a_page_is_the_generic_page_keeping_status_and_headers(
    make_app: AppFactory, status: int
) -> None:
    web = make_app([probe])
    response = web.client.get(f"/probe/http/{status}", headers=BROWSER)
    assert_error_page(response, GENERIC_PAGE._replace(status=status))
    assert response.headers["x-extra"] == "1"
    assert "hunter2" not in response.text
    json_answer = web.client.get(f"/probe/http/{status}")
    assert json_answer.status_code == status
    assert json_answer.headers["content-type"] == "application/json"
    assert json_answer.json()["error"]["code"] in {"http_error", "method_not_allowed"}


def test_a_404_raised_by_a_page_is_still_the_not_found_page(make_app: AppFactory) -> None:
    web = make_app([probe])
    response = web.client.get("/probe/http/404", headers=BROWSER)
    assert response.status_code == 404
    assert heading_of(response) == "Page not found"
    assert 'data-page="notfound"' in response.text


def unexpected(web: WebApp) -> Response:
    client = new_client(web.app, SAME_ORIGIN, raise_exc=False)
    return client.get("/probe/boom", headers=BROWSER)


def test_an_unexpected_error_of_a_page_is_the_generic_500_page(make_app: AppFactory) -> None:
    web = make_app([probe])
    response = unexpected(web)
    assert_error_page(response, GENERIC_PAGE)
    for leaked in ("hunter2", "RuntimeError", "Traceback", "/srv/app", "db.invalid"):
        assert leaked not in response.text
    # produced outside the security-headers middleware, so it must carry them itself
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert list(response.headers).count("content-security-policy") == 1


def test_an_unexpected_error_still_reaches_the_test_by_default(make_app: AppFactory) -> None:
    web = make_app([probe])
    with pytest.raises(RuntimeError, match="hunter2"):
        web.client.get("/probe/boom", headers=BROWSER)


def test_an_unexpected_error_for_a_client_without_html_is_the_envelope(
    make_app: AppFactory,
) -> None:
    web = make_app([probe])
    client = new_client(web.app, SAME_ORIGIN, raise_exc=False)
    response = client.get("/probe/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "details": []}
    }


def test_when_the_error_page_cannot_be_rendered_the_envelope_answers(
    make_app: AppFactory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError(LEAK)

    web = make_app([probe])
    monkeypatch.setattr(web_errors, "error_page", broken)
    with caplog.at_level(logging.ERROR, logger="sankey_studio.web.errors"):
        response = unexpected(web)
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "internal_error"
    assert "hunter2" not in response.text
    assert [record.getMessage() for record in caplog.records] == [
        "The error page could not be rendered"
    ]
