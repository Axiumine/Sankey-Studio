"""``RenderBundle``: everything a page needs to draw one graph, as JSON primitives only.

The bundle is the response of ``POST /preview``, ``GET /graphs/{id}/render`` and (as a list)
``GET /compare/render``. ``pipeline.assemble_bundle`` is the only code that builds one. The render
types it embeds (``LegendItem``, ``CategoryRow``, ``EntryRow``) are frozen dataclasses of lists,
strings and numbers, so pydantic can validate and serialise them without help.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from sankey_studio.render.legend import LegendItem
from sankey_studio.render.tables import CategoryRow, EntryRow

__all__ = ["BundleStats", "DonutEmptyReason", "RenderBundle"]

#: Why ``donut`` has nothing to show: no entry has a category, or the chosen basis selects none.
DonutEmptyReason = Literal["no_categories", "basis_empty"]


class BundleStats(BaseModel):
    """Totals of the built graph (before the drawing cap, unless the name says ``drawn``)."""

    model_config = ConfigDict(extra="forbid")

    nodes: int
    links: int
    #: Links in the figure: ``links`` capped by ``AppSettings.max_drawn_links``.
    drawn_links: int
    #: Flow leaving the source nodes (``node_in == 0``).
    total_in: float
    #: Flow arriving at the sink nodes (``node_out == 0``).
    total_out: float
    layers: int
    #: Real categories on the final links (``len(graph.categories)``).
    category_count: int


class RenderBundle(BaseModel):
    """One graph, drawn: Sankey figure, legend, donut, tables and warnings.

    ``donut`` is ``None`` exactly when ``donut_available`` is false, and ``donut_empty_reason`` is
    ``"no_categories"`` exactly then; when a donut exists but the basis selects no category, its
    figure holds only the empty-state note and the reason is ``"basis_empty"``. There is no
    ``donut_legend``: the donut has its native legend and ``categories`` is its table view.
    """

    model_config = ConfigDict(extra="forbid")

    figure: dict[str, Any]
    #: The in-figure Sankey legend, repeated for the page.
    legend: list[LegendItem]
    donut_available: bool
    donut: dict[str, Any] | None
    donut_empty_reason: DonutEmptyReason | None
    #: The donut as a table: ``[]`` when there is no donut.
    categories: list[CategoryRow]
    #: EVERY real category in slot order (display spelling), also those folded into ``Other``.
    category_names: list[str]
    stats: BundleStats
    #: A preview of the entries table; the full list is paged by ``POST /entries``.
    entries: list[EntryRow]
    entries_total: int
    warnings: list[str]

    @model_validator(mode="after")
    def _donut_fields_agree(self) -> RenderBundle:
        if self.donut_available and self.donut is None:
            raise ValueError("donut must be set when donut_available is true")
        if not self.donut_available and self.donut is not None:
            raise ValueError("donut must be null when donut_available is false")
        if (self.donut_empty_reason == "no_categories") == self.donut_available:
            raise ValueError("donut_empty_reason is 'no_categories' exactly when there is no donut")
        return self
