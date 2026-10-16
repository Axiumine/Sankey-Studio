# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``category_rules`` work guard: ``distinct names * rules`` is capped before matching starts."""

from __future__ import annotations

import time
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import GraphTooLargeError
from sankey_studio.graph import categories
from sankey_studio.graph.categories import MAX_RULE_WORK, check_rule_work
from tests.graph_support import make_graph, rows

if TYPE_CHECKING:
    from sankey_studio.models import RawLink


class Work(NamedTuple):
    names: int
    rules: int
    allowed: bool


WORK = [
    Work(100_000, 200, True),  # exactly 20,000,000
    Work(100_001, 200, False),
    Work(99_999, 200, True),
    Work(20_000_000, 1, True),
    Work(20_000_001, 1, False),
    Work(50_000, 400, True),
    Work(50_001, 400, False),
    Work(1, 200, True),
    Work(0, 200, True),
    Work(10**9, 0, True),  # no rules, no work, however many names
    Work(10**9, 1, False),
]


def test_the_cap_is_twenty_million_name_rule_pairs() -> None:
    assert MAX_RULE_WORK == 20_000_000


@pytest.mark.parametrize("case", WORK)
def test_the_work_cap_is_names_times_rules_and_the_limit_itself_is_allowed(case: Work) -> None:
    if case.allowed:
        check_rule_work(case.names, case.rules)
        return
    with pytest.raises(GraphTooLargeError) as caught:
        check_rule_work(case.names, case.rules)
    assert caught.value.message == (
        f"The category rules are too expensive for this graph ({case.rules} rules over "
        f"{case.names} distinct node names); remove rules or narrow the data"
    )
    assert caught.value.status_code == 413
    assert caught.value.code == "graph_too_large"


class Spy:
    """Counts the glob matches a build performs."""

    def __init__(self) -> None:
        self.calls = 0
        self.real = fnmatchcase

    def __call__(self, name: str, pattern: str) -> bool:
        self.calls += 1
        return self.real(name, pattern)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    counter = Spy()
    monkeypatch.setattr(categories, "fnmatchcase", counter)
    return counter


LINKS: list[RawLink] = [("A", "B", 1.0, None), ("C", "D", 2.0, None)]
RULES = [
    {"pattern": "A", "category": "first", "match": "source"},
    {"pattern": "D", "category": "second", "match": "target"},
]


def test_a_build_at_the_cap_matches_and_one_over_is_refused_before_matching(
    monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    monkeypatch.setattr(categories, "MAX_RULE_WORK", 8)  # 4 names * 2 rules
    graph = make_graph(LINKS, category_rules=RULES)
    assert [row[3] for row in rows(graph)] == ["first", "second"]
    matched = spy.calls
    assert matched > 0
    monkeypatch.setattr(categories, "MAX_RULE_WORK", 7)
    with pytest.raises(GraphTooLargeError, match="category rules are too expensive"):
        make_graph(LINKS, category_rules=RULES)
    assert spy.calls == matched


def test_merged_aliases_count_once_toward_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    links: list[RawLink] = [("A", "B", 1.0, None), ("A2", "B2", 2.0, None)]
    merge = {"A2": "A", "B2": "B"}
    monkeypatch.setattr(categories, "MAX_RULE_WORK", 4)  # 2 distinct names * 2 rules
    graph = make_graph(links, category_rules=RULES, merge_nodes=merge)
    assert graph.node_names == ("A", "B")
    assert graph.n_links == 1
    monkeypatch.setattr(categories, "MAX_RULE_WORK", 3)
    with pytest.raises(GraphTooLargeError):
        make_graph(links, category_rules=RULES, merge_nodes=merge)


def test_without_category_rules_the_cap_never_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(categories, "MAX_RULE_WORK", 0)
    assert make_graph(LINKS).n_links == 2


def test_two_hundred_rules_over_a_hundred_thousand_names_are_refused_without_matching(
    spy: Spy,
) -> None:
    links: list[RawLink] = [(f"s{i}", f"t{i}", 1.0, None) for i in range(50_001)]
    rules = [{"pattern": f"x{i}*", "category": f"c{i}"} for i in range(200)]
    started = time.perf_counter()
    with pytest.raises(GraphTooLargeError) as caught:
        make_graph(links, category_rules=rules)
    assert time.perf_counter() - started < 3.0
    assert caught.value.message == (
        "The category rules are too expensive for this graph (200 rules over 100002 distinct "
        "node names); remove rules or narrow the data"
    )
    assert spy.calls == 0


@pytest.mark.slow
def test_the_worst_accepted_build_is_bounded() -> None:
    """200 non-matching ``either`` rules over exactly 100,000 names: 20 million name-rule pairs."""
    links: list[RawLink] = [(f"s{i}", f"t{i}", 1.0, None) for i in range(50_000)]
    rules = [{"pattern": f"x{i}*", "category": f"c{i}"} for i in range(200)]
    started = time.perf_counter()
    graph = make_graph(links, category_rules=rules)
    assert time.perf_counter() - started < 10.0
    assert graph.n_links == 50_000
    assert graph.categories == ()


@pytest.mark.slow
def test_the_reported_case_two_hundred_rules_over_two_hundred_thousand_links_fails_fast() -> None:
    """It used to take 15.6 s of synchronous matching before the graph was drawn."""
    links: list[RawLink] = [(f"s{i}", f"t{i}", 1.0, None) for i in range(200_000)]
    rules = [{"pattern": f"x{i}*", "category": f"c{i}"} for i in range(200)]
    started = time.perf_counter()
    with pytest.raises(GraphTooLargeError, match="400000 distinct node names"):
        make_graph(links, category_rules=rules)
    assert time.perf_counter() - started < 5.0
