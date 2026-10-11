"""Donut data: totals per basis and the one fold into slices."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.render.colors import ColorMap
from sankey_studio.render.donut_fold import (
    Basis,
    CategoryTotal,
    basis_links,
    category_totals,
    donut_slices,
    fold_totals,
)
from tests.graph_support import make_graph
from tests.render.support import budget, many_categories, plain, style


class BasisCase(NamedTuple):
    basis: Basis
    links: list[int]
    totals: dict[str, float]


BASES = [
    BasisCase(
        "all",
        [0, 1, 2, 3, 4, 5, 6, 7],
        {
            "Income": 5800.0,
            "Fixed": 2000.0,
            "Variable": 1300.0,
            "Investing": 1500.0,
            "Uncategorized": 1500.0,
        },
    ),
    BasisCase("initial", [0, 1], {"Income": 5800.0}),
    BasisCase(
        "terminal",
        [2, 3, 4, 6, 7],
        {"Fixed": 2000.0, "Variable": 1300.0, "Investing": 1500.0},
    ),
]


@pytest.mark.parametrize("case", BASES)
def test_basis_selects_links_and_totals(case: BasisCase) -> None:
    graph = budget()
    assert basis_links(graph, case.basis) == case.links
    totals = category_totals(graph, case.basis)
    assert {t.name: t.value for t in totals} == case.totals
    whole = sum(case.totals.values())
    assert [t.share for t in totals] == [t.value / whole for t in totals]
    assert sum(t.share for t in totals) == pytest.approx(1.0)


def test_totals_are_in_category_order_then_uncategorized_flagged_by_kind() -> None:
    totals = category_totals(budget(), "all")
    assert [t.name for t in totals] == ["Income", "Fixed", "Variable", "Investing", "Uncategorized"]
    assert [t.kind for t in totals] == ["category"] * 4 + ["uncategorized"]


def test_shares_include_the_uncategorized_value() -> None:
    graph = make_graph([("A", "B", 3.0, "x"), ("A", "C", 1.0, None)])
    assert category_totals(graph, "all") == [
        CategoryTotal("x", 3.0, 0.75),
        CategoryTotal("Uncategorized", 1.0, 0.25, "uncategorized"),
    ]


def test_zero_value_categories_are_dropped_and_empty_bases_give_nothing() -> None:
    graph = budget()
    assert "Fixed" not in {t.name for t in category_totals(graph, "initial")}
    assert category_totals(plain(), "all") == [
        CategoryTotal("Uncategorized", 12100.0, 1.0, "uncategorized")
    ]
    assert donut_slices(plain(), style(), ColorMap.for_graph(plain(), style())) == []
    assert category_totals(make_graph([]), "all") == []


def test_initial_and_terminal_use_the_cycle_broken_node_sums() -> None:
    graph = make_graph(
        [("A", "B", 1.0, "x"), ("B", "C", 2.0, "y"), ("C", "A", 4.0, "z")], on_cycle="break"
    )
    assert [t.name for t in category_totals(graph, "initial")] == ["x"]
    assert [t.name for t in category_totals(graph, "terminal")] == ["y"]


def totals_of(values: dict[str, float]) -> list[CategoryTotal]:
    whole = sum(values.values())
    return [CategoryTotal(name, value, value / whole) for name, value in values.items()]


def colors_for(count: int) -> ColorMap:
    return ColorMap.for_graph(many_categories(count), style())


class Fold(NamedTuple):
    total: int
    max_slices: int
    kept: int
    folded: int


FOLDS = [
    Fold(3, 6, 3, 0),
    Fold(6, 6, 6, 0),
    Fold(7, 6, 6, 1),
    Fold(8, 6, 6, 2),
    Fold(8, 8, 8, 0),
    Fold(9, 8, 8, 1),
    Fold(10, 2, 2, 8),
    Fold(8, 7, 7, 1),
]


@pytest.mark.parametrize("case", FOLDS)
def test_the_top_n_categories_keep_a_slice_and_the_rest_fold_into_other(case: Fold) -> None:
    graph = many_categories(case.total)
    colors = ColorMap.for_graph(graph, style())
    slices = fold_totals(category_totals(graph, "all"), case.max_slices, colors)
    categories = [s for s in slices if s.kind == "category"]
    assert len(categories) == case.kept
    others = [s for s in slices if s.kind == "other"]
    assert len(others) == (1 if case.folded or case.total > 8 else 0)
    if others:
        assert slices[-1] is others[0]
        assert others[0].name == "Other"
    assert sum(s.value for s in slices) == pytest.approx(sum(1000.0 - i for i in range(case.total)))


def test_kept_slices_are_ranked_by_value_with_position_breaking_ties() -> None:
    graph = make_graph(
        [("a", "b", 5.0, "p"), ("a", "c", 9.0, "q"), ("a", "d", 5.0, "r"), ("a", "e", 7.0, "s")]
    )
    colors = ColorMap.for_graph(graph, style())
    slices = fold_totals(category_totals(graph, "all"), 3, colors)
    assert [(s.name, s.kind) for s in slices] == [
        ("q", "category"),
        ("s", "category"),
        ("p", "category"),
        ("Other", "other"),
    ]
    assert slices[-1].value == 5.0


def test_other_collects_hue_candidates_beyond_the_top_n_and_categories_without_a_hue() -> None:
    graph = many_categories(10)
    colors = ColorMap.for_graph(graph, style())
    slices = fold_totals(category_totals(graph, "all"), 6, colors)
    assert [s.name for s in slices[:-1]] == [f"cat{i:02d}" for i in range(6)]
    folded = [1000.0 - i for i in range(6, 10)]
    other = slices[-1]
    assert (other.name, other.value, other.kind) == ("Other", sum(folded), "other")
    assert other.share == pytest.approx(sum(folded) / sum(1000.0 - i for i in range(10)))


def test_uncategorized_sits_right_before_other() -> None:
    graph = make_graph(
        [("a", f"t{i}", 10.0 + i, f"c{i}") for i in range(9)] + [("a", "u", 4.0, None)]
    )
    colors = ColorMap.for_graph(graph, style())
    slices = fold_totals(category_totals(graph, "all"), 6, colors)
    assert [s.kind for s in slices] == ["category"] * 6 + ["uncategorized", "other"]
    assert slices[6].name == "Uncategorized"
    assert slices[6].value == 4.0


def test_uncategorized_alone_stays_a_slice_and_there_is_no_other() -> None:
    graph = make_graph([("a", "b", 4.0, None), ("a", "c", 1.0, "x")])
    slices = fold_totals(category_totals(graph, "all"), 6, ColorMap.for_graph(graph, style()))
    assert [s.kind for s in slices] == ["category", "uncategorized"]


def test_an_override_gives_a_hue_candidate_even_in_slot_nine() -> None:
    graph = many_categories(10)
    colors = ColorMap.for_graph(graph, style(category_colors={"cat09": "#123456"}))
    totals = category_totals(graph, "all")
    tight = fold_totals(totals, 8, colors)
    assert [s.name for s in tight] == [f"cat{i:02d}" for i in range(8)] + ["Other"]
    assert tight[-1].value == 992.0 + 991.0  # cat09 is a candidate but ranks ninth
    wide = fold_totals(totals, 9, colors)
    assert [s.name for s in wide] == [f"cat{i:02d}" for i in range(8)] + ["cat09", "Other"]
    assert wide[-1].value == 992.0  # cat08 has no hue: it folds even though there is room


def test_donut_slices_sorts_categories_by_value_or_by_name() -> None:
    graph = make_graph(
        [
            ("a", "b", 1.0, "banana"),
            ("a", "c", 9.0, "Cherry"),
            ("a", "d", 5.0, "apple"),
            ("a", "e", 2.0, None),
        ]
    )
    colors = ColorMap.for_graph(graph, style())
    by_value = donut_slices(graph, style(), colors)
    assert [s.name for s in by_value] == ["Cherry", "apple", "banana", "Uncategorized"]
    by_name = donut_slices(graph, style(donut={"sort": "name"}), colors)
    assert [s.name for s in by_name] == ["apple", "banana", "Cherry", "Uncategorized"]


def test_donut_slices_name_sort_keeps_uncategorized_and_other_last() -> None:
    graph = make_graph(
        [("a", f"t{i}", 100.0 - i, f"c{9 - i}") for i in range(10)] + [("a", "u", 1.0, None)]
    )
    colors = ColorMap.for_graph(graph, style())
    slices = donut_slices(graph, style(donut={"sort": "name", "max_slices": 3}), colors)
    assert [s.name for s in slices] == ["c7", "c8", "c9", "Uncategorized", "Other"]
    assert [s.kind for s in slices] == ["category"] * 3 + ["uncategorized", "other"]


def test_donut_slices_is_empty_when_the_basis_selects_no_categorised_value() -> None:
    graph = make_graph([("a", "b", 1.0, None), ("b", "c", 1.0, "x")])
    colors = ColorMap.for_graph(graph, style())
    assert donut_slices(graph, style(donut={"basis": "initial"}), colors) == []
    assert [s.name for s in donut_slices(graph, style(donut={"basis": "terminal"}), colors)] == [
        "x"
    ]
