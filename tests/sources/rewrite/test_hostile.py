# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Hostile names and categories survive every format (the self-check is the judge)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.sources.rewrite.support import add, categorise, reorder

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

NAMES = [
    "bell\x07name",
    "rlo" + chr(0x202E) + "name",
    "tab\tname",
    'quote"name',
    'dbl""quote',
    "=cmd|' /C calc'!A0",
    "-5",
    "+1",
    "@sum",
    "semi;colon",
    "com,ma",
    "pipe|name",
    "back\\slash",
    "//comment",
    "[bracket]",
    "[x] y",
    "café 中文 \U0001f600",
    "a  b",
]
TEXTS = {
    "csv": "source,target,value\nx,y,1\n",
    "tsv": "source\ttarget\tvalue\nx\ty\t1\n",
    "sankeymatic": "x [1] y\n",
    "json": '[{"source":"x","target":"y","value":1}]',
}


@pytest.mark.parametrize("name", NAMES, ids=[str(i) for i in range(len(NAMES))])
@pytest.mark.parametrize("fmt", sorted(TEXTS))
def test_a_hostile_name_is_added_categorised_and_reordered(
    rewrite: Rewriter, fmt: str, name: str
) -> None:
    added = rewrite(TEXTS[fmt], add(name, "y", 7, "Cat"), format=fmt)
    again = rewrite(added.text, categorise(name, "y", "Other cat"), format=fmt)
    moved = rewrite(again.text, reorder("y", name), format=fmt)
    assert (added.changed, again.changed, moved.changed) == (1, 1, 2)
