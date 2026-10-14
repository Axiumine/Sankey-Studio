"""``with_extra_links``: the graph-only entries come after the rows of the source."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.models import Link
from sankey_studio.sources.overlay import with_extra_links

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sankey_studio.models import RawLink

ROWS: list[RawLink] = [("a", "b", 1.0, None), ("b", "c", 2.0, "Fixed")]


def test_the_extra_links_follow_the_rows_in_order() -> None:
    extras = [Link(source="x", target="y", value=3.0), Link(source="y", target="z", value=4.5)]
    assert list(with_extra_links(ROWS, extras)) == [
        *ROWS,
        ("x", "y", 3.0, None),
        ("y", "z", 4.5, None),
    ]


def test_without_extra_links_the_rows_pass_through() -> None:
    assert list(with_extra_links(ROWS, [])) == ROWS
    assert list(with_extra_links([], [])) == []


def test_extra_links_alone_make_a_stream() -> None:
    extra = Link(source="x", target="y", value=1.0, category="Fun")
    assert list(with_extra_links([], [extra])) == [("x", "y", 1.0, "Fun")]


@pytest.mark.parametrize("category", [None, ""])
def test_an_empty_category_counts_as_none(category: str | None) -> None:
    link = Link.model_construct(source="x", target="y", value=1.0, category=category)
    assert list(with_extra_links([], [link])) == [("x", "y", 1.0, None)]


def test_a_real_category_is_kept_as_written() -> None:
    link = Link(source="x", target="y", value=1.0, category="Fun")
    assert next(with_extra_links([], [link]))[3] == "Fun"


class Source:
    """A source generator that records when it was closed (the cleanup of a text source)."""

    def __init__(self) -> None:
        self.closed = False
        self.stream = self._rows()

    def _rows(self) -> Iterator[RawLink]:
        try:
            yield from ROWS
        finally:
            self.closed = True


def test_closing_the_chain_closes_the_source_behind_it() -> None:
    source = Source()
    chain = with_extra_links(source.stream, [Link(source="x", target="y", value=1.0)])
    assert next(chain) == ROWS[0]
    assert not source.closed
    chain.close()
    assert source.closed


def test_the_chain_is_lazy() -> None:
    source = Source()
    chain = with_extra_links(source.stream, [])
    assert not source.closed
    assert next(chain) == ROWS[0]
    assert list(chain) == ROWS[1:]
    assert source.closed
