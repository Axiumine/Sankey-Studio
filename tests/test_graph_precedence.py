"""``build_graph``: the category precedence (entry choice > data > rules) and rule matching."""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest

from sankey_studio.graph.categories import rule_tables
from sankey_studio.models import CategoryRule
from tests.graph_support import make_graph, rows


class Case(NamedTuple):
    data: str | None
    rule: str | None
    entry: str | bool | None  # False = no entry choice, None = force uncategorised
    override: bool
    expected: str | None


def transform_of(case: Case) -> dict[str, Any]:
    fields: dict[str, Any] = {"rules_override": case.override}
    if case.rule is not None:
        fields["category_rules"] = [{"match": "either", "pattern": "A", "category": case.rule}]
    if case.entry is not False:
        fields["entry_categories"] = [{"source": "A", "target": "B", "category": case.entry}]
    return fields


PRECEDENCE = [
    Case("D", None, False, False, "D"),
    Case(None, "R", False, False, "R"),
    Case(None, None, "E", False, "E"),
    Case("D", "R", False, False, "D"),
    Case("D", "R", False, True, "R"),
    Case("D", None, False, True, "D"),
    Case(None, "R", False, True, "R"),
    Case("D", None, "E", False, "E"),
    Case(None, "R", "E", False, "E"),
    Case("D", "R", "E", False, "E"),
    Case("D", "R", "E", True, "E"),
    Case("D", None, None, False, None),
    Case(None, "R", None, False, None),
    Case("D", "R", None, False, None),
    Case("D", "R", None, True, None),
    Case(None, None, None, False, None),
]


@pytest.mark.parametrize("case", PRECEDENCE)
def test_precedence_table(case: Case) -> None:
    graph = make_graph([("A", "B", 1.0, case.data)], **transform_of(case))
    assert rows(graph) == [("A", "B", 1.0, case.expected)]


def test_an_entry_choice_applies_to_every_row_of_the_pair_and_only_to_it() -> None:
    graph = make_graph(
        [("A", "B", 1.0, "x"), ("A", "B", 2.0, "y"), ("A", "C", 4.0, "x"), ("B", "A", 8.0, "x")],
        entry_categories=[{"source": "A", "target": "B", "category": "E"}],
        on_cycle="break",
    )
    assert rows(graph) == [("A", "B", 3.0, "E"), ("A", "C", 4.0, "x")]


def test_the_data_spelling_wins_over_a_rule_or_entry_spelling() -> None:
    graph = make_graph(
        [("A", "B", 1.0, "food"), ("A", "C", 1.0, None), ("D", "E", 1.0, None)],
        category_rules=[{"match": "source", "pattern": "D", "category": "FOOD"}],
        entry_categories=[{"source": "A", "target": "C", "category": "Food"}],
    )
    assert graph.categories == ("food",)
    assert [row[3] for row in rows(graph)] == ["food", "food", "food"]


def test_entry_choices_match_post_merge_names_exactly() -> None:
    graph = make_graph(
        [("Old", "B", 1.0, None), ("a", "b", 1.0, None)],
        merge_nodes={"Old": "New"},
        entry_categories=[
            {"source": "Old", "target": "B", "category": "X"},
            {"source": "New", "target": "B", "category": "Y"},
            {"source": "A", "target": "B", "category": "Z"},
            {"source": "a", "target": "b", "category": "W"},
        ],
    )
    assert rows(graph) == [("New", "B", 1.0, "Y"), ("a", "b", 1.0, "W")]
    assert graph.warnings == ("2 entry_categories matched no entry",)


@pytest.mark.parametrize(
    ("entries", "warning"),
    [
        ([("A", "B", "x")], None),
        ([("B", "A", "x")], "1 entry_categories matched no entry"),
        ([("A", "Q", "x")], "1 entry_categories matched no entry"),
        ([("Q", "B", "x"), ("A", "Q", "y")], "2 entry_categories matched no entry"),
        (
            [("A", "B", "x"), ("B", "A", "y"), ("Q", "Q", "z")],
            "2 entry_categories matched no entry",
        ),
    ],
)
def test_unmatched_entry_choices_are_counted_in_one_warning(
    entries: list[tuple[str, str, str]], warning: str | None
) -> None:
    graph = make_graph(
        [("A", "B", 1.0, None)],
        entry_categories=[{"source": s, "target": t, "category": c} for s, t, c in entries],
    )
    assert graph.warnings == (() if warning is None else (warning,))


class RuleCase(NamedTuple):
    match: str
    pattern: str
    source: str
    target: str
    hit: bool


RULES = [
    RuleCase("source", "Sal*", "Salary", "Budget", True),
    RuleCase("source", "Sal*", "Budget", "Salary", False),
    RuleCase("target", "Sal*", "Budget", "Salary", True),
    RuleCase("target", "Sal*", "Salary", "Budget", False),
    RuleCase("either", "Sal*", "Salary", "Budget", True),
    RuleCase("either", "Sal*", "Budget", "Salary", True),
    RuleCase("either", "Sal*", "Budget", "Rent", False),
    RuleCase("source", "salary", "SALARY", "x", True),
    RuleCase("source", "SALARY", "salary", "x", True),
    RuleCase("source", "R?nt", "Rent", "x", True),
    RuleCase("source", "R?nt", "Rnt", "x", False),
    RuleCase("source", "R?nt", "Rental", "x", False),
    RuleCase("source", "[RT]ent", "Tent", "x", True),
    RuleCase("source", "[RT]ent", "Vent", "x", False),
    RuleCase("source", "Rent", "Rent 2", "x", False),
    RuleCase("source", "Rent", "My Rent", "x", False),
    RuleCase("source", "*", "anything", "x", True),
    RuleCase("source", "a.c", "abc", "x", False),
    RuleCase("source", "a.c", "a.c", "x", True),
    RuleCase("source", "(a+)+$", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!", "x", False),
]


@pytest.mark.parametrize("case", RULES)
def test_rule_matching_table(case: RuleCase) -> None:
    graph = make_graph(
        [(case.source, case.target, 1.0, None)],
        category_rules=[{"match": case.match, "pattern": case.pattern, "category": "R"}],
    )
    assert rows(graph)[0][3] == ("R" if case.hit else None)


def test_the_first_matching_rule_wins_across_sides() -> None:
    rules = [
        {"match": "target", "pattern": "T*", "category": "first"},
        {"match": "source", "pattern": "S*", "category": "second"},
        {"match": "either", "pattern": "*", "category": "third"},
    ]
    graph = make_graph(
        [("S1", "T1", 1.0, None), ("S2", "X", 1.0, None), ("Y", "Z", 1.0, None)],
        category_rules=rules,
    )
    assert [row[3] for row in rows(graph)] == ["first", "second", "third"]


def test_rule_tables_hold_the_first_match_per_node_and_side() -> None:
    rules = [
        CategoryRule(match="source", pattern="a*", category="r0"),
        CategoryRule(match="either", pattern="*b", category="r1"),
        CategoryRule(match="target", pattern="*", category="r2"),
    ]
    by_source, by_target = rule_tables(rules, ["ab", "xb", "q", "ax"])
    assert by_source == [0, 1, -1, 0]
    assert by_target == [1, 1, 2, 2]


def test_rules_override_ranks_rules_above_data_but_below_entries() -> None:
    rules = [{"match": "either", "pattern": "A", "category": "R"}]
    graph = make_graph(
        [("A", "B", 1.0, "D"), ("A", "C", 1.0, "D")],
        category_rules=rules,
        rules_override=True,
        entry_categories=[{"source": "A", "target": "C", "category": "E"}],
    )
    assert [row[3] for row in rows(graph)] == ["R", "E"]


def test_entries_re_merge_when_two_data_categories_collapse_into_one() -> None:
    graph = make_graph(
        [("A", "B", 1.0, "x"), ("A", "B", 2.0, "y"), ("A", "B", 4.0, None), ("A", "C", 8.0, "x")],
        category_rules=[{"match": "either", "pattern": "B", "category": "R"}],
        rules_override=True,
    )
    assert rows(graph) == [("A", "B", 7.0, "R"), ("A", "C", 8.0, "x")]
    assert graph.categories == ("R", "x")
    assert graph.category_color_slot == (0, 1)


def test_an_entry_choice_clearing_a_category_merges_with_the_uncategorised_entry() -> None:
    graph = make_graph(
        [("A", "B", 1.0, "x"), ("A", "B", 2.0, None)],
        entry_categories=[{"source": "A", "target": "B", "category": None}],
    )
    assert rows(graph) == [("A", "B", 3.0, None)]
    assert graph.categories == ()
