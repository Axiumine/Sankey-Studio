# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``render_bundle`` and ``render_compare``: the entry points of the web layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio import pipeline
from sankey_studio.errors import GraphBuildError
from sankey_studio.models import StyleSpec
from sankey_studio.pipeline import (
    BundleOptions,
    ResultCache,
    assemble_bundle,
    build_graph_from_draft,
    render_bundle,
    render_compare,
)
from sankey_studio.render.colors import ColorMap
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.palette import hue
from sankey_studio.render.sankey import build_figure
from sankey_studio.web.schemas import COMPARE_IDS_MAX
from tests.test_pipeline_support import (
    PipelineEnv,
    RecordingCache,
    count_loads,
    csv_draft,
    make_env,
    manual_draft,
    mongo_draft,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.bundle import RenderBundle
    from sankey_studio.models import GraphDraft


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


def many(count: int) -> GraphDraft:
    return manual_draft(*[(f"s{i}", f"t{i}", i + 1.0, None) for i in range(count)])


def drawn_links(bundle: RenderBundle) -> int:
    return len(bundle.figure["data"][0]["link"]["value"])


# --------------------------------------------------------------------------- render_bundle


def test_a_bundle_is_the_assembled_graph_of_the_draft(env: PipelineEnv) -> None:
    draft = manual_draft(("a", "b", 3, "X"), ("b", "c", 2, None))
    bundle = render_bundle(env.services, draft, BundleOptions("light"))
    graph = build_graph_from_draft(env.services, draft)
    assert bundle == assemble_bundle(graph, draft, BundleOptions("light", max_drawn_links=3000))
    assert bundle.stats.category_count == 1
    assert bundle.donut_available is True


def test_a_mongo_draft_is_rendered_end_to_end(env: PipelineEnv) -> None:
    env.mongo["flows"]["links"].insert_many(
        [
            {"source": "a", "target": "b", "value": 6, "category": "X"},
            {"source": "b", "target": "c", "value": 4},
        ]
    )
    bundle = render_bundle(
        env.services, mongo_draft(category_field="category"), BundleOptions("dark")
    )
    assert [(row.source, row.target, row.value, row.category) for row in bundle.entries] == [
        ("a", "b", 6.0, "X"),
        ("b", "c", 4.0, None),
    ]
    assert bundle.category_names == ["X"]
    assert bundle.stats.total_in == 6.0
    assert bundle.stats.total_out == 4.0


def test_the_drawing_cap_comes_from_the_settings(env: PipelineEnv) -> None:
    draft = many(60)
    assert render_bundle(env.services, draft, BundleOptions("light")).stats.drawn_links == 60
    env.change_settings(max_drawn_links=50)
    bundle = render_bundle(env.services, draft, BundleOptions("light"))
    assert bundle.stats.links == 60
    assert bundle.stats.drawn_links == 50
    assert drawn_links(bundle) == 50
    assert bundle.warnings == ["Showing 50 of 60 links"]


def test_an_explicit_cap_wins_over_the_settings(env: PipelineEnv) -> None:
    env.change_settings(max_drawn_links=50)
    bundle = render_bundle(env.services, many(60), BundleOptions("light", max_drawn_links=55))
    assert bundle.stats.drawn_links == 55
    assert bundle.warnings == ["Showing 55 of 60 links"]


def test_the_other_options_are_passed_on(env: PipelineEnv) -> None:
    colors = ColorMap(category_overrides={"x": "#abcdef"})
    options = BundleOptions("light", colors=colors, entries_limit=1)
    bundle = render_bundle(
        env.services, manual_draft(("a", "b", 3, "X"), ("b", "c", 2, "X")), options
    )
    assert len(bundle.entries) == 1
    assert bundle.entries_total == 2
    assert bundle.categories[0].color == "#abcdef"


def test_a_second_render_of_the_same_draft_does_not_load_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    first = render_bundle(env.services, csv_draft(), BundleOptions("light"))
    second = render_bundle(env.services, csv_draft(), BundleOptions("dark"))
    assert loads.count == 1
    assert first.figure != second.figure
    assert first.entries == second.entries


def test_graph_errors_reach_the_caller(env: PipelineEnv) -> None:
    cycle = manual_draft(("a", "b", 1, None), ("b", "a", 1, None))
    with pytest.raises(GraphBuildError):
        render_bundle(env.services, cycle, BundleOptions("light"))


# --------------------------------------------------------------------------- render_compare


def test_comparing_nothing_gives_nothing(env: PipelineEnv) -> None:
    assert render_compare(env.services, [], "light") == []


def pair() -> tuple[GraphDraft, GraphDraft]:
    """Alone the first card ranks X before Y; over both cards Y is the larger category."""
    first = manual_draft(("a", "b", 1, "X"), ("a", "c", 2, "Y"))
    second = manual_draft(("a", "b", 10, "Y"), style=StyleSpec(title="Second"))
    return first, second


def colors_of(bundle: RenderBundle) -> dict[str, str]:
    return {row.name: row.color for row in bundle.categories}


def test_every_card_uses_the_one_shared_category_ranking(env: PipelineEnv) -> None:
    first, second = pair()
    cards = render_compare(env.services, [first, second], "light")
    assert [card.stats.links for card in cards] == [2, 1]
    assert colors_of(cards[0])["Y"] == colors_of(cards[1])["Y"] == hue("light", 0)
    assert colors_of(cards[0])["X"] == hue("light", 1)
    alone = assemble_bundle(
        build_graph_from_draft(env.services, first), first, BundleOptions("light")
    )
    assert colors_of(alone)["X"] == hue("light", 0)  # on its own the first card ranks X first


def test_the_shared_map_is_the_one_of_color_map_for_graphs(env: PipelineEnv) -> None:
    first, second = pair()
    graphs = [build_graph_from_draft(env.services, d) for d in (first, second)]
    shared = ColorMap.for_graphs(graphs, first.style)
    cards = render_compare(env.services, [first, second], "dark")
    for card, graph, draft in zip(cards, graphs, (first, second), strict=True):
        expected = assemble_bundle(
            graph, draft, BundleOptions("dark", shared, max_drawn_links=3000)
        )
        assert card == expected


def test_each_card_keeps_its_own_style_but_the_first_overrides_apply_to_all(
    env: PipelineEnv,
) -> None:
    first = manual_draft(
        ("a", "b", 1, "X"), style=StyleSpec(title="First", category_colors={"x": "#abcdef"})
    )
    second = manual_draft(("a", "b", 1, "X"), style=StyleSpec(title="Second"))
    cards = render_compare(env.services, [first, second], "light")
    assert [card.figure["layout"]["title"]["text"] for card in cards] == ["First", "Second"]
    assert colors_of(cards[1])["X"] == "#abcdef"
    graph = build_graph_from_draft(env.services, second)
    shared = ColorMap.for_graphs([build_graph_from_draft(env.services, first), graph], first.style)
    assert cards[1].figure == build_figure(
        graph, second.style, "light", FigureOptions(colors=shared, max_links=3000)
    )


def test_the_cards_keep_the_order_of_the_drafts(env: PipelineEnv) -> None:
    drafts = [manual_draft(("a", f"b{n}", 1, None)) for n in range(3)]
    cards = render_compare(env.services, drafts, "light")
    assert [card.entries[0].target for card in cards] == ["b0", "b1", "b2"]


def test_the_drawing_cap_of_the_settings_applies_to_every_card(env: PipelineEnv) -> None:
    env.change_settings(max_drawn_links=50)
    cards = render_compare(env.services, [many(60), many(40)], "light")
    assert [card.stats.drawn_links for card in cards] == [50, 40]
    assert [card.warnings for card in cards] == [["Showing 50 of 60 links"], []]


def test_a_compare_loads_each_draft_once_and_reuses_the_cache(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    drafts = [manual_draft(("a", "b", 1, None)), manual_draft(("a", "c", 1, None))]
    render_compare(env.services, drafts, "light")
    render_compare(env.services, drafts, "dark")
    assert loads.count == 2


def test_a_compare_of_the_most_cards_is_served_from_the_app_cache_the_second_time(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    app_cache = ResultCache()
    drafts = [manual_draft((f"a{i}", "b", 1, None)) for i in range(COMPARE_IDS_MAX)]
    render_compare(env.services, drafts, "light", app_cache)
    assert loads.count == COMPARE_IDS_MAX
    render_compare(env.services, drafts, "light", app_cache)
    assert loads.count == COMPARE_IDS_MAX
    assert app_cache.size == COMPARE_IDS_MAX


def test_a_given_cache_is_used_by_both_entry_points(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    mine = RecordingCache()
    one = manual_draft(("a", "b", 1, None))
    two = manual_draft(("a", "c", 1, None))
    render_bundle(env.services, one, BundleOptions("light"), mine)
    assert len(mine.puts) == 1
    cards = render_compare(env.services, [one, two], "light", mine)
    assert len(cards) == 2
    assert len(mine.puts) == 2  # only the second draft was new
    assert loads.count == 2
    assert pipeline.cache_for(env.services).size == 0
