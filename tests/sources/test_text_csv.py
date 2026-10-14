"""csv/tsv parsing: delimiters, quoting, blank rows, row problems and hostile input."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.csv_rows import CATEGORY_HEADER, DEFAULT_COLUMNS
from sankey_studio.sources.formats.lines import BOM, LINE_MAX
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext

    Ctx = Callable[..., SourceContext]


def test_defaults() -> None:
    assert DEFAULT_COLUMNS == (("source", 0), ("target", 1), ("value", 2))
    assert CATEGORY_HEADER == "category"


def test_a_plain_csv_with_a_header(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "source,target,value\na,b,1\nb,c,2.5\n", format="csv")
    assert out.rows == [("a", "b", 1.0, None), ("b", "c", 2.5, None)]
    assert out.warnings == []
    assert out.skipped == 0


class Delim(NamedTuple):
    content: str
    fields: dict[str, Any]
    first_row: tuple[str, str, float, str | None]


DELIMITERS = [
    Delim("source;target;value\na;b;1", {}, ("a", "b", 1.0, None)),
    Delim("source\ttarget\tvalue\na\tb\t1", {"format": "csv"}, ("a", "b", 1.0, None)),
    Delim("source|target|value\na|b|1", {}, ("a", "b", 1.0, None)),
    Delim("source\ttarget\tvalue\na\tb\t1", {"format": "tsv"}, ("a", "b", 1.0, None)),
    Delim("source\ttarget\tvalue\na\tb\t1", {}, ("a", "b", 1.0, None)),
    # an explicit delimiter is honoured verbatim, whatever the format says
    Delim("source target value\na b 1", {"delimiter": " "}, ("a", "b", 1.0, None)),
    Delim("source,target,value\na,b,1", {"format": "tsv", "delimiter": ","}, ("a", "b", 1.0, None)),
    Delim("source|target|value\na|b|1", {"delimiter": "|", "format": "csv"}, ("a", "b", 1.0, None)),
    Delim("source;target;value\na;b;1", {"delimiter": ";", "format": "tsv"}, ("a", "b", 1.0, None)),
]


def test_the_tsv_format_means_tabs_even_when_commas_would_be_sniffed(
    source_ctx: SourceContext,
) -> None:
    out = inline(source_ctx, "a,b,c,d\te\t5\n", format="tsv", has_header=False)
    assert out.rows == [("a,b,c,d", "e", 5.0, None)]
    sniffed = inline(source_ctx, "a,b,c,d\te\t5\n", format="csv", has_header=False)
    assert sniffed.skipped == 1  # the csv format sniffs the comma and finds 'c' as the value


@pytest.mark.parametrize("case", DELIMITERS, ids=[str(i) for i in range(len(DELIMITERS))])
def test_delimiters(source_ctx: SourceContext, case: Delim) -> None:
    out = inline(source_ctx, case.content, **case.fields)
    assert out.rows[0] == case.first_row
    assert out.warnings == []


def test_a_leading_tab_is_not_stripped_from_the_text(source_ctx: SourceContext) -> None:
    fields = {"delimiter": "\t", "has_header": False}
    columns = {"source_column": 1, "target_column": 2, "value_column": 3}
    out = inline(source_ctx, "\tA\tB\t3\n", **fields, **columns)
    assert out.rows == [("A", "B", 3.0, None)]


def test_columns_by_position_without_a_header(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "a,b,1\nc,d,2\n", has_header=False, format="csv")
    assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]


def test_the_header_row_is_not_data(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "source,target,value\n", format="csv")
    assert out.rows == []
    assert out.warnings == []


def test_empty_text_yields_nothing(source_ctx: SourceContext) -> None:
    assert inline(source_ctx, "").rows == []
    assert inline(source_ctx, "\n\n  \n", format="csv").rows == []
    assert inline(source_ctx, "", format="csv", has_header=False).rows == []


def test_blank_lines_and_empty_rows_are_skipped_silently_but_counted_in_line_numbers(
    source_ctx: SourceContext,
) -> None:
    text = "\n\nsource,target,value\n\na,b,1\n , , \n,,\nc,d,x\n"
    out = inline(source_ctx, text, format="csv")
    assert out.rows == [("a", "b", 1.0, None)]
    assert out.warnings == ["inline:8: value must be a positive number"]
    assert out.skipped == 1


def test_byte_order_mark_and_crlf(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "\ufeffsource,target,value\r\na,b,1\r\nc,d,2\r\n")
    assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]


def test_quoted_fields(source_ctx: SourceContext) -> None:
    text = 'source,target,value\n"Food, drink","say ""hi""",5\n"two\nlines",x,1\n'
    out = inline(source_ctx, text, format="csv")
    assert out.rows == [("Food, drink", 'say "hi"', 5.0, None), ("two\nlines", "x", 1.0, None)]


def test_names_are_stripped_and_thousands_separators_work(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "source;target;value\n  a b ; c ;1,234.5\nd;e;1,234,567\n")
    assert out.rows == [("a b", "c", 1234.5, None), ("d", "e", 1234567.0, None)]


class Problem(NamedTuple):
    content: str
    warning: str


PROBLEMS = [
    Problem("source,target,value\na,b,abc", "inline:2: value must be a positive number"),
    Problem("source,target,value\na,b,0", "inline:2: value must be a positive number"),
    Problem("source,target,value\na,b,-3", "inline:2: value must be a positive number"),
    Problem("source,target,value\na,b,nan", "inline:2: value must be a positive number"),
    Problem("source,target,value\na,b,inf", "inline:2: value must be a positive number"),
    Problem("source,target,value\na,b,", "inline:2: value is empty"),
    Problem("source,target,value\na,b", "inline:2: value is missing"),
    Problem("source,target,value\na", "inline:2: target is missing"),
    Problem("source,target,value\n,b,1", "inline:2: source is empty"),
    Problem("source,target,value\na,,1", "inline:2: target is empty"),
    Problem(
        "source,target,value\n " + "x" * 201 + ",b,1",
        "inline:2: source is longer than 200 characters",
    ),
    Problem(
        "source,target,value\na," + "x" * 201 + ",1",
        "inline:2: target is longer than 200 characters",
    ),
    Problem("source,target,value\na\0,b,1", "inline:2: source contains a NUL character"),
]


@pytest.mark.parametrize("case", PROBLEMS, ids=[c.warning.split(": ", 1)[1] for c in PROBLEMS])
def test_row_problems_skip_the_row_with_a_numbered_warning(
    source_ctx: SourceContext, case: Problem
) -> None:
    out = inline(source_ctx, case.content + "\nok,fine,1\n", format="csv")
    assert out.rows == [("ok", "fine", 1.0, None)]
    assert out.warnings == [case.warning]
    assert out.skipped == 1


def test_the_longest_allowed_name_is_kept(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "source,target,value\n" + "x" * 200 + ",y,1\n")
    assert out.rows == [("x" * 200, "y", 1.0, None)]


def test_strict_mode_raises_on_the_first_problem(make_source_ctx: Ctx) -> None:
    ctx = make_source_ctx(strict=True)
    with pytest.raises(SourceError) as info:
        inline(ctx, "source,target,value\na,b,1\nc,d,oops\ne,f,2\n", format="csv")
    assert str(info.value) == "inline:3: value must be a positive number"


class Long(NamedTuple):
    extra: int
    kept: bool


@pytest.mark.parametrize("case", [Long(0, True), Long(1, False)], ids=["4096", "4097"])
def test_a_line_over_4096_characters_is_skipped_with_a_warning(
    source_ctx: SourceContext, case: Long
) -> None:
    pad = "x" * (LINE_MAX - len("a,b,1,") + case.extra)
    line = f"a,b,1,{pad}"
    assert len(line) == LINE_MAX + case.extra
    out = inline(source_ctx, f"source,target,value\n{line}\nc,d,2\n", format="csv")
    if case.kept:
        assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]
        assert out.warnings == []
    else:
        assert out.rows == [("c", "d", 2.0, None)]
        assert out.warnings == ["inline:2: line is longer than 4096 characters, skipped"]
        assert out.skipped == 1


@pytest.mark.parametrize("case", [Long(0, True), Long(1, False)], ids=["4096", "4097"])
def test_the_line_limit_counts_after_a_bom(source_ctx: SourceContext, case: Long) -> None:
    pad = "x" * (LINE_MAX - len("a,b,1,") + case.extra)
    line = f"a,b,1,{pad}"
    assert len(line) == LINE_MAX + case.extra
    tail = "" if case.kept else "EVIL,x,9"  # the tail of an overlong line is never a row
    text = f"{BOM}{line}{tail}\nc,d,2\n"  # no header: the BOM'd first line is data
    out = inline(source_ctx, text, format="csv", has_header=False, detect_category=False)
    if case.kept:
        assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]
        assert out.warnings == []
    else:
        assert out.rows == [("c", "d", 2.0, None)]
        assert out.warnings == ["inline:1: line is longer than 4096 characters, skipped"]
        assert out.skipped == 1


def test_an_overlong_line_is_an_error_in_strict_mode(make_source_ctx: Ctx) -> None:
    ctx = make_source_ctx(strict=True)
    text = "source,target,value\n" + "z" * 5000 + "\n"
    with pytest.raises(
        SourceError, match=r"^inline:2: line is longer than 4096 characters, skipped$"
    ):
        inline(ctx, text, format="csv")


class Field(NamedTuple):
    size: int
    fits: bool


@pytest.mark.parametrize("case", [Field(4096, True), Field(4097, False)], ids=["4096", "4097"])
def test_a_field_over_4096_characters_is_a_source_error(
    source_ctx: SourceContext, case: Field
) -> None:
    first = "x" * 2000
    second = "y" * (case.size - len(first) - 1)  # the newline inside the field counts
    text = f'source,target,value\na,b,1,"{first}\n{second}"\nc,d,2\n'  # an unused 4th column
    if case.fits:
        out = inline(source_ctx, text, format="csv")
        assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]
    else:
        with pytest.raises(SourceError) as info:
            inline(source_ctx, text, format="csv")
        assert str(info.value) == (
            "inline:3: invalid CSV data (field larger than field limit (4096))"
        )


def test_an_unterminated_quote_cannot_swallow_the_file(source_ctx: SourceContext) -> None:
    text = 'source,target,value\n"open,b,1\n' + "a,b,1\n" * 2000
    with pytest.raises(SourceError, match=r"^inline:\d+: invalid CSV data \(field larger"):
        inline(source_ctx, text, format="csv")


def test_the_row_stream_is_lazy(source_ctx: SourceContext) -> None:
    from sankey_studio.models import TextSource
    from sankey_studio.sources import open_source
    from sankey_studio.sources.base import Diagnostics

    spec = TextSource(content="source,target,value\na,b,1\nc,d,x\n", format="csv")
    diag = Diagnostics()
    rows = open_source(spec, source_ctx).iter_links(diag)
    assert diag.skipped == 0
    assert next(rows) == ("a", "b", 1.0, None)
    assert diag.skipped == 0  # the bad row has not been read yet
    assert list(rows) == []
    assert diag.skipped == 1
