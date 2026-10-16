# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Listing stays cheap: a thousand graphs are parsed once, not on every request."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.storage import FileGraphRepository
from sankey_studio.storage.files.codec import encode_graph, graph_filename
from tests.storage.support import Reads, Spec, definition

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

COUNT = 1000


def _populate(graphs_dir: Path) -> None:
    for i in range(COUNT):
        graph = definition(f"{i:032x}", f"graph {i}", spec=Spec(tags=(f"t{i % 10}",)))
        (graphs_dir / graph_filename(graph.id)).write_bytes(encode_graph(graph))


def test_a_thousand_graphs_are_parsed_once_and_then_served_from_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graphs_dir = tmp_path / "graphs"
    repo = FileGraphRepository(graphs_dir)
    _populate(graphs_dir)
    reads = Reads(monkeypatch)
    assert repo.count() == COUNT
    assert len(reads.paths) == COUNT
    reads.paths.clear()
    assert len(repo.list_graphs()) == 200  # the default page
    assert len(repo.list_graphs(offset=900)) == 100
    assert len(repo.list_graphs(limit=200, offset=800)) == 200
    assert len(repo.list_graphs(query="graph 99")) == 11  # 99, 990..999
    assert repo.count(tag="t3") == COUNT // 10
    assert repo.all_tags() == [f"t{i}" for i in range(10)]
    assert reads.paths == []


def test_only_the_graph_that_changed_is_parsed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graphs_dir = tmp_path / "graphs"
    repo = FileGraphRepository(graphs_dir)
    _populate(graphs_dir)
    repo.count()
    reads = Reads(monkeypatch)
    changed = definition(f"{7:032x}", "graph seven, renamed")
    repo.put(changed, overwrite=True)  # written through: no re-read at all
    assert repo.list_graphs(query="renamed")[0].id == changed.id
    assert reads.paths == []
    # another process rewrites one file: found by its signature, parsed exactly once
    other = definition(f"{8:032x}", "graph eight, edited elsewhere")
    (graphs_dir / graph_filename(other.id)).write_bytes(encode_graph(other))
    assert repo.list_graphs(query="elsewhere")[0].id == other.id
    assert reads.paths == [graph_filename(other.id)]
