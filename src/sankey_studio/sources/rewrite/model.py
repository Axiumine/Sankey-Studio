"""Data of the text rewriter: the job, the result and the document model the formats share.

A document is an ordered list of ``Item`` objects. An item is RAW (``pair is None``: header,
comments, blank lines, overlong lines, rows the parser skips: kept byte for byte) or a DATA row
whose ``pair`` is the canonical ``(source, target)``. ``payload`` belongs to the format adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sankey_studio.sources.formats.values import RowError, clean_name, clean_value

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from sankey_studio.models import AddEntry, ReorderNodes, SetCategory, TextSource
    from sankey_studio.sources.base import SourceContext

#: A text longer than this many characters is not rewritten (``file_too_large``).
REWRITE_MAX_BYTES = 8 * 1024 * 1024

Pair = tuple[str, str]


@dataclass(frozen=True, slots=True)
class RewriteJob:
    """One edit of one text. ``alias`` is ``graph.intern.resolve_aliases(merge_nodes)``."""

    spec: TextSource
    text: str
    edit: AddEntry | SetCategory | ReorderNodes
    alias: Mapping[str, str]
    #: Only used to build the parse job of the self-check; it is made lenient there.
    ctx: SourceContext


@dataclass(frozen=True, slots=True)
class Rewritten:
    """The edited text. ``spec`` is the job's spec plus the pins the edit needed (its
    ``content`` is NOT replaced: the caller stores ``text``)."""

    text: str
    spec: TextSource
    changed: int
    #: True when json text was re-serialised (formatting lost); the caller says so once.
    reformatted: bool = False


@dataclass(frozen=True, slots=True, eq=False)
class Item:
    """One piece of the text; compared by identity (a reorder moves the same objects)."""

    chunk: str
    pair: Pair | None = None
    payload: object = None


@dataclass(frozen=True, slots=True)
class NewRow:
    """The entry an ``add_entry`` appends (canonical names, a normalised category)."""

    source: str
    target: str
    value: float
    category: str | None


class TextDoc(Protocol):  # pragma: no mutate block - interface only, never executed
    """What ``apply`` needs from a format adapter."""

    spec: TextSource
    items: list[Item]
    reformatted: bool

    def with_category_column(self, items: list[Item]) -> list[Item]:
        """Make sure a category column/field exists (adds a header cell, pins the spec)."""
        ...

    def terminated(self, items: list[Item]) -> list[Item]:
        """The items with a line break after the last one."""
        ...

    def appended(self, items: list[Item], row: NewRow) -> list[Item]:
        """The items plus the new entry."""
        ...

    def recategorised(self, item: Item, category: str | None) -> Item:
        """A data item with its category set (``None`` clears it); ``item`` itself if unchanged."""
        ...

    def render(self, items: Sequence[Item]) -> str:
        """The text of ``items``."""
        ...


def canon(name: str, alias: Mapping[str, str]) -> str:
    """The node name after merging."""
    return alias.get(name, name)


def data_pair(
    source: object, target: object, value: object, alias: Mapping[str, str]
) -> Pair | None:
    """The canonical pair of a row the parser would turn into a link, else ``None``."""
    try:
        names = clean_name(source, "source"), clean_name(target, "target")
        clean_value(value)
    except RowError:
        return None
    return canon(names[0], alias), canon(names[1], alias)


def rank_key(order: Sequence[str], alias: Mapping[str, str]) -> Callable[[Pair], tuple[int, int]]:
    """Sort key of a pair: (rank of the source, rank of the target); unknown names last."""
    rank = {canon(name, alias): index for index, name in enumerate(order)}
    unknown = len(rank)

    def key(pair: Pair) -> tuple[int, int]:
        return rank.get(pair[0], unknown), rank.get(pair[1], unknown)

    return key


#: Whole numbers below this are written without a fraction (beyond it ``int`` text is long).
WHOLE_MAX = 1e15


def is_whole(value: float) -> bool:
    """Whether ``value`` is written as an integer."""
    return value.is_integer() and value < WHOLE_MAX


def number_text(value: float) -> str:
    """``value`` as the parsers read it back: a plain integer, else the shortest exact decimal."""
    return str(int(value)) if is_whole(value) else repr(value)
