"""Graph bundles: export saved graphs to one JSON document and import them back.

Format ``{"format": "sankey-studio/graphs", "version": 1, "graphs": [<GraphDefinition dump>]}``.
A bundle holds no secrets (a Mongo source names its connection, it never carries a URI). Import
validates every graph with pydantic on its own, so one bad graph never blocks the others; the
report lists what failed (by position, never by content). The byte cap of the request body is the
web layer's business; ``MAX_BUNDLE_GRAPHS`` bounds the graph count here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from sankey_studio.errors import BundleError, ConflictError, StorageError
from sankey_studio.models import GraphCreate, GraphDefinition
from sankey_studio.storage.base import upgrade_doc
from sankey_studio.storage.common import validation_lines

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sankey_studio.storage.base import GraphRepository

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "GRAPH_ROOT",
    "IMPORT_MODES",
    "MAX_BUNDLE_GRAPHS",
    "MAX_REPORTED_ERRORS",
    "BundleError",
    "ImportMode",
    "ImportReport",
    "export_bundle",
    "import_bundle",
]

BUNDLE_FORMAT = "sankey-studio/graphs"
BUNDLE_VERSION = 1
MAX_BUNDLE_GRAPHS = 1000
MAX_REPORTED_ERRORS = 50
#: Location label of an error that belongs to a bundle graph as a whole.
GRAPH_ROOT = "graph"

ImportMode = Literal["new_ids", "keep_ids"]
IMPORT_MODES = ("new_ids", "keep_ids")


@dataclass(frozen=True, slots=True)
class ImportReport:
    """``imported`` graphs (their ids in ``ids``), ``failed`` ones (first ``errors`` explained)."""

    imported: int
    failed: int
    ids: list[str]
    errors: list[str]


class _ItemError(ValueError):
    """One graph of the bundle cannot be used."""


@dataclass(slots=True)
class _Tally:
    ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed: int = 0

    def fail(self, position: int, reason: str) -> None:
        self.failed += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(f"graph {position}: {reason}")

    def report(self) -> ImportReport:
        return ImportReport(len(self.ids), self.failed, self.ids, self.errors)


def export_bundle(repo: GraphRepository, ids: Sequence[str] | None = None) -> dict[str, Any]:
    """The listed graphs (given order, duplicates dropped), or every graph when ``ids`` is None.

    ``NotFoundError`` for an unknown id; ``BundleError`` beyond ``MAX_BUNDLE_GRAPHS`` graphs.
    """
    graphs = repo.iter_definitions() if ids is None else map(repo.get, dict.fromkeys(ids))
    dumps = [graph.model_dump(mode="json") for graph in islice(graphs, MAX_BUNDLE_GRAPHS + 1)]
    if len(dumps) > MAX_BUNDLE_GRAPHS:
        raise BundleError(f"A bundle may hold at most {MAX_BUNDLE_GRAPHS} graphs")
    return {"format": BUNDLE_FORMAT, "version": BUNDLE_VERSION, "graphs": dumps}


def _graph_list(bundle: object) -> list[object]:
    if not isinstance(bundle, dict) or bundle.get("format") != BUNDLE_FORMAT:
        raise BundleError("This is not a sankey-studio graph bundle")
    version = bundle.get("version")
    if type(version) is not int or version != BUNDLE_VERSION:  # bool is an int: refuse it too
        raise BundleError("Unsupported bundle version")
    graphs = bundle.get("graphs")
    if not isinstance(graphs, list):
        raise BundleError("The bundle has no list of graphs")
    if len(graphs) > MAX_BUNDLE_GRAPHS:
        raise BundleError(f"A bundle may hold at most {MAX_BUNDLE_GRAPHS} graphs")
    return graphs


def _parse(item: object) -> GraphDefinition:
    if not isinstance(item, dict):
        raise _ItemError("not an object")
    try:
        return GraphDefinition.model_validate(upgrade_doc(item))
    except StorageError as exc:  # an unusable schema_version
        raise _ItemError(exc.message) from None
    except ValidationError as exc:
        lines = validation_lines(exc, GRAPH_ROOT)
        more = f" (+{len(lines) - 1} more)" if len(lines) > 1 else ""
        raise _ItemError(lines[0] + more) from None


def _as_create(graph: GraphDefinition) -> GraphCreate:
    return GraphCreate(
        name=graph.name,
        description=graph.description,
        tags=graph.tags,
        source=graph.source,
        transform=graph.transform,
        style=graph.style,
    )


def _store(repo: GraphRepository, graph: GraphDefinition, mode: ImportMode) -> str:
    if mode == "keep_ids":
        return repo.put(graph).id  # ConflictError when the id is taken
    return repo.create(_as_create(graph)).id


def import_bundle(
    repo: GraphRepository, bundle: object, mode: ImportMode = "new_ids"
) -> ImportReport:
    """Store every valid graph of ``bundle``; ``new_ids`` -> ``create``, ``keep_ids`` -> ``put``.

    ``mode`` defaults to ``new_ids``: fresh ids, so an import can never collide with a stored graph.

    Raises ``BundleError`` for an unknown ``mode`` or an unusable bundle (nothing is stored); a
    backend failure (``StorageError``) aborts the import. Invalid graphs and taken ids
    (``keep_ids``) are counted and explained in the report.
    """
    if mode not in IMPORT_MODES:
        raise BundleError(f"Unknown import mode; use one of: {', '.join(IMPORT_MODES)}")
    tally = _Tally()
    for position, item in enumerate(_graph_list(bundle), start=1):
        try:
            tally.ids.append(_store(repo, _parse(item), mode))
        except _ItemError as exc:
            tally.fail(position, str(exc))
        except ConflictError as exc:
            tally.fail(position, exc.message)
    return tally.report()
