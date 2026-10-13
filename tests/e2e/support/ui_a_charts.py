"""Readers for the Plotly DOM of the Sankey and the donut (UI-A suites).

``ChartDom(page)`` wraps the page and answers what a person sees in a drawn chart:

* Sankey: ``sankey_nodes`` / ``sankey_links`` (counts), ``link_fills()`` (the colour of every
  link as ``rgb(r, g, b)``), ``node_labels()``, ``node_label(name)`` (the text of one node).
* Donut: ``donut_slices`` (count), ``donut_labels()`` (one text per slice, e.g. ``Living15.5%``),
  ``donut_center()`` (the total in the middle), ``hover_slice(index)`` (the tooltip text),
  ``donut_texts`` / ``donut_slice(index)`` (the text printed on the slices).
* Legend: ``legend_colours()`` maps a legend label to its swatch colour as ``rgb(r, g, b)``, the
  same notation as ``link_fills()``, so the two can be compared.

Plotly draws SVG, so text is read with ``text_content`` (``inner_text`` is ``None`` there) and
slice labels come in pairs (a visible one and a spacer): ``donut_labels`` drops the repeats.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

SANKEY: Final = "[data-testid=sankey-chart]"
DONUT: Final = "[data-testid=donut-chart]"
HEX: Final = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")
HOVER_WAIT_MS: Final = 400
HOVER_POINTS: Final = ((0.5, 0.5), (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8))
_FILLS_JS = "els => els.map(el => getComputedStyle(el).fill)"
_SWATCH_JS = """els => els.map(el => [
    el.children[1].textContent.trim(),
    el.children[0].style.getPropertyValue('--swatch').trim()])"""


def rgb_of(color: str) -> str:
    """``#2a78d6`` as ``rgb(42, 120, 214)``; any other notation is returned unchanged."""
    found = HEX.match(color)
    if not found:
        return color
    red, green, blue = (int(part, 16) for part in found.groups())
    return f"rgb({red}, {green}, {blue})"


class ChartDom:
    """What is drawn in the Sankey and donut charts of the current page."""

    def __init__(self, page: Page) -> None:
        self.page = page

    # ------------------------------------------------------------------ Sankey

    @property
    def sankey_nodes(self) -> Locator:
        return self.page.locator(f"{SANKEY} .sankey-node")

    @property
    def sankey_links(self) -> Locator:
        return self.page.locator(f"{SANKEY} .sankey-link")

    @property
    def sankey_legend_labels(self) -> Locator:
        """The legend drawn INSIDE the Sankey figure (it travels into SVG, PNG and HTML exports)."""
        return self.page.locator(f"{SANKEY} .legendtext")

    def link_fills(self) -> list[str]:
        return list(self.sankey_links.evaluate_all(_FILLS_JS))

    def node_labels(self) -> list[str]:
        labels = self.page.locator(f"{SANKEY} .node-label")
        return [
            (text or "").strip()
            for text in labels.evaluate_all("els => els.map(e => e.textContent)")
        ]

    def node_label(self, name: str) -> Locator:
        """The ``<text>`` of the label of the node ``name``.

        Plotly splits a label with ``<br>`` into one ``tspan`` per line (a one-line label has none).
        """
        return self.page.locator(f"{SANKEY} text.node-label").filter(has_text=name).first

    def expect_counts(self, nodes: int, links: int) -> None:
        """The chart has ``nodes`` nodes and ``links`` links, in the DOM and in its aria-label."""
        expect(self.sankey_nodes).to_have_count(nodes)
        expect(self.sankey_links).to_have_count(links)
        label = self.page.locator(SANKEY)
        expect(label).to_have_attribute(
            "aria-label", re.compile(rf"{nodes} nodes and {links} links")
        )

    # ------------------------------------------------------------------ donut

    @property
    def donut_slices(self) -> Locator:
        return self.page.locator(f"{DONUT} .slice")

    def donut_labels(self) -> list[str]:
        raw = self.page.locator(f"{DONUT} .slicetext").evaluate_all(
            "els => els.map(e => e.textContent)"
        )
        return list(dict.fromkeys((text or "").strip() for text in raw))

    @property
    def donut_texts(self) -> Locator:
        """The text printed on the slices (one ``text.slicetext`` per slice that has any)."""
        return self.page.locator(f"{DONUT} text.slicetext")

    def donut_slice(self, index: int) -> Locator:
        """The ``<text>`` printed on slice ``index``: ``tspan`` lines such as ``3,800``, ``46%``."""
        return self.donut_texts.nth(index)

    def donut_center(self) -> str:
        center = self.page.locator(f"{DONUT} .annotation-text")
        return (center.first.text_content() or "").strip()

    def hover_slice(self, index: int) -> str:
        """Hover slice ``index`` and return the tooltip text (e.g. ``Living1,280 (15.5%)``).

        The middle of a big slice's box can lie in the hole of the donut, so the pointer tries a
        few points of the box until Plotly shows a tooltip.
        """
        tip = self.page.locator(f"{DONUT} .hoverlayer .hovertext")
        piece = self.donut_slices.nth(index)
        box = piece.bounding_box()
        assert box is not None, "the slice is not on screen"
        for across, down in HOVER_POINTS:
            piece.hover(
                position={"x": box["width"] * across, "y": box["height"] * down}, force=True
            )
            try:
                tip.first.wait_for(state="attached", timeout=HOVER_WAIT_MS)
            except PlaywrightTimeoutError:
                continue
            break
        expect(tip).to_have_count(1)
        return (tip.text_content() or "").strip()

    # ------------------------------------------------------------------ legend

    def legend_colours(self) -> dict[str, str]:
        """Legend label -> swatch colour (``rgb(...)``) of every ``legend-item``."""
        items = self.page.get_by_test_id("legend-item")
        pairs = items.evaluate_all(_SWATCH_JS)
        return {label: rgb_of(color) for label, color in pairs}
