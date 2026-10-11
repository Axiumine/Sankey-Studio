"""``build_graph``: the raw-row cap, the category cap, closing the stream, and speed."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import GraphTooLargeError, SourceError
from sankey_studio.graph import build_graph
from sankey_studio.models import MAX_CATEGORIES, RawLink, TransformSpec
from sankey_studio.sources.base import Diagnostics
from tests.graph_support import make_graph, rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

CATS = [f"c{i}" for i in range(9)] + [None]


class Stream:
    """A generator-like source that records how it was used."""

    def __init__(self, count: int, fail_at: int | None = None) -> None:
        self.pulled = 0
        self.closed = False
        self._count = count
        self._fail_at = fail_at

    def __iter__(self) -> Iterator[RawLink]:
        try:
            for i in range(self._count):
                self.pulled += 1
                if i == self._fail_at:
                    raise SourceError("bad row")
                yield (f"s{i}", f"t{i}", 1.0, None)
        finally:
            self.closed = True


def run(links: Iterable[RawLink], limit: int) -> None:
    build_graph(links, TransformSpec(), max_raw_links=limit, diag=Diagnostics())


@pytest.mark.parametrize(
    ("count", "limit", "fails"),
    [(5, 5, False), (6, 5, True), (1, 1, False), (2, 1, True), (0, 0, False)],
)
def test_more_rows_than_the_cap_is_graph_too_large(count: int, limit: int, fails: bool) -> None:
    links: list[RawLink] = [(f"s{i}", f"t{i}", 1.0, None) for i in range(count)]
    if not fails:
        run(links, limit)
        return
    with pytest.raises(GraphTooLargeError) as caught:
        run(links, limit)
    assert caught.value.message == (
        f"The source has more than {limit} links; "
        "raise max_links in the settings or narrow the data"
    )
    assert caught.value.status_code == 413


def test_the_stream_is_read_lazily_and_stops_at_the_cap() -> None:
    stream = Stream(1000)
    iterator = iter(stream)
    with pytest.raises(GraphTooLargeError):
        run(iterator, 3)
    assert stream.pulled == 4


def test_the_source_is_closed_when_the_cap_is_exceeded() -> None:
    stream = Stream(50)
    iterator = iter(stream)
    with pytest.raises(GraphTooLargeError):
        run(iterator, 10)
    assert stream.closed


def test_the_source_is_closed_when_it_fails_mid_stream() -> None:
    stream = Stream(50, fail_at=7)
    iterator = iter(stream)
    with pytest.raises(SourceError, match="bad row"):
        run(iterator, 100)
    assert stream.closed


def test_the_source_is_closed_after_a_complete_read() -> None:
    stream = Stream(5)
    iterator = iter(stream)
    run(iterator, 100)
    assert stream.closed


def test_plain_iterators_without_close_are_fine() -> None:
    links: list[RawLink] = [("A", "B", 1.0, None)]
    graph = build_graph(iter(links), TransformSpec(), max_raw_links=5, diag=Diagnostics())
    assert rows(graph) == [("A", "B", 1.0, None)]


@pytest.mark.parametrize(
    ("count", "dropped"),
    [
        (MAX_CATEGORIES - 1, 0),
        (MAX_CATEGORIES, 0),
        (MAX_CATEGORIES + 1, 1),
        (MAX_CATEGORIES + 3, 3),
    ],
)
def test_at_most_two_hundred_categories_later_ones_become_uncategorised(
    count: int, dropped: int
) -> None:
    links: list[RawLink] = [("A", f"T{i}", 1.0, f"cat{i}") for i in range(count)]
    graph = make_graph(links)
    assert MAX_CATEGORIES == 200
    assert len(graph.categories) == count - dropped
    assert graph.categories == tuple(f"cat{i}" for i in range(count - dropped))
    assert list(graph.category_color_slot) == list(range(count - dropped))
    assert [row[3] for row in rows(graph)].count(None) == dropped
    expected = (
        (f"{dropped} category name(s) beyond the limit of 200 were left uncategorised",)
        if dropped
        else ()
    )
    assert graph.warnings == expected


def test_dropped_categories_merge_with_the_uncategorised_entry_of_the_pair() -> None:
    links: list[RawLink] = [("S", f"T{i}", 1.0, f"c{i}") for i in range(MAX_CATEGORIES)]
    links += [("A", "B", 1.0, "late"), ("A", "B", 2.0, "later"), ("A", "B", 4.0, None)]
    graph = make_graph(links)
    assert ("A", "B", 7.0, None) in rows(graph)
    assert graph.warnings == ("2 category name(s) beyond the limit of 200 were left uncategorised",)


def test_the_cap_counts_rule_and_entry_categories_too() -> None:
    links: list[RawLink] = [("A", f"T{i}", 1.0, None) for i in range(MAX_CATEGORIES + 1)]
    choices = [
        {"source": "A", "target": f"T{i}", "category": f"e{i}"} for i in range(MAX_CATEGORIES + 1)
    ]
    graph = make_graph(links, entry_categories=choices)
    assert graph.categories == tuple(f"e{i}" for i in range(MAX_CATEGORIES))
    assert rows(graph)[-1] == ("A", f"T{MAX_CATEGORIES}", 1.0, None)
    assert graph.warnings == ("1 category name(s) beyond the limit of 200 were left uncategorised",)


@pytest.mark.slow
def test_two_hundred_thousand_links_build_in_under_three_seconds() -> None:
    rnd = random.Random(7)
    links: list[RawLink] = [
        (f"s{rnd.randrange(700)}", f"t{rnd.randrange(900)}", rnd.uniform(1, 50), rnd.choice(CATS))
        for _ in range(200_000)
    ]
    started = time.perf_counter()
    graph = make_graph(links)
    assert time.perf_counter() - started < 3.0
    assert graph.n_links > 150_000
    assert len(graph.categories) == 9
