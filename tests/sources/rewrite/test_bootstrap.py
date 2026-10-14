"""An empty text becomes a one-entry document in the format of the spec."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceEditRefused
from tests.sources.rewrite.support import add, categorise, reorder

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter


class Case(NamedTuple):
    fields: dict[str, Any]
    edit: Any
    text: str
    fmt: str


CASES = [
    Case({}, add("a", "b", 5), "source,target,value\na,b,5\n", "csv"),
    Case({}, add("a", "b", 5, "K"), "source,target,value,category\na,b,5,K\n", "csv"),
    Case({"format": "csv"}, add("a", "b", 5), "source,target,value\na,b,5\n", "csv"),
    Case({"has_header": False}, add("a", "b", 5), "a,b,5\n", "csv"),
    Case({"has_header": False}, add("a", "b", 5, "K"), "a,b,5,K\n", "csv"),
    Case({"delimiter": ";"}, add("a", "b", 5), "source;target;value\na;b;5\n", "csv"),
    Case({"format": "tsv"}, add("a", "b", 5), "source\ttarget\tvalue\na\tb\t5\n", "tsv"),
    Case({"format": "sankeymatic"}, add("a", "b", 5), "a [5] b\n", "sankeymatic"),
    Case({"format": "sankeymatic"}, add("a", "b", 5, "K"), "a [5] b | K\n", "sankeymatic"),
    Case(
        {"format": "json"},
        add("a", "b", 5),
        '[\n  {\n    "source": "a",\n    "target": "b",\n    "value": 5\n  }\n]\n',
        "json",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[str(i) for i in range(len(CASES))])
@pytest.mark.parametrize("blank", ["", "  \n\n", "\ufeff", "\r\n \t"])
def test_add_on_an_empty_text(rewrite: Rewriter, case: Case, blank: str) -> None:
    done = rewrite(blank, case.edit, **case.fields)
    assert (done.text, done.changed, done.spec.format) == (case.text, 1, case.fmt)


def test_the_category_column_is_named_when_detection_is_off(rewrite: Rewriter) -> None:
    done = rewrite("", add("a", "b", 5, "K"), detect_category=False)
    assert (done.text, done.spec.category_column) == (
        "source,target,value,category\na,b,5,K\n",
        "category",
    )
    done = rewrite("", add("a", "b", 5, "K"), detect_category=False, has_header=False)
    assert (done.text, done.spec.category_column) == ("a,b,5,K\n", 3)


def test_no_pin_is_added_when_detection_finds_the_column(rewrite: Rewriter) -> None:
    assert rewrite("", add("a", "b", 5, "K")).spec.category_column is None


def test_set_category_on_nothing_has_no_match(rewrite: Rewriter) -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite("", categorise("a", "b", "N"))
    assert info.value.reason == "no_match"


def test_reorder_on_nothing_changes_nothing(rewrite: Rewriter) -> None:
    done = rewrite("", reorder("a", "b"))
    assert (done.text, done.changed) == ("", 0)
