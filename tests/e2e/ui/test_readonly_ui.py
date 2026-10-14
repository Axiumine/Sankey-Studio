"""E2E.md B.8, the remote read-only server: banners, locked controls, and writes refused anyway.

``remote_mode=True`` is ``--allow-remote`` without ``--allow-remote-writes``. The graphs are put in
through the server's own services (what the owner did before starting it to others); the browser
can then only look, preview and export.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from sankey_studio.models import GraphCreate
from tests.e2e.support.builders import (
    BUDGET,
    MONGO_PASSWORD,
    graph_create,
    mongo_settings,
    unique_name,
)
from tests.e2e.support.clients import fetch_json
from tests.e2e.support.ui_b_common import DESKTOP, download_text
from tests.e2e.support.ui_b_editor import EditorPage
from tests.e2e.support.ui_b_library import LibraryPage
from tests.e2e.support.ui_b_settings import SettingsPage

if TYPE_CHECKING:
    from playwright.sync_api import Request

    from tests.e2e.support.pages import AppPage
    from tests.e2e.support.server import LiveServer, ServerFactory
    from tests.e2e.support.session import PageOpener
    from tests.e2e.support.watch import WatchedPage

NOT_AVAILABLE = "Not available: this server is read-only"


@pytest.fixture
def live_server(make_server: ServerFactory) -> LiveServer:
    return make_server(remote_mode=True, settings=mongo_settings("main", "flows"))


def stored_graph(server: LiveServer, name: str) -> str:
    """Save a graph in the server's store, around the HTTP guard; returns its id."""
    created = server.services.graphs().create(GraphCreate.model_validate(graph_create(name)))
    return created.id


def expect_banners(page: AppPage) -> None:
    expect(page.remote_banner).to_contain_text("Remote mode")
    expect(page.read_only_banner).to_contain_text("Read-only")


# ------------------------------------------------------------------------------ settings


def record_writes(page: WatchedPage) -> list[str]:
    """The URL of every non-GET request the page makes from now on."""
    writes: list[str] = []

    def note(request: Request) -> None:
        if request.method != "GET":
            writes.append(request.url)

    page.on("request", note)
    return writes


def expect_settings_locked(settings: SettingsPage) -> None:
    expect(settings.save_button).to_be_disabled()
    expect(settings.tid("connection-add")).to_be_disabled()
    expect(settings.tid("settings-test-storage")).to_be_disabled()
    expect(settings.tid("settings-storage-backend")).to_be_disabled()
    for key in ("max_links", "max_drawn_links", "max_upload_mb", "mongo_timeout_ms"):
        expect(settings.limit(key)).to_be_disabled()
    card = settings.connection(0)
    for locked in ("connection-test", "connection-delete", "connection-uri"):
        expect(card.get_by_test_id(locked)).to_be_disabled()
    expect(card).to_contain_text(
        "Stored: mongodb://***. Connection strings cannot be changed because this server is "
        "read-only."
    )
    migrate = settings.tid("settings-migrate")
    expect(migrate).not_to_be_checked()
    expect(migrate).to_be_disabled()
    nothing = "Not available: this server is read-only, so nothing can be copied."
    expect(settings.page.get_by_text(nothing)).to_be_visible()


def test_the_settings_page_is_locked_hides_secrets_and_the_theme_stays_on_this_device(
    page: WatchedPage, live_server: LiveServer
) -> None:
    writes = record_writes(page)
    settings = SettingsPage(page, live_server)
    settings.goto()
    expect_banners(settings)
    remote = "Remote: reachable from other machines"
    expect(settings.tid("settings-remote-mode")).to_have_text(remote)
    expect(settings.tid("settings-writes-allowed")).to_have_text("Read-only")
    expect(settings.tid("settings-sources-dir")).to_have_text(str(live_server.sources_dir))
    expect_settings_locked(settings)
    content = page.content()
    for hidden in (MONGO_PASSWORD, "tester", "mongo.invalid"):
        assert hidden not in content, f"{hidden!r} is visible on a read-only server"
    expect(page.locator("html")).to_have_attribute("data-theme-source", "device")
    settings.theme_button("dark").click()  # the switch still works, on this device only
    settings.expect_html_theme("dark")
    page.reload()
    settings.expect_ready()
    settings.expect_html_theme("dark")  # remembered by the browser
    assert writes == []  # nothing was sent to the server
    assert settings.stored()["theme"] == "system"


# ------------------------------------------------------------------------------ library and editor


def test_the_library_lists_graphs_but_cannot_change_them_and_an_empty_one_offers_nothing(
    page: WatchedPage, live_server: LiveServer
) -> None:
    name = unique_name("Look")
    graph_id = stored_graph(live_server, name)
    library = LibraryPage(page, live_server)
    library.goto()
    expect_banners(library)
    expect(library.page.locator(".readonly-note")).to_have_text(
        "Read-only server: duplicating, deleting, moving and importing are turned off. "
        "You can still open, preview and export graphs."
    )
    card = library.card(name)
    expect(card).to_be_visible()
    for action in ("graph-duplicate", "graph-delete"):
        button = card.get_by_test_id(action)
        expect(button).to_be_disabled()
        expect(button).to_have_attribute("title", NOT_AVAILABLE)
    expect(library.tid("library-import")).to_have_attribute("aria-disabled", "true")
    expect(library.tid("library-export")).to_be_enabled()  # reading is fine
    live_server.services.graphs().delete(graph_id)  # the owner removes it behind the server's back
    page.reload()
    library.expect_ready()
    empty = library.tid("library-empty")
    expect(empty).to_contain_text("This server is read-only, so graphs cannot be created")
    expect(empty.get_by_role("link", name="Create your first graph")).to_have_count(0)


def test_the_editor_previews_and_exports_but_cannot_save_or_upload(
    page: WatchedPage, live_server: LiveServer
) -> None:
    graph_id = stored_graph(live_server, unique_name("Edit"))
    editor = EditorPage(page, live_server, graph_id)
    editor.goto()
    expect_banners(editor)
    expect(editor.tid("save-button")).to_be_disabled()
    expect(editor.tid("save-as-copy")).to_be_disabled()
    expect(editor.status).to_have_text(
        "Read-only server: saving is turned off. You can still preview and export."
    )
    editor.source.fill(BUDGET.csv.replace("3000", "3300"))
    expect(editor.tid("stats")).to_contain_text("4,100")  # the preview recomputed the totals
    editor.open_export()
    name, text = download_text(page, editor.tid("export-csv").click)
    assert name.endswith(".csv")
    assert text.splitlines()[0] == "source,target,value,category"
    editor.tid("source-tab-upload").click()
    expect(editor.tid("source-upload-input")).to_be_disabled()
    editor.expect_settled()


def test_a_browser_that_bypasses_the_buttons_is_refused_by_the_server(
    page: WatchedPage, live_server: LiveServer
) -> None:
    library = LibraryPage(page, live_server)
    library.goto()
    page.allow_http(403, "/api/v1/")  # these writes are the point of the test
    created = fetch_json(page, "POST", "/api/v1/graphs", graph_create("sneaky"))
    assert created.status == 403
    assert created.json["error"]["code"] == "read_only_mode"
    saved = fetch_json(page, "PUT", "/api/v1/settings", {"max_links": 1000})
    assert (saved.status, saved.json["error"]["code"]) == (403, "read_only_mode")
    assert library.page.watch.matching(r"^http 403: ")


# ------------------------------------------------------------------------------ remote with writes


def test_a_remote_server_with_writes_shows_the_remote_banner_only(
    make_server: ServerFactory, open_page: PageOpener
) -> None:
    server = make_server(remote_mode=True, allow_remote_writes=True)
    settings = SettingsPage(open_page(server, color_scheme="light", viewport=DESKTOP), server)
    settings.goto()
    expect(settings.remote_banner).to_be_visible()
    expect(settings.read_only_banner).to_have_count(0)
    expect(settings.tid("settings-writes-allowed")).to_have_text("Allowed")
    settings.set_limit("max_links", "5000")
    settings.save()
    expect(settings.save_status).to_have_text("All changes saved.")
    assert settings.stored()["max_links"] == 5000
