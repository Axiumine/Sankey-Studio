"""E2E.md B.11, the HTML not-found pages: browsers get a calm page, everyone else JSON.

One server for the module. The document 404 of each visit is the one expected problem: it is
allowed per test, by path, and nothing else is.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import fetch_json, json_of, seed_graph
from tests.e2e.support.ui_b_library import LibraryPage
from tests.e2e.support.ui_b_viewer import ViewerPage
from tests.e2e.support.uiwait import wait_page, wait_shell

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Dialog, Request, Response

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

ZEROS: Final = "0" * 32
PAGE_TEXT: Final = "There is nothing at this address, so the link may be wrong or out of date."
GRAPH_TEXT: Final = "This graph does not exist any more, or the link is wrong."
TOO_MANY: Final = ",".join(f"{n:032x}" for n in range(1, 14))


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


def visit(page: WatchedPage, live_server: LiveServer, path: str) -> Response:
    """Open ``path`` (its document 404 is allowed) and wait for the shell."""
    page.allow_http(404, path.split("?", maxsplit=1)[0])
    response = page.goto(live_server.url_for(path), wait_until="commit")
    assert response is not None
    wait_shell(page)
    return response


CASES: Final = [
    ("/nope", "Page not found", PAGE_TEXT),
    ("/settings/extra", "Page not found", PAGE_TEXT),
    (f"/graphs/{ZEROS}", "Graph not found", GRAPH_TEXT),
    ("/graphs/not-an-id", "Graph not found", GRAPH_TEXT),
    ("/graphs/not-an-id/edit", "Graph not found", GRAPH_TEXT),
    (f"/graphs/{ZEROS}/edit", "Graph not found", GRAPH_TEXT),
    ("/compare?ids=bad", "Page not found", PAGE_TEXT),
    (f"/compare?ids={TOO_MANY}", "Page not found", PAGE_TEXT),
    ("/compare?other=1", "Page not found", PAGE_TEXT),
]
HOSTILE: Final = [
    "/%3Cscript%3Ealert(1)%3C/script%3E",
    "/graphs/%3Cimg%20src=x%20onerror=alert(1)%3E",
    "/compare?ids=%3Cb%3Ex%3C/b%3E",
]


def expect_not_found_page(page: WatchedPage, response: Response, heading: str, text: str) -> None:
    assert response.status == 404
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    wait_page(page, "notfound")
    expect(page.locator("#main h1")).to_have_text(heading)
    expect(page).to_have_title(f"{heading} - Sankey Studio")
    empty = page.get_by_test_id("state-empty")
    expect(empty).to_contain_text(text)
    expect(empty.get_by_role("link", name="Back to the library")).to_have_attribute("href", "/")
    for shell in ("nav-library", "nav-new", "nav-settings", "theme-switch"):
        expect(page.get_by_test_id(shell)).to_be_visible()
    sources = page.evaluate("[...document.querySelectorAll('script[src]')].map((s) => s.src)")
    assert [src.rsplit("/", 1)[-1].split("?v=")[0] for src in sources] == [
        "theme-init.js",
        "shell.js",
    ]  # no page module
    inline = page.evaluate("[...document.querySelectorAll('script:not([src])')].map((s) => s.type)")
    assert set(inline) <= {"application/json"}  # no inline code, only the boot data


def test_every_wrong_address_is_a_404_page_with_the_app_shell_and_a_way_back(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    for path, heading, text in CASES:
        expect_not_found_page(page, visit(page, live_server, path), heading, text)
    seed_graph(api, unique_name("Home"))
    page.get_by_role("link", name="Back to the library").click()
    LibraryPage(page, live_server).expect_ready()
    page.wait_for_url(live_server.url_for("/"))
    expect(page.locator("#main h1")).to_have_text("Graphs")


# ------------------------------------------------------------------------------ not browsers


def expect_not_echoed(page: WatchedPage, live_server: LiveServer, path: str) -> None:
    """A hostile address gives the plain not-found page and none of it appears in the page."""
    assert visit(page, live_server, path).status == 404
    body = page.content()
    for fragment in ("alert(1)", "onerror", "<b>x</b>", "%3C"):
        assert fragment not in body, f"{fragment!r} is echoed for {path}"
    expect(page.get_by_test_id("state-empty")).to_be_visible()
    assert page.evaluate("document.querySelectorAll('img[src=\"x\"], [onerror]').length") == 0


def test_hostile_addresses_are_not_echoed_and_non_browsers_still_get_the_json_envelope(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    dialogs: list[str] = []

    def dismiss(dialog: Dialog) -> None:
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", dismiss)
    for path in HOSTILE:
        expect_not_echoed(page, live_server, path)
    assert dialogs == []
    body = json_of(api.get("/nope"), 404)
    assert body["error"]["code"] == "not_found"
    assert api.get(f"/graphs/{ZEROS}").headers["content-type"].startswith("application/json")
    page.allow_http(404, "/nope")
    page.allow_http(404, "/api/v1/graphs/")
    page.allow_http(404, "/favicon.ico")  # a bare JSON document has no <link rel=icon>
    seen = fetch_json(page, "GET", "/nope")  # fetch sends Accept: */*: not a page
    assert (seen.status, seen.json["error"]["code"]) == (404, "not_found")
    missing = fetch_json(page, "GET", f"/api/v1/graphs/{ZEROS}")
    assert (missing.status, missing.json["error"]["code"]) == (404, "not_found")
    response = page.goto(live_server.url_for(f"/api/v1/graphs/{ZEROS}"))  # even a typed address
    assert response is not None
    assert response.status == 404
    assert response.headers["content-type"].startswith("application/json")


# ------------------------------------------------------------------------------ gone while open


def test_back_and_reload_after_the_graph_was_deleted_show_graph_not_found(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    graph = seed_graph(api, unique_name("Vanishing"))
    viewer = ViewerPage(page, live_server, graph["id"])
    viewer.goto()
    viewer.nav("library").click()
    LibraryPage(page, live_server).expect_ready()
    assert api.delete(f"/api/v1/graphs/{graph['id']}").status_code == 204
    documents: list[str] = []

    def note_document(request: Request) -> None:
        if request.resource_type == "document":
            documents.append(request.url)

    page.on("request", note_document)
    page.allow_http(404, f"/graphs/{graph['id']}")
    page.go_back()  # no-store: the browser asks the server again instead of showing its cache
    wait_page(page, "notfound")
    expect(page.locator("#main h1")).to_have_text("Graph not found")
    assert any(re.search(rf"/graphs/{graph['id']}$", url) for url in documents)
    page.reload()  # the same again after a reload
    wait_shell(page)
    wait_page(page, "notfound")
    expect(page.get_by_test_id("state-empty")).to_contain_text(GRAPH_TEXT)
