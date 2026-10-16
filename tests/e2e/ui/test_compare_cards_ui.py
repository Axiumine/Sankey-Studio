# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E.md B.7, the compare page with real graphs: cards, donut switches, shared colours, add/remove.

One server for the module and a tall window (charts draw when a card nears the viewport). Every
test seeds its own uniquely named graphs, so nothing depends on another test's data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from tests.e2e.support.builders import (
    BUDGET,
    BUDGET_CATEGORISED,
    LAYERED,
    csv_text,
    graph_draft,
    unique_name,
)
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.ui_b_common import TALL
from tests.e2e.support.ui_b_compare import ComparePage

if TYPE_CHECKING:
    import httpx
    from playwright.sync_api import ViewportSize

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server


@pytest.fixture
def viewport() -> ViewportSize:
    return TALL


@pytest.fixture
def compare(page: WatchedPage, live_server: LiveServer) -> ComparePage:
    return ComparePage(page, live_server)


class Trio:
    """Three saved graphs: a plain one, a categorised one and a three-level one."""

    def __init__(self, api: httpx.Client) -> None:
        prefix = unique_name("Trio")
        self.plain = f"{prefix} plain"
        self.cats = f"{prefix} cats"
        self.layers = f"{prefix} layers"
        self.ids = [
            seed_graph(api, self.plain, graph_draft(BUDGET.csv))["id"],
            seed_graph(api, self.cats, graph_draft(BUDGET_CATEGORISED.csv))["id"],
            seed_graph(api, self.layers, graph_draft(LAYERED.csv))["id"],
        ]


@pytest.fixture
def trio(api: httpx.Client) -> Trio:
    return Trio(api)


# ------------------------------------------------------------------------------ the grid


def test_three_graphs_make_three_drawn_cards_each_with_its_own_summary(
    compare: ComparePage, trio: Trio
) -> None:
    compare.open_ids(trio.ids)
    expect(compare.heading).to_have_text("Compare graphs")
    expect(compare.cards).to_have_count(3)
    expect(compare.tid("compare-grid")).to_have_attribute("data-count", "3")
    expect(compare.count_line).to_have_text("Comparing 3 graphs")
    assert [c.get_attribute("data-graph-id") for c in compare.cards.all()] == trio.ids
    expected = {
        trio.plain: ("10", "9", "3,800", "4", "0"),
        trio.cats: ("10", "9", "3,800", "4", "5"),
        trio.layers: ("6", "6", "16", "3", "0"),
    }
    for name, (nodes, links, total, layers, categories) in expected.items():
        compare.expect_drawn(name)
        table = compare.summary(name)
        expect(table.get_by_role("row", name="Nodes")).to_contain_text(nodes)
        expect(table.get_by_role("row", name="Links")).to_contain_text(links)
        expect(table.get_by_role("row", name="Total in")).to_contain_text(total)
        expect(table.get_by_role("row", name="Total out")).to_contain_text(total)
        expect(table.get_by_role("row", name="Layers")).to_contain_text(layers)
        expect(table.get_by_role("row", name="Categories")).to_contain_text(categories)
    a, b, _ = trio.ids
    compare.goto(f"?ids={a},,{b},{a}")  # blank and repeated ids are dropped
    expect(compare.cards).to_have_count(2)
    expect(compare.count_line).to_have_text("Comparing 2 graphs")


# ------------------------------------------------------------------------------ donut switch


def test_the_switch_of_a_categorised_card_draws_its_donut_the_others_stay_disabled(
    compare: ComparePage, trio: Trio
) -> None:
    compare.open_ids(trio.ids)
    card, switch = compare.card(trio.cats), compare.toggle(trio.cats)
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(card.get_by_test_id("donut-chart")).to_be_hidden()  # drawn only once asked for
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "true")
    expect(card).to_have_attribute("data-chart", "donut")
    donut = card.get_by_test_id("donut-chart")
    expect(donut).to_have_attribute("data-ready", "true")
    expect(donut.locator(".pielayer .slice")).to_have_count(5)
    expect(card.get_by_test_id("sankey-chart")).to_be_hidden()
    expect(compare.card(trio.plain)).to_have_attribute("data-chart", "sankey")  # others untouched
    switch.click()
    expect(card).to_have_attribute("data-chart", "sankey")
    expect(card.get_by_test_id("sankey-chart")).to_be_visible()
    for name in (trio.plain, trio.layers):  # no categories, no donut: the switch says why
        disabled = compare.toggle(name)
        expect(disabled).to_have_attribute("aria-disabled", "true")
        expect(disabled).to_have_attribute("title", "No categories, so there is no donut chart")
        disabled.click(force=True)
        expect(compare.card(name)).to_have_attribute("data-chart", "sankey")
        expect(compare.card(name).get_by_test_id("donut-chart")).to_be_hidden()


def test_all_cards_share_one_colour_map_for_categories(
    compare: ComparePage, api: httpx.Client
) -> None:
    prefix = unique_name("Colours")
    header = ("source", "target", "value", "category")
    first = csv_text([("In", "Home", 10, "Housing"), ("In", "Eat", 5, "Food")], header)
    second = csv_text(
        [("In", "Eat", 5, "Food"), ("In", "Save", 3, "Savings"), ("In", "Home", 10, "Housing")],
        header,
    )
    ids = [
        seed_graph(api, f"{prefix} one", graph_draft(first))["id"],
        seed_graph(api, f"{prefix} two", graph_draft(second))["id"],
    ]
    compare.open_ids(ids)
    compare.toggle(f"{prefix} one").click()
    compare.toggle(f"{prefix} two").click()
    one = compare.donut_colours(f"{prefix} one")
    two = compare.donut_colours(f"{prefix} two")
    assert set(one) == {"Housing", "Food"}
    assert set(two) == {"Food", "Savings", "Housing"}
    # the same category has the same colour in both cards, even though it comes in another order
    assert one["Food"] == two["Food"]
    assert one["Housing"] == two["Housing"]
    assert len({two["Food"], two["Housing"], two["Savings"]}) == 3
    legend = compare.tid("compare-shared-colours").get_by_role("list")
    for name in ("Food", "Housing", "Savings"):
        expect(legend).to_contain_text(name)


# ------------------------------------------------------------------------------ add and remove


def test_removing_cards_updates_the_address_adding_restores_and_the_last_one_leaves_it_empty(
    compare: ComparePage, trio: Trio
) -> None:
    compare.open_ids(trio.ids)
    compare.expect_drawn(trio.layers)
    compare.remove(trio.layers)
    expect(compare.cards).to_have_count(2)
    expect(compare.card(trio.layers)).to_have_count(0)
    assert compare.url_ids() == trio.ids[:2]
    expect(compare.count_line).to_have_text("Comparing 2 graphs")
    options = compare.tid("compare-add-select").locator("option")
    expect(options.filter(has_text=trio.layers)).to_have_count(1)  # the menu offers it again
    expect(options.filter(has_text=trio.plain)).to_have_count(0)  # but not what is already there
    compare.add(trio.layers)
    expect(compare.cards).to_have_count(3)
    assert compare.url_ids() == trio.ids
    compare.expect_drawn(trio.layers)
    for name in (trio.plain, trio.cats, trio.layers):
        compare.remove(name)
    expect(compare.cards).to_have_count(0)
    expect(compare.tid("state-empty")).to_contain_text("Nothing to compare yet")
    assert compare.page.url == compare.server.url_for("/compare")
    compare.page.reload()
    compare.expect_ready()
    expect(compare.tid("state-empty")).to_contain_text("Nothing to compare yet")
    expect(compare.count_line).to_have_text("No graphs in the comparison")
