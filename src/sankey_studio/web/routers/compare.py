# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``GET /compare/render``: several saved graphs drawn with ONE shared category colour map.

The ids come from ``CompareQuery`` (1..12 distinct, comma separated, each a well-formed graph id);
an unknown id answers 404 before any graph is built. The cards come back in the order of the ids.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from sankey_studio.bundle import RenderBundle
from sankey_studio.pipeline import render_compare
from sankey_studio.web.deps import ResultCacheDep, ServicesDep
from sankey_studio.web.routers.graphs import draft_of
from sankey_studio.web.schemas import CompareQuery

router = APIRouter(prefix="/api/v1")


@router.get("/compare/render")
def compare_render(
    query: Annotated[CompareQuery, Query()], services: ServicesDep, cache: ResultCacheDep
) -> list[RenderBundle]:
    """One bundle per graph; a category has the same colour on every card."""
    repo = services.graphs()
    drafts = [draft_of(repo.get(graph_id)) for graph_id in query.ids]
    return render_compare(services, drafts, query.theme, cache)
