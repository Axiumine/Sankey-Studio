"""SankeyMATIC-style text: entries, categories, quoted names, comments and malformed lines."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.lines import LINE_MAX
from sankey_studio.sources.formats.sankeymatic import COMMENT, Entry, split_entry
from sankey_studio.sources.formats.values import RowError
from tests.sources.idtools import safe_id
from tests.sources.text_support import inline

if TYPE_CHECKING:
    from collections.abc import Callable

    from sankey_studio.sources.base import SourceContext

    Ctx = Callable[..., SourceContext]


def test_the_comment_marker() -> None:
    assert COMMENT == "//"


class Split(NamedTuple):
    text: str
    entry: Entry


SPLITS = [
    Split("a [5] b", Entry("a", "b", "5", None)),
    Split("Xavier [5] Xerox | X", Entry("Xavier", "Xerox", "5", "X")),
    Split('a [5] "b"   ', Entry("a", "b", "5", None)),
    Split('a [5] "b"  |  c  ', Entry("a", "b", "5", "c")),
    Split("a[5]b", Entry("a", "b", "5", None)),
    Split(
        "  Big   Source  [ 12.5 ]  Some Target  ",
        Entry("Big   Source", "Some Target", " 12.5 ", None),
    ),
    Split("a [5] b | food", Entry("a", "b", "5", "food")),
    Split("a [5] b|food", Entry("a", "b", "5", "food")),
    Split("a [5] b |", Entry("a", "b", "5", None)),
    Split("a [5] b |   ", Entry("a", "b", "5", None)),
    Split("a [5] b | x | y", Entry("a", "b", "5", "x | y")),
    Split('a [5] b | "quoted"', Entry("a", "b", "5", '"quoted"')),
    Split('"a [x]" [5] "b | c"', Entry("a [x]", "b | c", "5", None)),
    Split('"say ""hi"""[5]b', Entry('say "hi"', "b", "5", None)),
    Split('"" [5] b', Entry("", "b", "5", None)),
    Split('a [5] "b" | c', Entry("a", "b", "5", "c")),
    Split("a [1,234.5] b", Entry("a", "b", "1,234.5", None)),
    Split("a [] b", Entry("a", "b", "", None)),
    Split("a [x [y] b", Entry("a", "b", "x [y", None)),
    Split('a "q" [5] b', Entry('a "q"', "b", "5", None)),  # a quote only opens a name at its start
]


@pytest.mark.parametrize("case", SPLITS, ids=[safe_id(repr(c.text)) for c in SPLITS])
def test_split_entry(case: Split) -> None:
    assert split_entry(case.text) == case.entry


class Malformed(NamedTuple):
    text: str
    message: str


UNEXPECTED = "unexpected text after the target name (quote names that contain brackets)"
MALFORMED = [
    Malformed("a b c", "expected '[value]' after the source name"),
    Malformed("a | b [5] c", "expected '[value]' after the source name"),
    Malformed("a ] b", "expected '[value]' after the source name"),
    Malformed("a [5 b", "missing ']'"),
    Malformed('"a [5] b', "a quoted name is missing its closing quote"),
    Malformed('a [5] "b', "a quoted name is missing its closing quote"),
    Malformed('"a" x [5] b', "expected '[value]' after the source name"),
    Malformed("a [5] b [c]", UNEXPECTED),
    Malformed("a [5] b ] c", UNEXPECTED),
    Malformed('a [5] "b" c', UNEXPECTED),
    Malformed("", "expected '[value]' after the source name"),
]


@pytest.mark.parametrize("case", MALFORMED, ids=[safe_id(repr(c.text)) for c in MALFORMED])
def test_split_entry_names_what_is_wrong(case: Malformed) -> None:
    with pytest.raises(RowError) as info:
        split_entry(case.text)
    assert str(info.value) == case.message


def test_entries_comments_and_blank_lines(source_ctx: SourceContext) -> None:
    text = (
        "// a title\n"
        "\n"
        "Wages [1000] Budget | income\n"
        "   // an indented comment\n"
        "Budget [400.5] Rent\n"
        "Budget [599.5] Food | needs\n"
        "\n"
    )
    out = inline(source_ctx, text, format="sankeymatic")
    assert out.rows == [
        ("Wages", "Budget", 1000.0, "income"),
        ("Budget", "Rent", 400.5, None),
        ("Budget", "Food", 599.5, "needs"),
    ]
    assert out.warnings == []


def test_the_format_is_found_by_sniffing(source_ctx: SourceContext) -> None:
    out = inline(source_ctx, "a [1] b\nb [1] c | z\n")
    assert out.rows == [("a", "b", 1.0, None), ("b", "c", 1.0, "z")]


def test_quoted_names_and_crlf_and_bom(source_ctx: SourceContext) -> None:
    text = '\ufeff"in [x]" [5] "out | y"\r\nplain [2] other\r\n'
    out = inline(source_ctx, text)
    assert out.rows == [("in [x]", "out | y", 5.0, None), ("plain", "other", 2.0, None)]


class Bad(NamedTuple):
    line: str
    warning: str


BAD_LINES = [
    Bad("a [x] b", "inline:2: value must be a positive number"),
    Bad("a [0] b", "inline:2: value must be a positive number"),
    Bad("a [-1] b", "inline:2: value must be a positive number"),
    Bad("a [nan] b", "inline:2: value must be a positive number"),
    Bad("a [] b", "inline:2: value is empty"),
    Bad("[5] b", "inline:2: source is empty"),
    Bad("a [5]", "inline:2: target is empty"),
    Bad("a b", "inline:2: expected '[value]' after the source name"),
    Bad("a [5 b", "inline:2: missing ']'"),
    Bad('a [5] "b', "inline:2: a quoted name is missing its closing quote"),
    Bad("a [5] b [c]", f"inline:2: {UNEXPECTED}"),
    Bad("x" * 201 + " [5] b", "inline:2: source is longer than 200 characters"),
]


@pytest.mark.parametrize("case", BAD_LINES, ids=[c.warning.split(": ", 1)[1] for c in BAD_LINES])
def test_a_bad_line_is_skipped_with_a_numbered_warning(
    source_ctx: SourceContext, case: Bad
) -> None:
    out = inline(source_ctx, f"a [1] b\n{case.line}\nc [2] d\n", format="sankeymatic")
    assert out.rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]
    assert out.warnings == [case.warning]
    assert out.skipped == 1


def test_a_bad_line_raises_in_strict_mode(make_source_ctx: Ctx) -> None:
    with pytest.raises(SourceError) as info:
        inline(make_source_ctx(strict=True), "a [1] b\nnonsense\n", format="sankeymatic")
    assert str(info.value) == "inline:2: expected '[value]' after the source name"


@pytest.mark.parametrize(("extra", "kept"), [(0, True), (1, False)], ids=["4096", "4097"])
def test_a_line_over_4096_characters_is_skipped_before_parsing(
    source_ctx: SourceContext, extra: int, kept: bool
) -> None:
    category = "c" * (LINE_MAX - len("a [1] b | ") + extra)
    line = f"a [1] b | {category}"
    assert len(line) == LINE_MAX + extra
    out = inline(source_ctx, f"{line}\nx [2] y\n", format="sankeymatic")
    if kept:
        assert [row[:3] for row in out.rows] == [("a", "b", 1.0), ("x", "y", 2.0)]
        assert out.warnings == [
            "Categories ignored (entries kept uncategorised): 1 longer than 100 characters"
        ]
    else:
        assert out.rows == [("x", "y", 2.0, None)]
        assert out.warnings == ["inline:1: line is longer than 4096 characters, skipped"]


@pytest.mark.parametrize(("extra", "kept"), [(0, True), (1, False)], ids=["4096", "4097"])
def test_the_line_limit_counts_after_a_bom(
    source_ctx: SourceContext, extra: int, kept: bool
) -> None:
    category = "c" * (LINE_MAX - len("a [1] b | ") + extra)
    out = inline(source_ctx, f"\ufeffa [1] b | {category}\nx [2] y\n", format="sankeymatic")
    if kept:
        assert [row[:3] for row in out.rows] == [("a", "b", 1.0), ("x", "y", 2.0)]
    else:
        assert out.rows == [("x", "y", 2.0, None)]
        assert out.warnings == ["inline:1: line is longer than 4096 characters, skipped"]


def test_a_bracket_flood_stays_fast_and_bounded(source_ctx: SourceContext) -> None:
    out = inline(
        source_ctx, "[" * 4000 + "\n" + "a [1] b\n" + '"' * 4000 + "\n", format="sankeymatic"
    )
    assert out.rows == [("a", "b", 1.0, None)]
    assert out.skipped == 2
