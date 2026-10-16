# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Parser internals whose results the public API hides (they decide ties, not outcomes)."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.sources.formats.sankeymatic import _Scanner
from sankey_studio.sources.formats.sniff import _consistency
from sankey_studio.sources.formats.values import RowError
from tests.sources.idtools import safe_id


class Consistency(NamedTuple):
    lines: list[str]
    delimiter: str
    expected: tuple[int, int]


CONSISTENCY = [
    Consistency([], ",", (0, 0)),
    Consistency(["abc"], ",", (0, 0)),
    Consistency(["a;b"], ",", (0, 0)),
    Consistency(["a,b"], ",", (1, 1)),
    Consistency(["a,b", "c,d", "e"], ",", (2, 1)),
    Consistency(["a,b,c", "a,b", "x,y,z"], ",", (2, 2)),
    Consistency(["a,b,c", "a,b,c,d", "a,b,c"], ",", (2, 2)),
    Consistency(["a\tb", "c\td"], "\t", (2, 1)),
]


@pytest.mark.parametrize("case", CONSISTENCY, ids=[safe_id(repr(c.lines)) for c in CONSISTENCY])
def test_consistency_counts_the_lines_that_split_like_the_first(case: Consistency) -> None:
    assert _consistency(case.lines, case.delimiter) == case.expected


def test_until_may_stop_at_the_very_first_character() -> None:
    scan = _Scanner("]rest")
    assert scan.until("]") == ""
    assert scan.rest() == "rest"


def test_until_without_the_character_says_which_one_is_missing() -> None:
    with pytest.raises(RowError) as info:
        _Scanner("abc").until("]")
    assert str(info.value) == "missing ']'"
