# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Live preview of an unsaved draft: ``POST /preview`` and ``POST /entries``.

Both are pure computations (nothing is persisted), so they stay available in read-only remote
mode. The graph is built through the app's ``ResultCache``: paging or filtering the entries table
does not parse the same file or query the same collection again on every keystroke.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from sankey_studio.bundle import RenderBundle
from sankey_studio.models import GraphDraft
from sankey_studio.pipeline import BundleOptions, build_graph_from_draft, render_bundle
from sankey_studio.render.tables import EntriesPage, entries_page
from sankey_studio.web.deps import ResultCacheDep, ServicesDep
from sankey_studio.web.schemas import EntriesQuery, ThemeQuery

router = APIRouter(prefix="/api/v1")


@router.post("/preview")
def preview(
    query: Annotated[ThemeQuery, Query()],
    draft: GraphDraft,
    services: ServicesDep,
    cache: ResultCacheDep,
) -> RenderBundle:
    """Draw ``draft`` (figure, legend, donut, tables) in the requested theme.

    The bundle also lists the drawn nodes (``nodes``, aligned with the figure's node labels):
    the editor needs their names for node order and node clicks.
    """
    options = BundleOptions(theme=query.theme, with_nodes=True)
    return render_bundle(services, draft, options, cache)


@router.post("/entries")
def entries(
    query: Annotated[EntriesQuery, Query()],
    draft: GraphDraft,
    services: ServicesDep,
    cache: ResultCacheDep,
) -> EntriesPage:
    """One filtered, sorted page (at most 500 rows) of the entries table of ``draft``."""
    graph = build_graph_from_draft(services, draft, cache)
    return entries_page(graph, draft.transform, query.options())
