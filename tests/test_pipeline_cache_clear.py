"""``ResultCache.clear`` / ``ClearableCache``: dropping every cached graph after a source write."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.pipeline import ClearableCache, ResultCache, build_graph_from_draft
from tests.graph_support import make_graph
from tests.test_pipeline_support import (
    FakeClock,
    PipelineEnv,
    RecordingCache,
    count_loads,
    csv_draft,
    make_env,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import SankeyGraph


def graph(tag: str = "x") -> SankeyGraph:
    return make_graph([(f"a-{tag}", f"b-{tag}", 1.0, None)])


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


def test_clear_drops_every_entry_live_or_not() -> None:
    clock = FakeClock(1000.0)
    cache = ResultCache(clock=clock)
    cache.put("live", graph("a"), 100)
    cache.put("short", graph("b"), 5)
    clock.now = 1006.0  # "short" is expired but nobody asked for it yet
    assert cache.size == 2
    cache.clear()
    assert cache.size == 0
    assert cache.get("live") is None
    assert cache.get("short") is None


def test_clearing_an_empty_cache_is_fine_and_the_cache_stays_usable() -> None:
    cache = ResultCache(max_entries=2, clock=FakeClock(1000.0))
    cache.clear()
    assert cache.size == 0
    first = graph("first")
    cache.put("a", first, 10)
    cache.clear()
    cache.put("a", first, 10)
    assert cache.get("a") is first
    cache.put("b", graph("b"), 10)
    cache.put("c", graph("c"), 10)  # the size limit still applies after a clear
    assert cache.size == 2
    assert cache.get("a") is None


def test_threads_can_clear_while_others_fill_the_cache() -> None:
    cache = ResultCache(max_entries=4)
    values = [graph(str(i)) for i in range(8)]

    def work(index: int) -> int:
        for round_ in range(50):
            cache.put(f"k{(index + round_) % 8}", values[index], 60)
            if round_ % 10 == index:
                cache.clear()
        return cache.size

    with ThreadPoolExecutor(max_workers=8) as pool:
        sizes = list(pool.map(work, range(8)))
    assert all(size <= 4 for size in sizes)


def test_the_real_cache_and_the_test_fake_are_clearable_caches() -> None:
    for cache in (ResultCache(), RecordingCache()):
        clearable: ClearableCache = cache
        clearable.put("k", graph(), 10)
        clearable.clear()
        assert clearable.get("k") is None


def test_the_fake_counts_its_clears() -> None:
    cache = RecordingCache()
    cache.put("k", graph(), 10)
    cache.clear()
    cache.clear()
    assert cache.clears == 2
    assert cache.items == {}


def test_a_cleared_cache_makes_the_pipeline_load_the_source_again(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    cache = ResultCache()
    draft = csv_draft()
    first = build_graph_from_draft(env.services, draft, cache)
    assert build_graph_from_draft(env.services, draft, cache) is first
    assert loads.count == 1
    cache.clear()
    again = build_graph_from_draft(env.services, draft, cache)
    assert again is not first
    assert loads.count == 2
    assert build_graph_from_draft(env.services, draft, cache) is again
