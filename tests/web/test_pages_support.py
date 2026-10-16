# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers of ``test_pages*.py`` and ``test_static*.py``: read a page like a browser would.

No tests here. ``parse(response)`` runs the standard HTML parser over a page and keeps what a
security review cares about: every tag that was opened and every ``<script>`` with its attributes
and text. A page is safe when its only script is the JSON data block and no injected tag exists.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from httpx2 import Response

DATA_ID = "page-data"
JSON_TYPE = "application/json"


class Script(NamedTuple):
    attrs: dict[str, str | None]
    text: str


class Link(NamedTuple):
    """One ``<a href>``: where it sits (``nav``, ``noscript`` or ``page``), its text and test id."""

    href: str
    text: str
    testid: str | None
    area: str


class Page(NamedTuple):
    tags: list[str]
    scripts: list[Script]
    attrs: list[tuple[str, str | None]]
    links: list[Link]
    elements: list[tuple[str, dict[str, str | None]]]

    def find(self, tag: str, **where: str) -> list[dict[str, str | None]]:
        """The attributes of every ``<tag>`` whose attributes include ``where`` (``_`` is ``-``)."""
        wanted = {key.replace("_", "-"): value for key, value in where.items()}
        return [
            attrs
            for name, attrs in self.elements
            if name == tag and all(attrs.get(key) == value for key, value in wanted.items())
        ]

    def elements_with_class(
        self, name: str | None, *, tag: str | None = None
    ) -> list[dict[str, str | None]]:
        """The attributes of every element with class ``name`` (any if ``None``) and tag ``tag``."""
        return [
            attrs
            for element, attrs in self.elements
            if (tag is None or element == tag)
            and (name is None or name in (attrs.get("class") or "").split())
        ]

    def nav_links(self) -> list[tuple[str, str]]:
        """``(href, text)`` of the header navigation and the no-JavaScript fallback list."""
        return [(link.href, link.text) for link in self.links if link.area in {"nav", "noscript"}]

    def data(self) -> dict[str, Any]:
        """The JSON of the ``page-data`` block (exactly one must exist)."""
        (block,) = [s for s in self.scripts if s.attrs.get("id") == DATA_ID]
        loaded: dict[str, Any] = json.loads(block.text)
        return loaded


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.scripts: list[Script] = []
        self.attrs: list[tuple[str, str | None]] = []
        self.links: list[Link] = []
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self._open: dict[str, str | None] | None = None
        self._text: list[str] = []
        self._area = "page"
        self._link: dict[str, str | None] | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attrs.extend(attrs)
        self.elements.append((tag, dict(attrs)))
        if tag == "script":
            self._open = dict(attrs)
            self._text = []
        elif tag in {"nav", "noscript"}:
            self._area = tag
        elif tag == "a" and "href" in dict(attrs):
            self._link = dict(attrs)
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._text.append(data)
        if self._link is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._open is not None:
            self.scripts.append(Script(self._open, "".join(self._text)))
            self._open = None
        elif tag in {"nav", "noscript"}:
            self._area = "page"
        elif tag == "a" and self._link is not None:
            href = self._link["href"] or ""
            text = "".join(self._link_text).strip()
            self.links.append(Link(href, text, self._link.get("data-testid"), self._area))
            self._link = None


def unversioned(url: str) -> str:
    """``url`` without the ``v-<digest>/`` segment ``web/assets.py`` puts after ``/static/``."""
    return re.sub(r"^/static/v-[0-9a-f]{12}/", "/static/", url)


def parse_text(text: str) -> Page:
    """Parse an HTML string."""
    collector = _Collector()
    collector.feed(text)
    collector.close()
    return Page(
        collector.tags, collector.scripts, collector.attrs, collector.links, collector.elements
    )


def parse(response: Response) -> Page:
    """Parse the body of a response."""
    return parse_text(response.text)
