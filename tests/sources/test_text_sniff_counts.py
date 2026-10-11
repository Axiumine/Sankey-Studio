"""``sniff_delimiter``: only lines with EXACTLY the first line's delimiter count agree."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from sankey_studio.sources.formats import sniff_delimiter
from tests.sources.idtools import safe_id


class Counts(NamedTuple):
    text: str
    expected: str


# A line with MORE delimiters than the first line is not a line "split the same way".
COUNTS = [
    # comma: only the first line has one comma (1 agreeing line); semicolon: all 3 lines agree
    Counts("x,y;z\np,q,r,s;t\np,q,r,s;t\n", ";"),
    # same shape with tabs against pipes
    Counts("x\ty|z\np\tq\tr\ts|t\np\tq\tr\ts|t\n", "|"),
    # fewer delimiters than the first line do not agree either
    Counts("x,y,z;w\np,q;r\np,q;r\n", ";"),
    # exactly equal counts agree: the comma wins on the earlier-candidate tie-break
    Counts("x,y;z\np,q;r\n", ","),
]


@pytest.mark.parametrize("case", COUNTS, ids=[safe_id(repr(c.text)[:24]) for c in COUNTS])
def test_only_equal_delimiter_counts_agree(case: Counts) -> None:
    assert sniff_delimiter(case.text) == case.expected
