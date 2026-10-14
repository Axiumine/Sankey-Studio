"""The fixed English sentence of every reason an edit stays in the graph.

Sentences never hold cell text, file content, URIs or driver messages: the browser shows them
as they are. ``NOTICES`` has one sentence per ``Reason`` except the silent ones (the person
chose them, or they are the normal case); a contract test pins that equality.
"""

from __future__ import annotations

from typing import Final

#: Said once (reason ``None``) when the first edit of inline json text re-formatted it.
REFORMATTED_NOTICE: Final = "Your JSON text was re-formatted."

_KEPT = "your change stays in this graph"

NOTICES: Final[dict[str, str]] = {
    "read_only_mode": (
        "This server is read-only here: your change stays in this graph and is not written "
        "to the source."
    ),
    "no_consent": "Writing to the source needs your permission first.",
    "no_match": f"No row or document matches that entry, so {_KEPT}.",
    "unsupported_format": f"This text cannot be edited in place, so {_KEPT}.",
    "file_too_large": f"The data is too large to rewrite, so {_KEPT}.",
    "cannot_verify": (f"The edited data could not be checked, so nothing was written and {_KEPT}."),
    "unreadable": f"The data could not be read for editing, so {_KEPT}.",
    "unrepresentable": f"The file's encoding cannot hold that text, so {_KEPT}.",
    "too_many": "There are too many entries to add another one.",
    "aggregate_mode": f"This collection is read through an aggregation, so {_KEPT}.",
    "source_incomplete": (
        f"The source names no connection, database or collection to write to, so {_KEPT}."
    ),
    "no_category_field": (
        "Choose the category field in the Source panel to save categories in MongoDB."
    ),
    "no_value_field": "Choose the value field in the Source panel to add entries to MongoDB.",
    "filter_not_equality": (
        f"The source filter is not a plain equality, so a new document would not match it and "
        f"{_KEPT}."
    ),
    "field_conflict": f"Two mapped fields overlap, so {_KEPT}.",
    "too_many_aliases": f"Too many nodes are merged into these names, so {_KEPT}.",
    "reserved_collection": (
        f"That collection belongs to this application or to the database system, so {_KEPT}."
    ),
    "unsafe_value": (
        "That text could be read as a spreadsheet formula, so it was kept in this graph only."
    ),
    "limit_reached": (
        f"The source already reads its limit of documents, so a new one would not show up and "
        f"{_KEPT}."
    ),
    "too_many_documents": f"The change would touch more than 1000 documents, so {_KEPT}.",
    "permission_denied": f"The database user may not write there, so {_KEPT}.",
    "write_rejected": f"The database refused the new document, so {_KEPT}.",
    "would_recolour": (
        "Rows were not reordered because that would change the colours. The order is kept in "
        "this graph."
    ),
}


def notice_for(reason: str | None) -> str | None:
    """The sentence for ``reason``; ``None`` for no reason and for the silent ones."""
    return None if reason is None else NOTICES.get(reason)
