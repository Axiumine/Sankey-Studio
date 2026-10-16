# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Memory budgets (pytest-memray): ``make memray`` = ``pytest -m memory --memray``.

pytest-memray measures only the body of a test function, so every input (the links, the CSV)
is built in a module-scoped fixture, and a warm-up fixture pays the import and cache costs once.
The budgets are the measured peak plus about 35% (measured with ``--trace-python-allocators``,
which reports more than the default mode, so a budget that holds there holds everywhere):

* ``build_graph`` on 100k links: measured 16.6 MiB, budget 23 MB
* ``build_graph`` on 200k links: measured 25.2 MiB, budget 34 MB
* ``build_figure`` on 20k links (the dict path): measured 5.4 MiB, budget 8 MB
* text parse of a 50k-row CSV: measured 5.2 MiB, budget 8 MB
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts.profile_memory import synthetic_links

from sankey_studio.graph import build_graph
from sankey_studio.models import StyleSpec, TextSource, TransformSpec
from sankey_studio.render.sankey import build_figure
from sankey_studio.sources.base import Diagnostics

if TYPE_CHECKING:
    from sankey_studio.models import RawLink, SankeyGraph
    from sankey_studio.sources.base import SourceContext

CSV_ROWS = 50_000


@pytest.fixture(scope="module", autouse=True)
def _warm_up() -> None:
    """One tiny graph and figure, so imports and caches are not charged to a budget."""
    graph = build_graph(
        synthetic_links(50), TransformSpec(), max_raw_links=1000, diag=Diagnostics()
    )
    build_figure(graph, StyleSpec(), "light")


@pytest.fixture(scope="module")
def links_100k() -> list[RawLink]:
    return synthetic_links(100_000)


@pytest.fixture(scope="module")
def links_200k() -> list[RawLink]:
    return synthetic_links(200_000)


@pytest.fixture(scope="module")
def graph_20k() -> SankeyGraph:
    links = synthetic_links(20_000)
    return build_graph(links, TransformSpec(), max_raw_links=1_000_000, diag=Diagnostics())


@pytest.fixture(scope="module")
def csv_50k() -> str:
    lines = [
        f"L0-{i % 400},L1-{(i * 7) % 400},{i % 997 + 1}.5,cat{i % 12:02d}" for i in range(CSV_ROWS)
    ]
    return "source,target,value,category\n" + "\n".join(lines) + "\n"


@pytest.mark.memory
@pytest.mark.limit_memory("23 MB")
def test_build_graph_100k_links(links_100k: list[RawLink]) -> None:
    graph = build_graph(links_100k, TransformSpec(), max_raw_links=1_000_000, diag=Diagnostics())
    assert graph.n_links > 90_000


@pytest.mark.memory
@pytest.mark.limit_memory("34 MB")
def test_build_graph_200k_links(links_200k: list[RawLink]) -> None:
    graph = build_graph(links_200k, TransformSpec(), max_raw_links=1_000_000, diag=Diagnostics())
    assert graph.n_links > 180_000


@pytest.mark.memory
@pytest.mark.limit_memory("8 MB")
def test_build_figure_20k_links(graph_20k: SankeyGraph) -> None:
    figure = build_figure(graph_20k, StyleSpec(), "light")
    assert len(figure["data"][0]["link"]["value"]) == graph_20k.n_links


@pytest.mark.memory
@pytest.mark.limit_memory("8 MB")
def test_text_parse_50k_row_csv(csv_50k: str, source_ctx: SourceContext) -> None:
    from sankey_studio.sources.text import TextDataSource

    spec = TextSource(content=csv_50k, format="csv")
    source = TextDataSource(spec, source_ctx)
    rows = sum(1 for _ in source.iter_links(Diagnostics()))
    assert rows == CSV_ROWS
