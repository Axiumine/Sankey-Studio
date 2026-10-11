"""Flow sums that overflow a float are a 422 build error, never a 500 or an ``inf`` in a bundle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.errors import GraphBuildError
from sankey_studio.pipeline import (
    BundleOptions,
    build_graph_from_draft,
    cache_for,
    render_bundle,
)
from tests.test_pipeline_support import PipelineEnv, csv_draft, make_env, manual_draft

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import GraphDraft

BIG = 1e308
HALF_MAX = 8.988465674311579e307  # two of them add up to the largest float, exactly


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


OVERFLOWS = {
    "two links into one sink": manual_draft(("a", "c", BIG, None), ("b", "c", BIG, None)),
    "the same as csv": csv_draft("source,target,value\na,c,1e308\nb,c,1e308\n"),
    "a node sum in the middle": manual_draft(
        ("z", "a", 1, None), ("z", "b", 1, None), ("a", "c", BIG, None), ("b", "c", BIG, None)
    ),
    "separate pairs, one column": manual_draft(("a", "c", BIG, None), ("b", "d", BIG, None)),
    "one pair twice": manual_draft(("a", "b", BIG, None), ("a", "b", BIG, "X")),
}


@pytest.mark.parametrize("draft", OVERFLOWS.values(), ids=OVERFLOWS.keys())
def test_overflowing_sums_are_a_graph_build_error(env: PipelineEnv, draft: GraphDraft) -> None:
    with pytest.raises(GraphBuildError) as caught:
        build_graph_from_draft(env.services, draft)
    assert caught.value.status_code == 422
    assert caught.value.code == "graph_build_error"
    assert (
        caught.value.message == "The flow sums are too large to draw: they exceed the float range."
    )
    assert cache_for(env.services).size == 0


def test_the_render_entry_point_refuses_them_too(env: PipelineEnv) -> None:
    with pytest.raises(GraphBuildError):
        render_bundle(env.services, OVERFLOWS["the same as csv"], BundleOptions("light"))


def test_sums_that_just_fit_are_drawn_and_serialise_to_json(env: PipelineEnv) -> None:
    draft = manual_draft(("a", "c", HALF_MAX, None), ("b", "c", HALF_MAX, None))
    bundle = render_bundle(env.services, draft, BundleOptions("light"))
    assert bundle.stats.total_in == 2 * HALF_MAX
    assert bundle.stats.total_out == 2 * HALF_MAX
    assert "Infinity" not in bundle.model_dump_json()
    assert cache_for(env.services).size == 1
