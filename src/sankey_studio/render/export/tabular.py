"""CSV export with the OWASP guard against spreadsheet formula injection."""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Literal

from sankey_studio.errors import NoCategoriesError
from sankey_studio.render.donut_fold import NO_CATEGORIES_TEXT, category_totals
from sankey_studio.util import starts_like_formula

if TYPE_CHECKING:
    from sankey_studio.models import SankeyGraph
    from sankey_studio.render.donut_fold import Basis


def csv_cell(text: str) -> str:
    """Prefix ``'`` when a spreadsheet could execute ``text``.

    Triggers: the text starts with ``= + - @`` after leading blanks, or the raw text starts with a
    tab or carriage return.
    """
    if starts_like_formula(text):
        return "'" + text
    return text


def _text(rows: list[list[str]]) -> str:
    """Quote and join rows; every cell has already been guarded by the caller."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def export_csv(graph: SankeyGraph, *, chart: Literal["sankey", "donut"], basis: Basis) -> str:
    """``source,target,value,category`` per link, or ``category,value,share`` for the donut."""
    if chart == "sankey":
        rows = [["source", "target", "value", "category"]]
        for link in range(graph.n_links):
            category = graph.link_category[link]
            rows.append(
                [
                    graph.node_names[graph.link_source[link]],
                    graph.node_names[graph.link_target[link]],
                    repr(graph.link_value[link]),
                    "" if category < 0 else graph.categories[category],
                ]
            )
    else:
        if not graph.has_categories:
            raise NoCategoriesError(NO_CATEGORIES_TEXT)
        rows = [["category", "value", "share"]]
        rows.extend(
            [total.name, repr(total.value), repr(total.share)]
            for total in category_totals(graph, basis)
        )
    return _text([[csv_cell(cell) for cell in row] for row in rows])
