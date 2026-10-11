"""Huge ``limit`` / ``offset`` values behave the same on both backends (BSON stops at 8 bytes)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import bson
import mongomock.collection
import pytest

from sankey_studio.storage.common import PAGE_MAX
from tests.storage.support import ID_A, ID_B, ID_C, definition

if TYPE_CHECKING:
    from sankey_studio.storage import MongoGraphRepository
    from tests.storage.conftest import RepoEnv

IDS = [ID_A, ID_B, ID_C]


@pytest.fixture(autouse=True)
def paging_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Make mongomock refuse what the real driver refuses: ints that do not fit 8 bytes.

    Returns the ``(method, value)`` pairs the store asked for, in order.
    """
    asked: list[tuple[str, int]] = []
    cursor = mongomock.collection.Cursor

    def wrap(name: str) -> None:
        original = getattr(cursor, name)

        def checked(self: Any, count: int) -> Any:
            bson.encode({name: count})  # OverflowError beyond 8 bytes, like pymongo's wire encoding
            asked.append((name, count))
            return original(self, count)

        monkeypatch.setattr(cursor, name, checked)

    wrap("skip")
    wrap("limit")
    return asked


class Page(NamedTuple):
    limit: int
    offset: int
    expected: list[str]


@pytest.mark.parametrize(
    "case",
    [
        Page(PAGE_MAX - 1, 0, IDS),
        Page(PAGE_MAX, 0, IDS),
        Page(PAGE_MAX + 1, 0, IDS),
        Page(2**63 - 1, 0, IDS),
        Page(2**63, 0, IDS),
        Page(10**30, 1, IDS[1:]),
        Page(2, PAGE_MAX - 1, []),
        Page(2, PAGE_MAX, []),
        Page(2, PAGE_MAX + 1, []),
        Page(2, 2**63 - 1, []),
        Page(2, 2**63, []),
        Page(2, 10**30, []),
        Page(2**63, 2**63, []),
        Page(-(2**63) - 1, -(2**64), []),
    ],
)
def test_huge_paging_values_are_clamped_not_rejected(env: RepoEnv, case: Page) -> None:
    for graph_id in IDS:
        env.repo.put(definition(graph_id, graph_id[:1]))
    page = env.repo.list_graphs(limit=case.limit, offset=case.offset)
    assert [summary.id for summary in page] == case.expected


def test_the_mongo_store_never_sends_a_value_beyond_the_cap(
    mongo_repo: MongoGraphRepository, paging_calls: list[tuple[str, int]]
) -> None:
    mongo_repo.put(definition(ID_A, "a"))
    mongo_repo.list_graphs(limit=2**63, offset=2**64)
    assert paging_calls == [("skip", PAGE_MAX), ("limit", PAGE_MAX)]
