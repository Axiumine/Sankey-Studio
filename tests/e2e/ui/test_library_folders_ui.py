"""E2E.md B.6, the library collections: create, walk, deep-link, rename and the empty states.

The user-visible word is "collection"; the code and the test ids say ``folder``. Every test has a
server of its own (a clean library), so counts and orders never depend on another test. Moving,
deleting and searching are in ``test_library_folders_actions_ui.py``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import unique_name
from tests.e2e.support.clients import json_of, seed_graph
from tests.e2e.support.ui_b_folders import FolderLibrary, seed_filed_graph, seed_folder

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import Route

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer) -> FolderLibrary:
    return FolderLibrary(page, live_server)


def url_has_folder(folder_id: str) -> re.Pattern[str]:
    return re.compile(rf"[?&]folder={folder_id}(&|$)")


# ------------------------------------------------------------------------------ nothing yet


def test_a_library_without_collections_shows_no_collection_chrome_but_the_new_button(
    library: FolderLibrary, api: httpx.Client
) -> None:
    name = unique_name("Plain")
    seed_graph(api, name)
    library.goto()
    expect(library.card(name)).to_be_visible()
    expect(library.breadcrumb).to_be_hidden()
    expect(library.folder_cards).to_have_count(0)
    expect(library.tid("graph-move")).to_have_count(0)  # there is nowhere to move it
    expect(library.tid("folder-new")).to_be_visible()
    expect(library.tid("folder-new-graph")).to_be_hidden()  # only inside a collection
    expect(library.tid("library-export")).to_contain_text("Export all (1)")
    library.tick(name).check()
    expect(library.tid("selection-bar")).to_be_visible()
    expect(library.tid("selection-move")).to_be_hidden()


def test_the_selection_bar_offers_move_as_soon_as_a_collection_exists_and_not_after(
    library: FolderLibrary, api: httpx.Client
) -> None:
    name, folder = unique_name("Plain"), unique_name("Later")
    seed_graph(api, name)
    library.goto()
    library.tick(name).check()
    expect(library.tid("selection-move")).to_be_hidden()
    library.new_folder(folder)
    expect(library.tid("selection-bar")).to_be_visible()  # the pick survives the reload
    expect(library.tid("selection-move")).to_be_visible()
    library.delete_folder(folder)
    expect(library.tid("selection-move")).to_be_hidden()


# ------------------------------------------------------------------------------ create and walk


def test_collections_nest_and_the_breadcrumb_walks_back_up(library: FolderLibrary) -> None:
    top, inner = unique_name("Finance"), unique_name("Q3")
    library.goto()
    library.new_folder(top)
    library.expect_toast(f"Created the collection “{top}”.", "success")
    card = library.folder_card(top)
    expect(card).to_contain_text("0 graphs, 0 collections")
    expect(card.get_by_test_id("folder-open")).to_be_focused()  # the keyboard lands on the new card
    top_id = library.folder_id(top)
    library.open_folder(top)
    expect(library.crumbs).to_have_text(["Library", top])
    expect(library.crumbs.last).to_have_attribute("aria-current", "page")
    expect(library.tid("library-folder-empty")).to_contain_text("This collection has no graphs")
    expect(library.page.locator(".folders")).to_have_text("")  # no cards, and no stray text
    new_graph = library.tid("folder-new-graph")
    expect(new_graph).to_have_attribute("href", f"/graphs/new?folder={top_id}")
    library.new_folder(inner)
    expect(library.folder_card(top)).to_have_count(0)  # the top level is one page up
    library.open_folder(inner)
    expect(library.crumbs).to_have_text(["Library", top, inner])
    library.crumbs.nth(1).click()
    expect(library.page).to_have_url(url_has_folder(top_id))
    library.expect_ready()
    expect(library.folder_names).to_have_text([inner])
    expect(library.folder_card(inner)).to_contain_text("0 graphs, 0 collections")
    library.crumbs.first.click()
    expect(library.page).not_to_have_url(re.compile(r"folder="))
    library.expect_ready()
    expect(library.folder_names).to_have_text([top])
    expect(library.folder_card(top)).to_contain_text("0 graphs, 1 collection")


def test_a_collection_lists_its_own_graphs_and_the_top_level_the_rest(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Trips"))
    filed, loose = unique_name("Filed"), unique_name("Loose")
    seed_filed_graph(api, filed, folder["id"])
    seed_graph(api, loose)
    library.goto()
    library.expect_names([loose])
    expect(library.folder_card(folder["name"])).to_contain_text("1 graph, 0 collections")
    library.open_folder(folder["name"])
    library.expect_names([filed])
    expect(library.page.locator(".folders")).to_have_text("")  # a collection without collections
    expect(library.count).to_have_text("1 graph")
    expect(library.tid("library-export")).to_contain_text("Export this collection (1)")


def test_a_deep_link_survives_reload_and_the_history_buttons(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Deep"))
    name = unique_name("Inside")
    seed_filed_graph(api, name, folder["id"])
    library.goto(f"?folder={folder['id']}")
    library.expect_names([name])
    library.page.reload()
    library.expect_ready()
    library.expect_names([name])
    expect(library.crumbs).to_have_text(["Library", folder["name"]])
    library.crumbs.first.click()
    expect(library.page).not_to_have_url(re.compile(r"folder="))
    library.expect_ready()
    library.page.go_back()
    expect(library.page).to_have_url(url_has_folder(folder["id"]))
    library.expect_ready()
    library.expect_names([name])
    library.page.go_forward()
    library.expect_ready()
    expect(library.breadcrumb).to_be_hidden()


def test_a_collection_that_does_not_exist_says_so_and_offers_the_library(
    library: FolderLibrary, api: httpx.Client
) -> None:
    name = unique_name("Loose")
    seed_graph(api, name)
    library.goto(f"?folder={'0' * 32}")
    missing = library.tid("library-folder-missing")
    expect(missing).to_contain_text("This collection no longer exists")
    expect(library.cards).to_have_count(0)
    expect(library.breadcrumb).to_be_hidden()
    expect(library.tid("folder-new")).to_be_hidden()
    missing.get_by_role("link", name="Back to the library").click()
    library.expect_ready()
    library.expect_names([name])


def test_a_level_with_collections_but_no_graphs_says_so_and_is_not_called_empty(
    library: FolderLibrary, api: httpx.Client
) -> None:
    outer = seed_folder(api, unique_name("Outer"))
    inner = seed_folder(api, unique_name("Inner"), outer["id"])
    library.goto()
    expect(library.folder_card(outer["name"])).to_be_visible()
    expect(library.page.locator(".folder-hint")).to_have_text(
        "There are no graphs outside the collections."
    )
    expect(library.tid("library-empty")).to_have_count(0)  # "No graphs yet" would mislead here
    library.open_folder(outer["name"])
    expect(library.folder_card(inner["name"])).to_be_visible()
    expect(library.page.locator(".folder-hint")).to_have_text(
        "There are no graphs directly in this collection."
    )
    expect(library.tid("library-folder-empty")).to_have_count(0)  # it holds a collection


def test_a_collection_opens_from_the_page_data_without_asking_the_api_for_a_list(
    page: WatchedPage, library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Boot"))
    name = unique_name("Inside")
    seed_filed_graph(api, name, folder["id"])
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))
    library.goto(f"?folder={folder['id']}")
    library.expect_names([name])
    expect(library.crumbs).to_have_text(["Library", folder["name"]])
    lists = [url for url in asked if re.search(r"/api/v1/(graphs|folders)(\?|$)", url)]
    assert lists == []  # the server sent the graphs and the tree with the page


# ------------------------------------------------------------------------------ keyboard


def test_a_collection_can_be_created_with_the_keyboard_alone(
    library: FolderLibrary, api: httpx.Client
) -> None:
    seed_graph(api, unique_name("Anchor"))
    name = unique_name("Keys")
    library.goto()
    library.tid("folder-new").focus()
    library.page.keyboard.press("Enter")
    expect(library.tid("folder-name-input")).to_be_focused()
    library.page.keyboard.type(name)
    library.page.keyboard.press("Enter")
    expect(library.name_dialog).to_be_hidden()
    expect(library.folder_card(name).get_by_test_id("folder-open")).to_be_focused()
    library.page.keyboard.press("Enter")  # the focused link opens it
    expect(library.page).to_have_url(re.compile(r"folder="))
    library.expect_ready()
    expect(library.crumbs.last).to_have_text(name)


def test_a_second_enter_while_the_request_runs_does_not_send_it_again(
    library: FolderLibrary,
) -> None:
    name = unique_name("Once")
    held: list[Route] = []
    posts: list[str] = []

    def hold_the_post(route: Route) -> None:
        if route.request.method != "POST":
            route.continue_()
            return
        posts.append(route.request.url)
        held.append(route)  # the answer waits until the test lets it go

    library.goto()
    library.page.route("**/api/v1/folders", hold_the_post)
    library.tid("folder-new").click()
    library.tid("folder-name-input").fill(name)
    library.page.keyboard.press("Enter")
    expect(library.tid("folder-name-confirm")).to_be_disabled()  # the request is running
    library.page.keyboard.press("Enter")
    held[0].continue_()
    expect(library.folder_card(name)).to_be_visible()
    assert len(posts) == 1


# ------------------------------------------------------------------------------ name rules


def test_the_name_dialog_asks_again_for_an_empty_or_taken_name_and_cancels_cleanly(
    library: FolderLibrary, api: httpx.Client
) -> None:
    existing = unique_name("Taken")
    seed_folder(api, existing)
    library.goto()
    library.page.allow_http(409, "/api/v1/folders")  # the clash is the point of the test
    library.tid("folder-new").click()
    expect(library.tid("folder-name-input")).to_be_focused()
    library.tid("folder-name-confirm").click()
    expect(library.tid("folder-name-error")).to_have_text("Give the collection a name.")
    library.fill_name(existing.upper())  # sibling names are compared ignoring case
    error = library.tid("folder-name-error")
    expect(error).to_contain_text("A collection with this name already exists")
    expect(library.name_dialog).to_be_visible()  # fixed in place, nothing was lost
    library.tid("folder-name-input").fill(unique_name("Free"))
    library.page.keyboard.press("Escape")
    expect(library.name_dialog).to_be_hidden()
    expect(library.folder_cards).to_have_count(1)
    expect(library.tid("folder-new")).to_be_focused()


def test_the_name_field_stops_at_the_length_the_server_accepts(
    library: FolderLibrary, api: httpx.Client
) -> None:
    library.goto()
    library.tid("folder-new").click()
    field = library.tid("folder-name-input")
    library.page.keyboard.type("b" * 105)  # five more than the most a name may hold
    expect(field).to_have_value("b" * 100)
    library.tid("folder-name-confirm").click()
    expect(library.name_dialog).to_be_hidden()
    names = [item["name"] for item in json_of(api.get("/api/v1/folders"))["items"]]
    assert names == ["b" * 100]  # the longest name is stored as typed


def test_a_collection_is_renamed_in_place_and_keeps_its_graphs(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Old"))
    name = unique_name("Kept")
    seed_filed_graph(api, name, folder["id"])
    renamed = unique_name("New")
    library.goto()
    library.rename_folder(folder["name"], renamed)
    library.expect_toast(f"Renamed to “{renamed}”.", "success")
    expect(library.folder_card(renamed)).to_contain_text("1 graph")
    expect(library.folder_card(renamed).get_by_test_id("folder-open")).to_be_focused()
    library.open_folder(renamed)
    library.expect_names([name])
    expect(library.crumbs.last).to_have_text(renamed)


def test_the_rename_dialog_starts_with_the_current_name_selected(
    library: FolderLibrary, api: httpx.Client
) -> None:
    folder = seed_folder(api, unique_name("Select"))
    library.goto()
    library.folder_card(folder["name"]).get_by_test_id("folder-rename").click()
    field = library.tid("folder-name-input")
    expect(field).to_have_value(folder["name"])
    library.page.keyboard.type("x")  # typing replaces the selected text
    expect(field).to_have_value("x")
    library.page.keyboard.press("Escape")
    expect(library.name_dialog).to_be_hidden()
    expect(library.folder_card(folder["name"])).to_be_visible()
    expect(library.folder_card(folder["name"]).get_by_test_id("folder-rename")).to_be_focused()


def test_the_move_dialog_works_with_the_keyboard_alone(
    library: FolderLibrary, api: httpx.Client
) -> None:
    first, second = unique_name("Alpha"), unique_name("Beta")
    seed_folder(api, first)
    seed_folder(api, second)
    name = unique_name("Mover")
    seed_graph(api, name)
    library.goto()
    library.card(name).get_by_test_id("graph-move").focus()
    library.page.keyboard.press("Enter")
    expect(library.move_option(first).locator("input")).to_be_focused()  # the library is "here"
    library.page.keyboard.press("ArrowDown")  # the arrow keys choose, as in any radio group
    expect(library.move_option(second).locator("input")).to_be_checked()
    library.page.keyboard.press("Tab")
    library.page.keyboard.press("Tab")
    expect(library.tid("move-confirm")).to_be_focused()
    library.page.keyboard.press("Enter")
    expect(library.move_dialog).to_be_hidden()
    library.expect_toast(f"Moved “{name}” to “{second}”.", "success")
    expect(library.folder_card(second)).to_contain_text("1 graph")
