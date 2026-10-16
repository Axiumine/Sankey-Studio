# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Library helpers of the HTTP flows: update bodies, seeded libraries and the documented order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from tests.e2e.support.builders import graph_create
from tests.e2e.support.clients import json_of
from tests.e2e.support.stamps import instant

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import httpx

UPDATE_FIELDS: Final = ("name", "description", "tags", "source", "transform", "style")
GRAPHS: Final = "/api/v1/graphs"


def update_body(graph: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    """A ``PUT /graphs/{id}`` body from a stored graph: its editable fields and its revision."""
    body = {key: graph[key] for key in UPDATE_FIELDS}
    return {**body, "revision": graph["revision"], **changes}


def newest_first(graphs: Sequence[Mapping[str, Any]]) -> list[str]:
    """The ids in the documented list order: ``updated_at`` descending, then ``id``."""
    by_id = sorted(graphs, key=lambda graph: str(graph["id"]))
    newest = sorted(by_id, key=lambda graph: instant(graph["updated_at"]), reverse=True)
    return [str(graph["id"]) for graph in newest]


def listed_ids(api: httpx.Client, **params: Any) -> list[str]:
    """The ids of ``GET /graphs`` with these query parameters, in answer order."""
    return [item["id"] for item in json_of(api.get(GRAPHS, params=params))["items"]]


@dataclass(frozen=True, slots=True)
class Library:
    """A server's graphs as created: ``graphs`` in creation order (the answers of the POSTs)."""

    graphs: list[dict[str, Any]]

    def by_name(self, name: str) -> dict[str, Any]:
        [found] = [graph for graph in self.graphs if graph["name"] == name]
        return found

    @property
    def ids(self) -> list[str]:
        return [str(graph["id"]) for graph in self.graphs]


def seed_library(api: httpx.Client, count: int = 25) -> Library:
    """``count`` graphs ``Budget 00..``: even/odd + ``all`` tags, every fifth one described.

    Graph 03 also carries the tag ``special`` and graph 07 a tag that only contains ``all``
    (``allocation``): searches and the exact tag filter must tell them apart.
    """
    graphs: list[dict[str, Any]] = []
    for number in range(count):
        tags = ["even" if number % 2 == 0 else "odd", "all"]
        tags += ["special"] if number == 3 else []
        tags += ["allocation"] if number == 7 else []
        description = "Quarterly report" if number % 5 == 0 else ""
        body = graph_create(f"Budget {number:02d}", tags=tags, description=description)
        graphs.append(json_of(api.post(GRAPHS, json=body), 201))
    return Library(graphs)
