"""E2E.md B.6, browsing: paging, search, tag chips and sorting of the library.

One server for the whole module (30 seeded graphs, nothing here writes), so the tests only read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import graph_create
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.stamps import instant
from tests.e2e.support.ui_b_common import query_of
from tests.e2e.support.ui_b_library import PAGE_SIZE, LibraryPage
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

TOTAL = 30
DASH = chr(0x2013)  # the en dash of "Showing 1-12 of 30 graphs"
EXTRA_TAGS = 12  # x01..x12: with budget and trips that is 14 tags, more than the 10 shown at first
NEWEST = "Flow 17"  # saved once more after all the others, so it is strictly the newest


class Seeded(NamedTuple):
    """What the module seeded: names in creation order and the API's own listing."""

    names: list[str]
    listing: list[dict[str, Any]]


def _graph_body(number: int) -> dict[str, Any]:
    tags = [f"x{number:02d}"] if number <= EXTRA_TAGS else []
    if number % 3 == 0:
        tags.append("trips")
    if number % 5 == 0:
        tags.append("budget")
    description = "Energy mix by source" if number == 7 else ""
    return graph_create(f"Flow {number:02d}", tags=tags, description=description)


def _touch(client: httpx.Client, graph_id: str) -> None:
    """Save ``graph_id`` again unchanged: a new revision and a new ``updated_at``."""
    stored = json_of(client.get(f"/api/v1/graphs/{graph_id}"))
    keep = ("name", "description", "tags", "source", "transform", "style", "revision")
    json_of(client.put(f"/api/v1/graphs/{graph_id}", json={key: stored[key] for key in keep}))


def _list_graphs(client: httpx.Client) -> list[dict[str, Any]]:
    return list(json_of(client.get("/api/v1/graphs", params={"limit": 200}))["items"])


def _make_newest_strictly_newest(client: httpx.Client) -> list[dict[str, Any]]:
    """Touch ``NEWEST`` until its timestamp is later than every other (ms resolution ties)."""

    def probe() -> list[dict[str, Any]] | None:
        listing = _list_graphs(client)
        others = [instant(item["updated_at"]) for item in listing if item["name"] != NEWEST]
        mine = next(item for item in listing if item["name"] == NEWEST)
        if instant(mine["updated_at"]) > max(others):
            return listing
        _touch(client, mine["id"])
        return None

    listing = wait_until(probe, what=f"{NEWEST} to be strictly the newest graph")
    assert listing is not None
    return listing


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture(scope="module")
def seeded(module_server: LiveServer) -> Seeded:
    with make_client(module_server) as client:
        for number in range(1, TOTAL + 1):
            json_of(client.post("/api/v1/graphs", json=_graph_body(number)), 201)
        listing = _make_newest_strictly_newest(client)
    return Seeded([f"Flow {n:02d}" for n in range(1, TOTAL + 1)], listing)


@pytest.fixture
def library(page: WatchedPage, live_server: LiveServer, seeded: Seeded) -> LibraryPage:
    assert len(seeded.listing) == TOTAL
    return LibraryPage(page, live_server)


def api_names(seeded: Seeded, start: int, stop: int) -> list[str]:
    return [item["name"] for item in seeded.listing[start:stop]]


# ------------------------------------------------------------------------------ paging


def test_pages_of_twelve_walk_forward_and_back_and_the_address_follows(
    library: LibraryPage, seeded: Seeded
) -> None:
    library.goto()
    expect(library.cards).to_have_count(PAGE_SIZE)
    expect(library.count).to_have_text(f"Showing 1{DASH}12 of 30 graphs")
    expect(library.pager).to_contain_text("Page 1 of 3")
    expect(library.tid("library-pager-prev")).to_be_disabled()
    library.expect_names(api_names(seeded, 0, PAGE_SIZE))  # newest first, as the API says
    library.next_page()
    assert query_of(library.page.url)["page"] == "2"
    expect(library.count).to_have_text(f"Showing 13{DASH}24 of 30 graphs")
    library.expect_names(api_names(seeded, 12, 24))
    library.next_page()
    expect(library.count).to_have_text(f"Showing 25{DASH}30 of 30 graphs")
    expect(library.cards).to_have_count(TOTAL - 2 * PAGE_SIZE)
    expect(library.tid("library-pager-next")).to_be_disabled()
    library.previous_page()
    assert query_of(library.page.url)["page"] == "2"
    expect(library.pager).to_contain_text("Page 2 of 3")


def test_a_far_out_page_number_opens_a_real_page_without_an_error(library: LibraryPage) -> None:
    for number in ("99999999999999999999", "0", "abc", "-3"):
        library.goto(f"?page={number}")
        expect(library.cards.first).to_be_visible()
        expect(library.tid("state-error")).to_have_count(0)
        assert 1 <= library.cards.count() <= PAGE_SIZE, number


# ------------------------------------------------------------------------------ search


def test_search_finds_names_and_descriptions_and_clear_brings_the_list_back(
    library: LibraryPage,
) -> None:
    library.goto()
    library.search("Flow 07")
    library.expect_names(["Flow 07"])
    expect(library.count).to_have_text("1 graph matching “Flow 07”")
    assert query_of(library.page.url)["q"] == "Flow 07"
    library.page.reload()
    library.expect_ready()
    expect(library.tid("library-search")).to_have_value("Flow 07")  # the address restored it
    library.search("energy mix")  # a word of the description
    library.expect_names(["Flow 07"])
    library.search("no-such-graph-anywhere")
    expect(library.tid("library-no-results")).to_contain_text("no-such-graph-anywhere")
    expect(library.cards).to_have_count(0)
    expect(library.count).to_be_hidden()
    expect(library.pager).to_be_hidden()
    library.tid("library-clear-filters").click()
    expect(library.cards).to_have_count(PAGE_SIZE)
    expect(library.tid("library-search")).to_have_value("")
    assert "q" not in query_of(library.page.url)
    expect(library.tid("library-clear-filters")).to_be_hidden()


# ------------------------------------------------------------------------------ tags


def test_tag_chips_filter_combine_with_search_and_collapse_beyond_ten(library: LibraryPage) -> None:
    library.goto()
    chips = library.tid("library-tag-filter")
    expect(chips).to_have_count(10)  # more than ten tags collapse behind "Show 4 more"
    expect(library.tag_chip("x12")).to_have_count(0)
    library.page.get_by_role("button", name="Show 4 more").click()
    expect(chips).to_have_count(14)
    library.page.get_by_role("button", name="Show fewer tags").click()
    expect(chips).to_have_count(10)
    library.toggle_tag("trips")
    expect(library.tag_chip("trips")).to_have_attribute("aria-pressed", "true")
    assert query_of(library.page.url)["tag"] == "trips"
    expect(library.count).to_have_text("10 graphs tagged “trips”")
    for number in (3, 6, 9, 12):
        expect(library.card(f"Flow {number:02d}")).to_be_visible()
    expect(library.card("Flow 01")).to_have_count(0)
    library.toggle_tag("trips")  # a second click clears it
    expect(library.tag_chip("trips")).to_have_attribute("aria-pressed", "false")
    assert "tag" not in query_of(library.page.url)
    expect(library.cards).to_have_count(PAGE_SIZE)
    library.toggle_tag("budget")
    expect(library.cards).to_have_count(TOTAL // 5)
    library.search("Flow 30")  # tagged budget as well
    library.expect_names(["Flow 30"])
    expect(library.count).to_contain_text("tagged “budget”")
    library.search("Flow 01")  # tagged x01 only: not a budget graph
    expect(library.tid("library-no-results")).to_be_visible()


# ------------------------------------------------------------------------------ sorting


def test_sorting_by_name_and_by_update_time(library: LibraryPage, seeded: Seeded) -> None:
    library.goto()
    library.sort_by("name-asc")
    assert query_of(library.page.url)["sort"] == "name-asc"
    library.expect_names(seeded.names[:PAGE_SIZE])
    library.sort_by("name-desc")
    newest_last = list(reversed(seeded.names))
    library.expect_names(newest_last[:PAGE_SIZE])
    library.next_page()
    library.expect_names(newest_last[PAGE_SIZE : 2 * PAGE_SIZE])
    library.sort_by("updated-desc")
    assert "sort" not in query_of(library.page.url)  # the default order is not in the address
    expect(library.names.first).to_have_text(NEWEST)
    library.sort_by("updated-asc")
    expect(library.names.first).not_to_have_text(NEWEST)  # the list was re-sorted
    stamps = {item["name"]: instant(item["updated_at"]) for item in seeded.listing}
    assert stamps[library.names.first.inner_text()] == min(stamps.values())
    assert query_of(library.page.url)["sort"] == "updated-asc"


def test_the_filters_in_the_address_are_applied_on_load(library: LibraryPage) -> None:
    library.goto("?q=Flow+1&sort=name-desc&tag=x10")
    library.expect_names(["Flow 10"])
    expect(library.tid("library-sort")).to_have_value("name-desc")
    expect(library.tag_chip("x10")).to_have_attribute("aria-pressed", "true")
