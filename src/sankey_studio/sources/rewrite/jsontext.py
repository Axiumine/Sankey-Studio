"""JSON adapter: one array of entry objects, or NDJSON (any run of objects).

Array: every element is an item, the text is re-serialised (``indent=2``, ``ensure_ascii=False``)
when it changes, and ``reformatted`` says whether that loses the person's formatting. NDJSON: the
text between objects is kept as raw items and only a touched object is re-dumped in place.
An edit only ever touches the ``category`` member of an object; non-object elements of an array
keep their slot.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

from sankey_studio.errors import SourceEditRefused
from sankey_studio.sources.rewrite.lines import dominant_eol, peel_bom
from sankey_studio.sources.rewrite.model import Item, data_pair, is_whole

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sankey_studio.sources.rewrite.model import NewRow, RewriteJob

_NON_SPACE_RE = re.compile(r"[^ \t\r\n]")
_DECODER = json.JSONDecoder()
CATEGORY_KEY = "category"


def dumps(value: object, *, indent: int | None = None) -> str:
    """JSON text that keeps non-ASCII characters readable."""
    return json.dumps(value, indent=indent, ensure_ascii=False)


def entry_object(row: NewRow) -> dict[str, Any]:
    """The JSON object of a new entry (whole values stay integers)."""
    value = int(row.value) if is_whole(row.value) else row.value
    obj: dict[str, Any] = {"source": row.source, "target": row.target, "value": value}
    if row.category is not None:
        obj[CATEGORY_KEY] = row.category
    return obj


def _pair_of(element: object, alias: Mapping[str, str]) -> tuple[str, str] | None:
    if not isinstance(element, dict):
        return None
    return data_pair(element.get("source"), element.get("target"), element.get("value"), alias)


def _with_category(obj: dict[str, Any], category: str | None) -> dict[str, Any] | None:
    """``obj`` with its category set or removed; ``None`` when that changes nothing."""
    if category is None:
        return (
            None if CATEGORY_KEY not in obj else {k: v for k, v in obj.items() if k != CATEGORY_KEY}
        )
    if obj.get(CATEGORY_KEY) == category:
        return None
    return {**obj, CATEGORY_KEY: category}


class JsonDoc:
    """A JSON text as items."""

    def __init__(self, job: RewriteJob) -> None:
        self.spec = job.spec
        self._alias = job.alias
        self._bom, body = peel_bom(job.text)
        self._eol = dominant_eol(body)
        self.array = body.lstrip(" \t\r\n").startswith("[")
        try:
            self.items = self._array_items(body) if self.array else self._line_items(body)
        except ValueError, RecursionError:
            raise SourceEditRefused("unreadable") from None
        #: Whether writing the text back loses its formatting.
        self.reformatted = self.array and self.render(self.items) != job.text

    def _array_items(self, body: str) -> list[Item]:
        elements: list[Any] = json.loads(body)  # the text starts with "[": a list or an error
        return [Item("", _pair_of(element, self._alias), element) for element in elements]

    def _line_items(self, body: str) -> list[Item]:
        items: list[Item] = []
        position = 0
        while found := _NON_SPACE_RE.search(body, position):
            if found.start() > position:
                items.append(Item(body[position : found.start()]))
            obj, end = _DECODER.raw_decode(body, found.start())
            if not isinstance(obj, dict):
                raise ValueError("not an object")  # noqa: TRY004 - caught by the caller
            items.append(Item(body[found.start() : end], _pair_of(obj, self._alias), obj))
            position = end
        if position < len(body):
            items.append(Item(body[position:]))
        return items

    # ------------------------------------------------------------------ TextDoc

    def with_category_column(self, items: list[Item]) -> list[Item]:
        return items  # a category is just a member of the object

    def terminated(self, items: list[Item]) -> list[Item]:
        if self.array or not items or items[-1].chunk.endswith(("\n", "\r")):
            return items
        return [*items, Item(self._eol)]

    def appended(self, items: list[Item], row: NewRow) -> list[Item]:
        obj = entry_object(row)
        chunk = "" if self.array else dumps(obj) + self._eol
        return [*items, Item(chunk, (row.source, row.target), obj)]

    def recategorised(self, item: Item, category: str | None) -> Item:
        old = cast("dict[str, Any]", item.payload)  # only objects are data items
        obj = _with_category(old, category)
        if obj is None:
            return item
        if self.array:
            return Item("", item.pair, obj)
        text = dumps(obj)
        self.reformatted = self.reformatted or dumps(old) != item.chunk
        return Item(text, item.pair, obj)

    def render(self, items: Sequence[Item]) -> str:
        if self.array:
            return self._bom + dumps([item.payload for item in items], indent=2) + "\n"
        return self._bom + "".join(item.chunk for item in items)


def json_text(row: NewRow) -> str:
    """The text of an empty JSON source holding one entry."""
    return dumps([entry_object(row)], indent=2) + "\n"
