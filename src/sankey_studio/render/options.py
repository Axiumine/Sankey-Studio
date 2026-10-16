# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Option types: one small frozen dataclass per purpose, never a fifth parameter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sankey_studio.models.base import ENTRIES_PAGE_MAX

if TYPE_CHECKING:
    from sankey_studio.render.colors import ColorMap

ImageFormat = Literal["svg", "png"]
EntrySort = Literal["value", "source", "target", "category"]


@dataclass(frozen=True, slots=True)
class ImageOptions:
    """What the caller asks of an image export (clamped by ``resolve_image``)."""

    width: int = 1200
    height: int | None = None
    scale: float = 2.0
    transparent: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedImage:
    """The numbers the Chrome seam receives: clamped, and checked against the pixel cap."""

    fmt: ImageFormat
    width: int
    height: int
    scale: float


@dataclass(frozen=True, slots=True)
class FigureOptions:
    """Extras of ``build_figure`` / ``build_donut_figure``.

    ``max_links`` (Sankey only) draws the top-N links by value. ``colors`` is the category map of
    the compare view; node colours always come from the graph itself.
    """

    max_links: int | None = None
    colors: ColorMap | None = None


@dataclass(frozen=True, slots=True)
class EntriesOptions:
    """Filter, sort and page of the entries table."""

    q: str | None = None
    only_uncategorized: bool = False
    sort: EntrySort = "value"
    offset: int = 0
    limit: int = 100

    def window(self) -> tuple[int, int]:
        """``(offset, limit)`` clamped to ``0 <= offset`` and ``0 <= limit <= ENTRIES_PAGE_MAX``."""
        return max(self.offset, 0), min(max(self.limit, 0), ENTRIES_PAGE_MAX)
