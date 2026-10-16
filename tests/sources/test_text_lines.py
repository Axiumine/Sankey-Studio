# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``LineReader``: bounded lines, BOM, newlines and decode errors."""

from __future__ import annotations

import io
from typing import NamedTuple

import pytest

from sankey_studio.errors import SourceError
from sankey_studio.sources.formats.lines import (
    BOM,
    LINE_MAX,
    Line,
    LineReader,
    decode_error,
    located_decode_error,
)
from tests.sources.idtools import safe_id


def reader(text: str, limit: int = 5) -> LineReader:
    return LineReader(io.StringIO(text), limit, "t")


def test_the_limit_is_4096_characters() -> None:
    assert LINE_MAX == 4096
    assert BOM == "\ufeff"


class Boundary(NamedTuple):
    text: str
    expected: list[Line]


# limit 5: a line may hold 5 characters, its newline does not count
BOUNDARY = [
    Boundary("12345\n", [Line(1, "12345\n", overlong=False)]),
    Boundary("12345", [Line(1, "12345", overlong=False)]),
    Boundary("123456\n", [Line(1, "12345", overlong=True)]),
    Boundary("123456", [Line(1, "12345", overlong=True)]),
    Boundary("1234567\n", [Line(1, "12345", overlong=True)]),
    Boundary(
        "x" * 23 + "\nok\n", [Line(1, "xxxxx", overlong=True), Line(2, "ok\n", overlong=False)]
    ),
    Boundary("x" * 10 + "\nok", [Line(1, "xxxxx", overlong=True), Line(2, "ok", overlong=False)]),
    Boundary(
        "x" * 6 + "\n\nok\n",
        [
            Line(1, "xxxxx", overlong=True),
            Line(2, "\n", overlong=False),
            Line(3, "ok\n", overlong=False),
        ],
    ),
    Boundary("", []),
    Boundary("\n", [Line(1, "\n", overlong=False)]),
    Boundary("a\nb\n", [Line(1, "a\n", overlong=False), Line(2, "b\n", overlong=False)]),
]


@pytest.mark.parametrize("case", BOUNDARY, ids=[safe_id(repr(c.text)[:24]) for c in BOUNDARY])
def test_line_limit_boundary(case: Boundary) -> None:
    assert list(reader(case.text).lines()) == case.expected


def test_number_is_the_last_line_read() -> None:
    lines = reader("a\nb\nc\n")
    assert lines.number == 0
    it = lines.lines()
    next(it)
    assert lines.number == 1
    next(it)
    assert lines.number == 2


def test_an_overlong_line_is_drained_without_being_held() -> None:
    huge = "y" * 100_000
    out = list(reader(huge + "\nnext\n", limit=LINE_MAX).lines())
    assert [(line.number, line.overlong) for line in out] == [(1, True), (2, False)]
    assert out[0].text == "y" * LINE_MAX
    assert out[1].text == "next\n"


def test_the_default_limit_boundary_is_4096_content_characters() -> None:
    fits = "a" * LINE_MAX + "\n"
    too_long = "a" * (LINE_MAX + 1) + "\n"
    out = list(LineReader(io.StringIO(fits + too_long + "z\n"), LINE_MAX, "t").lines())
    assert [line.overlong for line in out] == [False, True, False]
    assert out[0].text == fits


def test_bom_is_dropped_from_the_first_line_only() -> None:
    out = list(reader(f"{BOM}a,b\n{BOM}c\n", limit=50).lines())
    assert [line.text for line in out] == ["a,b\n", f"{BOM}c\n"]


def test_a_lone_bom_leaves_an_empty_line() -> None:
    assert list(reader(BOM, limit=50).lines()) == [Line(1, "", overlong=False)]


# the BOM is dropped BEFORE the budget applies: every case above behaves the same behind a BOM
BOM_BOUNDARY = [Boundary(BOM + case.text, case.expected) for case in BOUNDARY if case.text]


@pytest.mark.parametrize(
    "case", BOM_BOUNDARY, ids=[safe_id(repr(c.text)[:24]) for c in BOM_BOUNDARY]
)
def test_the_line_limit_boundary_behind_a_bom(case: Boundary) -> None:
    assert list(reader(case.text).lines()) == case.expected


def test_a_bom_line_cannot_smuggle_its_tail_into_the_next_row() -> None:
    out = list(reader(BOM + "abcde" + "EVIL\nok\n").lines())
    assert out == [Line(1, "abcde", overlong=True), Line(2, "ok\n", overlong=False)]


def test_the_topped_up_character_is_not_lost() -> None:
    out = list(reader(BOM + "abcde\nnext\n").lines())
    assert out == [Line(1, "abcde\n", overlong=False), Line(2, "next\n", overlong=False)]


def test_universal_newlines_come_from_the_text_wrapper() -> None:
    wrapper = io.TextIOWrapper(io.BytesIO(b"a\r\nb\rc"), encoding="utf-8", errors="strict")
    out = list(LineReader(wrapper, 50, "t").lines())
    assert [line.text for line in out] == ["a\n", "b\n", "c"]


def wrapped(data: bytes, encoding: str = "utf-8") -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(data), encoding=encoding, errors="strict")


def decode_message(data: bytes, encoding: str = "utf-8", limit: int = 50) -> str:
    with pytest.raises(SourceError) as info:
        list(LineReader(wrapped(data, encoding), limit, "d").lines())
    return str(info.value)


class Located(NamedTuple):
    data: bytes
    line: int
    encoding: str = "utf-8"


BLOCK = b"abcdefg\n" * 1024  # exactly one 8192-byte block of 1024 lines
LOCATED = [
    Located(b"\xff\n", 1),
    Located(b"ok\n\xff\xfe\n", 2),
    Located(b"a\nb\n\xff\n", 3),
    Located(b"a\nbc\xffd\n", 2),
    Located(b"a\r\nb\r\n\xff\r\n", 3),
    Located(b"a\rb\r\xff\r", 3),
    Located(b"a\n\n\n\xff", 4),
    Located(b"ok\n" * 4000 + b"\xff\n", 4001),
    Located(b"ok\n" * 4000 + b"x\ny\n\xff\n", 4003),
    Located(BLOCK + b"\xff\n", 1025),
    Located(BLOCK + b"\n\xff\n", 1026),
    Located(b"a" * 8191 + b"\r" + b"\n\xff", 2),
    Located(b"x" * 8191 + b"\xe2" + b"(\n", 1),
    Located(b"a\nb\n\x81c\n", 3, "cp1252"),
    Located(b"a\nb\n\xe9c\n", 3, "ascii"),
    Located(b"\xef\xbb\xbfa\nb\n\xff", 3, "utf-8-sig"),
]


@pytest.mark.parametrize(
    "case", LOCATED, ids=[safe_id(f"{c.encoding}-{c.line}-{c.data[-6:]!r}") for c in LOCATED]
)
def test_a_decode_error_names_the_real_line(case: Located) -> None:
    expected = f"d:{case.line}: cannot decode the data as {case.encoding}"
    assert decode_message(case.data, case.encoding, limit=50) == expected


def test_the_first_bad_line_is_named_whatever_follows_it() -> None:
    assert decode_message(b"ok\n\xff\n\xfe\n") == "d:2: cannot decode the data as utf-8"


def test_the_label_is_part_of_the_message() -> None:
    wrapper = wrapped(b"ok\n\xff\xfe\n")
    with pytest.raises(SourceError) as info:
        list(LineReader(wrapper, 50, "data.csv").lines())
    assert str(info.value) == "data.csv:2: cannot decode the data as utf-8"


def test_a_decode_error_after_the_first_block_names_a_later_line() -> None:
    good = b"ok\n" * 4000  # 12000 bytes: the decoder reads 8192-byte blocks
    lines = LineReader(wrapped(good + b"\xff\n"), 50, "d")
    with pytest.raises(SourceError) as info:
        list(lines.lines())
    assert lines.number == 2730  # the error comes while line 2731 is read
    assert str(info.value) == "d:4001: cannot decode the data as utf-8"


class Drained(NamedTuple):
    data: bytes
    line: int


# limit 10: the first line is overlong, the error comes while the rest of it is drained
DRAINED = [
    Drained(b"x" * 20_000 + b"\xff\n", 1),
    Drained(b"x" * 20_000 + b"\nok\n\xff\n", 3),
    Drained(b"x" * 20_000 + b"\n\n\n\n\n\n\xff\n", 7),
]


@pytest.mark.parametrize("case", DRAINED, ids=[str(c.line) for c in DRAINED])
def test_a_decode_error_while_draining_names_the_line_being_drained(case: Drained) -> None:
    expected = f"d:{case.line}: cannot decode the data as utf-8"
    assert decode_message(case.data, limit=10) == expected


def test_a_decode_error_while_topping_up_behind_a_bom_counts_from_the_first_line() -> None:
    # BOM + 8189 characters fill the first 8192-byte block exactly; the top-up reads the next
    head = BOM.encode() + b"x" * 8189
    assert decode_message(head + b"\xff", limit=8189) == "d:1: cannot decode the data as utf-8"
    assert decode_message(head + b"\n\n\xff", limit=8189) == "d:3: cannot decode the data as utf-8"


UTF16 = "a\nb\n".encode("utf-16") + b"\xff\xd8"  # a lone high surrogate at the end


def test_an_encoding_whose_blocks_cannot_be_scanned_says_at_or_after() -> None:
    expected = "d:3: cannot decode the data as utf-16 (at or after this line)"
    assert decode_message(UTF16, "utf-16") == expected


def test_the_decode_error_helpers_format_their_messages() -> None:
    assert str(decode_error("f.csv", 7, "utf-32")) == (
        "f.csv:7: cannot decode the data as utf-32 (at or after this line)"
    )
    exc = UnicodeDecodeError("utf-8", b"a\nb\xff", 3, 4, "invalid start byte")
    assert str(located_decode_error("f.csv", 10, exc, "utf-8")) == (
        "f.csv:11: cannot decode the data as utf-8"
    )
    assert str(located_decode_error("f.csv", 10, exc, "utf-16")) == (
        "f.csv:10: cannot decode the data as utf-16 (at or after this line)"
    )
    assert str(located_decode_error("f.csv", 10, exc, "utf-8-sig")) == (
        "f.csv:11: cannot decode the data as utf-8-sig"
    )
