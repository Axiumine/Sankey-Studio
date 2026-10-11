"""Storage contract for saved graphs. Implementations: ``files.py`` and ``mongo_store.py``.

Application settings are *not* behind this protocol: they always live in the local
``settings.json`` (they hold the Mongo connection needed to reach a Mongo store).

Rules every implementation follows:

* Ids are ``uuid4().hex`` and validated with ``check_graph_id`` BEFORE any path or query use;
  a malformed id is just "not found".
* Listing order is ``(updated_at desc, id asc)`` so offset paging is stable when timestamps tie.
* Persisted documents are read through ``upgrade_doc`` (strips ``_id``, applies schema upgrades)
  before ``GraphDefinition.model_validate``.
* The revision compare and the write happen in ONE critical section shared by every user of the
  same store (``Services.graphs()`` hands out one cached instance per backend target).
* Messages never contain URIs or credentials.
* The MongoDB backend must not store user-controlled field NAMES: a key containing ``.`` or
  starting with ``$`` is rejected by MongoDB < 5.0 and awkward in later versions (``node_colors``
  keyed by a node called ``R.D``, a ``find`` filter holding ``$gt``). ``encode_mongo_doc`` /
  ``decode_mongo_doc`` below rewrite exactly those dicts, and ``find_unsafe_key`` is the guard.
  mongomock accepts such keys, so only the codec tests (and that guard) can catch a regression.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any, Protocol

from sankey_studio.errors import NotFoundError, StorageError
from sankey_studio.models import GRAPH_ID_PATTERN, SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sankey_studio.models import GraphCreate, GraphDefinition, GraphSummary, GraphUpdate

#: Collection (inside ``AppSettings.storage_database``) used by the Mongo graph store.
MONGO_GRAPHS_COLLECTION = "sankey_studio_graphs"

_GRAPH_ID_RE = re.compile(GRAPH_ID_PATTERN)


def new_graph_id() -> str:
    return uuid.uuid4().hex


def check_graph_id(graph_id: str) -> str:
    """Return ``graph_id`` if it is a valid id; ``NotFoundError`` otherwise (``../x``, NUL, ...)."""
    if _GRAPH_ID_RE.fullmatch(graph_id) is None:
        raise NotFoundError("Graph not found")
    return graph_id


def upgrade_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Prepare a stored document for ``GraphDefinition.model_validate`` (returns a new dict).

    Drops the Mongo ``_id``, fills a missing ``schema_version`` with 1 and applies upgrades from
    older versions (none exist yet). A document written by a NEWER version raises
    ``StorageError`` instead of being silently mangled.
    """
    out = {k: v for k, v in doc.items() if k != "_id"}
    version = out.setdefault("schema_version", 1)
    if not isinstance(version, int) or version < 1:
        raise StorageError("Stored graph has an invalid schema version")
    if version > SCHEMA_VERSION:
        raise StorageError("Stored graph was written by a newer version of sankey-studio")
    return out


# --------------------------------------------------------------------------- Mongo documents

#: ``(section, field)`` dicts keyed by user text; stored as ``[[key, value], ...]`` pair lists.
_PAIR_FIELDS = (
    ("transform", "merge_nodes"),
    ("style", "node_colors"),
    ("style", "category_colors"),
)
#: Mongo-source fields holding operator keys (``$gt``) and dotted paths; stored as JSON text.
_JSON_FIELDS = ("filter", "pipeline")
_SECTIONS = ("source", "transform", "style")
#: What a malformed encoded field raises: a pair list that is not pairs, JSON that is not JSON or
#: nested too deep. A constant, not a three-name ``except A, B, C:``, which Semgrep cannot parse.
_DECODE_ERRORS = (TypeError, ValueError, RecursionError)


def encode_mongo_doc(dump: Mapping[str, Any]) -> dict[str, Any]:
    """``GraphDefinition.model_dump(mode="json")`` -> a document whose field names are all ours.

    Returns a new dict. ``transform.merge_nodes``, ``style.node_colors`` and
    ``style.category_colors`` become ``[[key, value], ...]`` lists; ``source.filter`` and
    ``source.pipeline`` of a Mongo source become JSON strings. Everything else (``created_at``
    as a real datetime, ``_id``, ...) is the repository's business. Only the Mongo backend uses
    this; the file backend stores the plain dump.
    """
    out: dict[str, Any] = dict(dump)
    for section in _SECTIONS:
        if isinstance(out.get(section), dict):
            out[section] = dict(out[section])
    for section, name in _PAIR_FIELDS:
        block = out.get(section)
        if isinstance(block, dict) and isinstance(block.get(name), dict):
            block[name] = [[key, value] for key, value in block[name].items()]
    source = out.get("source")
    if isinstance(source, dict) and source.get("type") == "mongo":
        for name in _JSON_FIELDS:
            if name in source:
                source[name] = json.dumps(source[name], separators=(",", ":"))
    return out


def decode_mongo_doc(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Inverse of ``encode_mongo_doc``; run it BEFORE ``upgrade_doc`` and ``model_validate``.

    Returns a new dict. A malformed encoded field raises ``StorageError`` (the record is
    unreadable, not the whole store).
    """
    out: dict[str, Any] = dict(stored)
    for section in _SECTIONS:
        if isinstance(out.get(section), dict):
            out[section] = dict(out[section])
    try:
        for section, name in _PAIR_FIELDS:
            block = out.get(section)
            if isinstance(block, dict) and isinstance(block.get(name), list):
                block[name] = dict(block[name])
        source = out.get("source")
        if isinstance(source, dict) and source.get("type") == "mongo":
            for name in _JSON_FIELDS:
                if isinstance(source.get(name), str):
                    source[name] = json.loads(source[name])
    except _DECODE_ERRORS:
        raise StorageError("Stored graph has an unreadable encoded field") from None
    return out


def find_unsafe_key(doc: object) -> str | None:
    """Location of the first dict key MongoDB < 5.0 cannot store, else ``None``.

    Unsafe = not a string, contains ``.`` or NUL, or starts with ``$``. The location is the
    dotted path of the dict that holds the key (``"<root>"`` for the top level); the key itself
    is never echoed. The Mongo store runs this on every encoded document and raises
    ``StorageError`` instead of letting the driver fail (or, on mongomock, silently succeed).
    """
    stack: list[tuple[str, object]] = [("<root>", doc)]
    while stack:
        where, node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str) or "." in key or "\0" in key or key.startswith("$"):
                    return where
                stack.append((key if where == "<root>" else f"{where}.{key}", value))
        elif isinstance(node, list | tuple):
            stack.extend((where, item) for item in node)
    return None


class GraphRepository(Protocol):  # pragma: no mutate block - interface only, never executed
    def list_graphs(
        self,
        *,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[GraphSummary]:
        """``(updated_at desc, id asc)``. ``query`` is a case-insensitive substring match on
        name/description/tags; ``tag`` is an exact tag match. Unreadable records are skipped
        with a logged warning."""
        ...

    def count(self, *, query: str | None = None, tag: str | None = None) -> int: ...

    def all_tags(self) -> list[str]:
        """Sorted distinct tags across all graphs."""
        ...

    def get(self, graph_id: str) -> GraphDefinition:
        """Raises ``NotFoundError`` (also for a malformed id) or ``StorageError`` (unreadable)."""
        ...

    def create(self, data: GraphCreate) -> GraphDefinition:
        """Assigns a new id, ``revision=1`` and both timestamps (UTC, tz-aware)."""
        ...

    def update(self, graph_id: str, data: GraphUpdate) -> GraphDefinition:
        """Raises ``NotFoundError``; raises ``ConflictError`` (with the current revision and
        ``updated_at``) when ``data.revision`` is not the stored revision. On success bumps
        ``revision`` and ``updated_at``."""
        ...

    def put(self, graph: GraphDefinition, *, overwrite: bool = False) -> GraphDefinition:
        """Store ``graph`` verbatim: id, revision, schema_version and timestamps are kept
        (backend migration, bundle import with ``keep_ids``). ``ConflictError`` when the id
        already exists and ``overwrite`` is false."""
        ...

    def iter_definitions(self) -> Iterator[GraphDefinition]:
        """Every readable graph in listing order, streamed (paged internally)."""
        ...

    def unreadable_ids(self) -> list[str]:
        """Ids of stored records ``iter_definitions`` cannot yield (damaged, or written by a newer
        version), as text, in a stable order; ``[]`` when every record is readable. Never raises
        for a damaged record, and the ids are all it reports (no content)."""
        ...

    def delete(self, graph_id: str) -> None:
        """Raises ``NotFoundError``."""
        ...

    def ping(self) -> None:
        """Raises ``StorageError`` if the backend is unreachable or unwritable."""
        ...
