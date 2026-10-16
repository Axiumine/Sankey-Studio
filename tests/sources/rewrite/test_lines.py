# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Physical lines, BOM and line breaks of the rewriter."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.errors import SourceEditRefused
from sankey_studio.sources.formats.lines import LINE_MAX
from sankey_studio.sources.rewrite.lines import (
    check_line_length,
    dominant_eol,
    eol_of,
    peel_bom,
    split_physical,
    without_eol,
)

BOM = chr(0xFEFF)
#: VT, FF, NEL, LS and PS: parts of a line for the parsers (not for ``str.splitlines``).
ODD = "a\x0bb\x0cc\x85d" + chr(0x2028) + "e" + chr(0x2029) + "f\n"


class Split(NamedTuple):
    text: str
    lines: list[str]


SPLITS = [
    Split("", []),
    Split("a", ["a"]),
    Split("a\n", ["a\n"]),
    Split("a\r\nb\rc\nd", ["a\r\n", "b\r", "c\n", "d"]),
    Split("\n\n", ["\n", "\n"]),
    Split("\r\n\r\n", ["\r\n", "\r\n"]),
    # only \r, \n and \r\n end a line: VT, FF, NEL and the Unicode separators stay inside
    Split(ODD, [ODD]),
]


@pytest.mark.parametrize("case", SPLITS, ids=[repr(c.text) for c in SPLITS])
def test_split_physical_keeps_every_character(case: Split) -> None:
    assert split_physical(case.text) == case.lines
    assert "".join(split_physical(case.text)) == case.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [(f"{BOM}a", (BOM, "a")), ("a", ("", "a")), (BOM, (BOM, "")), (f"a{BOM}", ("", f"a{BOM}"))],
)
def test_peel_bom(text: str, expected: tuple[str, str]) -> None:
    assert peel_bom(text) == expected


@pytest.mark.parametrize(
    ("line", "eol"),
    [("a\r\n", "\r\n"), ("a\n", "\n"), ("a\r", "\r"), ("a", ""), ("", ""), ("\n", "\n")],
)
def test_eol_of_and_without_eol(line: str, eol: str) -> None:
    assert eol_of(line) == eol
    assert without_eol(line) == line.removesuffix(eol)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "\n"),
        ("no break", "\n"),
        ("a\nb\n", "\n"),
        ("a\r\nb\r\n", "\r\n"),
        ("a\rb\r", "\r"),
        ("a\r\nb\r\nc\n", "\r\n"),
        ("a\nb\nc\r\n", "\n"),
        ("a\r\nb\n", "\n"),  # a tie goes to the line feed
        ("a\r\nb\r", "\r\n"),  # ... then to CRLF
    ],
)
def test_dominant_eol(text: str, expected: str) -> None:
    assert dominant_eol(text) == expected


@pytest.mark.parametrize(
    ("chunk", "refused"),
    [
        ("a" * LINE_MAX, False),
        ("a" * LINE_MAX + "\n", False),  # the break is not counted
        ("a" * LINE_MAX + "\r\n", False),
        ("a" * (LINE_MAX + 1), True),
        ("a" * (LINE_MAX + 1) + "\n", True),
        ("ok\n" + "a" * (LINE_MAX + 1), True),  # any line of a multi-line chunk
        ("", False),
    ],
)
def test_check_line_length_matches_the_reader_limit(chunk: str, refused: bool) -> None:
    if not refused:
        check_line_length(chunk)
        return
    with pytest.raises(SourceEditRefused) as info:
        check_line_length(chunk)
    assert info.value.reason == "unsupported_format"
