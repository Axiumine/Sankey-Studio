# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Format and delimiter sniffing on a bounded sample (the UI 'detect' button uses it too)."""

from __future__ import annotations

from typing import Literal

from sankey_studio.sources.formats.lines import BOM
from sankey_studio.sources.formats.sankeymatic import COMMENT, split_entry
from sankey_studio.sources.formats.values import RowError

#: Sniffing looks at no more than this many characters.
SNIFF_CHARS = 4096
#: ...and at no more than this many non-blank lines of them.
SNIFF_LINES = 20
DEFAULT_DELIMITER = ","
#: Candidate delimiters; on a tie the earlier one wins, so the default also wins when none fits.
DELIMITERS = (DEFAULT_DELIMITER, ";", "\t", "|")

ParsedFormat = Literal["csv", "tsv", "sankeymatic", "json"]


def _head(sample: str) -> str:
    return sample.removeprefix(BOM)[:SNIFF_CHARS]


def _data_lines(sample: str) -> list[str]:
    lines = [line for line in _head(sample).splitlines() if line.strip()]
    return lines[:SNIFF_LINES]


def _consistency(lines: list[str], delimiter: str) -> tuple[int, int]:
    """(lines with as many delimiters as the first line, delimiters in the first line)."""
    first = lines[0].count(delimiter) if lines else 0
    if first == 0:
        return 0, 0
    return sum(1 for line in lines if line.count(delimiter) == first), first


def sniff_delimiter(sample: str) -> str:
    """The delimiter that splits the most lines into the same number of columns."""
    lines = _data_lines(sample)
    return max(DELIMITERS, key=lambda delimiter: _consistency(lines, delimiter))


def _starts_like_sankeymatic(sample: str) -> bool:
    """True when the first entry-looking line parses as ``Source [value] Target``."""
    for line in _data_lines(sample):
        text = line.strip()
        if text.startswith(COMMENT):
            continue
        try:
            split_entry(text)
        except RowError:
            return False
        return True
    return False


def detect_format(text_sample: str) -> ParsedFormat:
    """Guess the format of ``text_sample`` (only its first 4 KB are looked at).

    JSON starts with ``[`` or ``{``; ``Source [12] Target`` lines are SankeyMATIC; anything else
    is delimited text, ``tsv`` when tabs split the lines best and ``csv`` otherwise.
    """
    head = _head(text_sample)
    if head.lstrip()[:1] in ("[", "{"):
        return "json"
    if _starts_like_sankeymatic(head):
        return "sankeymatic"
    return "tsv" if sniff_delimiter(head) == "\t" else "csv"
