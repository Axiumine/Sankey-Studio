# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""csv/tsv rewriting: set_category, add_entry and reorder over many shapes of text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from tests.sources.rewrite.support import categorise

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

HEAD = "source,target,value"
HEADC = "source,target,value,category"


class Case(NamedTuple):
    text: str
    edit: Any
    expected: str
    changed: int = 1
    fields: dict[str, Any] | None = None


SET = [
    # the category cell is rewritten or cleared; every other byte stays
    Case(
        f"{HEADC}\na,b,1,K\nc,d,2,L\n",
        categorise("a", "b", "New"),
        f"{HEADC}\na,b,1,New\nc,d,2,L\n",
    ),
    Case(f"{HEADC}\na,b,1,K\nc,d,2,L\n", categorise("a", "b", None), f"{HEADC}\na,b,1,\nc,d,2,L\n"),
    Case(f"{HEADC}\na,b,1,K\n", categorise("a", "b", "K"), f"{HEADC}\na,b,1,K\n", 0),
    Case(
        f"{HEADC}\na,b,1\n", categorise("a", "b", None), f"{HEADC}\na,b,1\n", 0
    ),  # nothing to clear
    Case(f"{HEADC}\na,b,1\n", categorise("a", "b", "New"), f"{HEADC}\na,b,1,New\n"),  # short record
    # a missing category column is added to the header
    Case(f"{HEAD}\na,b,1\nc,d,2\n", categorise("a", "b", "New"), f"{HEADC}\na,b,1,New\nc,d,2\n"),
    Case(f"{HEAD}\na,b,1\n", categorise("a", "b", None), f"{HEAD}\na,b,1\n", 0),
    # line breaks, final break, BOM, delimiters, quoting
    Case(f"{HEAD}\r\na,b,1\r\n", categorise("a", "b", "N"), f"{HEADC}\r\na,b,1,N\r\n"),
    Case(f"{HEAD}\ra,b,1", categorise("a", "b", "N"), f"{HEADC}\ra,b,1,N"),
    Case(f"\ufeff{HEAD}\na,b,1\n", categorise("a", "b", "N"), f"\ufeff{HEADC}\na,b,1,N\n"),
    Case(
        "source;target;value\na;b;1\n",
        categorise("a", "b", "N"),
        "source;target;value;category\na;b;1;N\n",
    ),
    Case(
        "source\ttarget\tvalue\na\tb\t1\n",
        categorise("a", "b", "N"),
        "source\ttarget\tvalue\tcategory\na\tb\t1\tN\n",
        fields={"format": "tsv"},
    ),
    Case(
        f'{HEAD}\n"a,1",b,1\n',
        categorise("a,1", "b", "N"),
        f'{HEADC}\n"a,1",b,1,N\n',
    ),
    Case(
        'source,target,value,note\na,b,1,"x\ny"\n',
        categorise("a", "b", "N"),
        'source,target,value,note,category\na,b,1,"x\ny",N\n',
    ),
    # headerless: the fourth column, or the first free one after an explicit pick
    Case(
        "a,b,1\nc,d,2\n",
        categorise("a", "b", "N"),
        "a,b,1,N\nc,d,2\n",
        fields={"has_header": False},
    ),
    Case("a,b,1,K\n", categorise("a", "b", "N"), "a,b,1,N\n", fields={"has_header": False}),
    Case(
        "a,b,x,1\n",
        categorise("a", "b", "N"),
        "a,b,x,1,N\n",
        fields={"has_header": False, "value_column": 3},
    ),
    # named columns and indexes
    Case(
        "from,to,amount\na,b,1\n",
        categorise("a", "b", "N"),
        "from,to,amount,category\na,b,1,N\n",
        fields={"source_column": "from", "target_column": "to", "value_column": "amount"},
    ),
    Case(
        "x,a,y,b,1\n",
        categorise("a", "b", "N"),
        "x,a,y,b,1,N\n",
        fields={
            "has_header": False,
            "source_column": 1,
            "target_column": 3,
            "value_column": 4,
        },
    ),
    # every row of the pair changes; merged names match through the alias
    Case(
        f"{HEAD}\na,b,1\na,b,2\nc,d,3\n",
        categorise("a", "b", "N"),
        f"{HEADC}\na,b,1,N\na,b,2,N\nc,d,3\n",
        2,
    ),
]


@pytest.mark.parametrize("case", SET, ids=[str(i) for i in range(len(SET))])
def test_set_category(rewrite: Rewriter, case: Case) -> None:
    done = rewrite(case.text, case.edit, **(case.fields or {}))
    assert (done.text, done.changed) == (case.expected, case.changed)


def test_a_merged_name_matches_the_rows_of_its_aliases(rewrite: Rewriter) -> None:
    text = f"{HEAD}\nA1,b,1\nA2,b,2\nA,c,3\n"
    done = rewrite(text, categorise("A", "b", "N"), alias={"A1": "A", "A2": "A"})
    assert done.text == f"{HEADC}\nA1,b,1,N\nA2,b,2,N\nA,c,3\n"
    assert done.changed == 2
