# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The real 32 MiB cap at full scale: a model-valid graph can never be saved and then be unreadable.

Before the write side shared the read cap, 20000 entry choices with 200-character CJK names
(escaped to ASCII, six bytes a character) were saved as a 60 MB file that ``get`` then refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.models import (
    MAX_ENTRY_CATEGORIES,
    EntryCategory,
    GraphCreate,
    GraphDefinition,
    TextSource,
    TransformSpec,
)
from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.files.codec import MAX_GRAPH_BYTES, encode_graph, graph_filename
from tests.storage.support import ID_A, NOW

if TYPE_CHECKING:
    from pathlib import Path

CJK = chr(0x6F22)  # six bytes once escaped to ASCII JSON
TOO_LARGE = r"^The graph is too large to save$"


def _entries(count: int) -> list[EntryCategory]:
    return [
        EntryCategory(source=f"{i:05d}" + CJK * 195, target=CJK * 200, category=CJK * 100)
        for i in range(count)
    ]


def _graph(entries: int, description: str = "") -> GraphDefinition:
    return GraphDefinition(
        id=ID_A,
        name="big",
        description=description,
        source=TextSource(content="a,b,1\n"),
        transform=TransformSpec(entry_categories=_entries(entries)),
        created_at=NOW,
        updated_at=NOW,
    )


def _encoded_size(entries: int) -> int:
    return len(encode_graph(_graph(entries)))


def _padding(missing: int) -> str:
    """A description that costs exactly ``missing`` bytes: CJK characters take six, ASCII one."""
    return CJK * (missing // 6) + "d" * (missing % 6)


@pytest.fixture(scope="module")
def at_cap() -> GraphDefinition:
    """A graph whose file is exactly ``MAX_GRAPH_BYTES`` long."""
    one, two = _encoded_size(1), _encoded_size(2)
    stride = two - one  # every entry has the same length
    count = 1 + (MAX_GRAPH_BYTES - one) // stride
    missing = MAX_GRAPH_BYTES - (one + (count - 1) * stride)
    graph = _graph(count, _padding(missing))
    assert len(encode_graph(graph)) == MAX_GRAPH_BYTES
    return graph


def test_a_graph_of_exactly_the_cap_is_saved_and_read_back(
    tmp_path: Path, at_cap: GraphDefinition
) -> None:
    repo = FileGraphRepository(tmp_path / "graphs")
    assert repo.put(at_cap) == at_cap
    assert (tmp_path / "graphs" / graph_filename(ID_A)).stat().st_size == MAX_GRAPH_BYTES
    assert repo.get(ID_A) == at_cap
    assert [(row.id, row.revision) for row in repo.list_graphs()] == [(ID_A, 1)]


def test_one_byte_more_than_the_cap_is_refused_and_nothing_is_written(
    tmp_path: Path, at_cap: GraphDefinition
) -> None:
    repo = FileGraphRepository(tmp_path / "graphs")
    over = at_cap.model_copy(update={"description": at_cap.description + "d"})
    with pytest.raises(StorageError, match=TOO_LARGE):
        repo.put(over)
    assert list((tmp_path / "graphs").iterdir()) == []
    assert repo.list_graphs() == []


def test_twenty_thousand_cjk_entry_choices_are_refused_by_create(tmp_path: Path) -> None:
    repo = FileGraphRepository(tmp_path / "graphs")
    data = GraphCreate(
        name="big",
        source=TextSource(content="a,b,1\n"),
        transform=TransformSpec(entry_categories=_entries(MAX_ENTRY_CATEGORIES)),
    )
    with pytest.raises(StorageError, match=TOO_LARGE):
        repo.create(data)
    assert list((tmp_path / "graphs").iterdir()) == []
    assert repo.count() == 0
