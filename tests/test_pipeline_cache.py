"""``ResultCache`` (LRU + TTL with an injected clock) and the per-``Services`` registry."""

from __future__ import annotations

import gc
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from sankey_studio import pipeline
from sankey_studio.config import BootstrapConfig
from sankey_studio.pipeline import CACHE_ENTRIES, ResultCache, cache_for, use_cache
from sankey_studio.services import Services
from sankey_studio.web.schemas import COMPARE_IDS_MAX
from tests.graph_support import make_graph
from tests.test_pipeline_support import FakeClock

if TYPE_CHECKING:
    from pathlib import Path

    from sankey_studio.models import SankeyGraph


def graph(tag: str = "x") -> SankeyGraph:
    return make_graph([(f"a-{tag}", f"b-{tag}", 1.0, None)])


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(1000.0)


def test_the_defaults_are_sixteen_entries_and_the_monotonic_clock() -> None:
    cache = ResultCache()
    assert CACHE_ENTRIES == 16
    assert cache._max_entries == 16
    assert cache._clock is time.monotonic


def test_the_default_room_holds_a_whole_compare_view() -> None:
    assert CACHE_ENTRIES >= COMPARE_IDS_MAX


@pytest.mark.parametrize("bad", [0, -1])
def test_a_cache_needs_room_for_one_entry(bad: int) -> None:
    with pytest.raises(ValueError, match=r"^max_entries must be at least 1$"):
        ResultCache(max_entries=bad)
    assert ResultCache(max_entries=1).size == 0


def test_a_miss_is_none_and_a_hit_is_the_same_object(clock: FakeClock) -> None:
    cache = ResultCache(clock=clock)
    value = graph()
    assert cache.get("k") is None
    cache.put("k", value, 10)
    assert cache.get("k") is value
    assert cache.get("other") is None
    assert cache.size == 1


def test_an_entry_is_valid_until_its_ttl_and_not_at_it(clock: FakeClock) -> None:
    cache = ResultCache(clock=clock)
    cache.put("k", graph(), 10)
    clock.now = 1009.999
    assert cache.get("k") is not None
    clock.now = 1010.0
    assert cache.get("k") is None
    assert cache.size == 0


def test_the_ttl_counts_from_the_put_not_from_the_last_hit(clock: FakeClock) -> None:
    cache = ResultCache(clock=clock)
    cache.put("k", graph(), 10)
    clock.now = 1008.0
    assert cache.get("k") is not None
    clock.now = 1011.0
    assert cache.get("k") is None


def test_a_zero_ttl_is_already_expired(clock: FakeClock) -> None:
    cache = ResultCache(clock=clock)
    cache.put("k", graph(), 0)
    assert cache.get("k") is None


def test_putting_a_key_again_replaces_value_and_ttl(clock: FakeClock) -> None:
    cache = ResultCache(clock=clock)
    first, second = graph("1"), graph("2")
    cache.put("k", first, 10)
    clock.now = 1008.0
    cache.put("k", second, 10)
    clock.now = 1015.0
    assert cache.get("k") is second
    assert cache.size == 1


def test_the_least_recently_used_entry_goes_first(clock: FakeClock) -> None:
    cache = ResultCache(max_entries=2, clock=clock)
    a, b, c = graph("a"), graph("b"), graph("c")
    cache.put("a", a, 100)
    cache.put("b", b, 100)
    assert cache.get("a") is a  # a is now the most recently used
    cache.put("c", c, 100)
    assert cache.get("b") is None
    assert cache.get("a") is a
    assert cache.get("c") is c
    assert cache.size == 2


def test_one_entry_too_many_evicts_the_first(clock: FakeClock) -> None:
    cache = ResultCache(clock=clock)
    for index in range(CACHE_ENTRIES + 1):
        cache.put(f"k{index}", graph(str(index)), 100)
    assert cache.size == CACHE_ENTRIES
    assert cache.get("k0") is None
    assert cache.get("k1") is not None
    assert cache.get(f"k{CACHE_ENTRIES}") is not None


@pytest.mark.parametrize("now", [1005.0, 1006.0], ids=["at the ttl", "after the ttl"])
def test_a_put_drops_expired_entries_before_it_evicts_a_live_one(
    clock: FakeClock, now: float
) -> None:
    cache = ResultCache(max_entries=2, clock=clock)
    live = graph("live")
    cache.put("short", graph("short"), 5)
    cache.put("live", live, 100)
    assert cache.get("short") is not None  # the short-lived entry is the most recently used
    clock.now = now
    cache.put("new", graph("new"), 100)
    assert cache.size == 2
    assert cache.get("live") is live
    assert cache.get("short") is None


def test_threads_never_push_the_cache_over_its_size() -> None:
    cache = ResultCache(max_entries=4)
    values = [graph(str(i)) for i in range(16)]

    def work(index: int) -> int:
        for round_ in range(50):
            cache.put(f"k{(index + round_) % 16}", values[index], 60)
            cache.get(f"k{round_ % 16}")
        return cache.size

    with ThreadPoolExecutor(max_workers=8) as pool:
        sizes = list(pool.map(work, range(8)))
    assert all(size <= 4 for size in sizes)
    assert cache.size == 4


# --------------------------------------------------------------------------- the registry


def test_each_services_instance_has_its_own_cache(tmp_path: Path) -> None:
    one = Services.create(BootstrapConfig(data_dir=tmp_path / "one"))
    two = Services.create(BootstrapConfig(data_dir=tmp_path / "two"))
    assert cache_for(one) is cache_for(one)
    assert cache_for(one) is not cache_for(two)
    assert isinstance(cache_for(one), ResultCache)


def test_use_cache_replaces_the_cache_of_one_instance(tmp_path: Path) -> None:
    services = Services.create(BootstrapConfig(data_dir=tmp_path / "one"))
    other = Services.create(BootstrapConfig(data_dir=tmp_path / "two"))
    mine = ResultCache(max_entries=3)
    use_cache(services, mine)
    assert cache_for(services) is mine
    assert cache_for(other) is not mine


def test_the_cache_goes_away_with_its_services(tmp_path: Path) -> None:
    services = Services.create(BootstrapConfig(data_dir=tmp_path / "one"))
    cache = weakref.ref(cache_for(services))
    before = len(pipeline._CACHES)
    del services
    gc.collect()
    assert cache() is None
    assert len(pipeline._CACHES) == before - 1
