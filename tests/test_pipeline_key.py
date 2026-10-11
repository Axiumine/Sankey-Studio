"""``cache_key``: what makes two drafts the same load, and when a load is not cacheable."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio import pipeline
from sankey_studio.models import StyleSpec
from sankey_studio.pipeline import cache_key
from tests.test_pipeline_support import (
    CSV,
    PipelineEnv,
    age_files,
    csv_draft,
    file_draft,
    make_env,
    manual_draft,
    mongo_draft,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import GraphDraft


@pytest.fixture
def env(
    tmp_path: Path, mongo_client: MongoClient[Any], monkeypatch: pytest.MonkeyPatch
) -> Iterator[PipelineEnv]:
    age_files(monkeypatch)
    with make_env(tmp_path, mongo_client) as value:
        yield value


def key_of(env: PipelineEnv, draft: GraphDraft) -> str | None:
    return cache_key(draft, env.services.source_context())


def test_the_key_is_a_sha256_hex_digest(env: PipelineEnv) -> None:
    key = key_of(env, csv_draft())
    assert key is not None
    assert re.fullmatch(r"[0-9a-f]{64}", key)


def test_equal_drafts_share_a_key_and_the_style_does_not_count(env: PipelineEnv) -> None:
    plain = manual_draft(("a", "b", 1, None))
    styled = manual_draft(("a", "b", 1, None), style=StyleSpec(title="T", orientation="v"))
    assert key_of(env, plain) == key_of(env, manual_draft(("a", "b", 1, None)))
    assert key_of(env, plain) == key_of(env, styled)


@pytest.mark.parametrize(
    "other",
    [
        manual_draft(("a", "b", 2, None)),
        manual_draft(("a", "b", 1, "X")),
        manual_draft(("a", "b", 1, None), min_link_value=0.5),
        manual_draft(("a", "b", 1, None), top_links=3),
        manual_draft(("a", "b", 1, None), strict=True),
        csv_draft(),
    ],
    ids=["value", "category", "min_link_value", "top_links", "strict", "text"],
)
def test_a_different_source_or_transform_is_a_different_key(
    env: PipelineEnv, other: GraphDraft
) -> None:
    assert key_of(env, manual_draft(("a", "b", 1, None))) != key_of(env, other)


def test_the_raw_row_cap_is_part_of_the_key(env: PipelineEnv) -> None:
    before = key_of(env, csv_draft())
    env.change_settings(max_links=1000)
    assert key_of(env, csv_draft()) != before


def test_a_file_without_a_stat_is_not_cacheable(env: PipelineEnv) -> None:
    assert key_of(env, file_draft("missing.csv")) is None


def test_a_file_that_vanishes_between_check_and_stat_is_not_cacheable(
    env: PipelineEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "resolve_source_path", lambda _root, _rel: tmp_path / "gone.csv")
    assert key_of(env, file_draft()) is None


def test_the_key_of_a_file_follows_its_content_stamp(env: PipelineEnv) -> None:
    env.sources_dir.mkdir(parents=True, exist_ok=True)
    path = env.sources_dir / "flows.csv"
    path.write_text(CSV)
    first = key_of(env, file_draft())
    assert first is not None
    assert key_of(env, file_draft()) == first
    path.write_text(CSV + "x,y,1\n")
    assert key_of(env, file_draft()) != first


def test_a_mongo_source_of_an_unknown_connection_still_has_a_key(env: PipelineEnv) -> None:
    ghost = mongo_draft(connection="ghost")
    assert key_of(env, ghost) is not None
    assert key_of(env, ghost) != key_of(env, mongo_draft(connection="ghost2"))


def sort_draft(order: dict[str, int]) -> GraphDraft:
    return mongo_draft(mode="aggregate", pipeline=[{"$sort": order}, {"$limit": 1}])


def test_the_order_of_the_keys_of_a_stage_is_part_of_the_key(env: PipelineEnv) -> None:
    by_a_then_b = key_of(env, sort_draft({"a": 1, "b": -1}))
    by_b_then_a = key_of(env, sort_draft({"b": -1, "a": 1}))
    assert by_a_then_b is not None
    assert by_b_then_a is not None
    assert by_a_then_b != by_b_then_a
    assert key_of(env, sort_draft({"a": 1, "b": -1})) == by_a_then_b
