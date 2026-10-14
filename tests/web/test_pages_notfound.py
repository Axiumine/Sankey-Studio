"""The HTML not-found page: who gets it, what it says, what it never contains.

A browser navigation (``GET`` with ``Accept: text/html`` outside ``/api/`` and ``/static/``) to an
unknown URL, to a graph page whose graph is gone, or to a page query that is not valid gets a 404
page in the app shell. Every other client keeps the JSON envelope exactly as before. The page has
fixed text: the requested URL, id and query are never echoed. Every HTML answer is ``no-store``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from sankey_studio.models import AppSettings
from tests.web.test_pages_support import DATA_ID, JSON_TYPE, parse, unversioned
from tests.web.test_routes_graphs_support import MALFORMED_IDS, PLAIN, UNKNOWN_ID, code, save

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import AppFactory, WebApp

BROWSER: Final = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
HTML: Final = "text/html; charset=utf-8"
PAGE_TEXT: Final = "There is nothing at this address, so the link may be wrong or out of date."
GRAPH_TEXT: Final = "This graph does not exist any more, or the link is wrong."
NOT_FOUND_JSON: Final = {"error": {"code": "not_found", "message": "Not Found", "details": []}}
GRAPH_JSON: Final = {"error": {"code": "not_found", "message": "Graph not found", "details": []}}
HOSTILE: Final = "ZQXmark<script>alert(1)</script>\"'&amp;"


def browse(web: WebApp, path: str, **params: str) -> Response:
    return web.client.get(path, headers=BROWSER, params=params or None)


def heading_of(response: Response) -> str:
    return response.text.split("<h1>")[1].split("</h1>")[0]


def assert_not_found_page(response: Response, heading: str, text: str) -> None:
    page = parse(response)
    assert response.status_code == 404
    assert response.headers["content-type"] == HTML
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("<!doctype html>")
    assert heading_of(response) == heading
    assert f"<title>{heading} - Sankey Studio</title>" in response.text
    assert text in response.text
    assert 'data-page="notfound"' in response.text
    assert page.find("div", data_testid="state-empty")
    assert page.find("main", data_testid="app-root")
    assert page.find("div", data_testid="theme-switch")


@pytest.mark.parametrize(
    "path", ["/nope", "/graphs", "/graphs/new/x", "/compare/x", "/a/b/c", "/apix", "/staticx"]
)
def test_an_unknown_url_is_the_page_not_found_page(web: WebApp, path: str) -> None:
    assert_not_found_page(browse(web, path), "Page not found", PAGE_TEXT)


@pytest.mark.parametrize("suffix", ["", "/edit"])
@pytest.mark.parametrize("graph_id", [UNKNOWN_ID, *MALFORMED_IDS])
def test_a_gone_or_malformed_graph_is_the_graph_not_found_page(
    web: WebApp, graph_id: str, suffix: str
) -> None:
    assert_not_found_page(browse(web, f"/graphs/{graph_id}{suffix}"), "Graph not found", GRAPH_TEXT)


def test_a_deleted_graph_has_the_page_too(web: WebApp) -> None:
    stored = save(web, "Soon gone", *PLAIN)
    assert browse(web, f"/graphs/{stored.id}").status_code == 200
    web.services.graphs().delete(stored.id)
    for suffix in ("", "/edit"):
        assert_not_found_page(
            browse(web, f"/graphs/{stored.id}{suffix}"), "Graph not found", GRAPH_TEXT
        )


@pytest.mark.parametrize("ids", ["short", "x" * 32, f"{'a' * 32},short"])
def test_a_malformed_compare_query_is_the_page_not_found_page(web: WebApp, ids: str) -> None:
    assert_not_found_page(browse(web, "/compare", ids=ids), "Page not found", PAGE_TEXT)


def test_too_many_compare_ids_is_the_page_not_found_page(web: WebApp) -> None:
    ids = ",".join(f"{number:032x}" for number in range(13))
    assert_not_found_page(browse(web, "/compare", ids=ids), "Page not found", PAGE_TEXT)


def test_the_page_offers_one_way_back_to_the_library(web: WebApp) -> None:
    page = parse(browse(web, "/nope"))
    back = [(link.href, link.text) for link in page.links if "library" in link.text.lower()]
    assert back == [("/", "Library"), ("/", "Back to the library")]
    nav = [(link.href, link.text) for link in page.links if link.area == "nav"]
    assert nav == [("/", "Library"), ("/graphs/new", "New graph"), ("/settings", "Settings")]
    assert page.find("a", **{"class": "btn btn-primary"})


def test_the_page_loads_only_the_shell_script_and_its_data_block(web: WebApp) -> None:
    page = parse(browse(web, "/nope"))
    data = [script for script in page.scripts if script.attrs.get("type") == JSON_TYPE]
    assert [script.attrs["id"] for script in data] == [DATA_ID]
    sources = [script.attrs.get("src") for script in page.scripts if script not in data]
    assert [unversioned(src or "") for src in sources] == [
        "/static/js/core/theme-init.js",
        "/static/js/core/shell.js",
    ]
    assert page.find("link", href="/static/css/pages/notfound.css") == []
    assert page.data() == {
        "page": "notfound",
        "kind": "page",
        "remote_mode": False,
        "writes_allowed": True,
        "theme": "system",
    }


def test_the_graph_page_boot_data_says_it_is_about_a_graph(web: WebApp) -> None:
    data = parse(browse(web, f"/graphs/{UNKNOWN_ID}")).data()
    assert (data["page"], data["kind"]) == ("notfound", "graph")


@pytest.mark.parametrize(
    "path",
    [
        f"/{HOSTILE}",
        f"/graphs/{HOSTILE}",
        f"/graphs/{HOSTILE}/edit",
        f"/compare?ids={HOSTILE}",
        f"/nope?{HOSTILE}=1",
    ],
)
def test_nothing_of_the_request_is_echoed(web: WebApp, path: str) -> None:
    response = web.client.get(path, headers=BROWSER)
    assert response.status_code == 404
    assert "ZQXmark" not in response.text
    assert "alert(1)" not in response.text
    assert HOSTILE not in response.text


def test_the_page_never_names_the_graph_id_it_was_asked_for(web: WebApp) -> None:
    graph_id = "0123456789abcdef0123456789abcdef"
    for path in (f"/graphs/{graph_id}", f"/graphs/{graph_id}/edit", f"/nope/{graph_id}"):
        assert graph_id not in browse(web, path).text


@pytest.mark.parametrize(
    "accept",
    ["text/html", "TEXT/HTML", "text/html;q=0.9", "application/json, text/html", *BROWSER.values()],
)
def test_any_accept_header_that_names_text_html_gets_the_page(web: WebApp, accept: str) -> None:
    response = web.client.get("/nope", headers={"Accept": accept})
    assert response.status_code == 404
    assert response.headers["content-type"] == HTML


@pytest.mark.parametrize("accept", ["*/*", "application/json", "text/plain", "image/*", ""])
def test_a_client_that_does_not_ask_for_html_keeps_the_json_envelope(
    web: WebApp, accept: str
) -> None:
    headers = {"Accept": accept}
    unknown = web.client.get("/nope", headers=headers)
    graph = web.client.get(f"/graphs/{UNKNOWN_ID}", headers=headers)
    assert (unknown.status_code, unknown.json()) == (404, NOT_FOUND_JSON)
    assert (graph.status_code, graph.json()) == (404, GRAPH_JSON)
    assert unknown.headers["content-type"] == "application/json"
    bad = web.client.get("/compare", params={"ids": "short"}, headers=headers)
    assert (bad.status_code, code(bad)) == (422, "validation_error")


def test_a_request_with_no_accept_header_at_all_gets_json(web: WebApp) -> None:
    response = web.bare.get("/nope", headers={"Accept": ""})
    assert response.json() == NOT_FOUND_JSON


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api/v1/nope",
        f"/api/v1/graphs/{UNKNOWN_ID}",
        "/api/v1/graphs/short",
        "/static",
        "/static/nope.js",
    ],
)
def test_api_and_static_paths_stay_json_even_for_a_browser(web: WebApp, path: str) -> None:
    response = browse(web, path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "not_found"


def test_an_api_validation_error_stays_json_for_a_browser(web: WebApp) -> None:
    response = browse(web, "/api/v1/graphs", limit="0")
    assert (response.status_code, code(response)) == (422, "validation_error")


def test_only_get_gets_the_page(web: WebApp) -> None:
    post = web.client.post("/nope", headers=BROWSER, json={})
    assert (post.status_code, post.json()) == (404, NOT_FOUND_JSON)
    wrong_verb = web.client.post("/", headers=BROWSER, json={})
    assert (wrong_verb.status_code, code(wrong_verb)) == (405, "method_not_allowed")


def test_a_405_is_never_the_page(web: WebApp) -> None:
    response = web.client.delete("/settings", headers=BROWSER)
    assert (response.status_code, code(response)) == (405, "method_not_allowed")


def test_other_errors_of_a_page_are_not_the_not_found_page_for_a_browser(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store that is down is a 503 page (``test_pages_errors.py``), not a 404 and not JSON."""
    from sankey_studio.errors import StorageError

    def boom(*_args: object, **_kwargs: object) -> None:
        raise StorageError("Storage is unreachable")

    monkeypatch.setattr(web.services.folders().__class__, "list_folders", boom)
    response = browse(web, "/")
    assert response.status_code == 503
    assert response.headers["content-type"] == HTML
    assert 'data-page="notfound"' not in response.text
    assert '{"error"' not in response.text
    json_answer = web.client.get("/", headers={"Accept": "*/*"})
    assert (json_answer.status_code, code(json_answer)) == (503, "storage_error")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_page_is_painted_in_the_stored_theme(make_app: AppFactory, theme: str) -> None:
    web = make_app(settings=AppSettings(theme=theme))  # type: ignore[arg-type]
    page = parse(browse(web, "/nope"))
    assert page.find("html")[0]["data-theme"] == theme
    assert page.data()["theme"] == theme


def test_the_page_survives_unreadable_settings(web: WebApp) -> None:
    web.config.data_dir.mkdir(parents=True, exist_ok=True)
    web.config.settings_file.write_text("{ not json", encoding="utf-8")
    response = browse(web, "/nope")
    assert response.status_code == 404
    assert parse(response).data()["theme"] == "system"


def test_a_read_only_remote_server_shows_its_banners_on_the_page(make_app: AppFactory) -> None:
    web = make_app(mode="remote_read_only")
    page = parse(browse(web, "/nope"))
    assert page.find("div", data_testid="remote-banner")
    assert page.find("div", data_testid="read-only-banner")
    assert (page.data()["remote_mode"], page.data()["writes_allowed"]) == (True, False)


def test_the_page_carries_the_security_headers(web: WebApp) -> None:
    response = browse(web, "/nope")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("suffix", ["", "/edit"])
def test_every_html_page_is_no_store(web: WebApp, suffix: str) -> None:
    stored = save(web, "Cached?", *PLAIN)
    paths = ["/", "/graphs/new", "/settings", "/compare", f"/compare?ids={stored.id}"]
    for path in [*paths, f"/graphs/{stored.id}{suffix}"]:
        response = web.client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store", path


def test_json_answers_keep_their_own_cache_rules(web: WebApp) -> None:
    api = web.client.get("/api/v1/graphs")
    assert api.headers["cache-control"] == "no-store"
    plotly = web.client.get("/static/vendor/plotly.min.js")
    assert plotly.headers["cache-control"] == "no-store"
    static = web.client.get("/static/css/tokens.css")
    assert static.headers["cache-control"] == "no-store"
