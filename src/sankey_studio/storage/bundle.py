"""Graph bundles: export saved graphs to one JSON document and import them back.

Format ``{"format": "sankey-studio/graphs", "version": 2, "graphs": [<GraphDefinition dump>],
"folders": [<FolderDefinition dump>]}`` (version 1 is refused). A bundle holds no secrets (a Mongo
source names its connection, it never carries a URI), and an import never trusts a saved
write-back consent: ``source.write_back`` is dropped from every graph, in both modes, because a
consent names a file or connection of the machine that exported it. Import validates every graph
with pydantic on its own, so one bad graph never blocks the others; the report lists what failed
(by position, never by content). The byte cap of the request body is the web layer's business;
``MAX_BUNDLE_GRAPHS`` bounds the graph count here. The folders ("collections") of a bundle are
``bundle_folders``' business; without a folder repository an import ignores them and every graph
lands at the top level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from sankey_studio.errors import BundleError, ConflictError, StorageError
from sankey_studio.models import GraphCreate, GraphDefinition
from sankey_studio.storage.base import upgrade_doc
from sankey_studio.storage.bundle_folders import (
    FOLDER_ROOT,
    export_folders,
    folder_items,
    import_folders,
)
from sankey_studio.storage.common import validation_lines

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sankey_studio.storage.base import GraphRepository
    from sankey_studio.storage.folders_base import FolderRepository

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
BUNDLE_VERSION = 2
MAX_BUNDLE_GRAPHS = 1000
MAX_REPORTED_ERRORS = 50
#: Location label of an error that belongs to a bundle graph as a whole.
GRAPH_ROOT = "graph"

ImportMode = Literal["new_ids", "keep_ids"]
IMPORT_MODES = ("new_ids", "keep_ids")


@dataclass(frozen=True, slots=True)
class ImportReport:
    """``imported`` graphs (their ids in ``ids``), ``failed`` ones (first ``errors`` explained).

    ``folders`` counts the library folders ("collections") the import created; a folder that
    could not be stored adds a line to ``errors`` but is not a failed graph.
    """

    imported: int
    failed: int
    ids: list[str]
    errors: list[str]
    folders: int = 0


class _ItemError(ValueError):
    """One graph of the bundle cannot be used."""


@dataclass(slots=True)
class _Tally:
    ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed: int = 0

    folders: int = 0

    def _line(self, line: str) -> None:
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(line)

    def fail(self, position: int, reason: str) -> None:
        self.failed += 1
        self._line(f"graph {position}: {reason}")

    def folder_failed(self, position: int, reason: str) -> None:
        self._line(f"{FOLDER_ROOT} {position}: {reason}")

    def report(self) -> ImportReport:
        return ImportReport(len(self.ids), self.failed, self.ids, self.errors, self.folders)


def export_bundle(
    repo: GraphRepository,
    ids: Sequence[str] | None = None,
    folders: FolderRepository | None = None,
) -> dict[str, Any]:
    """The listed graphs (given order, duplicates dropped), or every graph when ``ids`` is None.

    ``folders`` adds the library folders: all of them (empty ones too) for the whole library,
    else the ones the listed graphs sit in plus their ancestors, parents first. Without it the
    ``folders`` list is empty. ``NotFoundError`` for an unknown id; ``BundleError`` beyond
    ``MAX_BUNDLE_GRAPHS`` graphs.
    """
    found = repo.iter_definitions() if ids is None else map(repo.get, dict.fromkeys(ids))
    graphs = list(islice(found, MAX_BUNDLE_GRAPHS + 1))
    if len(graphs) > MAX_BUNDLE_GRAPHS:
        raise BundleError(f"A bundle may hold at most {MAX_BUNDLE_GRAPHS} graphs")
    used = None if ids is None else {graph.folder_id for graph in graphs}
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "graphs": [graph.model_dump(mode="json") for graph in graphs],
        "folders": export_folders(folders, used),
    }


def _header(bundle: object) -> dict[str, Any]:
    """``bundle`` if it is a bundle of this format and version; ``BundleError`` otherwise."""
    if not isinstance(bundle, dict) or bundle.get("format") != BUNDLE_FORMAT:
        raise BundleError("This is not a sankey-studio graph bundle")
    version = bundle.get("version")
    if type(version) is not int or version != BUNDLE_VERSION:  # bool is an int: refuse it too
        raise BundleError("Unsupported bundle version")
    return bundle


def _graph_list(bundle: dict[str, Any]) -> list[object]:
    graphs = bundle.get("graphs")
    if not isinstance(graphs, list):
        raise BundleError("The bundle has no list of graphs")
    if len(graphs) > MAX_BUNDLE_GRAPHS:
        raise BundleError(f"A bundle may hold at most {MAX_BUNDLE_GRAPHS} graphs")
    return graphs


def _without_consent(doc: dict[str, Any]) -> dict[str, Any]:
    """``doc`` whose source has no saved write-back consent (a stranger's bundle is not trusted)."""
    source = doc.get("source")
    if not isinstance(source, dict) or source.get("write_back") is None:
        return doc
    return {**doc, "source": {**source, "write_back": None}}


def _parse(item: object) -> GraphDefinition:
    if not isinstance(item, dict):
        raise _ItemError("not an object")
    try:
        return GraphDefinition.model_validate(_without_consent(upgrade_doc(item)))
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


def _store(
    repo: GraphRepository,
    graph: GraphDefinition,
    mode: ImportMode,
    placed: Mapping[str | None, str | None],
) -> str:
    if mode == "keep_ids":
        if graph.folder_id in placed:  # a refused folder: the graph falls back to where it landed
            graph = GraphDefinition.model_validate(
                {**graph.model_dump(), "folder_id": placed[graph.folder_id]}
            )
        return repo.put(graph).id  # ConflictError when the id is taken
    return repo.create(_as_create(graph), folder_id=placed.get(graph.folder_id)).id


def _store_folders(
    folders: FolderRepository | None, items: Sequence[object], mode: ImportMode, tally: _Tally
) -> Mapping[str | None, str | None]:
    """Store the folders ``items`` of a bundle; the map of where each one's graphs land."""
    if folders is None:
        return {}
    result = import_folders(folders, items, keep_ids=mode == "keep_ids")
    for position, reason in result.failures:
        tally.folder_failed(position, reason)
    tally.folders = result.created
    return result.placed


def import_bundle(
    repo: GraphRepository,
    bundle: object,
    mode: ImportMode = "new_ids",
    folders: FolderRepository | None = None,
) -> ImportReport:
    """Store every valid graph of ``bundle``; ``new_ids`` -> ``create``, ``keep_ids`` -> ``put``.

    ``mode`` defaults to ``new_ids``: fresh ids, so an import can never collide with a stored graph.
    With ``folders`` the bundle's folders are stored first (``bundle_folders`` says how) and the
    graphs land in them; without it the ``folders`` key is ignored and every graph lands at the
    top level. ``source.write_back`` is dropped from every graph.

    Raises ``BundleError`` for an unknown ``mode`` or an unusable bundle (nothing is stored); a
    backend failure (``StorageError``) aborts the import. Invalid graphs and taken ids
    (``keep_ids``) are counted and explained in the report.
    """
    if mode not in IMPORT_MODES:
        raise BundleError(f"Unknown import mode; use one of: {', '.join(IMPORT_MODES)}")
    header = _header(bundle)
    graphs = _graph_list(header)
    wanted = [] if folders is None else folder_items(header)  # refused before anything is stored
    tally = _Tally()
    placed = _store_folders(folders, wanted, mode, tally)
    for position, item in enumerate(graphs, start=1):
        try:
            tally.ids.append(_store(repo, _parse(item), mode, placed))
        except _ItemError as exc:
            tally.fail(position, str(exc))
        except ConflictError as exc:
            tally.fail(position, exc.message)
    return tally.report()
