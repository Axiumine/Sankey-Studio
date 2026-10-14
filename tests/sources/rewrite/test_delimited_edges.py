"""csv/tsv rewriting: refusals, raw records, pins and untouched bytes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.sources.formats.csv_rows import RECORD_MAX_CHARS
from sankey_studio.sources.formats.lines import LINE_MAX
from tests.sources.rewrite.support import add, categorise

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

HEAD = "source,target,value"
LONG = "n" * (LINE_MAX - 10)


class Refused(NamedTuple):
    text: str
    edit: Any
    reason: str
    fields: dict[str, Any] | None = None


REFUSALS = [
    Refused(f"{HEAD}\na,b,1\n", categorise("x", "y", "N"), "no_match"),
    Refused(f"{HEAD}\n", categorise("a", "b", "N"), "no_match"),
    Refused("", categorise("a", "b", "N"), "no_match"),
    # a pair whose rows the parser skips is not there
    Refused(f"{HEAD}\na,b,oops\n", categorise("a", "b", "N"), "no_match"),
    Refused(f"{HEAD}\na,b\n", categorise("a", "b", "N"), "no_match"),  # short record
    # the text does not load: a named column that is not there
    Refused(f"{HEAD}\na,b,1\n", categorise("a", "b", "N"), "unreadable", {"source_column": "nope"}),
    # one field beyond the field limit
    Refused(f'{HEAD}\n"{"x" * 3000}\n{"x" * 3000}",b,1\n', categorise("a", "b", "N"), "unreadable"),
    # a record longer than the record budget
    Refused(
        f'{HEAD}\n"' + ("x" * 4000 + "\n") * (RECORD_MAX_CHARS // 4000 + 1) + '",b,1\n',
        categorise("a", "b", "N"),
        "unreadable",
    ),
    # a header-less text of a header format: no header record to extend
    Refused(",,\n,\n", add("x", "y", 1), "unreadable"),
    # a line the reader would skip
    Refused(
        f"{HEAD},note\na,b,1,{LONG}\n",
        categorise("a", "b", "C" * 50),
        "unsupported_format",
    ),
]


@pytest.mark.parametrize("case", REFUSALS, ids=[str(i) for i in range(len(REFUSALS))])
def test_refusals(rewrite: Rewriter, case: Refused) -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite(case.text, case.edit, **(case.fields or {}))
    assert info.value.reason == case.reason


def test_a_record_with_an_overlong_line_is_never_rewritten(rewrite: Rewriter) -> None:
    # The reader drops the overlong line, so re-emitting the record would delete it.
    text = f'{HEAD},note\na,b,1,"x\n{"z" * (LINE_MAX + 1)}\ny"\nc,d,2,\n'
    with pytest.raises(SourceEditRefused) as info:
        rewrite(text, categorise("a", "b", "N"))
    assert info.value.reason == "no_match"
    done = rewrite(text, categorise("c", "d", "N"))
    assert done.text.startswith(f'{HEAD},note,category\na,b,1,"x\n{"z" * (LINE_MAX + 1)}\ny"\n')
    assert done.text.endswith("c,d,2,,N\n")


def test_overlong_lines_and_skipped_rows_stay_byte_for_byte(rewrite: Rewriter) -> None:
    junk = "z" * (LINE_MAX + 5)
    text = f"{HEAD}\n{junk}\n  \n,,\nx,y,oops\na,b,1\n"
    done = rewrite(text, categorise("a", "b", "N"))
    assert done.text == f"{HEAD},category\n{junk}\n  \n,,\nx,y,oops\na,b,1,N\n"


def test_the_line_breaks_inside_a_quoted_cell_are_kept(rewrite: Rewriter) -> None:
    text = f'{HEAD},note\r\na,b,1,"x\r\ny"\r\n'
    done = rewrite(text, categorise("a", "b", "N"))
    # a quoted cell is read through universal newlines: its break is a plain one afterwards
    assert done.text == f'{HEAD},note,category\r\na,b,1,"x\ny",N\r\n'


def test_a_text_with_only_a_header_takes_a_new_row(rewrite: Rewriter) -> None:
    assert rewrite(HEAD, add("a", "b", 2)).text == f"{HEAD}\na,b,2\n"


def test_the_category_pin_names_the_new_column_when_detection_is_off(rewrite: Rewriter) -> None:
    done = rewrite(f"{HEAD}\na,b,1\n", categorise("a", "b", "N"), detect_category=False)
    assert done.text == f"{HEAD},category\na,b,1,N\n"
    assert done.spec.category_column == "category"


def test_an_existing_category_header_that_detection_ignores_is_pinned_by_index(
    rewrite: Rewriter,
) -> None:
    text = f"{HEAD},category\na,b,1,x\n"
    done = rewrite(text, categorise("a", "b", "N"), detect_category=False)
    assert done.text == f"{HEAD},category,category\na,b,1,x,N\n"
    assert done.spec.category_column == 4


def test_the_headerless_pin_is_the_fourth_column_when_detection_is_off(rewrite: Rewriter) -> None:
    done = rewrite("a,b,1\n", categorise("a", "b", "N"), has_header=False, detect_category=False)
    assert (done.text, done.spec.category_column) == ("a,b,1,N\n", 3)


def test_the_headerless_pin_moves_after_a_pick_on_the_fourth_column(rewrite: Rewriter) -> None:
    fields: dict[str, Any] = {"has_header": False, "value_column": 3}
    done = rewrite("a,b,x,1\n", categorise("a", "b", "N"), **fields)
    assert (done.text, done.spec.category_column) == ("a,b,x,1,N\n", 4)


def test_the_rewritten_spec_is_the_job_spec_when_nothing_was_pinned(rewrite: Rewriter) -> None:
    done = rewrite(f"{HEAD}\na,b,1\n", add("x", "y", 1), format="csv")
    assert done.spec.format == "csv"
    assert done.spec.category_column is None
    assert done.spec.content == "x"  # the caller stores the text; the spec keeps its content
