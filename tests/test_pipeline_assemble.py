"""``assemble_bundle``: figure, legend, donut, tables, stats and warnings of one graph."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import DonutStyle, GraphDraft, ManualSource, StyleSpec, TransformSpec
from sankey_studio.pipeline import BundleOptions, assemble_bundle, preview_entries
from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.legend import legend_items
from sankey_studio.render.options import EntriesOptions, FigureOptions
from sankey_studio.render.sankey import build_figure
from sankey_studio.render.tables import category_table, entries_page
from tests.graph_support import make_graph
from tests.render.support import budget, many_categories, plain, style

if TYPE_CHECKING:
    from sankey_studio.bundle import RenderBundle
    from sankey_studio.models import SankeyGraph, Theme


def draft_of(style_: StyleSpec | None = None, **transform: object) -> GraphDraft:
    return GraphDraft(
        source=ManualSource(),
        transform=TransformSpec.model_validate(transform),
        style=style_ or StyleSpec(),
    )


def bundle_of(
    graph: SankeyGraph, draft: GraphDraft | None = None, theme: Theme = "light", **options: Any
) -> RenderBundle:
    return assemble_bundle(graph, draft or draft_of(), BundleOptions(theme, **options))


def link_count(bundle: RenderBundle) -> int:
    return len(bundle.figure["data"][0]["link"]["value"])


def chain(count: int) -> SankeyGraph:
    """``count`` separate links with the values count, count-1, ... 1."""
    return make_graph([(f"s{i}", f"t{i}", float(count - i), None) for i in range(count)])


# --------------------------------------------------------------------------- options


def test_the_option_defaults() -> None:
    options = BundleOptions("dark")
    assert options.theme == "dark"
    assert options.colors is None
    assert options.entries_limit == 2000
    assert options.max_drawn_links is None


# --------------------------------------------------------------------------- a categorised graph


def test_the_figure_and_the_legend_are_those_of_the_renderer() -> None:
    graph, look = budget(), style(color_mode="category")
    bundle = bundle_of(graph, draft_of(look))
    assert bundle.figure == build_figure(graph, look, "light", FigureOptions())
    assert bundle.legend == legend_items(graph, look, "light", FigureOptions())
    assert [item.kind for item in bundle.legend] == ["category"] * len(bundle.legend)
    assert len(bundle.legend) == 5  # four categories and Uncategorized


def test_the_theme_reaches_every_part() -> None:
    graph, look = budget(), StyleSpec()
    dark = bundle_of(graph, draft_of(look), theme="dark")
    assert dark.figure == build_figure(graph, look, "dark", FigureOptions())
    assert dark.donut == build_donut_figure(graph, look, "dark", FigureOptions())
    assert dark.categories == category_table(graph, look, "dark")
    assert dark.figure != bundle_of(graph, draft_of(look)).figure
    assert dark.categories != bundle_of(graph, draft_of(look)).categories


def test_a_categorised_graph_offers_the_donut_and_its_table() -> None:
    graph, look = budget(), StyleSpec()
    bundle = bundle_of(graph, draft_of(look))
    assert bundle.donut_available is True
    assert bundle.donut == build_donut_figure(graph, look, "light", FigureOptions())
    assert bundle.donut_empty_reason is None
    assert bundle.categories == category_table(graph, look, "light")
    assert [row.name for row in bundle.categories] == [
        "Income",
        "Fixed",
        "Investing",
        "Variable",
        "Uncategorized",
    ]
    assert bundle.category_names == ["Income", "Fixed", "Variable", "Investing"]  # slot order
    assert bundle.stats.category_count == 4


def test_category_names_also_list_the_categories_folded_into_other() -> None:
    graph = many_categories(10)
    bundle = bundle_of(graph)
    assert bundle.category_names == [f"cat{i:02d}" for i in range(10)]
    assert bundle.stats.category_count == 10
    assert bundle.categories[-1].kind == "other"
    assert len(bundle.categories) == 7  # six slices and Other


def test_a_basis_that_selects_nothing_gives_an_empty_donut_with_a_reason() -> None:
    graph = make_graph([("A", "B", 5.0, None), ("B", "C", 3.0, "X")])
    initial = style(donut={"basis": "initial"})
    bundle = bundle_of(graph, draft_of(initial))
    assert bundle.donut_available is True
    assert bundle.donut is not None
    assert bundle.donut["data"] == []
    assert bundle.donut_empty_reason == "basis_empty"
    assert bundle.categories == []
    assert bundle.category_names == ["X"]
    terminal = bundle_of(graph, draft_of(StyleSpec(donut=DonutStyle(basis="terminal"))))
    assert terminal.donut_empty_reason is None
    assert [row.name for row in terminal.categories] == ["X"]


# --------------------------------------------------------------------------- no categories


def test_a_plain_graph_has_no_donut_and_no_category_rows() -> None:
    bundle = bundle_of(plain())
    assert bundle.donut_available is False
    assert bundle.donut is None
    assert bundle.donut_empty_reason == "no_categories"
    assert bundle.categories == []
    assert bundle.category_names == []
    assert bundle.stats.category_count == 0
    assert bundle.legend == []


def test_the_layer_legend_is_repeated_for_the_page() -> None:
    bundle = bundle_of(plain(), draft_of(style(color_mode="layer")))
    assert [item.kind for item in bundle.legend] == ["layer"] * len(bundle.legend)
    assert [item.label for item in bundle.legend][:2] == ["Layer 1", "Layer 2"]


def test_an_empty_graph_is_a_valid_bundle() -> None:
    bundle = bundle_of(make_graph([]))
    assert bundle.stats.model_dump() == {
        "nodes": 0,
        "links": 0,
        "drawn_links": 0,
        "total_in": 0.0,
        "total_out": 0.0,
        "layers": 0,
        "category_count": 0,
    }
    assert bundle.entries == []
    assert bundle.entries_total == 0
    assert bundle.warnings == []


def test_the_bundle_is_json_serialisable() -> None:
    dumped = bundle_of(budget(), draft_of(style(color_mode="category"))).model_dump(mode="json")
    assert json.loads(json.dumps(dumped)) == dumped


# --------------------------------------------------------------------------- shared colours


def test_a_shared_colour_map_reaches_the_figure_legend_and_table() -> None:
    graph, look = budget(), style(color_mode="category")
    colors = ColorMap(
        category_slots={"income": 7, "fixed": 6, "variable": 5, "investing": 4},
        category_overrides={"fixed": "#123456"},
    )
    own = bundle_of(graph, draft_of(look))
    shared = bundle_of(graph, draft_of(look), colors=colors)
    options = FigureOptions(colors=colors)
    assert shared.figure == build_figure(graph, look, "light", options)
    assert shared.legend == legend_items(graph, look, "light", options)
    assert shared.donut == build_donut_figure(graph, look, "light", options)
    assert shared.categories == category_table(graph, look, "light", colors)
    assert {row.name: row.color for row in shared.categories}["Fixed"] == "#123456"
    assert shared.categories != own.categories
    assert shared.figure != own.figure


# --------------------------------------------------------------------------- stats


def test_totals_count_the_flow_leaving_sources_and_arriving_at_sinks() -> None:
    graph = make_graph([("A", "B", 10.0, None), ("B", "C", 4.0, None), ("B", "D", 3.0, None)])
    stats = bundle_of(graph).stats
    assert stats.nodes == 4
    assert stats.links == 3
    assert stats.total_in == 10.0
    assert stats.total_out == 7.0
    assert stats.layers == 3


def test_several_sources_and_sinks_add_up_exactly() -> None:
    graph = make_graph(
        [(f"s{i}", "hub", 0.1, None) for i in range(10)] + [("hub", "end", 0.5, None)]
    )
    stats = bundle_of(graph).stats
    assert stats.total_in == 1.0  # math.fsum: sum() of ten 0.1 gives 0.9999999999999999
    assert stats.total_out == 0.5
    assert stats.layers == 3


def test_a_single_link_has_two_layers() -> None:
    stats = bundle_of(make_graph([("A", "B", 2.0, None)])).stats
    assert (stats.nodes, stats.links, stats.layers) == (2, 1, 2)
    assert (stats.total_in, stats.total_out) == (2.0, 2.0)


# --------------------------------------------------------------------------- the drawing cap


@pytest.mark.parametrize(
    ("cap", "drawn"),
    [(None, 5), (6, 5), (5, 5), (4, 4), (1, 1), (0, 0), (-2, 0)],
)
def test_the_cap_limits_the_drawn_links_and_says_so(cap: int | None, drawn: int) -> None:
    bundle = bundle_of(chain(5), max_drawn_links=cap)
    assert bundle.stats.links == 5
    assert bundle.stats.drawn_links == drawn
    assert link_count(bundle) == drawn
    expected = [] if drawn == 5 else [f"Showing {drawn} of 5 links"]
    assert bundle.warnings == expected


def test_the_cap_keeps_the_largest_links_and_the_full_entries_table() -> None:
    bundle = bundle_of(chain(5), max_drawn_links=2)
    assert bundle.figure["data"][0]["link"]["value"] == [5.0, 4.0]
    assert bundle.entries_total == 5
    assert len(bundle.entries) == 5


def test_the_cap_does_not_touch_the_donut() -> None:
    graph = budget()
    capped = bundle_of(graph, max_drawn_links=3)
    assert capped.donut == bundle_of(graph).donut
    assert capped.categories == bundle_of(graph).categories


def test_the_warnings_of_the_load_come_before_the_truncation_note() -> None:
    from sankey_studio.graph import build_graph
    from sankey_studio.sources.base import Diagnostics

    diag = Diagnostics()
    diag.warn("one row was skipped")
    graph = build_graph(
        [("a", "b", 2.0, None), ("c", "d", 1.0, None)],
        TransformSpec(),
        max_raw_links=10,
        diag=diag,
    )
    bundle = bundle_of(graph, max_drawn_links=1)
    assert bundle.warnings == ["one row was skipped", "Showing 1 of 2 links"]


# --------------------------------------------------------------------------- entries


@pytest.mark.parametrize(("limit", "shown"), [(10, 5), (5, 5), (4, 4), (1, 1), (0, 0), (-1, 0)])
def test_the_entries_preview_is_capped_but_the_total_is_not(limit: int, shown: int) -> None:
    bundle = bundle_of(chain(5), entries_limit=limit)
    assert len(bundle.entries) == shown
    assert bundle.entries_total == 5
    assert [row.value for row in bundle.entries] == [5.0, 4.0, 3.0, 2.0, 1.0][:shown]


def test_the_preview_holds_up_to_2000_entries() -> None:
    graph = make_graph([(f"s{i}", f"t{i}", 1.0, None) for i in range(2001)])
    bundle = bundle_of(graph)
    assert len(bundle.entries) == 2000
    assert bundle.entries_total == 2001


def test_the_preview_is_the_value_sorted_first_page_with_the_same_ties() -> None:
    links = [(f"s{i % 7}", f"t{i}", float(1 + i % 3), None) for i in range(40)]
    graph = make_graph(links)
    page = entries_page(graph, TransformSpec(), EntriesOptions(limit=40))
    rows, total = preview_entries(graph, TransformSpec(), 40)
    assert rows == page.rows
    assert total == page.total == 40


def test_entries_remember_which_pairs_were_set_explicitly() -> None:
    choice = [{"source": "Salary", "target": "Budget", "category": "Pay"}]
    graph = make_graph(
        [("Salary", "Budget", 9.0, None), ("Budget", "Food", 3.0, None)], entry_categories=choice
    )
    bundle = bundle_of(graph, draft_of(entry_categories=choice))
    assert [(row.source, row.category, row.overridden) for row in bundle.entries] == [
        ("Salary", "Pay", True),
        ("Budget", None, False),
    ]
