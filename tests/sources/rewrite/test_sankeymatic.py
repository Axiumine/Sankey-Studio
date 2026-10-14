"""SankeyMATIC rewriting: comments, quoting, value text and indentation survive."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.sources.formats.lines import LINE_MAX
from sankey_studio.sources.rewrite.sankeymatic import quoted
from tests.sources.rewrite.support import add, categorise, reorder

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

TEXT = "// budget\nSalary [3000] Budget\n\n  Budget [1200] Rent | Fixed\n"


class Case(NamedTuple):
    text: str
    edit: Any
    expected: str
    changed: int = 1


CASES = [
    # set / clear / replace a category; value text, indent and comments stay
    Case(
        TEXT,
        categorise("Salary", "Budget", "Income"),
        TEXT.replace("Budget\n\n", "Budget | Income\n\n"),
    ),
    Case(TEXT, categorise("Budget", "Rent", None), TEXT.replace(" | Fixed", "")),
    Case(TEXT, categorise("Budget", "Rent", "Home"), TEXT.replace("Fixed", "Home")),
    Case(TEXT, categorise("Budget", "Rent", "Fixed"), TEXT, 0),
    Case("a [ 1.50 ] b\n", categorise("a", "b", "N"), "a [ 1.50 ] b | N\n"),
    Case("a [1] b\r\nc [2] d\r\n", categorise("c", "d", "N"), "a [1] b\r\nc [2] d | N\r\n"),
    Case("a [1] b", categorise("a", "b", "N"), "a [1] b | N"),
    Case("\ufeffa [1] b\n", categorise("a", "b", "N"), "\ufeffa [1] b | N\n"),
    # names are quoted only when the grammar needs it
    Case('"a [x]" [1] b\n', categorise("a [x]", "b", "N"), '"a [x]" [1] b | N\n'),
    Case('"a ""q"" b" [1] c\n', categorise('a "q" b', "c", "N"), '"a ""q"" b" [1] c | N\n'),
    Case('"x|y" [1] "p]q"\n', categorise("x|y", "p]q", "N"), '"x|y" [1] "p]q" | N\n'),
    # add: appended with the dominant break; the missing final break is added first
    Case(TEXT, add("a", "b", 5), TEXT + "a [5] b\n"),
    Case("a [1] b", add("c", "d", 5, "N"), "a [1] b\nc [5] d | N\n"),
    Case("a [1] b\r\n", add("c", "d", 2.5), "a [1] b\r\nc [2.5] d\r\n"),
    Case("a [1] b\n", add("a [x]", 'q"r', 1), 'a [1] b\n"a [x]" [1] "q""r"\n'),
    Case("a [1] b\n", add("lead", "//x", 1), 'a [1] b\nlead [1] "//x"\n'),
    Case("a [1] b\n", add("é", "ü", 1), "a [1] b\né [1] ü\n"),
    # reorder fills the data slots; comments and blanks stay
    Case(
        "// c\nb [1] c\n\na [2] b\n",
        reorder("a", "b", "c"),
        "// c\na [2] b\n\nb [1] c\n",
        2,
    ),
    Case("b [1] c\na [2] b", reorder("a", "b", "c"), "a [2] b\nb [1] c\n", 2),
    Case("a [1] b\nb [2] c\n", reorder("a", "b", "c"), "a [1] b\nb [2] c\n", 0),
    # lines the parser skips are raw and stay in place
    Case(
        "b [1] c\nnot an entry\na [2] b\nx [oops] y\n",
        reorder("a", "b"),
        "a [2] b\nnot an entry\nb [1] c\nx [oops] y\n",
        2,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[str(i) for i in range(len(CASES))])
def test_sankeymatic_edits(rewrite: Rewriter, case: Case) -> None:
    done = rewrite(case.text, case.edit, format="sankeymatic")
    assert (done.text, done.changed) == (case.expected, case.changed)


def test_the_format_is_found_without_being_told(rewrite: Rewriter) -> None:
    done = rewrite("a [1] b\n", categorise("a", "b", "N"))
    assert done.text == "a [1] b | N\n"


@pytest.mark.parametrize("name", ["a\nb", "a\rb"])
def test_a_name_with_a_line_break_cannot_be_written(rewrite: Rewriter, name: str) -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite("a [1] b\n", add(name, "z", 1), format="sankeymatic")
    assert info.value.reason == "unrepresentable"


def test_a_line_the_parser_would_skip_is_refused(rewrite: Rewriter) -> None:
    text = " " * (LINE_MAX - 20) + "a [1] b\n"  # the indent is kept: the category does not fit
    with pytest.raises(SourceEditRefused) as info:
        rewrite(text, categorise("a", "b", "N" * 30), format="sankeymatic")
    assert info.value.reason == "unsupported_format"


def test_an_overlong_line_is_raw_and_no_match(rewrite: Rewriter) -> None:
    text = f"a [1] b | {'c' * LINE_MAX}\nd [1] e\n"  # the reader drops the whole line
    with pytest.raises(SourceEditRefused) as info:
        rewrite(text, categorise("a", "b", "N"), format="sankeymatic")
    assert info.value.reason == "no_match"


@pytest.mark.parametrize(
    ("name", "quoted_form"),
    [
        ("plain", "plain"),
        ("a b", "a b"),
        (" x", '" x"'),
        ("x ", '"x "'),
        ("//c", '"//c"'),
        ("a//c", "a//c"),
        ("a[b", '"a[b"'),
        ("a]b", '"a]b"'),
        ("a|b", '"a|b"'),
        ('a"b', '"a""b"'),
    ],
)
def test_names_are_quoted_only_when_the_grammar_needs_it(name: str, quoted_form: str) -> None:
    assert quoted(name) == quoted_form
