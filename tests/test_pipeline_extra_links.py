# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``transform.extra_links``: graph-only entries are appended to every kind of source."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio import pipeline
from sankey_studio.errors import GraphBuildError, GraphTooLargeError
from sankey_studio.models import GraphDraft, TransformSpec
from sankey_studio.pipeline import build_graph_from_draft
from tests.graph_support import rows
from tests.test_pipeline_support import (
    CSV,
    PipelineEnv,
    RecordingCache,
    age_files,
    count_loads,
    csv_draft,
    file_draft,
    make_env,
    manual_draft,
    mongo_draft,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.models import RawLink

GIFT = {"source": "b", "target": "gift", "value": 5, "category": "Fun"}
SPARE = {"source": "gift", "target": "card", "value": 1}


@pytest.fixture
def env(
    tmp_path: Path, mongo_client: MongoClient[Any], monkeypatch: pytest.MonkeyPatch
) -> Iterator[PipelineEnv]:
    age_files(monkeypatch)
    with make_env(tmp_path, mongo_client) as value:
        yield value


def test_the_extra_links_come_after_the_rows_of_an_inline_text(env: PipelineEnv) -> None:
    graph = build_graph_from_draft(env.services, csv_draft(extra_links=[GIFT, SPARE]))
    assert rows(graph) == [
        ("a", "b", 10.0, None),
        ("b", "c", 4.0, None),
        ("b", "gift", 5.0, "Fun"),
        ("gift", "card", 1.0, None),
    ]
    assert graph.node_names == ("a", "b", "c", "gift", "card")  # new nodes take the last ids


def test_the_extra_links_come_after_the_links_of_a_manual_source(env: PipelineEnv) -> None:
    draft = manual_draft(("a", "b", 3, None), extra_links=[GIFT])
    assert rows(build_graph_from_draft(env.services, draft)) == [
        ("a", "b", 3.0, None),
        ("b", "gift", 5.0, "Fun"),
    ]


def test_the_extra_links_come_after_the_rows_of_a_file(env: PipelineEnv) -> None:
    env.sources_dir.mkdir(parents=True, exist_ok=True)
    (env.sources_dir / "flows.csv").write_text(CSV)
    graph = build_graph_from_draft(env.services, file_draft(extra_links=[GIFT]))
    assert rows(graph)[-1] == ("b", "gift", 5.0, "Fun")
    assert graph.n_links == 3


def test_the_extra_links_come_after_the_documents_of_a_mongo_source(env: PipelineEnv) -> None:
    env.mongo["flows"]["links"].insert_many([{"source": "a", "target": "b", "value": 10}])
    draft = GraphDraft(
        source=mongo_draft().source, transform=TransformSpec.model_validate({"extra_links": [GIFT]})
    )
    graph = build_graph_from_draft(env.services, draft)
    assert rows(graph) == [("a", "b", 10.0, None), ("b", "gift", 5.0, "Fun")]


def test_an_extra_link_is_merged_like_any_row(env: PipelineEnv) -> None:
    draft = csv_draft(extra_links=[GIFT], merge_nodes={"b": "a"})
    graph = build_graph_from_draft(env.services, draft)
    assert rows(graph) == [("a", "c", 4.0, None), ("a", "gift", 5.0, "Fun")]


def test_an_extra_link_can_hit_a_hidden_node(env: PipelineEnv) -> None:
    graph = build_graph_from_draft(env.services, csv_draft(extra_links=[GIFT], hide_nodes=["gift"]))
    assert rows(graph) == [("a", "b", 10.0, None), ("b", "c", 4.0, None)]


def test_an_extra_link_adds_to_the_value_of_an_existing_pair(env: PipelineEnv) -> None:
    extra = {"source": "a", "target": "b", "value": 2.5}
    graph = build_graph_from_draft(env.services, csv_draft(extra_links=[extra]))
    assert rows(graph)[0] == ("a", "b", 12.5, None)


@pytest.mark.parametrize(("extras", "fits"), [(1, True), (2, False)])
def test_the_extra_links_count_toward_the_raw_row_cap(
    env: PipelineEnv, extras: int, fits: bool
) -> None:
    env.change_settings(max_links=100)
    text = "source,target,value\n" + "".join(f"s{i},t{i},1\n" for i in range(99))
    more = [{"source": f"x{i}", "target": f"y{i}", "value": 1} for i in range(extras)]
    draft = csv_draft(text, extra_links=more)
    if fits:
        assert build_graph_from_draft(env.services, draft).n_links == 99 + extras
    else:
        with pytest.raises(GraphTooLargeError):
            build_graph_from_draft(env.services, draft)


def test_an_extra_link_that_closes_a_cycle_is_a_422_build_error(env: PipelineEnv) -> None:
    back = {"source": "c", "target": "a", "value": 1}
    with pytest.raises(GraphBuildError) as caught:
        build_graph_from_draft(env.services, csv_draft(extra_links=[back]))
    assert caught.value.status_code == 422
    assert caught.value.code == "graph_build_error"


def test_a_cycle_through_an_extra_link_can_be_broken(env: PipelineEnv) -> None:
    back = {"source": "c", "target": "a", "value": 1}
    graph = build_graph_from_draft(env.services, csv_draft(extra_links=[back], on_cycle="break"))
    assert graph.n_links == 2


class Rows:
    """A source stand-in whose row generator records its cleanup (the text source's ``finally``).

    It keeps a reference to the generator, so only an explicit ``close()`` can finish it.
    """

    def __init__(self, count: int) -> None:
        self.count = count
        self.finished = False
        self.stream: Iterator[RawLink] | None = None

    def iter_links(self, _diag: object) -> Iterator[RawLink]:
        self.stream = self._rows()
        return self.stream

    def _rows(self) -> Iterator[RawLink]:
        try:
            for i in range(self.count):
                yield f"s{i}", f"t{i}", 1.0, None
        finally:
            self.finished = True


def test_a_failed_build_closes_the_source_behind_the_extra_links(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Rows(count=150)
    monkeypatch.setattr(pipeline, "open_source", lambda _spec, _ctx: source)
    env.change_settings(max_links=100)
    with pytest.raises(GraphTooLargeError):
        build_graph_from_draft(env.services, csv_draft(extra_links=[GIFT]))
    assert source.finished


def test_a_finished_build_leaves_nothing_open(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Rows(count=3)
    monkeypatch.setattr(pipeline, "open_source", lambda _spec, _ctx: source)
    graph = build_graph_from_draft(env.services, csv_draft(extra_links=[GIFT]))
    assert graph.n_links == 4
    assert source.finished


def test_without_extra_links_the_graph_is_the_same_as_before(env: PipelineEnv) -> None:
    graph = build_graph_from_draft(env.services, csv_draft())
    assert rows(graph) == [("a", "b", 10.0, None), ("b", "c", 4.0, None)]


def test_the_extra_links_are_part_of_what_the_cache_serves(
    env: PipelineEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = count_loads(monkeypatch)
    cache = RecordingCache()
    with_gift = csv_draft(extra_links=[GIFT])
    first = build_graph_from_draft(env.services, with_gift, cache)
    assert build_graph_from_draft(env.services, with_gift, cache) is first
    plain = build_graph_from_draft(env.services, csv_draft(), cache)
    assert plain is not first
    assert loads.count == 2
    assert plain.n_links == 2
    assert first.n_links == 3
