"""Data builders of the e2e suites: CSV text, sample graphs, request payloads, Mongo seeds.

``csv_text(rows, header=None)``
    CSV text from row tuples. ``header=None`` picks ``source,target,value`` (3 columns) or
    ``source,target,value,category`` (4); ``header=()`` writes no header line.

``Sample`` and the ready-made samples (``csv`` plus what the app reports in ``stats``):

* ``BUDGET`` - UI.md flow F1, no categories: Salary/Freelance -> Budget -> Rent/Utilities/Food/
  Transport/Savings, Food -> Groceries/Restaurants. 10 nodes, 9 links, 4 columns, 3,800 in and out.
* ``BUDGET_CATEGORISED`` - the same links with a ``category`` column (Income, Housing, Food,
  Transport, Savings); ``categories`` holds the flow per category over ALL links (donut basis
  ``all``: 3,800 + 1,460 + 1,280 + 230 + 1,470 = 8,240).
* ``LAYERED`` - a 3-level graph: A -> M1/M2 -> X/Y/Z (6 nodes, 6 links, 3 columns, 16 in and out).
* ``CYCLE`` - Start -> A -> B -> C -> A. ``on_cycle="error"`` is a 422 ``graph_build_error``;
  with ``on_cycle="break"`` it draws (the stats are those AFTER breaking: 4 nodes, 3 links).
* ``MANY_LINKS`` / ``many_links(links)`` - 300 distinct links S000..S019 -> T000..T014, values 1..9.

Payload factories (dicts, JSON ready):

* ``graph_draft(content=BUDGET.csv, *, source=, transform=, style=)`` - the body of ``/preview``,
  ``/entries`` and ``POST /export``: an inline CSV text source; the keyword mappings are merged on
  top of the defaults (``source={"category_column": "kind"}``, ``transform={"on_cycle": "break"}``).
* ``graph_create(name, draft=None, *, tags=(), description="")`` - the body of ``POST /graphs``.
* ``unique_name(prefix)`` - ``"<prefix> <8 hex>"``: a graph name no other test uses.

Mongo (mongomock) seeds: ``seed_flows`` (a ``seed_mongo`` option: database ``flows``, collection
``transfers``, fields ``from``/``to``/``amount``/``kind``), ``mongo_settings(name, database)`` (a
``settings`` option with one connection whose URI holds the password ``MONGO_PASSWORD``, which
no response, page or log may ever contain).
"""

from __future__ import annotations

import csv
import io
import math
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from pydantic import SecretStr

from sankey_studio.models import MongoConnection

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from pymongo import MongoClient

DEFAULT_HEADERS: Final = {
    3: ("source", "target", "value"),
    4: ("source", "target", "value", "category"),
}
MONGO_PASSWORD: Final = "hunter2"
MONGO_URI: Final = f"mongodb://tester:{MONGO_PASSWORD}@mongo.invalid:27017/?appName=e2e"
FLOWS_DATABASE: Final = "flows"
FLOWS_COLLECTION: Final = "transfers"


def csv_text(rows: Iterable[Sequence[object]], header: Sequence[str] | None = None) -> str:
    """CSV text (``\\n`` line ends) of ``rows``; see the module doc for ``header``."""
    body = [tuple(row) for row in rows]
    if header is None:
        header = DEFAULT_HEADERS.get(len(body[0]) if body else 3, DEFAULT_HEADERS[3])
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    if header:
        writer.writerow(header)
    writer.writerows(body)
    return out.getvalue()


@dataclass(frozen=True, slots=True)
class Sample:
    """A CSV text and what the app reports for it (``RenderBundle.stats``)."""

    csv: str
    nodes: int
    links: int
    total: float
    layers: int
    categories: Mapping[str, float] = field(default_factory=dict)

    @property
    def category_count(self) -> int:
        return len(self.categories)


_BUDGET_LINKS: Final = (
    ("Salary", "Budget", 3000, "Income"),
    ("Freelance", "Budget", 800, "Income"),
    ("Budget", "Rent", 1200, "Housing"),
    ("Budget", "Utilities", 260, "Housing"),
    ("Budget", "Food", 640, "Food"),
    ("Budget", "Transport", 230, "Transport"),
    ("Budget", "Savings", 1470, "Savings"),
    ("Food", "Groceries", 500, "Food"),
    ("Food", "Restaurants", 140, "Food"),
)

BUDGET: Final = Sample(
    csv_text([row[:3] for row in _BUDGET_LINKS]), nodes=10, links=9, total=3800.0, layers=4
)
BUDGET_CATEGORISED: Final = Sample(
    csv_text(_BUDGET_LINKS),
    nodes=10,
    links=9,
    total=3800.0,
    layers=4,
    categories={
        "Income": 3800.0,
        "Housing": 1460.0,
        "Food": 1280.0,
        "Transport": 230.0,
        "Savings": 1470.0,
    },
)
LAYERED: Final = Sample(
    csv_text(
        [
            ("A", "M1", 10),
            ("A", "M2", 6),
            ("M1", "X", 7),
            ("M1", "Y", 3),
            ("M2", "Y", 4),
            ("M2", "Z", 2),
        ]
    ),
    nodes=6,
    links=6,
    total=16.0,
    layers=3,
)
CYCLE: Final = Sample(
    csv_text([("Start", "A", 4), ("A", "B", 5), ("B", "C", 3), ("C", "A", 2)]),
    nodes=4,
    links=3,
    total=4.0,
    layers=4,
)
MANY_LINKS_FAN: Final = 15  # targets per source


def many_links(links: int = 300) -> Sample:
    """``links`` distinct links ``S<i> -> T<j>`` (``j`` < 15), values 1..9, no categories."""
    pairs = [divmod(k, MANY_LINKS_FAN) for k in range(links)]
    rows = [(f"S{i:03d}", f"T{j:03d}", 1 + (i * 7 + j * 3) % 9) for i, j in pairs]
    sources = math.ceil(links / MANY_LINKS_FAN)
    targets = min(links, MANY_LINKS_FAN)
    return Sample(
        csv_text(rows),
        nodes=sources + targets,
        links=links,
        total=float(sum(row[2] for row in rows)),
        layers=2,
    )


MANY_LINKS: Final = many_links(300)


def _merged(base: dict[str, Any], extra: Mapping[str, Any] | None) -> dict[str, Any]:
    return {**base, **(extra or {})}


def graph_draft(
    content: str = BUDGET.csv,
    *,
    source: Mapping[str, Any] | None = None,
    transform: Mapping[str, Any] | None = None,
    style: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A ``GraphDraft`` body: inline CSV ``content`` plus merged source/transform/style."""
    base = {"type": "text", "origin": "inline", "format": "csv", "content": content}
    return {
        "source": _merged(base, source),
        "transform": dict(transform or {}),
        "style": dict(style or {}),
    }


def graph_create(
    name: str,
    draft: Mapping[str, Any] | None = None,
    *,
    tags: Sequence[str] = (),
    description: str = "",
) -> dict[str, Any]:
    """A ``POST /graphs`` body: name, tags, description and the draft (default: the budget)."""
    body = dict(draft if draft is not None else graph_draft())
    return {"name": name, "description": description, "tags": list(tags), **body}


def unique_name(prefix: str) -> str:
    """``"<prefix> <8 hex digits>"``: unique per call, so tests never share a graph name."""
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# ------------------------------------------------------------------------------ mongomock seeds

FLOW_DOCS: Final = (
    {"from": "Salary", "to": "Account", "amount": 3000, "kind": "Income"},
    {"from": "Account", "to": "Rent", "amount": 1200, "kind": "Housing"},
    {"from": "Account", "to": "Food", "amount": 640, "kind": "Food"},
    {"from": "Account", "to": "Transport", "amount": 230, "kind": "Transport"},
    {"from": "Account", "to": "Savings", "amount": 930, "kind": "Savings"},
)


def seed_flows(client: MongoClient[Any]) -> None:
    """``seed_mongo`` hook: ``flows.transfers`` with ``FLOW_DOCS`` (3,000 in, 3,000 out)."""
    client[FLOWS_DATABASE][FLOWS_COLLECTION].insert_many([dict(doc) for doc in FLOW_DOCS])


def mongo_settings(name: str = "main", database: str = FLOWS_DATABASE) -> dict[str, Any]:
    """A ``settings`` option value: one connection ``name`` (mongomock answers; never dialled)."""
    connection = MongoConnection(name=name, uri=SecretStr(MONGO_URI), default_database=database)
    return {"mongo_connections": [connection]}
