"""E2E.md B.11, failures: the error envelope reaches the person as a sentence, never as JSON.

Some failures are real (a stopped server, an unreachable MongoDB), the rest are answers the server
could give, served by ``page.route`` from the browser side.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest
from playwright.sync_api import expect

from sankey_studio.models import GraphCreate
from tests.e2e.support.builders import MONGO_PASSWORD, graph_create, mongo_settings, unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_common import DESKTOP
from tests.e2e.support.ui_b_editor import EditorPage
from tests.e2e.support.ui_b_library import LibraryPage

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Route

    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage

UNREACHABLE: Final = "Cannot reach the server. Check that Sankey Studio is still running."
RAW_FRAGMENTS: Final = ('{"', '"error"', "Traceback", "<html", "<h1>", "internal_error")
API_ROUTE: Final = "**/api/**"
DUPLICATE_ROUTE: Final = "**/api/v1/graphs/*/duplicate"


class Failure(NamedTuple):
    """An answer the server could give and the one sentence the person must see for it."""

    status: int
    body: str
    content_type: str
    shown: str


def envelope(code: str, message: str, details: tuple[str, ...] = ()) -> str:
    return json.dumps({"error": {"code": code, "message": message, "details": list(details)}})


def json_failure(status: int, code: str, message: str, shown: str) -> Failure:
    return Failure(status, envelope(code, message), "application/json", shown)


TOO_BIG = envelope("payload_too_large", "Too big", ("limit_bytes=8388608",))
FAILURES: Final = [
    json_failure(500, "internal_error", "Something went wrong.", "Something went wrong."),
    json_failure(503, "busy", "Too many exports at once.", "Too many exports at once."),
    Failure(413, TOO_BIG, "application/json", "That is too large for the server (limit 8 MB)."),
    json_failure(
        415, "unsupported_media_type", "text/plain", "The server did not accept that kind of data."
    ),
    json_failure(
        403,
        "forbidden",
        "Cross-origin request refused",
        "The server refused this request because it did not come from the app itself.",
    ),
    Failure(502, "<html><h1>Bad Gateway</h1></html>", "text/html", "Request failed (502)"),
    Failure(500, '{"detail": "not our envelope"}', "application/json", "Request failed (500)"),
]


def answer(failure: Failure) -> Any:
    def handler(route: Route) -> None:
        route.fulfill(status=failure.status, body=failure.body, content_type=failure.content_type)

    return handler


def refuse(route: Route) -> None:
    """What the browser sees while nothing listens on the port."""
    route.abort("connectionrefused")


# ------------------------------------------------------------------------------ envelopes


def test_every_kind_of_error_answer_becomes_one_plain_sentence_in_a_toast(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    name = unique_name("Err")
    seed_graph(api, name)
    library = LibraryPage(page, live_server)
    library.goto(f"?q={name}")
    duplicate = library.card(name).get_by_test_id("graph-duplicate")
    for failure in FAILURES:
        page.allow_http(failure.status, "/duplicate")
        page.route(DUPLICATE_ROUTE, answer(failure))
        duplicate.click()
        toast = library.expect_toast(failure.shown, "error")
        shown = toast.inner_text()
        for fragment in RAW_FRAGMENTS:
            assert fragment not in shown, f"raw server output in the toast: {shown!r}"
        toast.get_by_role("button").first.click()
        page.unroute(DUPLICATE_ROUTE)
        expect(library.cards).to_have_count(1)  # nothing was copied, and the page still works
    duplicate.click()  # the real server again
    library.expect_toast(f"Created “{name} (copy)”.", "success")
    library.expect_names([f"{name} (copy)", name])  # the list reloaded: the page is idle again


def test_a_failed_save_keeps_the_edit_and_the_next_try_works(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    graph = seed_graph(api, unique_name("Retry"))
    route = f"**/api/v1/graphs/{graph['id']}"
    editor = EditorPage(page, live_server, graph["id"])
    editor.goto()
    page.allow_http(500, f"/api/v1/graphs/{graph['id']}")
    page.route(route, answer(json_failure(500, "internal_error", "Could not save the graph.", "")))
    editor.rename("Renamed after trouble")
    editor.save()
    toast = editor.expect_toast("Could not save the graph.", "error")
    assert "{" not in toast.inner_text()
    expect(editor.status).to_have_attribute("data-state", "error")
    expect(editor.status).to_contain_text("Could not save the graph.")
    editor.expect_name("Renamed after trouble")  # nothing is lost
    page.unroute(route)
    editor.save()
    expect(editor.status).to_contain_text("Revision 2")
    expect(editor.status).to_contain_text("All changes saved")
    editor.expect_settled()


# ------------------------------------------------------------------------------ storage outage


class MongoStore:
    """A server whose graphs live in (mongomock) MongoDB, with one graph stored in it."""

    def __init__(self, server: LiveServer) -> None:
        self.server = server
        self.name = unique_name("InMongo")
        graph = GraphCreate.model_validate(graph_create(self.name))
        self.graph_id = server.services.graphs().create(graph).id

    def outage(self, *, down: bool) -> None:
        self.server.mongo.unreachable = down


@pytest.fixture
def mongo_store(make_server: ServerFactory) -> MongoStore:
    config = {
        **mongo_settings("main", "flows"),
        "storage_backend": "mongo",
        "storage_connection": "main",
    }
    return MongoStore(make_server(settings=config))


def test_a_graph_database_that_goes_away_gives_a_retry_that_works_once_it_is_back(
    mongo_store: MongoStore, open_page: PageOpener
) -> None:
    server = mongo_store.server
    library = LibraryPage(open_page(server, color_scheme="light", viewport=DESKTOP), server)
    library.goto()
    expect(library.card(mongo_store.name)).to_be_visible()
    library.page.allow_http(503, "/api/v1/graphs")
    mongo_store.outage(down=True)
    library.search(mongo_store.name)  # the list is asked for again
    error = library.tid("state-error")
    expect(error).to_contain_text("The library could not be loaded")
    expect(error).to_contain_text("MongoDB connection 'main' is unreachable")
    for secret in (MONGO_PASSWORD, "mongo.invalid", "tester"):
        assert secret not in error.inner_text() + library.page.content()
    expect(library.cards).to_have_count(0)
    mongo_store.outage(down=False)
    library.tid("state-retry").click()
    expect(library.card(mongo_store.name)).to_be_visible()
    expect(error).to_have_count(0)


def test_opening_a_page_while_the_graph_database_is_down_shows_a_friendly_page_not_json(
    mongo_store: MongoStore, open_page: PageOpener
) -> None:
    server = mongo_store.server
    paths = {
        "library": "/",
        "viewer": f"/graphs/{mongo_store.graph_id}",
        "editor": f"/graphs/{mongo_store.graph_id}/edit",
        "compare": f"/compare?ids={mongo_store.graph_id}",
    }
    page = open_page(server, color_scheme="light", viewport=DESKTOP)
    page.allow_http(503, "")  # the document itself fails: that is what is under test
    mongo_store.outage(down=True)
    state = page.get_by_test_id("state-error")
    for where, path in paths.items():
        response = page.goto(server.url_for(path))
        assert response is not None
        assert response.status == 503, where
        assert "text/html" in response.headers["content-type"], where
        assert response.headers["cache-control"] == "no-store", where
        assert '{"error"' not in page.content(), where
        expect(page.locator("#main h1")).to_have_text("Graph database unavailable")
        expect(state).to_contain_text("The graph database is not reachable right now.")
        expect(state).to_contain_text("Check that MongoDB is running, then reload.")
        expect(state.get_by_role("link", name="Back to the library")).to_have_attribute("href", "/")
        expect(state.get_by_role("link", name="Open Settings")).to_have_attribute(
            "href", "/settings"
        )
        for secret in (MONGO_PASSWORD, "mongo.invalid", "tester", mongo_store.graph_id):
            assert secret not in page.content(), (where, secret)
    for still_open in ("/graphs/new", "/settings"):  # these never read the graph store
        opened = page.goto(server.url_for(still_open))
        assert opened is not None
        assert opened.status == 200, still_open
    page.goto(server.url_for(paths["library"]))
    mongo_store.outage(down=False)
    page.get_by_test_id("state-retry").click()  # a plain link to the same address
    expect(LibraryPage(page, server).card(mongo_store.name)).to_be_visible()
    expect(state).to_have_count(0)


# ------------------------------------------------------------------------------ server away


def test_outages_give_a_friendly_message_and_recover_and_a_stopped_server_does_not_crash_the_page(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    name = unique_name("Back")
    graph = seed_graph(api, name)
    library = LibraryPage(page, live_server)
    library.goto(f"?q={name}")
    page.allow_errors(r"ERR_CONNECTION_REFUSED")
    page.route(API_ROUTE, refuse)
    library.tid("library-search").fill(f"{name}x")
    expect(library.tid("state-error")).to_contain_text(UNREACHABLE)
    page.unroute(API_ROUTE)  # the server is reachable again
    library.tid("state-retry").click()
    expect(library.tid("state-error")).to_have_count(0)
    library.search(name)
    expect(library.card(name)).to_be_visible()
    editor = EditorPage(page, live_server, graph["id"])
    editor.goto()
    page.route(API_ROUTE, refuse)
    editor.rename("Typed while offline")
    editor.save()
    toast = editor.expect_toast(UNREACHABLE, "error")
    assert "{" not in toast.inner_text()
    expect(editor.status).to_have_attribute("data-state", "error")
    editor.expect_name("Typed while offline")  # the edit is kept
    page.unroute(API_ROUTE)
    editor.save()
    expect(editor.status).to_contain_text("Revision 2")
    expect(editor.status).to_contain_text("All changes saved")
    editor.expect_settled()
    assert json_of(api.get(f"/api/v1/graphs/{graph['id']}"))["name"] == "Typed while offline"
    live_server.stop()  # and now the real thing: the server process is gone
    editor.rename("Typed after the server stopped")
    editor.save()
    editor.expect_toast(UNREACHABLE, "error")
    expect(editor.status).to_have_attribute("data-state", "error")
    assert page.watch.matching("ERR_CONNECTION_REFUSED")  # the outage really happened
