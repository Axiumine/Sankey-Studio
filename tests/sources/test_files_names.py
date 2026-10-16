# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Upload filename validation: allow-list, Unicode, lengths and every refusal message."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.errors import SourceError, UnsafeSourceError
from sankey_studio.sources.files import ALLOWED_EXTENSIONS, clean_filename
from sankey_studio.sources.files.names import NAME_MAX_BYTES
from tests.sources.idtools import safe_id

EXTENSIONS_MESSAGE = (
    "only files with these extensions are allowed: .csv, .json, .ndjson, .sankey, .tsv, .txt"
)


def test_the_allow_list() -> None:
    assert {".csv", ".tsv", ".txt", ".json", ".ndjson", ".sankey"} == ALLOWED_EXTENSIONS
    assert NAME_MAX_BYTES == 255


class Name(NamedTuple):
    raw: str
    stored: str


ACCEPTED = [
    Name("a.csv", "a.csv"),
    Name("Report 2024.CSV", "Report 2024.CSV"),
    Name("x.tar.csv", "x.tar.csv"),
    Name("donn\u00e9es.tsv", "donn\u00e9es.tsv"),
    Name("e\u0301.csv", "\u00e9.csv"),  # NFC
    Name("..a.csv", "a.csv"),
    Name(".hidden.json", "hidden.json"),
    Name("X.csv", "X.csv"),  # only dots are stripped from the front, not letters
    Name("..XX.csv", "XX.csv"),
    Name("...x.txt", "x.txt"),
    Name(" lead.csv", " lead.csv"),  # names are not trimmed
    Name("\u65e5\u672c\u8a9e.sankey", "\u65e5\u672c\u8a9e.sankey"),
    *[Name(f"n{ext}", f"n{ext}") for ext in sorted(ALLOWED_EXTENSIONS)],
    *[Name(f"n{ext.upper()}", f"n{ext.upper()}") for ext in sorted(ALLOWED_EXTENSIONS)],
    Name("n.CsV", "n.CsV"),
]


@pytest.mark.parametrize("case", ACCEPTED, ids=[safe_id(repr(c.raw)) for c in ACCEPTED])
def test_accepted_names(case: Name) -> None:
    assert clean_filename(case.raw) == case.stored


class Refused(NamedTuple):
    raw: str
    error: type[SourceError]
    message: str


CONTROL = "filename must not contain control or formatting characters"
SEPARATOR = "filename must be a plain name without path separators"
REFUSED = [
    Refused("a\x00.csv", SourceError, CONTROL),
    Refused("a\n.csv", SourceError, CONTROL),
    Refused("a\t.csv", SourceError, CONTROL),
    Refused("a\x7f.csv", SourceError, CONTROL),
    Refused("a\x85.csv", SourceError, CONTROL),
    Refused("a\u202e.csv", SourceError, CONTROL),  # right-to-left override (Cf)
    Refused("a\u200b.csv", SourceError, CONTROL),  # zero-width space (Cf)
    Refused("a\u2066.csv", SourceError, CONTROL),  # bidi isolate (Cf)
    Refused("a\ufeff.csv", SourceError, CONTROL),
    Refused("\ud800.csv", SourceError, CONTROL),  # lone surrogate (Cs)
    Refused("a/b.csv", UnsafeSourceError, SEPARATOR),
    Refused("../x.csv", UnsafeSourceError, SEPARATOR),
    Refused("/etc/x.csv", UnsafeSourceError, SEPARATOR),
    Refused("a\\b.csv", UnsafeSourceError, SEPARATOR),
    Refused("C:\\fakepath\\x.csv", UnsafeSourceError, SEPARATOR),
    Refused("", SourceError, "filename is empty"),
    Refused(".", SourceError, "filename is empty"),
    Refused("..", SourceError, "filename is empty"),
    Refused("....", SourceError, "filename is empty"),
    Refused("a", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.exe", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.csv.exe", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused(".csv", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.csv.", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.csv ", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.csvx", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.xcsv", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.html", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.py", UnsafeSourceError, EXTENSIONS_MESSAGE),
    Refused("a.part", UnsafeSourceError, EXTENSIONS_MESSAGE),
]


@pytest.mark.parametrize("case", REFUSED, ids=[safe_id(repr(c.raw)) for c in REFUSED])
def test_refused_names(case: Refused) -> None:
    with pytest.raises(case.error) as info:
        clean_filename(case.raw)
    assert type(info.value) is case.error
    assert str(info.value) == case.message


class Size(NamedTuple):
    raw: str
    bytes_: int
    ok: bool


SIZES = [
    Size("x" * 251 + ".csv", 255, True),
    Size("x" * 252 + ".csv", 256, False),
    Size("\u00e9" * 125 + ".csv", 254, True),
    Size("\u00e9" * 126 + ".csv", 256, False),
    Size("\u00e9" * 125 + "x.csv", 255, True),
    Size("\u65e5" * 83 + "xx.csv", 255, True),
    Size("\u65e5" * 84 + ".csv", 256, False),
]


@pytest.mark.parametrize("case", SIZES, ids=[f"{c.bytes_}-{c.ok}-{i}" for i, c in enumerate(SIZES)])
def test_the_name_may_take_255_bytes(case: Size) -> None:
    assert len(case.raw.encode()) == case.bytes_
    if case.ok:
        assert clean_filename(case.raw) == case.raw
        return
    with pytest.raises(SourceError) as info:
        clean_filename(case.raw)
    assert str(info.value) == "filename is longer than 255 bytes"


def test_the_length_is_checked_after_normalisation() -> None:
    # 'e' + combining acute (3 bytes) normalises to one 2-byte character
    raw = "e\u0301" * 125 + ".csv"
    assert len(raw.encode()) > 255
    assert len(clean_filename(raw).encode()) == 125 * 2 + 4
