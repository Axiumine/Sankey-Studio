"""Table views: entries (filter, sort, page), nodes and the category table."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.models import ENTRIES_PAGE_MAX, RawLink, TransformSpec
from sankey_studio.render.colors import ColorMap
from sankey_studio.render.options import EntriesOptions, EntrySort
from sankey_studio.render.palette import CATEGORICAL, OTHER_COLOR, UNCATEGORIZED_COLOR
from sankey_studio.render.tables import (
    CategoryRow,
    EntryRow,
    NodeRow,
    category_table,
    entries_page,
    nodes_table,
)
from tests.graph_support import make_graph
from tests.render.support import HandLink, budget, hand_graph, many_categories, plain, style

LINKS: list[RawLink] = [
    ("Salary", "Budget", 5000.0, "Income"),
    ("Salary", "Budget", 100.0, None),
    ("Budget", "Rent", 2000.0, "Fixed"),
    ("Budget", "food", 900.0, "Variable"),
    ("Budget", "Fun", 900.0, None),
    ("Budget", "Zoo", 50.0, None),
]
NO_CHOICES = TransformSpec()


def page(options: EntriesOptions, transform: TransformSpec = NO_CHOICES) -> list[tuple[str, str]]:
    return [
        (row.source, row.target) for row in entries_page(make_graph(LINKS), transform, options).rows
    ]


def test_one_row_per_pair_with_the_pair_total_and_the_main_category() -> None:
    result = entries_page(make_graph(LINKS), NO_CHOICES, EntriesOptions())
    assert result.total == 5
    assert result.rows == [
        EntryRow("Salary", "Budget", 5100.0, "Income", True, False),
        EntryRow("Budget", "Rent", 2000.0, "Fixed", False, False),
        EntryRow("Budget", "food", 900.0, "Variable", False, False),
        EntryRow("Budget", "Fun", 900.0, None, False, False),
        EntryRow("Budget", "Zoo", 50.0, None, False, False),
    ]


class Main(NamedTuple):
    links: list[RawLink]
    category: str | None
    mixed: bool


MAINS = [
    Main([("a", "b", 5.0, "x"), ("a", "b", 3.0, "y")], "x", True),
    Main([("a", "b", 3.0, "x"), ("a", "b", 5.0, "y")], "y", True),
    Main([("a", "b", 4.0, "x"), ("a", "b", 4.0, "y")], "x", True),
    Main([("a", "b", 4.0, "y"), ("a", "b", 4.0, "x")], "y", True),
    Main([("a", "b", 4.0, None), ("a", "b", 4.0, "x")], "x", True),
    Main([("a", "b", 3.0, "x"), ("a", "b", 4.0, None)], None, True),
    Main([("a", "b", 3.0, "x"), ("a", "b", 2.0, "X")], "x", False),
    Main([("a", "b", 3.0, None)], None, False),
]


@pytest.mark.parametrize("case", MAINS)
def test_a_pair_with_several_categories_shows_the_largest_and_is_mixed(case: Main) -> None:
    (row,) = entries_page(make_graph(case.links), NO_CHOICES, EntriesOptions()).rows
    assert (row.category, row.mixed) == (case.category, case.mixed)


def test_overridden_marks_pairs_set_in_entry_categories() -> None:
    transform = TransformSpec.model_validate(
        {
            "entry_categories": [
                {"source": "Budget", "target": "Rent", "category": "Fixed"},
                {"source": "Budget", "target": "Fun", "category": None},
                {"source": "budget", "target": "Zoo", "category": "x"},
            ]
        }
    )
    result = entries_page(make_graph(LINKS, **transform.model_dump()), transform, EntriesOptions())
    assert [(r.target, r.overridden) for r in result.rows] == [
        ("Budget", False),
        ("Rent", True),
        ("food", False),
        ("Fun", True),
        ("Zoo", False),
    ]


class Sort(NamedTuple):
    sort: EntrySort
    targets: list[str]


SORTS = [
    Sort("value", ["Budget", "Rent", "food", "Fun", "Zoo"]),
    Sort("source", ["Rent", "food", "Fun", "Zoo", "Budget"]),
    Sort("target", ["Budget", "food", "Fun", "Rent", "Zoo"]),
    Sort("category", ["Rent", "Budget", "food", "Fun", "Zoo"]),
]


@pytest.mark.parametrize("case", SORTS)
def test_sort_orders(case: Sort) -> None:
    assert [t for _s, t in page(EntriesOptions(sort=case.sort))] == case.targets


def test_value_sort_is_descending_with_ties_in_first_appearance_order() -> None:
    targets = [t for _s, t in page(EntriesOptions(sort="value"))]
    assert targets == ["Budget", "Rent", "food", "Fun", "Zoo"]
    assert targets.index("food") < targets.index("Fun")


def test_text_sorts_are_case_insensitive_and_stable() -> None:
    graph = make_graph(
        [("b", "x", 1.0, None), ("B", "y", 2.0, None), ("a", "z", 3.0, None), ("A", "w", 4.0, None)]
    )
    by_source = entries_page(graph, NO_CHOICES, EntriesOptions(sort="source")).rows
    assert [(r.source, r.target) for r in by_source] == [
        ("a", "z"),
        ("A", "w"),
        ("b", "x"),
        ("B", "y"),
    ]
    by_target = entries_page(graph, NO_CHOICES, EntriesOptions(sort="target")).rows
    assert [r.target for r in by_target] == ["w", "x", "y", "z"]


def test_category_sort_puts_uncategorised_rows_last() -> None:
    graph = make_graph(
        [("a", "1", 1.0, None), ("a", "2", 1.0, "b"), ("a", "3", 1.0, "A"), ("a", "4", 1.0, "a")]
    )
    rows = entries_page(graph, NO_CHOICES, EntriesOptions(sort="category")).rows
    assert [r.target for r in rows] == ["3", "4", "2", "1"]


class Query(NamedTuple):
    q: str | None
    targets: list[str]


QUERIES = [
    Query(None, ["Budget", "Rent", "food", "Fun", "Zoo"]),
    Query("", ["Budget", "Rent", "food", "Fun", "Zoo"]),
    Query("rent", ["Rent"]),
    Query("  RENT  ", ["Rent"]),
    Query("fixed", ["Rent"]),
    Query("FOOD", ["food"]),
    Query("variable", ["food"]),
    Query("sal", ["Budget"]),
    Query("budget", ["Budget", "Rent", "food", "Fun", "Zoo"]),
    Query("fu", ["Fun"]),
    Query("nothing", []),
    Query("xxx", []),
    Query("none", []),
]


@pytest.mark.parametrize("case", QUERIES)
def test_q_matches_source_target_and_category_text_case_insensitively(case: Query) -> None:
    assert [t for _s, t in page(EntriesOptions(q=case.q))] == case.targets


def test_total_counts_every_match_not_only_the_page() -> None:
    result = entries_page(make_graph(LINKS), NO_CHOICES, EntriesOptions(q="budget", limit=2))
    assert len(result.rows) == 2
    assert result.total == 5


def test_only_uncategorized_keeps_rows_without_a_category() -> None:
    result = entries_page(make_graph(LINKS), NO_CHOICES, EntriesOptions(only_uncategorized=True))
    assert [r.target for r in result.rows] == ["Fun", "Zoo"]
    assert result.total == 2
    both = entries_page(
        make_graph(LINKS), NO_CHOICES, EntriesOptions(only_uncategorized=True, q="zoo")
    )
    assert [r.target for r in both.rows] == ["Zoo"]


class Window(NamedTuple):
    offset: int
    limit: int
    expected: tuple[int, int]


WINDOWS = [
    Window(0, 100, (0, 100)),
    Window(5, 10, (5, 10)),
    Window(-1, 10, (0, 10)),
    Window(0, 0, (0, 0)),
    Window(0, -5, (0, 0)),
    Window(0, 1, (0, 1)),
    Window(0, ENTRIES_PAGE_MAX, (0, ENTRIES_PAGE_MAX)),
    Window(0, ENTRIES_PAGE_MAX + 1, (0, ENTRIES_PAGE_MAX)),
    Window(0, 10**6, (0, ENTRIES_PAGE_MAX)),
]


@pytest.mark.parametrize("case", WINDOWS)
def test_window_clamps_offset_and_limit(case: Window) -> None:
    assert EntriesOptions(offset=case.offset, limit=case.limit).window() == case.expected
    assert ENTRIES_PAGE_MAX == 500


class Slice(NamedTuple):
    offset: int
    limit: int
    targets: list[str]


SLICES = [
    Slice(0, 2, ["Budget", "Rent"]),
    Slice(1, 2, ["Rent", "food"]),
    Slice(3, 10, ["Fun", "Zoo"]),
    Slice(4, 1, ["Zoo"]),
    Slice(5, 1, []),
    Slice(99, 5, []),
    Slice(-3, 1, ["Budget"]),
    Slice(0, 0, []),
]


@pytest.mark.parametrize("case", SLICES)
def test_pagination_edges(case: Slice) -> None:
    result = entries_page(
        make_graph(LINKS), NO_CHOICES, EntriesOptions(offset=case.offset, limit=case.limit)
    )
    assert [r.target for r in result.rows] == case.targets
    assert result.total == 5


def test_a_page_never_exceeds_the_page_maximum() -> None:
    graph = make_graph([("a", f"t{i}", 1.0, None) for i in range(ENTRIES_PAGE_MAX + 5)])
    result = entries_page(graph, NO_CHOICES, EntriesOptions(limit=10_000))
    assert len(result.rows) == ENTRIES_PAGE_MAX
    assert result.total == ENTRIES_PAGE_MAX + 5
    tail = entries_page(graph, NO_CHOICES, EntriesOptions(offset=ENTRIES_PAGE_MAX, limit=10_000))
    assert len(tail.rows) == 5


def test_nodes_table_lists_layers_and_flows() -> None:
    rows = nodes_table(budget())
    assert rows[0] == NodeRow("Salary", 0, 0.0, 5000.0)
    assert rows[1] == NodeRow("Budget", 1, 5800.0, 4800.0)
    assert [r.name for r in rows] == list(budget().node_names)
    assert nodes_table(make_graph([])) == []


def test_category_table_mirrors_the_donut_slices() -> None:
    rows = category_table(budget(), style(), "light")
    whole = 12100.0
    assert rows == [
        CategoryRow("Income", CATEGORICAL["light"][0], 5800.0, 5800.0 / whole, "category"),
        CategoryRow("Fixed", CATEGORICAL["light"][1], 2000.0, 2000.0 / whole, "category"),
        CategoryRow("Investing", CATEGORICAL["light"][3], 1500.0, 1500.0 / whole, "category"),
        CategoryRow("Variable", CATEGORICAL["light"][2], 1300.0, 1300.0 / whole, "category"),
        CategoryRow("Uncategorized", UNCATEGORIZED_COLOR, 1500.0, 1500.0 / whole, "uncategorized"),
    ]


def test_category_table_folds_into_one_other_row_with_the_theme_colour() -> None:
    graph = many_categories(10)
    for theme in ("light", "dark"):
        rows = category_table(graph, style(donut={"max_slices": 6}), theme)
        assert [r.kind for r in rows] == ["category"] * 6 + ["other"]
        assert rows[-1].name == "Other"
        assert rows[-1].color == OTHER_COLOR[theme]
        assert rows[-1].value == sum(1000.0 - i for i in range(6, 10))
        assert rows[0].color == CATEGORICAL[theme][0]
        assert sum(r.share for r in rows) == pytest.approx(1.0)


def test_category_table_is_empty_without_a_donut() -> None:
    assert category_table(plain(), style(), "light") == []
    assert category_table(budget(), style(donut={"basis": "initial"}), "light")[0].name == "Income"
    graph = make_graph([("a", "b", 1.0, None), ("b", "c", 1.0, "x")])
    assert category_table(graph, style(donut={"basis": "initial"}), "light") == []


def test_category_table_uses_the_given_colour_map() -> None:
    graph = many_categories(3)
    colors = ColorMap.for_graph(graph, style(category_colors={"cat01": "#0f0f0f"}))
    rows = category_table(graph, style(), "dark", colors)
    assert [r.color for r in rows] == [CATEGORICAL["dark"][0], "#0f0f0f", CATEGORICAL["dark"][2]]


class Main2(NamedTuple):
    links: list[HandLink]
    category: str | None
    value: float
    mixed: bool


A_TO_B = (0, 1)
HAND_MAINS = [
    # a category repeated on parallel links of one pair adds up before the pairs compete
    Main2(
        [HandLink(*A_TO_B, 0, 3.0), HandLink(*A_TO_B, 1, 4.0), HandLink(*A_TO_B, 0, 3.0)],
        "x",
        10.0,
        True,
    ),
    # a tie goes to the lower slot even when the higher slot is listed first
    Main2([HandLink(*A_TO_B, 1, 5.0), HandLink(*A_TO_B, 0, 5.0)], "x", 10.0, True),
    # ... and to a real category over the uncategorised bucket
    Main2([HandLink(*A_TO_B, -1, 5.0), HandLink(*A_TO_B, 0, 5.0)], "x", 10.0, True),
    Main2([HandLink(*A_TO_B, -1, 6.0), HandLink(*A_TO_B, 0, 5.0)], None, 11.0, True),
]


@pytest.mark.parametrize("case", HAND_MAINS, ids=range(len(HAND_MAINS)))
def test_the_main_category_of_hand_built_parallel_links(case: Main2) -> None:
    graph = hand_graph(("A", "B"), case.links, ("x", "y"))
    (row,) = entries_page(graph, NO_CHOICES, EntriesOptions()).rows
    assert (row.category, row.value, row.mixed) == (case.category, case.value, case.mixed)


def test_uncategorised_rows_sort_last_whatever_the_category_text() -> None:
    graph = make_graph(
        [
            ("a", "n", 1.0, None),
            ("a", "m", 2.0, "None"),
            ("a", "z", 3.0, "Zed"),
            ("a", "b", 4.0, "ab"),
        ]
    )
    page = entries_page(graph, NO_CHOICES, EntriesOptions(sort="category"))
    assert [row.category for row in page.rows] == ["ab", "None", "Zed", None]
