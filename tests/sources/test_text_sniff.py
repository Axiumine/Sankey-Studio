"""``detect_format`` and ``sniff_delimiter``: the 4 KB window and the tie-breaks."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.sources.formats import detect_format, sniff_delimiter
from sankey_studio.sources.formats.sniff import (
    DEFAULT_DELIMITER,
    DELIMITERS,
    SNIFF_CHARS,
    SNIFF_LINES,
)
from tests.sources.idtools import safe_id


class Sample(NamedTuple):
    text: str
    expected: str


FORMATS = [
    Sample('[{"source": "a", "target": "b", "value": 1}]', "json"),
    Sample('{"source": "a"}\n{"source": "b"}', "json"),
    Sample('  \n\t {"a": 1}', "json"),
    Sample("\ufeff[1]", "json"),
    Sample("a [5] b", "sankeymatic"),
    Sample("// comment\n\nWages [1,234.5] Budget | income", "sankeymatic"),
    Sample('"x [y]" [5] z', "sankeymatic"),
    Sample("   a [5] b   ", "sankeymatic"),
    Sample("source,target,value\na,b,1", "csv"),
    Sample("source;target;value\na;b;1", "csv"),
    Sample("source|target|value\na|b|1", "csv"),
    Sample("source\ttarget\tvalue\na\tb\t1", "tsv"),
    Sample("a,b\tc", "csv"),  # a tie goes to the earlier candidate
    Sample("a\tb\tc,d", "tsv"),
    Sample("just words", "csv"),
    Sample("", "csv"),
    Sample("   \n  ", "csv"),
    Sample("x [bad\ny,z", "csv"),  # the first entry-looking line is not an entry
    Sample("// only a comment", "csv"),
    Sample("\ufeffa\tb", "tsv"),
]


@pytest.mark.parametrize("case", FORMATS, ids=[safe_id(repr(c.text)[:28]) for c in FORMATS])
def test_detect_format_table(case: Sample) -> None:
    assert detect_format(case.text) == case.expected


def test_detect_format_only_looks_at_the_first_4096_characters() -> None:
    assert SNIFF_CHARS == 4096
    assert detect_format(" " * 4095 + "[1]") == "json"  # the bracket is character 4096
    assert detect_format(" " * 4096 + "[1]") == "csv"  # character 4097 is out of sight
    assert detect_format("a" * 4094 + ",b,c") == "csv"
    assert detect_format("a" * 4095 + "\t") == "tsv"  # the tab is inside the window
    assert detect_format("a" * 4096 + "\t") == "csv"  # the tab is outside


DELIMITER_TABLE = [
    Sample("a,b,c\n1,2,3", ","),
    Sample("a;b;c\n1;2;3", ";"),
    Sample("a\tb\tc\n1\t2\t3", "\t"),
    Sample("a|b|c\n1|2|3", "|"),
    Sample("abc", ","),
    Sample("", ","),
    Sample("\n\n", ","),
    Sample("\ufeffa;b", ";"),
    # the delimiter that splits most lines the same way wins, not the most frequent one
    Sample("a,b;c\nd,e;f\ng;h", ";"),
    Sample("a,b,c,d\nx;y\np;q\nr;s", ","),  # the first line sets the expected column count
    # equal consistency: more delimiters in the first line wins
    Sample("a,b;c;d\nx,y\np;q;r", ";"),
    # equal everything: the earlier candidate wins
    Sample("a,b;c", ","),
    Sample("a;b|c", ";"),
    Sample("a|b\tc", "\t"),
    Sample("only,one\n", ","),
]


@pytest.mark.parametrize(
    "case", DELIMITER_TABLE, ids=[safe_id(repr(c.text)[:28]) for c in DELIMITER_TABLE]
)
def test_sniff_delimiter_table(case: Sample) -> None:
    assert sniff_delimiter(case.text) == case.expected


def test_sniff_constants() -> None:
    assert DELIMITERS == (",", ";", "\t", "|")
    assert DEFAULT_DELIMITER == ","
    assert SNIFF_LINES == 20


def test_sniff_delimiter_looks_at_20_lines_at_most() -> None:
    head = "a,b;c;d\n" + "x,y\n" * 10  # comma: 11 lines; semicolon: 1 so far
    body = "p;q;r\n" * 10  # lines 12..21
    assert sniff_delimiter(head + body) == ","  # line 21 is not read: 10 < 11
    assert sniff_delimiter(head + "p;q;r\n" * 9) == ","
    # one line fewer of comma evidence and the 21st line would flip it; the 20-line cap decides
    assert sniff_delimiter("a,b;c;d\n" + "x,y\n" * 9 + "p;q;r\n" * 11) == ";"


def test_sniff_delimiter_window_is_4096_characters() -> None:
    assert sniff_delimiter("x" * 4095 + ";") == ";"
    assert sniff_delimiter("x" * 4096 + ";") == ","
