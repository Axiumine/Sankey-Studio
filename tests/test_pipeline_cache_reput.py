# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``ResultCache.put`` on a key that is already held: the entry becomes the most recent one."""

from __future__ import annotations

from sankey_studio.pipeline import ResultCache
from tests.graph_support import make_graph
from tests.test_pipeline_support import FakeClock


def test_putting_a_held_key_again_makes_it_the_newest_entry() -> None:
    cache = ResultCache(max_entries=2, clock=FakeClock(1000.0))
    old, new, other = (make_graph([(f"a-{tag}", f"b-{tag}", 1.0, None)]) for tag in "xyz")
    cache.put("a", old, 10)
    cache.put("b", other, 10)
    cache.put("a", new, 10)
    cache.put("c", other, 10)
    assert cache.get("b") is None
    assert cache.get("a") is new
    assert cache.get("c") is other
    assert cache.size == 2


def test_putting_a_held_key_again_restarts_its_time_to_live() -> None:
    clock = FakeClock(1000.0)
    cache = ResultCache(max_entries=2, clock=clock)
    graph = make_graph([("a", "b", 1.0, None)])
    cache.put("k", graph, 10)
    clock.now = 1008.0
    cache.put("k", graph, 10)
    clock.now = 1017.999
    assert cache.get("k") is graph
    clock.now = 1018.0
    assert cache.get("k") is None
