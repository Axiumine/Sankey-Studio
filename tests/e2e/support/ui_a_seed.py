# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Seeding for the UI-A suites: save a graph through the API, never through the page under test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft, unique_name
from tests.e2e.support.clients import make_client, seed_graph

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tests.e2e.support.server import LiveServer


@dataclass(frozen=True, slots=True)
class SavedGraph:
    """A graph that exists on the server: its id and its (unique) name."""

    id: str
    name: str


def save_graph(
    server: LiveServer,
    prefix: str,
    csv: str = BUDGET_CATEGORISED.csv,
    tags: Sequence[str] = (),
) -> SavedGraph:
    """Create a graph named ``<prefix> <random>`` from ``csv`` and return its id and name."""
    name = unique_name(prefix)
    with make_client(server) as client:
        created = seed_graph(client, name, graph_draft(csv), tags=tags)
    return SavedGraph(created["id"], name)
