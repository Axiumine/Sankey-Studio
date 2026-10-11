"""What an exported HTML page is made of, read the way a browser reads it (``html.parser``)."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser


class PageShape(HTMLParser):
    """Counts the start tags of a page and keeps the text of its ``<title>``.

    ``<script>`` and ``<style>`` bodies are raw text for the parser (a ``<b>`` inside the figure
    JSON is not a tag), exactly as for a browser. A hostile name that closes ``</title>`` or opens
    ``<script>`` by itself therefore shows up as a second ``title``/``script`` start tag and as a
    changed title text.
    """

    def __init__(self, page: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: Counter[str] = Counter()
        self.title = ""
        self._in_title = False
        self.feed(page)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002 - the parser's signature
        self.tags[tag] += 1
        self._in_title = tag == "title"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
