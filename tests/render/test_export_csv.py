"""CSV export and the OWASP guard against formula injection."""

from __future__ import annotations

import csv
import io
from typing import NamedTuple

import pytest

from sankey_studio.errors import NoCategoriesError
from sankey_studio.render.export import csv_cell, export_csv
from sankey_studio.util import starts_like_formula
from tests.graph_support import make_graph
from tests.render.support import budget, plain


class Cell(NamedTuple):
    raw: str
    guarded: bool


CELLS = [
    Cell("=1+1", True),
    Cell("+1", True),
    Cell("-1", True),
    Cell("@SUM(A1)", True),
    Cell(" =1", True),
    Cell("  +1", True),
    Cell("\t=1", True),
    Cell("\r=1", True),
    Cell("\n=1", True),
    Cell(" \t\r\n@x", True),
    Cell("\t5", True),
    Cell("\rabc", True),
    Cell("=", True),
    Cell("-", True),
    Cell("=cmd|' /C calc'!A0", True),
    Cell('=HYPERLINK("http://evil.example","x")', True),
    Cell("a=1", False),
    Cell("a+b", False),
    Cell("5-3", False),
    Cell("x@y", False),
    Cell("'=1", False),
    Cell("Food", False),
    Cell("", False),
    Cell("   ", False),
    Cell("é=", False),
    Cell("1.5", False),
    # only space, tab, CR and LF count as leading blanks; other whitespace hides nothing
    Cell("\x0b=1", False),
    Cell("\x0c+1", False),
    Cell("\xa0@x", False),
    Cell("\u2003-1", False),
]


@pytest.mark.parametrize("case", CELLS)
def test_owasp_payload_table(case: Cell) -> None:
    assert csv_cell(case.raw) == ("'" + case.raw if case.guarded else case.raw)


@pytest.mark.parametrize("case", CELLS)
def test_the_guard_is_the_shared_formula_predicate(case: Cell) -> None:
    assert starts_like_formula(case.raw) is case.guarded


def parse(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_sankey_csv_has_one_row_per_link() -> None:
    rows = parse(export_csv(budget(), chart="sankey", basis="all"))
    assert rows[0] == ["source", "target", "value", "category"]
    assert rows[1] == ["Salary", "Budget", "5000.0", "Income"]
    assert rows[6] == ["Budget", "Savings", "1500.0", ""]
    assert len(rows) == 1 + budget().n_links


def test_donut_csv_has_category_value_share() -> None:
    rows = parse(export_csv(budget(), chart="donut", basis="all"))
    assert rows[0] == ["category", "value", "share"]
    assert rows[1] == ["Income", "5800.0", repr(5800.0 / 12100.0)]
    assert [r[0] for r in rows[1:]] == [
        "Income",
        "Fixed",
        "Variable",
        "Investing",
        "Uncategorized",
    ]
    assert [r[1] for r in rows[1:]] == ["5800.0", "2000.0", "1300.0", "1500.0", "1500.0"]


def test_donut_csv_follows_the_basis() -> None:
    rows = parse(export_csv(budget(), chart="donut", basis="initial"))
    assert rows == [["category", "value", "share"], ["Income", "5800.0", "1.0"]]


def test_donut_csv_without_categories_is_no_categories() -> None:
    with pytest.raises(NoCategoriesError) as caught:
        export_csv(plain(), chart="donut", basis="all")
    assert caught.value.message == "No entry has a category, so there is no donut chart"
    assert export_csv(plain(), chart="sankey", basis="all").startswith(
        "source,target,value,category\n"
    )


def test_every_text_cell_is_guarded_in_both_charts() -> None:
    graph = make_graph([("=src", "+tgt", 1.0, "-cat"), ("@a", "\tb", 2.0, " =c")])
    sankey = parse(export_csv(graph, chart="sankey", basis="all"))
    assert sankey[1] == ["'=src", "'+tgt", "1.0", "'-cat"]
    assert sankey[2] == ["'@a", "'\tb", "2.0", "'=c"]
    donut = parse(export_csv(graph, chart="donut", basis="all"))
    assert [row[0] for row in donut[1:]] == ["'-cat", "'=c"]


def test_commas_quotes_and_newlines_are_quoted_not_split() -> None:
    graph = make_graph([('a,"b"', "c\nd", 1.0, "e,f")])
    text = export_csv(graph, chart="sankey", basis="all")
    assert parse(text)[1] == ['a,"b"', "c\nd", "1.0", "e,f"]
    assert text.endswith("\n")
    assert "\r" not in text


def test_numbers_are_not_guarded() -> None:
    graph = make_graph([("a", "b", 1e-7, None)])
    assert parse(export_csv(graph, chart="sankey", basis="all"))[1][2] == "1e-07"
