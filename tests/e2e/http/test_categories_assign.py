"""E2E A.3 (categories): chosen entries, glob rules, precedence, clearing and the donut sums."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import BUDGET, BUDGET_CATEGORISED, graph_draft
from tests.e2e.support.http_a_categories import entries, entry, preview, rule, slices

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer

TOTAL = 8240.0  # the sum of all nine links of the budget sample (donut basis "all")


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: every test here is a pure computation or uses its own names."""
    return module_server


def csv_total(content: str) -> float:
    """The sum of the ``value`` column of a CSV text: what the donut must add up to."""
    rows = csv.DictReader(io.StringIO(content))
    return sum(float(row["value"]) for row in rows)


def assert_donut_adds_up(bundle: dict[str, Any], content: str) -> None:
    """Every slice together is the CSV sum, the shares sum to 1 and the pie shows the same."""
    values = slices(bundle)
    assert sum(values.values()) == pytest.approx(csv_total(content))
    assert sum(row["share"] for row in bundle["categories"]) == pytest.approx(1.0)
    pie = bundle["donut"]["data"][0]
    assert pie["type"] == "pie"
    assert dict(zip(pie["labels"], pie["values"], strict=True)) == pytest.approx(values)


def test_chosen_entries_make_a_donut_with_an_uncategorized_slice(api: httpx.Client) -> None:
    transform = {
        "entry_categories": [entry("Budget", "Rent", "Housing"), entry("Budget", "Food", "Food")]
    }
    bundle = preview(api, BUDGET.csv, transform)
    assert bundle["donut_available"] is True
    assert bundle["donut_empty_reason"] is None
    assert slices(bundle) == {"Housing": 1200.0, "Food": 640.0, "Uncategorized": 6400.0}
    kinds = {row["name"]: row["kind"] for row in bundle["categories"]}
    assert kinds == {"Housing": "category", "Food": "category", "Uncategorized": "uncategorized"}
    assert bundle["category_names"] == ["Housing", "Food"]  # the real ones, in slot order
    assert bundle["stats"]["category_count"] == 2
    assert_donut_adds_up(bundle, BUDGET.csv)


def test_the_entries_table_marks_what_was_chosen(api: httpx.Client) -> None:
    transform = {"entry_categories": [entry("Budget", "Rent", "Housing")]}
    rows = entries(api, BUDGET.csv, transform)
    assert len(rows) == BUDGET.links
    chosen = rows["Budget", "Rent"]
    assert (chosen["category"], chosen["overridden"], chosen["mixed"]) == ("Housing", True, False)
    untouched = rows["Budget", "Food"]
    assert (untouched["category"], untouched["overridden"]) == (None, False)


def test_categories_from_the_data_add_up_to_the_csv_sums(api: httpx.Client) -> None:
    bundle = preview(api, BUDGET_CATEGORISED.csv)
    assert slices(bundle) == dict(BUDGET_CATEGORISED.categories)
    assert bundle["stats"]["category_count"] == len(BUDGET_CATEGORISED.categories)
    assert_donut_adds_up(bundle, BUDGET_CATEGORISED.csv)
    assert sum(slices(bundle).values()) == TOTAL


@dataclass(frozen=True, slots=True)
class RuleCase:
    """Rules on the uncategorised budget and the donut they must produce (None = no donut)."""

    rules: list[dict[str, Any]]
    expected: dict[str, float] | None = field(default=None)


RULES = [
    pytest.param(
        RuleCase([rule("target", "R*", "Rules")], {"Rules": 1340.0, "Uncategorized": 6900.0}),
        id="glob-on-target",
    ),
    pytest.param(
        RuleCase([rule("target", "r*", "Rules")], {"Rules": 1340.0, "Uncategorized": 6900.0}),
        id="case-insensitive",
    ),
    pytest.param(
        RuleCase([rule("source", "Budget", "Spend")], {"Spend": 3800.0, "Uncategorized": 4440.0}),
        id="match-source",
    ),
    pytest.param(
        RuleCase([rule("either", "Food", "Eat")], {"Eat": 1280.0, "Uncategorized": 6960.0}),
        id="match-either",
    ),
    pytest.param(
        RuleCase([rule("target", "Util?ties", "U")], {"U": 260.0, "Uncategorized": 7980.0}),
        id="question-mark",
    ),
    pytest.param(
        RuleCase([rule("target", "[RS]*", "RS")], {"RS": 2810.0, "Uncategorized": 5430.0}),
        id="character-class",
    ),
    pytest.param(
        RuleCase(
            [rule("target", "Rent", "First"), rule("target", "R*", "Second")],
            {"First": 1200.0, "Second": 140.0, "Uncategorized": 6900.0},
        ),
        id="first-rule-wins",
    ),
    pytest.param(RuleCase([rule("either", "zzz*", "Nothing")]), id="matches-nothing"),
]


@pytest.mark.parametrize("case", RULES)
def test_glob_rules_categorise_the_entries_they_match(api: httpx.Client, case: RuleCase) -> None:
    bundle = preview(api, BUDGET.csv, {"category_rules": case.rules})
    if case.expected is None:
        assert (bundle["donut"], bundle["donut_empty_reason"]) == (None, "no_categories")
        return
    assert slices(bundle) == pytest.approx(case.expected)
    assert_donut_adds_up(bundle, BUDGET.csv)


def test_data_beats_rules_unless_the_rules_override(api: httpx.Client) -> None:
    rules = [rule("target", "R*", "Rules")]
    kept = preview(api, BUDGET_CATEGORISED.csv, {"category_rules": rules})
    assert slices(kept) == dict(BUDGET_CATEGORISED.categories)  # the data category stays
    forced = preview(api, BUDGET_CATEGORISED.csv, {"category_rules": rules, "rules_override": True})
    assert slices(forced) == {
        "Income": 3800.0,
        "Savings": 1470.0,
        "Rules": 1340.0,  # Rent 1200 (was Housing) + Restaurants 140 (was Food)
        "Food": 1140.0,
        "Housing": 260.0,
        "Transport": 230.0,
    }
    assert_donut_adds_up(forced, BUDGET_CATEGORISED.csv)


def test_a_chosen_entry_beats_the_data_and_the_rules(api: httpx.Client) -> None:
    transform = {
        "category_rules": [rule("target", "R*", "Rules")],
        "rules_override": True,
        "entry_categories": [entry("Budget", "Rent", "Mine")],
    }
    wide = {"donut": {"max_slices": 8}}  # keep the small slices out of "Other"
    values = slices(preview(api, BUDGET_CATEGORISED.csv, transform, wide))
    assert values["Mine"] == 1200.0
    assert values["Rules"] == 140.0  # only Restaurants is left for the rule
    assert values["Housing"] == 260.0


def test_a_null_category_clears_what_the_data_says(api: httpx.Client) -> None:
    transform = {"entry_categories": [entry("Budget", "Rent", None)]}
    bundle = preview(api, BUDGET_CATEGORISED.csv, transform)
    assert slices(bundle) == {
        "Income": 3800.0,
        "Savings": 1470.0,
        "Food": 1280.0,
        "Housing": 260.0,  # Utilities keeps it, Rent lost it
        "Transport": 230.0,
        "Uncategorized": 1200.0,
    }
    row = entries(api, BUDGET_CATEGORISED.csv, transform)["Budget", "Rent"]
    assert (row["category"], row["overridden"]) == (None, True)
    assert_donut_adds_up(bundle, BUDGET_CATEGORISED.csv)


def test_a_null_category_also_beats_a_rule_that_overrides(api: httpx.Client) -> None:
    transform = {
        "category_rules": [rule("either", "*", "Everything")],
        "rules_override": True,
        "entry_categories": [entry("Budget", "Rent", None)],
    }
    assert slices(preview(api, BUDGET.csv, transform)) == pytest.approx(
        {"Everything": TOTAL - 1200.0, "Uncategorized": 1200.0}
    )


def test_clearing_every_category_removes_the_donut_again(api: httpx.Client) -> None:
    pairs = list(entries(api, BUDGET_CATEGORISED.csv))
    transform = {"entry_categories": [entry(source, target, None) for source, target in pairs]}
    bundle = preview(api, BUDGET_CATEGORISED.csv, transform)
    assert (bundle["donut"], bundle["donut_available"]) == (None, False)
    assert bundle["donut_empty_reason"] == "no_categories"
    assert bundle["stats"]["category_count"] == 0
    refused = api.post(
        "/api/v1/export",
        params={"chart": "donut", "format": "csv"},
        json=graph_draft(BUDGET_CATEGORISED.csv, transform=transform),
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "no_categories"


def test_an_entry_that_matches_nothing_is_a_warning_not_an_error(api: httpx.Client) -> None:
    transform = {
        "entry_categories": [entry("Nobody", "Nothing", "X"), entry("budget", "RENT", "Y")]
    }
    bundle = preview(api, BUDGET.csv, transform)
    assert bundle["donut_available"] is False
    assert bundle["warnings"] == ["2 entry_categories matched no entry"]


def test_more_categories_than_slices_fold_into_other_without_losing_value(
    api: httpx.Client,
) -> None:
    rows = "\n".join(f"A,T{i},{i + 1},Cat{i}" for i in range(10))
    content = f"source,target,value,category\n{rows}\n"
    bundle = preview(api, content)
    shown = bundle["categories"]
    # max_slices is 6 and only the first 8 categories get a hue: the other 4 (Cat0 and Cat1 are
    # the smallest hue ones, Cat8 and Cat9 have no hue left) fold into one "Other" slice.
    assert [row["name"] for row in shown] == [*(f"Cat{i}" for i in range(7, 1, -1)), "Other"]
    assert [row["kind"] for row in shown] == ["category"] * 6 + ["other"]
    assert shown[-1]["value"] == 1 + 2 + 9 + 10
    assert len(bundle["category_names"]) == 10  # all of them stay available for the editor
    assert sum(row["value"] for row in shown) == csv_total(content)
    assert_donut_adds_up(bundle, content)
