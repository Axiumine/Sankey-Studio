# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""JSON rewriting: arrays are re-formatted (and say so), NDJSON is edited in place."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.errors import SourceEditRefused
from tests.sources.rewrite.support import add, categorise, reorder

if TYPE_CHECKING:
    from tests.sources.rewrite.conftest import Rewriter

ONE = '{"source":"a","target":"b","value":1}'
TWO = '{"source":"c","target":"d","value":2,"category":"K"}'


def pretty(items: list[Any]) -> str:
    return json.dumps(items, indent=2, ensure_ascii=False) + "\n"


def loads(text: str) -> Any:
    return json.loads(text)


class Case(NamedTuple):
    text: str
    edit: Any
    expected: list[Any]


ARRAYS = [
    Case(
        f"[{ONE},{TWO}]",
        categorise("a", "b", "N"),
        [{"source": "a", "target": "b", "value": 1, "category": "N"}, loads(TWO)],
    ),
    Case(
        f"[{ONE},{TWO}]",
        categorise("c", "d", None),
        [loads(ONE), {"source": "c", "target": "d", "value": 2}],
    ),
    Case(
        f"[{ONE}]",
        add("x", "y", 5, "N"),
        [loads(ONE), {"source": "x", "target": "y", "value": 5, "category": "N"}],
    ),
    Case(
        f"[{ONE}]", add("x", "y", 2.5), [loads(ONE), {"source": "x", "target": "y", "value": 2.5}]
    ),
    Case("[]", add("x", "y", 5), [{"source": "x", "target": "y", "value": 5}]),
    Case(f"[{TWO},{ONE}]", reorder("a", "b", "c", "d"), [loads(ONE), loads(TWO)]),
    # elements that are not entries keep their slot
    Case(
        f'[{TWO},null,"text",{{"source":"x"}},{ONE}]',
        reorder("a", "b"),
        [loads(ONE), None, "text", {"source": "x"}, loads(TWO)],
    ),
    # unicode stays readable
    Case(
        '[{"source":"é","target":"ü","value":1}]',
        categorise("é", "ü", "Süß"),
        [{"source": "é", "target": "ü", "value": 1, "category": "Süß"}],
    ),
]


@pytest.mark.parametrize("case", ARRAYS, ids=[str(i) for i in range(len(ARRAYS))])
def test_array_edits(rewrite: Rewriter, case: Case) -> None:
    done = rewrite(case.text, case.edit, format="json")
    assert done.text == pretty(case.expected)
    assert done.changed >= 1


def test_an_array_that_was_not_formatted_this_way_is_reported_as_reformatted(
    rewrite: Rewriter,
) -> None:
    assert rewrite(f"[{ONE}]", categorise("a", "b", "N")).reformatted is True


def test_an_array_that_already_has_this_format_is_not(rewrite: Rewriter) -> None:
    text = pretty([loads(ONE), loads(TWO)])
    done = rewrite(text, categorise("a", "b", "N"))
    assert done.reformatted is False
    assert done.text == pretty([{**loads(ONE), "category": "N"}, loads(TWO)])


def test_a_bom_is_kept(rewrite: Rewriter) -> None:
    done = rewrite(f"\ufeff[{ONE}]", categorise("a", "b", "N"))
    assert done.text == "\ufeff" + pretty([{**loads(ONE), "category": "N"}])


def test_a_category_that_is_already_set_changes_nothing(rewrite: Rewriter) -> None:
    text = f"[{TWO}]"
    done = rewrite(text, categorise("c", "d", "K"))
    assert (done.text, done.changed, done.reformatted) == (text, 0, False)


def test_clearing_a_missing_category_changes_nothing(rewrite: Rewriter) -> None:
    done = rewrite(f"[{ONE}]", categorise("a", "b", None))
    assert (done.text, done.changed) == (f"[{ONE}]", 0)


def test_ndjson_edits_only_the_touched_object(rewrite: Rewriter) -> None:
    done = rewrite(f"{ONE}\n{TWO}\n", categorise("a", "b", "N"))
    assert done.text == (
        '{"source": "a", "target": "b", "value": 1, "category": "N"}\n' + TWO + "\n"
    )
    assert done.reformatted is True  # the touched object was written with other spacing


def test_a_touched_object_that_is_already_written_this_way_is_not_reformatted(
    rewrite: Rewriter,
) -> None:
    line = '{"source": "a", "target": "b", "value": 1}'
    done = rewrite(f"{line}\n", categorise("a", "b", "N"))
    assert done.text == '{"source": "a", "target": "b", "value": 1, "category": "N"}\n'
    assert done.reformatted is False


def test_ndjson_add_appends_a_line_without_reformatting(rewrite: Rewriter) -> None:
    done = rewrite(f"{ONE}\n{TWO}", add("x", "y", 3))
    assert done.text == f'{ONE}\n{TWO}\n{{"source": "x", "target": "y", "value": 3}}\n'
    assert done.reformatted is False


def test_ndjson_clear_removes_the_member(rewrite: Rewriter) -> None:
    done = rewrite(f"{ONE}\n{TWO}\n", categorise("c", "d", None))
    assert done.text == f'{ONE}\n{{"source": "c", "target": "d", "value": 2}}\n'


def test_ndjson_reorder_moves_objects_and_keeps_the_gaps(rewrite: Rewriter) -> None:
    done = rewrite(f"{TWO}\n\n{ONE}", reorder("a", "b", "c", "d"))
    assert done.text == f"{ONE}\n\n{TWO}\n"
    assert done.changed == 2


def test_ndjson_objects_may_share_a_line_or_span_several(rewrite: Rewriter) -> None:
    text = f'{TWO} {ONE}\n{{\n "source": "e",\n "target": "f",\n "value": 3\n}}\n'
    done = rewrite(text, reorder("e", "f", "a", "b", "c", "d"))
    assert done.text.startswith('{\n "source": "e",')
    assert done.text.count("\n") == text.count("\n")


@pytest.mark.parametrize(
    "text",
    [
        "[1, 2",
        '{"a": 1}\n[1]',
        '{"a":',
        "[[",
        '{"source": NaN, "x"',
        "[" * 10_000,
        '"just a string"[1]',
    ],
)
def test_a_text_that_does_not_load_is_unreadable(rewrite: Rewriter, text: str) -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite(text, categorise("a", "b", "N"), format="json")
    assert info.value.reason == "unreadable"


def test_a_non_array_start_with_a_non_object_is_unreadable(rewrite: Rewriter) -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite("12 13", categorise("a", "b", "N"), format="json")
    assert info.value.reason == "unreadable"


def test_no_match_in_json(rewrite: Rewriter) -> None:
    with pytest.raises(SourceEditRefused) as info:
        rewrite(f"[{ONE}]", categorise("x", "y", "N"))
    assert info.value.reason == "no_match"
