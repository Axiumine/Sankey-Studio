# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Optimistic concurrency under real threads: exactly one writer wins, nothing is torn."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import mongomock.collection

from sankey_studio.errors import ConflictError
from sankey_studio.models import GraphDefinition
from sankey_studio.storage import FileGraphRepository, MongoGraphRepository
from tests.storage.conftest import STORE_TARGET
from tests.storage.support import Spec, create_data, update_data

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from sankey_studio.mongo import MongoClients
    from sankey_studio.storage.base import GraphRepository
    from tests.storage.conftest import RepoEnv

THREADS = 50


def _race(work: Callable[[int], object]) -> list[object]:
    """Run ``work(i)`` in ``THREADS`` threads released together; return every outcome."""
    barrier = threading.Barrier(THREADS)
    outcomes: list[object] = [None] * THREADS

    def run(index: int) -> None:
        barrier.wait()
        try:
            outcomes[index] = work(index)
        except Exception as exc:  # noqa: BLE001 - the test inspects every outcome, errors included
            outcomes[index] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def _assert_one_winner(repo: GraphRepository, graph_id: str, outcomes: list[object]) -> None:
    winners = [o for o in outcomes if not isinstance(o, Exception)]
    losers = [o for o in outcomes if isinstance(o, Exception)]
    assert len(winners) == 1
    assert len(losers) == THREADS - 1
    assert all(isinstance(e, ConflictError) for e in losers)
    assert {e.current_revision for e in losers if isinstance(e, ConflictError)} <= {2}
    stored = repo.get(graph_id)
    assert stored.revision == 2
    assert stored == winners[0]


def test_two_file_repositories_on_one_directory_have_one_winner(tmp_path: Path) -> None:
    graphs = tmp_path / "graphs"
    repos = [FileGraphRepository(graphs), FileGraphRepository(graphs)]
    created = repos[0].create(create_data("start"))

    def work(i: int) -> object:
        return repos[i % 2].update(created.id, update_data(1, f"writer {i}"))

    outcomes = _race(work)
    _assert_one_winner(repos[1], created.id, outcomes)
    assert sorted(p.name for p in graphs.iterdir()) == [f"{created.id}.json"]


def test_the_mongo_store_is_a_compare_and_set_on_id_and_revision(
    mongo_clients: MongoClients, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real server runs ``findOneAndUpdate`` atomically; mongomock does not, so model that."""
    lock = threading.Lock()
    original: Any = mongomock.collection.Collection.find_one_and_update

    def atomic(self: Any, *args: Any, **kwargs: Any) -> Any:
        with lock:
            return original(self, *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "find_one_and_update", atomic)
    repos = [MongoGraphRepository(mongo_clients, STORE_TARGET) for _ in range(2)]
    created = repos[0].create(create_data("start"))

    def work(i: int) -> object:
        return repos[i % 2].update(created.id, update_data(1, f"writer {i}"))

    _assert_one_winner(repos[1], created.id, _race(work))


def test_concurrent_creates_all_succeed_with_distinct_ids(env: RepoEnv) -> None:
    outcomes = _race(lambda i: env.repo.create(create_data(f"g{i}")))
    created = [o for o in outcomes if isinstance(o, GraphDefinition)]
    assert len(created) == THREADS  # no exception among the outcomes
    assert len({graph.id for graph in created}) == THREADS
    assert env.repo.count() == THREADS


def test_readers_never_see_a_torn_graph_while_a_writer_updates(tmp_path: Path) -> None:
    repo = FileGraphRepository(tmp_path / "graphs")
    created = repo.create(create_data("v1", Spec(links=40)))
    done = threading.Event()
    seen: list[int] = []
    errors: list[Exception] = []

    def read() -> None:
        while not done.is_set():
            try:
                seen.append(repo.get(created.id).revision)
                repo.list_graphs()
            except Exception as exc:  # noqa: BLE001 - any failure fails the test below
                errors.append(exc)
                return

    readers = [threading.Thread(target=read) for _ in range(4)]
    for reader in readers:
        reader.start()
    for revision in range(1, 31):
        repo.update(created.id, update_data(revision, f"v{revision + 1}", Spec(links=40)))
    done.set()
    for reader in readers:
        reader.join()
    assert errors == []
    assert seen == [] or max(seen) <= 31
    assert repo.get(created.id).revision == 31
