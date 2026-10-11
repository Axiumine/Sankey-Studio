"""E2E.md B.6, a graph edited in two tabs: the second save meets a conflict (409) and is not lost.

Tab B saves first; tab A then saves a stale revision. Nothing of A may reach the server until the
person chooses: reload (discard A's edit) or save A's version as a copy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_editor import EditorPage

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

CONFLICT = "/api/v1/graphs/"


class Tabs:
    """Two editors of the same graph in one browser context."""

    def __init__(self, page: WatchedPage, server: LiveServer, graph_id: str, base: str) -> None:
        self.graph_id = graph_id
        self.base = base
        self.a = EditorPage(page, server, graph_id)
        self.b = EditorPage(page.new_tab(), server, graph_id)
        self.a.goto()
        self.b.goto()
        self.a.page.allow_http(409, CONFLICT + graph_id)

    def settle(self) -> None:
        """Both editors are idle (the harness stops the server before it closes the pages)."""
        self.a.expect_settled()
        self.b.expect_settled()

    def collide(self, revision: int, label: str) -> tuple[str, str]:
        """B saves ``revision``; A then saves its stale one and gets the banner."""
        name_a, name_b = f"{self.base} {label} A", f"{self.base} {label} B"
        self.b.rename_and_save(name_b, revision)
        self.a.rename(name_a)
        self.a.save()
        expect(self.a.banner).to_be_visible()
        return name_a, name_b


@pytest.fixture
def tabs(page: WatchedPage, live_server: LiveServer, api: httpx.Client) -> Tabs:
    base = unique_name("Shared")
    return Tabs(page, live_server, seed_graph(api, base)["id"], base)


def stored(api: httpx.Client, graph_id: str) -> dict[str, object]:
    return dict(json_of(api.get(f"/api/v1/graphs/{graph_id}")))


def test_a_stale_save_shows_the_banner_and_reload_or_save_as_copy_get_out_of_it(
    tabs: Tabs, api: httpx.Client
) -> None:
    _name_a, name_b = tabs.collide(2, "first")
    banner = tabs.a.banner
    expect(banner).to_contain_text("This graph was saved somewhere else after you opened it.")
    expect(banner).to_contain_text("It is now at revision 2")
    expect(banner).to_contain_text("Your changes are not saved.")
    expect(tabs.a.status).to_contain_text("Unsaved changes")
    assert stored(api, tabs.graph_id)["name"] == name_b  # nothing of A reached the server
    assert tabs.a.page.watch.matching(r"^http 409: PUT ")
    tabs.a.tid("conflict-reload").click()  # way out 1: drop my edit
    expect(banner).to_be_hidden()
    expect(tabs.a.name_field).to_have_value(name_b)
    expect(tabs.a.status).to_contain_text("Revision 2")
    expect(tabs.a.status).to_contain_text("All changes saved")
    name_a, name_b3 = tabs.collide(3, "second")  # way out 2: keep both versions
    tabs.a.tid("conflict-save-copy").click()
    copy_name = f"{name_a} (copy)"
    tabs.a.expect_toast(f"Saved as a copy: {copy_name}.", "success")
    expect(banner).to_be_hidden()
    expect(tabs.a.status).to_contain_text("All changes saved")
    found = json_of(api.get("/api/v1/graphs", params={"q": tabs.base}))["items"]
    assert {item["name"] for item in found} == {name_b3, copy_name}
    original = next(item for item in found if item["id"] == tabs.graph_id)
    copy = next(item for item in found if item["id"] != tabs.graph_id)
    assert (original["name"], original["revision"]) == (name_b3, 3)  # A never overwrote anything
    assert copy["revision"] == 1
    expect(tabs.a.page).to_have_url(tabs.a.server.url_for(f"/graphs/{copy['id']}/edit"))
    tabs.settle()


def test_a_graph_deleted_elsewhere_offers_to_save_my_version_as_a_new_graph(
    tabs: Tabs, api: httpx.Client
) -> None:
    assert api.delete(f"/api/v1/graphs/{tabs.graph_id}").status_code == 204
    tabs.a.page.allow_http(404, CONFLICT + tabs.graph_id)
    name_a = f"{tabs.base} lonely"
    tabs.a.rename(name_a)
    tabs.a.save()
    expect(tabs.a.banner).to_contain_text("This graph no longer exists")
    expect(tabs.a.tid("conflict-reload")).to_be_hidden()
    tabs.a.tid("conflict-save-copy").click()
    expect(tabs.a.banner).to_be_hidden()
    expect(tabs.a.status).to_contain_text("All changes saved")
    found = json_of(api.get("/api/v1/graphs", params={"q": tabs.base}))["items"]
    assert [item["name"] for item in found] == [f"{name_a} (copy)"]
    tabs.settle()
