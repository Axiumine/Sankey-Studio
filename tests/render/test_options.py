"""Option types (SPEC section 2.1): the defaults later waves rely on, spelled out."""

from __future__ import annotations

from sankey_studio.models.base import ENTRIES_PAGE_MAX
from sankey_studio.render.options import EntriesOptions, FigureOptions, ImageOptions


def test_image_options_defaults() -> None:
    assert ImageOptions() == ImageOptions(width=1200, height=None, scale=2.0, transparent=False)


def test_figure_options_defaults() -> None:
    options = FigureOptions()
    assert options.max_links is None
    assert options.colors is None


def test_entries_options_defaults_and_their_window() -> None:
    options = EntriesOptions()
    assert options == EntriesOptions(
        q=None, only_uncategorized=False, sort="value", offset=0, limit=100
    )
    assert options.window() == (0, 100)
    assert ENTRIES_PAGE_MAX == 500
