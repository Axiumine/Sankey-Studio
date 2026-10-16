# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``BundleOptions.style``: the style a bundle is drawn with instead of ``draft.style``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import StyleSpec
from sankey_studio.pipeline import (
    BundleOptions,
    ResultCache,
    assemble_bundle,
    build_graph_from_draft,
    render_bundle,
)
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.legend import legend_items
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.sankey import build_figure
from sankey_studio.render.tables import category_table
from tests.render.support import budget, plain, style
from tests.test_pipeline_assemble import bundle_of, draft_of
from tests.test_pipeline_support import PipelineEnv, count_loads, make_env, manual_draft

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

SAVED = style(color_mode="category", title="Saved")
OVERRIDE = style(
    color_mode="node",
    title="Override",
    show_values_in_labels=True,
    donut={"show_value": True, "show_percent": False},
)


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


def test_the_options_default_to_the_style_of_the_draft() -> None:
    graph = budget()
    bundle = bundle_of(graph, draft_of(SAVED))
    assert BundleOptions("light").style is None
    assert bundle.figure == build_figure(graph, SAVED, "light", FigureOptions())
    assert bundle.donut == build_donut_figure(graph, SAVED, "light", FigureOptions())


def test_the_style_of_the_options_replaces_the_style_of_the_draft_everywhere() -> None:
    graph, options = budget(), FigureOptions()
    bundle = bundle_of(graph, draft_of(SAVED), style=OVERRIDE)
    assert bundle.figure == build_figure(graph, OVERRIDE, "light", options)
    assert bundle.donut == build_donut_figure(graph, OVERRIDE, "light", options)
    assert bundle.legend == legend_items(graph, OVERRIDE, "light", options)
    assert bundle.categories == category_table(graph, OVERRIDE, "light")
    assert bundle.figure != bundle_of(graph, draft_of(SAVED)).figure
    assert bundle.donut != bundle_of(graph, draft_of(SAVED)).donut


def test_the_override_reaches_the_labels_of_both_charts() -> None:
    bundle = bundle_of(budget(), draft_of(SAVED), style=OVERRIDE)
    assert bundle.figure["data"][0]["node"]["label"][0] == "Salary<br>5,000"
    assert bundle.donut is not None
    assert bundle.donut["data"][0]["textinfo"] == "text"  # five slices: no name
    assert bundle.donut["data"][0]["text"][0] == "5,800"


def test_a_default_style_in_the_options_still_replaces_a_saved_one() -> None:
    graph = budget()
    bundle = bundle_of(graph, draft_of(SAVED), style=StyleSpec())
    assert bundle.figure == build_figure(graph, StyleSpec(), "light", FigureOptions())
    assert bundle.figure != bundle_of(graph, draft_of(SAVED)).figure


def test_the_theme_still_comes_from_the_options() -> None:
    graph = budget()
    bundle = assemble_bundle(graph, draft_of(SAVED), BundleOptions("dark", style=OVERRIDE))
    assert bundle.figure == build_figure(graph, OVERRIDE, "dark", FigureOptions())
    assert bundle.donut == build_donut_figure(graph, OVERRIDE, "dark", FigureOptions())


def test_a_graph_without_categories_has_no_donut_whatever_the_style() -> None:
    bundle = bundle_of(plain(), draft_of(SAVED), style=OVERRIDE)
    assert (bundle.donut, bundle.donut_available) == (None, False)
    assert bundle.donut_empty_reason == "no_categories"


def test_render_bundle_keeps_the_style_when_it_fills_in_the_drawing_cap(env: PipelineEnv) -> None:
    draft = manual_draft(("a", "b", 3, "X"), ("b", "c", 2, None), style=SAVED)
    bundle = render_bundle(env.services, draft, BundleOptions("light", style=OVERRIDE))
    graph = build_graph_from_draft(env.services, draft)
    figure_options = FigureOptions(max_links=3000)
    assert bundle.figure == build_figure(graph, OVERRIDE, "light", figure_options)
    assert bundle.donut == build_donut_figure(graph, OVERRIDE, "light", figure_options)


def test_the_style_override_does_not_change_the_cached_graph(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads, cache = count_loads(monkeypatch), ResultCache()
    draft = manual_draft(("a", "b", 3, "X"), ("b", "c", 2, None), style=SAVED)
    render_bundle(env.services, draft, BundleOptions("light"), cache)
    render_bundle(env.services, draft, BundleOptions("light", style=OVERRIDE), cache)
    render_bundle(env.services, draft, BundleOptions("dark", style=StyleSpec()), cache)
    assert loads.count == 1
    assert cache.size == 1
