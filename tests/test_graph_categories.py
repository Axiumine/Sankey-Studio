"""``build_graph``: categories from the data (identity, display, tolerance, slots)."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.graph.intern import data_category
from sankey_studio.graph.state import BuildState
from sankey_studio.models import RawLink, TransformSpec
from sankey_studio.sources.base import Diagnostics
from sankey_studio.util import category_key
from tests.graph_support import make_graph, rows, stripped, topology


def test_data_categories_split_a_pair_into_parallel_links() -> None:
    graph = make_graph(
        [
            ("A", "B", 5.0, "Food"),
            ("A", "B", 2.0, None),
            ("A", "B", 1.0, "Rent"),
            ("B", "C", 1.0, "Food"),
        ]
    )
    assert graph.categories == ("Food", "Rent")
    assert graph.category_color_slot == (0, 1)
    assert rows(graph) == [
        ("A", "B", 5.0, "Food"),
        ("A", "B", 1.0, "Rent"),
        ("A", "B", 2.0, None),
        ("B", "C", 1.0, "Food"),
    ]
    assert graph.has_categories


def test_the_uncategorised_link_is_last_within_its_pair() -> None:
    graph = make_graph([("A", "B", 1.0, None), ("A", "B", 1.0, "z"), ("A", "B", 1.0, "a")])
    assert [row[3] for row in rows(graph)] == ["z", "a", None]


class Variants(NamedTuple):
    spellings: list[str]
    display: str


VARIANTS = [
    Variants(["Food", "food", "FOOD"], "Food"),
    Variants(["food", "Food", "FOOD"], "food"),
    Variants(["Food", "  food ", "FOOD  "], "Food"),
    Variants(["Caf\u00e9", "Cafe\u0301", "CAFE\u0301"], "Caf\u00e9"),
    Variants(["Cafe\u0301", "Caf\u00e9"], "Caf\u00e9"),
    Variants(["Fast  Food", "fast food", "FAST\tFOOD"], "Fast Food"),
]


@pytest.mark.parametrize("case", VARIANTS)
def test_case_and_nfc_variants_are_one_category_with_the_first_spelling(case: Variants) -> None:
    links: list[RawLink] = [("A", f"T{i}", 1.0, name) for i, name in enumerate(case.spellings)]
    graph = make_graph(links)
    assert graph.categories == (case.display,)
    assert list(graph.link_category) == [0] * len(case.spellings)


def test_variants_on_one_pair_merge_into_one_link() -> None:
    graph = make_graph([("A", "B", 1.0, "Food"), ("A", "B", 2.0, "food")])
    assert rows(graph) == [("A", "B", 3.0, "Food")]


@pytest.mark.parametrize("name", ["Uncategorized", "other", " OTHER ", "UnCategorized"])
def test_reserved_names_from_data_become_none_with_one_warning(name: str) -> None:
    graph = make_graph([("A", "B", 1.0, name), ("A", "C", 1.0, name), ("A", "D", 1.0, "Food")])
    assert [row[3] for row in rows(graph)] == [None, None, "Food"]
    assert graph.categories == ("Food",)
    assert graph.warnings == (
        "1 category value(s) in the data were empty, reserved or unusable; ignored",
    )


def test_unusable_values_are_counted_per_distinct_value() -> None:
    graph = make_graph(
        [
            ("A", "B", 1.0, "bad\x00"),
            ("A", "C", 1.0, ""),
            ("A", "D", 1.0, "Other"),
            ("A", "E", 1.0, "\x01"),
        ]
    )
    assert graph.categories == ()
    assert [row[3] for row in rows(graph)] == [None] * 4
    assert graph.warnings == (
        "4 category value(s) in the data were empty, reserved or unusable; ignored",
    )


def test_a_category_that_only_exists_on_hidden_links_is_not_listed() -> None:
    graph = make_graph([("A", "B", 1.0, "Gone"), ("A", "C", 1.0, "Kept")], hide_nodes=["B"])
    assert graph.categories == ("Kept",)
    assert graph.category_color_slot == (1,)
    assert list(graph.link_category) == [0]


def test_data_category_is_normalised_once_per_distinct_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real = category_key

    def counting(value: str) -> str:
        calls.append(value)
        return real(value)

    monkeypatch.setattr("sankey_studio.graph.intern.category_key", counting)
    make_graph([("A", f"T{i}", 1.0, "Food") for i in range(50)])
    assert calls == ["Food"]


def test_data_category_ids_start_at_one_and_zero_means_none() -> None:
    state = BuildState(transform=TransformSpec(), diag=Diagnostics())
    assert data_category(state, None) == 0
    assert data_category(state, "Food") == 1
    assert data_category(state, "food") == 1
    assert data_category(state, "Rent") == 2
    assert data_category(state, "Other") == 0
    assert state.data_cats == ["Food", "Rent"]
    assert state.unusable_categories == 1
    assert data_category(state, "Other") == 0
    assert state.unusable_categories == 1


def test_categories_do_not_change_the_topology() -> None:
    links: list[RawLink] = [
        ("A", "B", 5.0, "Food"),
        ("A", "B", 2.5, "Rent"),
        ("A", "B", 1.0, None),
        ("B", "C", 3.0, "Food"),
        ("A", "C", 4.0, "x"),
        ("C", "D", 0.5, "y"),
    ]
    with_categories = make_graph(links)
    without = make_graph(stripped(links))
    assert topology(with_categories) == topology(without)
    assert without.categories == ()


def test_slots_follow_first_appearance_of_the_resolved_categories() -> None:
    graph = make_graph([("A", "B", 1.0, "c"), ("A", "C", 1.0, "a"), ("A", "D", 1.0, "b")])
    assert graph.categories == ("c", "a", "b")
    assert graph.category_color_slot == (0, 1, 2)
