"""csv/tsv rewriting: add_entry and reorder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from tests.sources.rewrite.support import add, reorder

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

HEAD = "source,target,value"
HEADC = "source,target,value,category"


class Case(NamedTuple):
    text: str
    edit: Any
    expected: str
    fields: dict[str, Any] | None = None


ADD = [
    Case(f"{HEAD}\na,b,1\n", add("x", "y", 5), f"{HEAD}\na,b,1\nx,y,5\n"),
    Case(
        f"{HEAD}\na,b,1", add("x", "y", 5), f"{HEAD}\na,b,1\nx,y,5\n"
    ),  # the missing break is added
    Case(f"{HEAD}\r\na,b,1\r\n", add("x", "y", 5), f"{HEAD}\r\na,b,1\r\nx,y,5\r\n"),
    Case(f"{HEAD}\r\na,b,1", add("x", "y", 5), f"{HEAD}\r\na,b,1\r\nx,y,5\r\n"),
    Case(f"\ufeff{HEAD}\na,b,1\n", add("x", "y", 5), f"\ufeff{HEAD}\na,b,1\nx,y,5\n"),
    Case(f"{HEAD}\n", add("x", "y", 5), f"{HEAD}\nx,y,5\n"),
    Case(f"{HEADC}\na,b,1,K\n", add("x", "y", 5, "Fun"), f"{HEADC}\na,b,1,K\nx,y,5,Fun\n"),
    Case(f"{HEADC}\na,b,1,K\n", add("x", "y", 5), f"{HEADC}\na,b,1,K\nx,y,5,\n"),  # full width
    Case(f"{HEAD}\na,b,1\n", add("x", "y", 5, "Fun"), f"{HEADC}\na,b,1\nx,y,5,Fun\n"),
    Case("value,source,target\n1,a,b\n", add("x", "y", 5), "value,source,target\n1,a,b\n5,x,y\n"),
    Case("a,b,1\n", add("x", "y", 5), "a,b,1\nx,y,5\n", {"has_header": False}),
    Case("a,b,1\n", add("x", "y", 5, "Fun"), "a,b,1\nx,y,5,Fun\n", {"has_header": False}),
    Case("a;b;1\n", add("x", "y", 5), "a;b;1\nx;y;5\n", {"has_header": False}),
    Case(
        "a\tb\t1\n", add("x", "y", 5), "a\tb\t1\nx\ty\t5\n", {"has_header": False, "format": "tsv"}
    ),
    Case(
        "a,b,1\n",
        add("x", "y", 5, "Fun"),
        "a,b,1\nx,y,5,,Fun\n",
        {"has_header": False, "category_column": 4},
    ),
    # names that need quoting; unicode stays as it is
    Case(f"{HEAD}\n", add("a,b", 'q"r', 1), f'{HEAD}\n"a,b","q""r",1\n'),
    Case(f"{HEAD}\n", add("café", "über", 1), f"{HEAD}\ncafé,über,1\n"),
]


@pytest.mark.parametrize("case", ADD, ids=[str(i) for i in range(len(ADD))])
def test_add_entry(rewrite: Rewriter, case: Case) -> None:
    done = rewrite(case.text, case.edit, **(case.fields or {}))
    assert (done.text, done.changed) == (case.expected, 1)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (5.0, "5"),
        (3000.0, "3000"),
        (0.5, "0.5"),
        (1e-07, "1e-07"),
        (0.1 + 0.2, "0.30000000000000004"),
        (999999999999999.0, "999999999999999"),
        (1e15, "1000000000000000.0"),
        (1e22, "1e+22"),
        (1234567.89, "1234567.89"),
    ],
)
def test_the_value_is_written_as_the_parsers_read_it_back(
    rewrite: Rewriter, value: float, text: str
) -> None:
    assert rewrite(f"{HEAD}\n", add("x", "y", value)).text == f"{HEAD}\nx,y,{text}\n"


REORDER = [
    Case(f"{HEAD}\nb,c,1\na,b,2\n", reorder("a", "b", "c"), f"{HEAD}\na,b,2\nb,c,1\n"),
    # header and blank lines never move; rows fill the same slots
    Case(
        f"{HEAD}\nb,c,1\n\na,b,2\n",
        reorder("a", "b", "c"),
        f"{HEAD}\na,b,2\n\nb,c,1\n",
    ),
    # unknown names go last, ties keep the file order
    Case(
        f"{HEAD}\nz,y,1\nb,c,2\nx,w,3\na,b,4\n",
        reorder("a", "b", "c"),
        f"{HEAD}\na,b,4\nb,c,2\nz,y,1\nx,w,3\n",
    ),
    Case(f"{HEAD}\nb,x,1\nb,a,2\n", reorder("b", "a"), f"{HEAD}\nb,a,2\nb,x,1\n"),
    # a row the parser skips stays in its slot
    Case(
        f"{HEAD}\nb,c,1\nx,y,oops\na,b,2\n",
        reorder("a", "b", "c"),
        f"{HEAD}\na,b,2\nx,y,oops\nb,c,1\n",
    ),
    # the row without a final break that moves gets one
    Case(f"{HEAD}\nb,c,1\na,b,2", reorder("a", "b", "c"), f"{HEAD}\na,b,2\nb,c,1\n"),
    Case(f"{HEAD}\r\nb,c,1\r\na,b,2", reorder("a", "b", "c"), f"{HEAD}\r\na,b,2\r\nb,c,1\r\n"),
]


@pytest.mark.parametrize("case", REORDER, ids=[str(i) for i in range(len(REORDER))])
def test_reorder(rewrite: Rewriter, case: Case) -> None:
    done = rewrite(case.text, case.edit, **(case.fields or {}))
    assert done.text == case.expected
    assert done.changed >= 2  # a swap moves at least two rows


def test_reorder_counts_the_rows_that_moved(rewrite: Rewriter) -> None:
    text = f"{HEAD}\nb,c,1\na,b,2\nz,y,3\n"
    done = rewrite(text, reorder("a", "b", "c"))
    assert (done.text, done.changed) == (f"{HEAD}\na,b,2\nb,c,1\nz,y,3\n", 2)


@pytest.mark.parametrize("order", [("a", "b", "c"), ("a", "b"), ()])
def test_a_reorder_that_moves_nothing_returns_the_text_unchanged(
    rewrite: Rewriter, order: tuple[str, ...]
) -> None:
    text = f"{HEAD}\na,b,1\nb,c,2"  # no final break: nothing moves, so nothing is added
    done = rewrite(text, reorder(*order))
    assert (done.text, done.changed) == (text, 0)


def test_a_reorder_merges_names_through_the_alias(rewrite: Rewriter) -> None:
    text = f"{HEAD}\nB1,c,1\na,B1,2\n"
    done = rewrite(text, reorder("a", "B", "c"), alias={"B1": "B"})
    assert done.text == f"{HEAD}\na,B1,2\nB1,c,1\n"
