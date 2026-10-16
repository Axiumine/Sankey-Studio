# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Whole-pipeline memory profile: a synthetic 200k-link graph through the render layer.

``make profile`` runs it under ``memray run`` (then ``memray stats`` / ``memray flamegraph``
read ``.memray/bench.bin``). Run it plainly and it prints the peak resident set size instead.
A nested ``memray.Tracker`` raises ("No more than one Tracker instance can be active"), so this
script never starts one.
"""

from __future__ import annotations

import random
import resource
import sys
from dataclasses import dataclass

from sankey_studio.graph import build_graph
from sankey_studio.models import RawLink, StyleSpec, TransformSpec
from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.options import FigureOptions
from sankey_studio.render.sankey import build_figure
from sankey_studio.sources.base import Diagnostics

LINKS = 200_000
LAYERS = 4
WIDTH = 400
#: The pipeline draws at most ``AppSettings.max_drawn_links`` links (default 3000).
DRAWN = 3_000
CATEGORIES: tuple[str | None, ...] = (*(f"cat{i:02d}" for i in range(12)), None)
KIB_PER_MIB = 1024


@dataclass(frozen=True, slots=True)
class Summary:
    """What one run produced: sizes only, nothing that keeps the data alive."""

    raw_links: int
    nodes: int
    links: int
    categories: int
    full_figure_links: int
    drawn_figure_links: int
    donut_slices: int


def synthetic_links(count: int, seed: int = 7) -> list[RawLink]:
    """``count`` links between ``LAYERS`` layers of ``WIDTH`` nodes, 12 categories."""
    rnd = random.Random(seed)
    names = [[f"L{layer}-{i}" for i in range(WIDTH)] for layer in range(LAYERS)]
    links: list[RawLink] = []
    for _ in range(count):
        layer = rnd.randrange(LAYERS - 1)
        source = names[layer][rnd.randrange(WIDTH)]
        target = names[layer + 1][rnd.randrange(WIDTH)]
        links.append((source, target, round(rnd.uniform(1, 1000), 2), rnd.choice(CATEGORIES)))
    return links


def run_pipeline(links: list[RawLink]) -> Summary:
    """``build_graph`` + the Sankey (whole and as drawn) + the donut."""
    diag = Diagnostics()
    graph = build_graph(links, TransformSpec(), max_raw_links=len(links) + 1, diag=diag)
    style = StyleSpec()
    full = build_figure(graph, style, "light")
    drawn = build_figure(graph, style, "light", FigureOptions(max_links=DRAWN))
    donut = build_donut_figure(graph, style, "light")
    return Summary(
        raw_links=len(links),
        nodes=graph.n_nodes,
        links=graph.n_links,
        categories=len(graph.categories),
        full_figure_links=len(full["data"][0]["link"]["value"]),
        drawn_figure_links=len(drawn["data"][0]["link"]["value"]),
        donut_slices=len(donut["data"][0]["labels"]),
    )


def under_memray() -> bool:
    """True inside ``memray run``: the memray package is already imported by its runner."""
    return "memray" in sys.modules


def peak_mib() -> float:
    """Peak resident set size of this process in MiB (``ru_maxrss`` is KiB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / KIB_PER_MIB


def main() -> None:
    summary = run_pipeline(synthetic_links(LINKS))
    print(
        f"{summary.raw_links} raw links -> {summary.nodes} nodes, {summary.links} links, "
        f"{summary.categories} categories; figure with {summary.full_figure_links} links "
        f"({summary.drawn_figure_links} when drawn), donut with {summary.donut_slices} slices"
    )
    if under_memray():
        print("running under memray: read the numbers with `memray stats .memray/bench.bin`")
    else:
        print(f"peak RSS: {peak_mib():.1f} MiB")


if __name__ == "__main__":
    main()
