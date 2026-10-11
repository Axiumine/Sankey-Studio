"""Helpers of ``test_routes_{preview,graphs,compare,exports}*.py`` (no tests here)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from sankey_studio.models import GraphCreate, GraphDefinition

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import WebApp

API: Final = "/api/v1"
#: A well-formed graph id that is never stored.
UNKNOWN_ID: Final = "0" * 32
#: Not graph ids: the repository answers 404 for each of them.
MALFORMED_IDS: Final = ["short", "g" * 32, "A" * 32, "a" * 31, "a" * 33, "x.y", "%20" * 3]

Link = tuple[str, str, float, str | None]
#: (source, target, value, category): two categories and one uncategorised flow.
BUDGET: Final[tuple[Link, ...]] = (
    ("Salary", "Budget", 3000.0, "Income"),
    ("Freelance", "Budget", 1000.0, "Income"),
    ("Budget", "Rent", 1200.0, "Housing"),
    ("Budget", "Food", 600.0, None),
)
#: Two flows and no category at all.
PLAIN: Final[tuple[Link, ...]] = (("a", "b", 10.0, None), ("b", "c", 4.0, None))


def manual_source(*links: Link) -> dict[str, Any]:
    return {
        "type": "manual",
        "links": [{"source": s, "target": t, "value": v, "category": c} for s, t, v, c in links],
    }


def draft_json(*links: Link, **parts: Any) -> dict[str, Any]:
    """The JSON of a ``GraphDraft`` over a manual source; ``parts`` adds transform/style."""
    return {"source": manual_source(*links), **parts}


def graph_json(name: str, *links: Link, **parts: Any) -> dict[str, Any]:
    """The JSON body of ``POST /graphs``."""
    return {"name": name, **draft_json(*links), **parts}


def csv_source(rows: int) -> dict[str, Any]:
    """An inline CSV source with ``rows`` distinct flows ``n0 -> m0`` ... of value 1, 2, ..."""
    lines = ["source,target,value", *(f"n{i},m{i},{i + 1}" for i in range(rows))]
    return {"type": "text", "origin": "inline", "format": "csv", "content": "\n".join(lines)}


def grid_source(links: int) -> dict[str, Any]:
    """An inline CSV of ``links`` distinct flows between 50 sources and few targets."""
    lines = ["source,target,value", *(f"s{i % 50},t{i // 50},1" for i in range(links))]
    return {"type": "text", "origin": "inline", "format": "csv", "content": "\n".join(lines)}


def save(web: WebApp, name: str, *links: Link, **parts: Any) -> GraphDefinition:
    """Store a manual-source graph directly in the repository (no HTTP, no guard)."""
    return web.services.graphs().create(
        GraphCreate.model_validate(graph_json(name, *links, **parts))
    )


def save_source(web: WebApp, name: str, source: dict[str, Any], **parts: Any) -> GraphDefinition:
    """Store a graph over any source JSON."""
    body = {"name": name, "source": source, **parts}
    return web.services.graphs().create(GraphCreate.model_validate(body))


def save_csv(web: WebApp, name: str, rows: int) -> GraphDefinition:
    """Store a graph over an inline CSV of ``rows`` flows (see ``csv_source``)."""
    return save_source(web, name, csv_source(rows))


def put_graph(web: WebApp, number: int, name: str, tags: list[str] | None = None) -> str:
    """Store a graph verbatim with id ``number`` (hex) and ``updated_at`` = minute ``number``.

    The list order is ``updated_at`` descending, so the numbers give tests a fixed order.
    """
    stamp = datetime(2026, 1, 1, 12, number, tzinfo=UTC)
    definition = GraphDefinition.model_validate(
        {
            **graph_json(name, *PLAIN, tags=tags or []),
            "id": f"{number:032x}",
            "created_at": stamp,
            "updated_at": stamp,
        }
    )
    return web.services.graphs().put(definition).id


def put_filler(web: WebApp, number: int, chars: int) -> str:
    """Store graph ``number`` (hex id, fixed stamps) over an inline text of ``chars`` letters.

    A letter is one byte in the JSON of a bundle, so the size of an export is exact arithmetic.
    """
    stamp = datetime(2026, 1, 1, 12, number, tzinfo=UTC)
    source = {"type": "text", "origin": "inline", "format": "csv", "content": "a" * chars}
    definition = GraphDefinition.model_validate(
        {
            "name": f"Filler {number}",
            "source": source,
            "id": f"{number:032x}",
            "created_at": stamp,
            "updated_at": stamp,
        }
    )
    return web.services.graphs().put(definition).id


def ids_of(count: int) -> str:
    """``count`` distinct well-formed ids, comma separated (none of them stored)."""
    return ",".join(f"{number:032x}" for number in range(1, count + 1))


def code(response: Response) -> str:
    """The ``error.code`` of an error envelope."""
    return str(response.json()["error"]["code"])
