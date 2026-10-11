"""Text helpers: escaping of user text for Plotly and label truncation.

Plotly renders a small pseudo-HTML subset in labels, titles, legends, annotations and hover
text, so ``<a href="...">`` would become a clickable link even in an exported SVG. EVERY
user-derived string goes through ``escape_label``; user text never enters a ``hovertemplate``.

``escape_label`` also removes the characters that have no glyph or that change how the text around
them is drawn (``strip_unseen``): a bell or an escape character is not valid in XML 1.0, so one in a
node name made the SVG export ill-formed and the PNG export fail, and a right-to-left override
reverses the words that follow it. Quotes are left alone on purpose: Plotly does not decode
``&quot;`` (checked in Chrome: it would be drawn as the six characters), and a quote outside a tag
is inert once ``<`` is escaped.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from sankey_studio.render.numfmt import format_value

if TYPE_CHECKING:
    from sankey_studio.models import StyleSpec

#: Node labels longer than this are cut (the full name stays in the hover text).
LABEL_MAX = 32
ELLIPSIS = "…"

#: C0 controls (tab, line feed and carriage return too), DEL, the C1 block, bidi embeddings and
#: overrides (U+202A-U+202E) and bidi isolates (U+2066-U+2069). Same set as
#: ``static/js/core/text.js`` (which keeps tab, LF and CR for HTML). A regex, not ``str.translate``:
#: ``sub`` hands back the very same string when nothing matches, so a graph of 20 000 clean names
#: is not copied three times (the memory budget of ``build_figure`` counts it).
_UNSEEN: Final = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def strip_unseen(text: str) -> str:
    """``text`` without control characters and without bidirectional overrides and isolates."""
    return _UNSEEN.sub("", text)


def escape_label(text: str) -> str:
    """``text`` stripped of unseen characters, with ``&``, ``<`` and ``>`` as entities.

    ``&`` goes first, so the entities are not doubled; Plotly decodes them back to the literal
    characters, so ``<b>`` is drawn as the three characters.
    """
    return strip_unseen(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def truncate_label(text: str, limit: int = LABEL_MAX) -> str:
    """At most ``limit`` characters followed by an ellipsis; shorter text is returned as is."""
    if len(text) <= limit:
        return text
    return text[:limit] + ELLIPSIS


def value_text(value: float, style: StyleSpec) -> str:
    """``value`` per ``style.value_format`` plus the escaped ``value_suffix``.

    A suffix that starts with a letter or digit (``USD``) is separated by a space; a symbol
    (``%``, ``$``) is attached.
    """
    text = format_value(value, style.value_format)
    suffix = escape_label(style.value_suffix)
    if suffix[:1].isalnum():
        return f"{text} {suffix}"
    return text + suffix
