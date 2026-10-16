# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Manual links: the three edits, by canonical pair."""

from __future__ import annotations

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import MAX_MANUAL_LINKS, Link
from sankey_studio.sources.rewrite.manual import rewrite_links
from tests.sources.rewrite.support import add, categorise, reorder


def link(source: str, target: str, value: float, category: str | None = None) -> Link:
    return Link(source=source, target=target, value=value, category=category)


LINKS = [link("b", "c", 1, "K"), link("a", "b", 2), link("a", "b", 3, "L")]


def test_set_category_changes_every_link_of_the_pair() -> None:
    out = rewrite_links(LINKS, categorise("a", "b", "N"), {})
    assert [(x.source, x.target, x.value, x.category) for x in out] == [
        ("b", "c", 1, "K"),
        ("a", "b", 2, "N"),
        ("a", "b", 3, "N"),
    ]


def test_set_category_none_clears() -> None:
    out = rewrite_links(LINKS, categorise("b", "c", None), {})
    assert out[0].category is None
    assert [x.category for x in out[1:]] == [None, "L"]


def test_the_alias_matches_merged_names() -> None:
    links = [link("A1", "b", 1), link("A2", "b", 2), link("x", "b", 3)]
    out = rewrite_links(links, categorise("A", "b", "N"), {"A1": "A", "A2": "A"})
    assert [x.category for x in out] == ["N", "N", None]


def test_no_match_is_refused() -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite_links(LINKS, categorise("x", "y", "N"), {})
    assert info.value.reason == "no_match"


def test_the_input_is_not_changed() -> None:
    before = [x.model_dump() for x in LINKS]
    rewrite_links(LINKS, categorise("a", "b", "N"), {})
    assert [x.model_dump() for x in LINKS] == before


def test_add_appends_a_validated_link() -> None:
    out = rewrite_links(LINKS, add("x", "y", 5, "N"), {})
    assert out[:3] == LINKS
    assert (out[3].source, out[3].target, out[3].value, out[3].category) == ("x", "y", 5, "N")
    assert rewrite_links([], add("x", "y", 5), {})[0].category is None


def test_add_stops_at_the_cap() -> None:
    full = [link("a", "b", 1)] * MAX_MANUAL_LINKS
    assert len(rewrite_links(full[:-1], add("x", "y", 1), {})) == MAX_MANUAL_LINKS
    with pytest.raises(SourceEditRefused) as info:
        rewrite_links(full, add("x", "y", 1), {})
    assert info.value.reason == "too_many"


def test_reorder_is_a_stable_sort_by_the_ranks_of_the_ends() -> None:
    links = [link("z", "y", 1), link("b", "c", 2), link("a", "b", 3), link("a", "b", 4)]
    out = rewrite_links(links, reorder("a", "b", "c"), {})
    assert [x.value for x in out] == [3, 4, 2, 1]


def test_reorder_with_an_alias() -> None:
    links = [link("B1", "c", 1), link("a", "B1", 2)]
    out = rewrite_links(links, reorder("a", "B", "c"), {"B1": "B"})
    assert [x.value for x in out] == [2, 1]
