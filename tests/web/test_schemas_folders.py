# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Wire models of the folder routes: ``MoveGraphsIn`` and ``FolderList``."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.models import FolderSummary
from sankey_studio.web.schemas import MOVE_IDS_MAX, FolderList, MoveGraphsIn
from tests.web.test_schemas_support import Case, check_case, digest, gid

LOW = "too_short"
HIGH = "too_long"
PATTERN = "string_pattern_mismatch"
BASE = {"ids": [gid(1)], "folder_id": None}


def ids(count: int) -> list[str]:
    return [gid(number) for number in range(1, count + 1)]


MOVE = [
    Case("ids", ids(1)),
    Case("ids", ids(200)),
    Case("ids", [], LOW),
    Case("ids", ids(201), HIGH),
    Case("folder_id", None),
    Case("folder_id", gid(9)),
    Case("folder_id", "F" * 32, PATTERN),
    Case("folder_id", "f" * 31, PATTERN),
    Case("folder_id", "root", PATTERN),
]


def test_the_cap_is_the_one_of_a_bundle_export() -> None:
    assert MOVE_IDS_MAX == 200


@pytest.mark.parametrize("case", MOVE, ids=repr)
def test_move_bounds(case: Case) -> None:
    check_case(MoveGraphsIn, case, BASE)


@pytest.mark.parametrize("bad", [["short"], ["A" * 32], [1], [None], "x" * 32, {}])
def test_every_id_must_be_a_graph_id(bad: Any) -> None:
    with pytest.raises(ValidationError):
        MoveGraphsIn.model_validate({**BASE, "ids": bad})


def test_ids_must_be_distinct() -> None:
    with pytest.raises(ValidationError) as caught:
        MoveGraphsIn.model_validate({"ids": [gid(1), gid(2), gid(1)], "folder_id": None})
    assert digest(caught) == [(("ids",), "value_error")]
    assert "ids must not repeat a graph" in str(caught.value)
    assert MoveGraphsIn.model_validate({"ids": [gid(1), gid(2)], "folder_id": None}).ids == [
        gid(1),
        gid(2),
    ]


def test_the_folder_key_is_required_even_for_the_top_level() -> None:
    with pytest.raises(ValidationError) as caught:
        MoveGraphsIn.model_validate({"ids": [gid(1)]})
    assert digest(caught) == [(("folder_id",), "missing")]
    with pytest.raises(ValidationError) as caught:
        MoveGraphsIn.model_validate({"folder_id": None})
    assert digest(caught) == [(("ids",), "missing")]


def test_an_unknown_key_is_refused_and_the_input_is_not_echoed() -> None:
    with pytest.raises(ValidationError) as caught:
        MoveGraphsIn.model_validate({**BASE, "ids": ["SECRET-IDS"], "bogus": 1})
    assert ("bogus",) in [loc for loc, _ in digest(caught)]
    assert "SECRET" not in str(caught.value)


def test_a_list_of_folders_forbids_other_keys() -> None:
    assert FolderList(items=[]).model_dump() == {"items": []}
    with pytest.raises(ValidationError) as caught:
        FolderList.model_validate({"items": [], "total": 0})
    assert digest(caught) == [(("total",), "extra_forbidden")]


def test_a_list_holds_folder_summaries() -> None:
    row = {
        "id": gid(1),
        "name": "F",
        "parent_id": None,
        "revision": 1,
        "updated_at": "2026-01-01T00:00:00Z",
        "graph_count": 0,
        "child_count": 0,
    }
    (item,) = FolderList.model_validate({"items": [row]}).items
    assert isinstance(item, FolderSummary)
