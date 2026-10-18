# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Hostile text for the browser security suite, and the checks that prove a page stayed inert.

``HostileGraph`` holds one saved graph whose name, tag, description, node names, categories and
chart title all carry markup, script text, direction overrides, a control character and (in the
description) an ``<img onerror>`` followed by emoji up to the 2000 character limit. ``Inert``
watches a page: ``Inert(page)`` records every JavaScript dialog (an ``alert`` is a dialog, so any
dialog means code ran) and ``Inert.check()`` asserts that no injected element, handler, inline
script, CSP violation or dialog exists.

``literal_text(chart)`` is what the figure shows as text: the ``text_content`` of every node, link
and label, which must contain the hostile names as plain characters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from tests.e2e.support.builders import csv_text, graph_create

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from playwright.sync_api import Dialog, Locator

    from tests.e2e.support.watch import WatchedPage

EMOJI: Final = "\U0001f600"
IMG: Final = "<img src=x onerror=alert(1)>"
SCRIPT_CLOSE: Final = (
    "</script><script>alert(2)"  # short: Plotly cuts node labels at about 32 characters
)
BOLD: Final = "<b>x</b>"
RLO: Final = chr(0x202E)  # right-to-left override (written as a number: no bidi in the source)
BELL: Final = "\u0007"
NAME: Final = f'{IMG} "><b>x</b> {EMOJI * 60}'
TAG: Final = "<script>x</script>"
DESCRIPTION_MAX: Final = 2000  # characters (docs/api.md section 6: ``description`` <= 2000)
#: Markup FIRST (a card that cuts long text still shows it), then emoji up to the limit.
DESCRIPTION: Final = IMG + EMOJI * (DESCRIPTION_MAX - len(IMG))
TITLE: Final = "</script><svg onload=alert(3)>"
CATEGORY_SCRIPT: Final = "</script>"
BIDI_NODE: Final = f"RLO {RLO}evil"
BELL_NODE: Final = f"Bell{BELL} out"
BELL_CLEAN: Final = "Bell out"

#: Names the figure must show as plain characters (control and direction characters removed).
LITERAL_NODES: Final = (IMG, SCRIPT_CLOSE, "Bell out", "RLO evil")
#: Elements that may never appear inside the page because of the hostile text.
INJECTED: Final = (
    "img[src=x]",
    "[onerror]",
    "[onload]",
    "main b",
    "main script",
    "main iframe",
    "svg script",
)
CATEGORIES: Final = (BOLD, CATEGORY_SCRIPT)


def hostile_csv() -> str:
    rows = [
        (IMG, "Hub", 10, BOLD),
        ("Hub", SCRIPT_CLOSE, 6, CATEGORY_SCRIPT),
        ("Hub", BELL_NODE, 4, BOLD),
        (BIDI_NODE, "Hub", 3, ""),
    ]
    return csv_text(rows, header=("source", "target", "value", "category"))


def hostile_body(name: str = NAME) -> dict[str, Any]:
    draft = {
        "source": {
            "type": "text",
            "origin": "inline",
            "format": "csv",
            "content": hostile_csv(),
        },
        "transform": {},
        "style": {"title": TITLE, "color_mode": "category"},
    }
    return graph_create(name, draft, tags=[TAG], description=DESCRIPTION)


def literal_text(chart: Locator) -> str:
    """All the text the Plotly figure draws, one per line (SVG text needs ``text_content``)."""
    texts = chart.locator("text").evaluate_all("nodes => nodes.map((n) => n.textContent)")
    return "\n".join(str(text) for text in texts)


@dataclass(slots=True)
class Inert:
    """Records JavaScript dialogs of a page and asserts nothing hostile happened."""

    page: WatchedPage
    dialogs: list[str]

    @classmethod
    def watch(cls, page: WatchedPage) -> Inert:
        found: list[str] = []

        def on_dialog(dialog: Dialog) -> None:
            found.append(f"{dialog.type}: {dialog.message}")
            dialog.dismiss()

        page.on("dialog", on_dialog)
        return cls(page, found)

    def injected(self) -> Mapping[str, int]:
        script = (
            "selectors => Object.fromEntries("
            "selectors.map((s) => [s, document.querySelectorAll(s).length]))"
        )
        found = self.page.evaluate(script, list(INJECTED))
        return {selector: count for selector, count in found.items() if count}

    def inline_scripts(self) -> list[str]:
        script = (
            "[...document.querySelectorAll('script:not([src])')].map((s) => s.type + '#' + s.id)"
        )
        return [str(item) for item in self.page.evaluate(script)]

    def check(self) -> None:
        assert self.dialogs == [], f"JavaScript dialogs opened: {self.dialogs}"
        assert self.injected() == {}, f"injected elements: {dict(self.injected())}"
        assert self.inline_scripts() == ["application/json#page-data"], "an inline script exists"
        assert self.page.watch.csp == [], f"CSP violations: {self.page.watch.csp}"
