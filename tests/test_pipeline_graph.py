# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``build_graph_from_draft``: sources, strictness, limits, errors, and the result cache."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio import pipeline
from sankey_studio.errors import GraphBuildError, GraphTooLargeError, SourceError
from sankey_studio.models import StyleSpec
from sankey_studio.pipeline import (
    CACHE_ENTRIES,
    FILE_TTL_S,
    MONGO_TTL_S,
    ResultCache,
    build_graph_from_draft,
    cache_for,
    cache_key,
    use_cache,
)
from tests.graph_support import rows
from tests.test_pipeline_support import (
    CSV,
    FakeClock,
    PipelineEnv,
    RecordingCache,
    age_files,
    count_loads,
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

    from sankey_studio.models import GraphDraft, SankeyGraph


@pytest.fixture
def env(
    tmp_path: Path, mongo_client: MongoClient[Any], monkeypatch: pytest.MonkeyPatch
) -> Iterator[PipelineEnv]:
    age_files(monkeypatch)
    with make_env(tmp_path, mongo_client) as value:
        yield value


# --------------------------------------------------------------------------- sources


def test_a_manual_draft_builds_its_graph(env: PipelineEnv) -> None:
    graph = build_graph_from_draft(
        env.services, manual_draft(("a", "b", 3, "X"), ("a", "b", 2, None))
    )
    assert rows(graph) == [("a", "b", 3.0, "X"), ("a", "b", 2.0, None)]


def test_an_inline_text_draft_builds_its_graph(env: PipelineEnv) -> None:
    graph = build_graph_from_draft(env.services, csv_draft())
    assert rows(graph) == [("a", "b", 10.0, None), ("b", "c", 4.0, None)]


def test_a_file_draft_reads_the_managed_sources_dir(env: PipelineEnv) -> None:
    env.sources_dir.mkdir(parents=True, exist_ok=True)
    (env.sources_dir / "flows.csv").write_text(CSV)
    graph = build_graph_from_draft(env.services, file_draft())
    assert rows(graph) == [("a", "b", 10.0, None), ("b", "c", 4.0, None)]


def test_a_mongo_draft_reads_the_connection_default_database(env: PipelineEnv) -> None:
    env.mongo["flows"]["links"].insert_many(
        [
            {"source": "a", "target": "b", "value": 5},
            {"source": "b", "target": "c", "value": 2.5},
        ]
    )
    graph = build_graph_from_draft(env.services, mongo_draft(database=None))
    assert rows(graph) == [("a", "b", 5.0, None), ("b", "c", 2.5, None)]


# --------------------------------------------------------------------------- strict, limits


BAD_ROW = "source,target,value\na,b,x\nb,c,4\n"


def test_a_lenient_draft_skips_a_bad_row_with_a_warning(env: PipelineEnv) -> None:
    graph = build_graph_from_draft(env.services, csv_draft(BAD_ROW))
    assert rows(graph) == [("b", "c", 4.0, None)]
    assert len(graph.warnings) == 1


def test_a_strict_draft_fails_on_the_same_row(env: PipelineEnv) -> None:
    with pytest.raises(SourceError):
        build_graph_from_draft(env.services, csv_draft(BAD_ROW, strict=True))


def csv_of(count: int) -> str:
    return "source,target,value\n" + "".join(f"s{i},t{i},1\n" for i in range(count))


def test_max_links_of_the_settings_caps_the_raw_rows(env: PipelineEnv) -> None:
    env.change_settings(max_links=100)
    assert build_graph_from_draft(env.services, csv_draft(csv_of(100))).n_links == 100
    with pytest.raises(GraphTooLargeError):
        build_graph_from_draft(env.services, csv_draft(csv_of(101)))


def test_a_changed_max_links_is_not_served_from_the_cache(env: PipelineEnv) -> None:
    draft = csv_draft(csv_of(150))
    assert build_graph_from_draft(env.services, draft).n_links == 150
    env.change_settings(max_links=100)
    with pytest.raises(GraphTooLargeError):
        build_graph_from_draft(env.services, draft)


def test_errors_are_raised_every_time_and_never_cached(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    cycle = manual_draft(("a", "b", 1, None), ("b", "a", 1, None))
    for attempt in (1, 2):
        with pytest.raises(GraphBuildError):
            build_graph_from_draft(env.services, cycle)
        assert loads.count == attempt
    assert cache_for(env.services).size == 0


# --------------------------------------------------------------------------- the cache


def test_the_same_draft_is_loaded_once(env: PipelineEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, csv_draft())
    second = build_graph_from_draft(env.services, csv_draft())
    assert second is first
    assert loads.count == 1
    assert cache_for(env.services).size == 1


def test_the_style_is_not_part_of_the_key(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    plain = manual_draft(("a", "b", 1, None))
    styled = manual_draft(("a", "b", 1, None), style=StyleSpec(title="Other", color_mode="mono"))
    assert build_graph_from_draft(env.services, styled) is build_graph_from_draft(
        env.services, plain
    )
    assert loads.count == 1


@pytest.mark.parametrize(
    "other",
    [
        csv_draft(CSV + "c,d,1\n"),
        csv_draft(CSV, min_link_value=5),
        csv_draft(CSV, strict=True),
        csv_draft(CSV, on_cycle="break"),
        manual_draft(("a", "b", 10, None)),
    ],
    ids=["source", "min_link_value", "strict", "on_cycle", "source type"],
)
def test_another_source_or_transform_is_loaded_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch, other: GraphDraft
) -> None:
    loads = count_loads(monkeypatch)
    build_graph_from_draft(env.services, csv_draft())
    build_graph_from_draft(env.services, other)
    assert loads.count == 2


@pytest.mark.parametrize(
    ("draft", "ttl"),
    [
        (csv_draft(), FILE_TTL_S),
        (manual_draft(("a", "b", 1, None)), FILE_TTL_S),
        (mongo_draft(), MONGO_TTL_S),
    ],
    ids=["inline", "manual", "mongo"],
)
def test_entries_live_120_seconds_and_mongo_ones_30(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch, draft: GraphDraft, ttl: float
) -> None:
    assert (FILE_TTL_S, MONGO_TTL_S) == (120.0, 30.0)
    env.mongo["flows"]["links"].insert_one({"source": "a", "target": "b", "value": 1})
    clock = FakeClock(500.0)
    use_cache(env.services, ResultCache(clock=clock))
    loads = count_loads(monkeypatch)
    build_graph_from_draft(env.services, draft)
    clock.now = 500.0 + ttl - 0.1
    build_graph_from_draft(env.services, draft)
    assert loads.count == 1
    clock.now = 500.0 + ttl
    build_graph_from_draft(env.services, draft)
    assert loads.count == 2


def test_one_draft_too_many_leaves_the_most_recent_ones_in_the_cache(env: PipelineEnv) -> None:
    for index in range(CACHE_ENTRIES + 1):
        build_graph_from_draft(env.services, manual_draft((f"a{index}", "b", 1, None)))
    assert cache_for(env.services).size == CACHE_ENTRIES


def test_two_services_do_not_share_results(
    env: PipelineEnv, tmp_path: Path, mongo_client: MongoClient[Any]
) -> None:
    other_dir = tmp_path / "other"
    with make_env(other_dir, mongo_client) as other:
        build_graph_from_draft(env.services, csv_draft())
        assert cache_for(env.services).size == 1
        assert cache_for(other.services).size == 0


def test_a_cache_hit_keeps_the_warnings_of_the_load(env: PipelineEnv) -> None:
    first = build_graph_from_draft(env.services, csv_draft(BAD_ROW))
    second = build_graph_from_draft(env.services, csv_draft(BAD_ROW))
    assert second is first
    assert len(second.warnings) == 1


# --------------------------------------------------------------------------- file sources


def write_flows(env: PipelineEnv, text: str) -> Path:
    env.sources_dir.mkdir(parents=True, exist_ok=True)
    path = env.sources_dir / "flows.csv"
    path.write_text(text)
    return path


def test_an_unchanged_file_is_loaded_once(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_flows(env, CSV)
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, file_draft())
    assert build_graph_from_draft(env.services, file_draft()) is first
    assert loads.count == 1


def test_a_file_that_changed_size_is_loaded_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_flows(env, CSV)
    stat = path.stat()
    loads = count_loads(monkeypatch)
    build_graph_from_draft(env.services, file_draft())
    path.write_text(CSV + "c,d,1\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # same mtime, only the size moved
    graph = build_graph_from_draft(env.services, file_draft())
    assert loads.count == 2
    assert graph.n_links == 3


def test_a_file_that_changed_mtime_is_loaded_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_flows(env, CSV)
    stat = path.stat()
    loads = count_loads(monkeypatch)
    build_graph_from_draft(env.services, file_draft())
    path.write_text(CSV.replace("10", "99"))  # same size
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    graph = build_graph_from_draft(env.services, file_draft())
    assert loads.count == 2
    assert rows(graph)[0] == ("a", "b", 99.0, None)


def test_a_missing_file_is_a_source_error_and_nothing_is_cached(env: PipelineEnv) -> None:
    with pytest.raises(SourceError):
        build_graph_from_draft(env.services, file_draft("nope.csv"))
    assert cache_for(env.services).size == 0


def test_a_file_that_cannot_be_stamped_is_loaded_every_time_and_never_cached(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_flows(env, CSV)
    monkeypatch.setattr(pipeline, "resolve_source_path", lambda _root, _rel: tmp_path / "gone.csv")
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, file_draft())
    second = build_graph_from_draft(env.services, file_draft())
    assert rows(first) == rows(second)
    assert second is not first
    assert loads.count == 2
    assert cache_for(env.services).size == 0


# --------------------------------------------------------------------------- mongo sources


def seed(env: PipelineEnv, database: str, value: float) -> None:
    env.mongo[database]["links"].insert_one({"source": "a", "target": "b", "value": value})


def other_connection(**fields: object) -> list[dict[str, object]]:
    return [
        {
            "name": "test",
            "uri": "mongodb://tester:hunter2@mongo.invalid:27017/?appName=tests",
            "default_database": "flows",
            **fields,
        }
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"uri": "mongodb://tester:hunter2@elsewhere.invalid:27017/?appName=tests"},
        {"uri": "mongodb://other:hunter2@mongo.invalid:27017/?appName=tests"},
        {"default_database": "second"},
    ],
    ids=["host", "user", "default database"],
)
def test_another_connection_behind_the_same_name_is_loaded_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    seed(env, "flows", 1)
    seed(env, "second", 2)
    loads = count_loads(monkeypatch)
    first = build_graph_from_draft(env.services, mongo_draft(database=None))
    env.change_settings(mongo_connections=other_connection(**change))
    second = build_graph_from_draft(env.services, mongo_draft(database=None))
    assert second is not first
    assert loads.count == 2


def test_a_changed_mongo_timeout_is_loaded_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(env, "flows", 1)
    loads = count_loads(monkeypatch)
    build_graph_from_draft(env.services, mongo_draft())
    env.change_settings(mongo_timeout_ms=20_000)
    build_graph_from_draft(env.services, mongo_draft())
    assert loads.count == 2


def test_an_unknown_connection_fails_and_leaves_the_cache_empty(env: PipelineEnv) -> None:
    with pytest.raises(SourceError, match=re.escape("Unknown MongoDB connection 'ghost'")):
        build_graph_from_draft(env.services, mongo_draft(connection="ghost"))
    assert cache_for(env.services).size == 0


def test_two_sort_orders_are_two_graphs_even_in_a_shared_cache(env: PipelineEnv) -> None:
    env.mongo["flows"]["links"].insert_many(
        [
            {"source": "first-by-a", "target": "x", "value": 1, "a": 1, "b": 1},
            {"source": "first-by-b", "target": "x", "value": 1, "a": 2, "b": 2},
        ]
    )
    shared = ResultCache()
    by_a = mongo_draft(mode="aggregate", pipeline=[{"$sort": {"a": 1, "b": -1}}, {"$limit": 1}])
    by_b = mongo_draft(mode="aggregate", pipeline=[{"$sort": {"b": -1, "a": 1}}, {"$limit": 1}])
    first = build_graph_from_draft(env.services, by_a, shared)
    second = build_graph_from_draft(env.services, by_b, shared)
    assert first.node_names == ("first-by-a", "x")
    assert second.node_names == ("first-by-b", "x")
    assert shared.size == 2


def test_the_key_never_contains_the_password(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real_put = ResultCache.put

    def spy(self: ResultCache, key: str, value: SankeyGraph, ttl_s: float) -> None:
        seen.append(key)
        real_put(self, key, value, ttl_s)

    monkeypatch.setattr(ResultCache, "put", spy)
    seed(env, "flows", 1)
    build_graph_from_draft(env.services, mongo_draft())
    assert len(seen) == 1
    assert "hunter2" not in seen[0]
    assert re.fullmatch(r"[0-9a-f]{64}", seen[0])


def test_use_cache_swaps_the_cache_the_pipeline_fills(env: PipelineEnv) -> None:
    mine = ResultCache(max_entries=2)
    use_cache(env.services, mine)
    build_graph_from_draft(env.services, csv_draft())
    assert mine.size == 1
    assert pipeline.cache_for(env.services) is mine


# --------------------------------------------------------------------------- a given cache


def test_a_given_cache_is_asked_first_and_filled_with_the_key_and_the_ttl(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    mine = RecordingCache()
    draft = csv_draft()
    key = cache_key(draft, env.services.source_context())
    first = build_graph_from_draft(env.services, draft, mine)
    assert (mine.gets, mine.puts) == ([key], [(key, 120.0)])
    assert build_graph_from_draft(env.services, draft, mine) is first
    assert mine.gets == [key, key]
    assert mine.puts == [(key, 120.0)]
    assert loads.count == 1
    assert cache_for(env.services).size == 0  # the cache of the Services was not touched


def test_a_given_cache_gets_the_mongo_ttl_for_a_mongo_draft(env: PipelineEnv) -> None:
    env.mongo["flows"]["links"].insert_one({"source": "a", "target": "b", "value": 1})
    mine = RecordingCache()
    build_graph_from_draft(env.services, mongo_draft(), mine)
    assert [ttl for _key, ttl in mine.puts] == [30.0]


def test_a_given_cache_is_left_alone_when_the_load_cannot_be_keyed(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_flows(env, CSV)
    monkeypatch.setattr(pipeline, "resolve_source_path", lambda _root, _rel: tmp_path / "gone.csv")
    mine = RecordingCache()
    build_graph_from_draft(env.services, file_draft(), mine)
    assert (mine.gets, mine.puts) == ([], [])
