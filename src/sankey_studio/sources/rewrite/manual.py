"""Manual source: the same three edits over ``ManualSource.links``.

``set_category`` goes by the canonical pair (names after ``merge_nodes``), which is what fixes the
raw-versus-merged mismatch of the browser-side edit. A manual source has one authority, so a full
list is an error (``too_many``), not an overlay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sankey_studio.errors import SourceEditRefused
from sankey_studio.models import MAX_MANUAL_LINKS, AddEntry, Link, SetCategory
from sankey_studio.sources.rewrite.model import canon, rank_key

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sankey_studio.models import ReorderNodes


def rewrite_links(
    links: Sequence[Link], edit: AddEntry | SetCategory | ReorderNodes, alias: Mapping[str, str]
) -> list[Link]:
    """The links after ``edit`` (new ``Link`` objects, validated)."""
    if isinstance(edit, AddEntry):
        return _added(links, edit)
    if isinstance(edit, SetCategory):
        return _categorised(links, edit, alias)
    key = rank_key(edit.order, alias)
    return sorted(links, key=lambda link: key((link.source, link.target)))


def _added(links: Sequence[Link], edit: AddEntry) -> list[Link]:
    if len(links) >= MAX_MANUAL_LINKS:
        raise SourceEditRefused("too_many")
    link = Link.model_validate(
        {
            "source": edit.source,
            "target": edit.target,
            "value": edit.value,
            "category": edit.category,
        }
    )
    return [*links, link]


def _categorised(links: Sequence[Link], edit: SetCategory, alias: Mapping[str, str]) -> list[Link]:
    pair = (canon(edit.source, alias), canon(edit.target, alias))

    def matches(link: Link) -> bool:
        return (canon(link.source, alias), canon(link.target, alias)) == pair

    if not any(matches(link) for link in links):
        raise SourceEditRefused("no_match")
    return [
        Link.model_validate({**link.model_dump(), "category": edit.category})
        if matches(link)
        else link
        for link in links
    ]
