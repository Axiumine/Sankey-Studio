"""MongoDB data source: streams ``find`` / ``aggregate`` results as ``RawLink`` tuples.

Read-only by construction: the filter, the pipeline and the namespace go through
``mongo_safety`` again here (the spec validated them once, this is the second lock), and the only
driver calls are ``find`` and ``aggregate``. Driver failures are mapped by ``mongo_errors`` to a
``SourceError`` that names the connection and the exception class only; nothing logs or echoes
``str(exc)``, a URI or a document.

Document-level problems (a missing or unusable source/target/value) are skipped with a warning
via ``ctx.row_problem``; the category never drops a row (``CategoryCleaner``). No more than
``AppSettings.max_links + 1`` ROWS are ever yielded (documents the source skips do not count, or a
dirty collection would be cut silently below the cap), so ``build_graph`` raises
``GraphTooLargeError`` exactly when more than ``max_links`` usable rows exist, without the source
materialising an unbounded result. How many documents are used is bounded by ``MongoSource.limit``
and the time limit.

The server is asked for ONE document more than ``limit``. That extra document is never turned into
a row: it only proves the collection held more than ``limit``, and it alone makes the source warn
"Result truncated at limit N" (exactly ``limit`` documents is a complete result, no warning). The
row cap above stops reading earlier, before the extra document can be seen, and then the build
fails with ``GraphTooLargeError`` anyway.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sankey_studio.errors import SourceError, SourceNotFoundError
from sankey_studio.models.base import CONNECTION_NAME_RE
from sankey_studio.mongo import mongo_errors
from sankey_studio.mongo_safety import check_filter, check_pipeline, validate_namespace
from sankey_studio.sources.base import CategoryCleaner
from sankey_studio.sources.mongo_extract import FieldMap, extract_row

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from pymongo.collection import Collection
    from pymongo.command_cursor import CommandCursor
    from pymongo.cursor import Cursor

    from sankey_studio.models import AppSettings, MongoConnection, MongoSource, RawLink
    from sankey_studio.sources.base import Diagnostics, SourceContext

#: Documents fetched per round trip.
BATCH_SIZE = 1_000


def require_connection(ctx: SourceContext, name: str) -> MongoConnection:
    """The configured connection ``name``, else ``SourceNotFoundError`` (before any slot or
    client exists for it). The name is echoed only when it looks like a connection name: inspect
    calls receive raw query parameters."""
    connection = ctx.settings.connection(name)
    if connection is None:
        shown = name if CONNECTION_NAME_RE.fullmatch(name) else "?"
        raise SourceNotFoundError(f"Unknown MongoDB connection '{shown}'")
    return connection


@dataclass(frozen=True, slots=True)
class QueryLimits:
    """How much a query may read and for how long.

    ``limit`` counts the documents the source uses; ``fetch`` is what the server is asked for,
    one more, so that a document past ``limit`` proves the result was cut. ``max_rows`` counts
    the usable rows the source yields: ``max_links + 1``, because one row past the cap proves it
    was hit.
    """

    limit: int
    max_time_ms: int
    max_rows: int
    batch_size: int = BATCH_SIZE

    @property
    def fetch(self) -> int:
        """The server-side document limit: ``limit`` plus the one that proves truncation."""
        return self.limit + 1

    @classmethod
    def for_source(cls, spec: MongoSource, settings: AppSettings) -> QueryLimits:
        max_time = spec.max_time_ms if spec.max_time_ms is not None else settings.mongo_timeout_ms
        return cls(limit=spec.limit, max_time_ms=max_time, max_rows=settings.max_links + 1)


@dataclass(frozen=True, slots=True)
class Query:
    """What to send to the server. ``run`` is the only place that calls the collection."""

    mode: Literal["find", "aggregate"]
    body: Any  # the filter (find) or the pipeline (aggregate)
    projection: dict[str, int] | None
    options: dict[str, Any]

    def run(self, collection: Collection[Any]) -> Cursor[Any] | CommandCursor[Any]:
        if self.mode == "find":
            return collection.find(self.body, self.projection, **self.options)
        return collection.aggregate(self.body, **self.options)


def _is_small_limit(stage: Mapping[str, Any], limit: int) -> bool:
    if list(stage) != ["$limit"]:
        return False
    count = stage["$limit"]
    return isinstance(count, int) and not isinstance(count, bool) and count <= limit


def limited_pipeline(pipeline: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The user's pipeline plus ``{"$limit": limit}``, unless its last stage already limits
    to ``limit`` or less (a smaller user limit is kept as it is). ``limit`` is the number of
    documents to ask the server for (``QueryLimits.fetch``)."""
    stages = list(pipeline)
    if not stages or not _is_small_limit(stages[-1], limit):
        stages.append({"$limit": limit})
    return stages


def _find_query(spec: MongoSource, fields: FieldMap, limits: QueryLimits) -> Query:
    check_filter(spec.filter)
    options: dict[str, Any] = {
        "limit": limits.fetch,
        "max_time_ms": limits.max_time_ms,
        "batch_size": limits.batch_size,
    }
    return Query("find", spec.filter, fields.projection(), options)


def _aggregate_query(spec: MongoSource, limits: QueryLimits) -> Query:
    check_pipeline(spec.pipeline)
    options: dict[str, Any] = {
        "allowDiskUse": False,
        "maxTimeMS": limits.max_time_ms,
        "batchSize": limits.batch_size,
    }
    return Query("aggregate", limited_pipeline(spec.pipeline, limits.fetch), None, options)


def build_query(spec: MongoSource, fields: FieldMap, limits: QueryLimits) -> Query:
    """Pure: the arguments of the one driver call, checked by ``mongo_safety`` first."""
    if spec.mode == "find":
        return _find_query(spec, fields, limits)
    return _aggregate_query(spec, limits)


@dataclass(slots=True)
class _Run:
    """Per-iteration state: what was read and what to report once at the end."""

    diag: Diagnostics
    cleaner: CategoryCleaner
    limits: QueryLimits
    docs: int = 0
    rows: int = 0
    text_values: int = 0

    @property
    def past_limit(self) -> bool:
        """A document beyond ``limits.limit`` was seen: the result was cut."""
        return self.docs > self.limits.limit

    def report(self) -> None:
        """Warn once, at the end of the iteration, about what the reader had to tolerate."""
        if self.text_values:
            self.diag.warn(f"Read {self.text_values} text value(s) as numbers")
        if self.past_limit:
            self.diag.warn(f"Result truncated at limit {self.limits.limit}")


class MongoDataSource:
    def __init__(self, spec: MongoSource, ctx: SourceContext) -> None:
        self._spec = spec
        self._ctx = ctx
        self._fields = FieldMap.from_spec(spec)

    def iter_links(self, diag: Diagnostics) -> Iterator[RawLink]:
        limits = QueryLimits.for_source(self._spec, self._ctx.settings)
        run = _Run(diag, CategoryCleaner(diag), limits)
        try:
            yield from self._stream(run)
        finally:
            run.cleaner.finish()

    def _database(self) -> str:
        spec = self._spec
        connection = require_connection(self._ctx, spec.connection)
        database = spec.database if spec.database is not None else connection.default_database
        if database is None:
            raise SourceError(
                f"MongoDB connection '{spec.connection}' has no default database; "
                "choose a database on the source"
            )
        return database

    def _stream(self, run: _Run) -> Iterator[RawLink]:
        spec = self._spec
        database = self._database()
        validate_namespace(database, spec.collection)  # before the client is even touched
        query = build_query(spec, self._fields, run.limits)
        with self._ctx.mongo.slot(spec.connection), mongo_errors(spec.connection):
            collection = self._ctx.mongo.get(spec.connection)[database][spec.collection]
            with closing(query.run(collection)) as cursor:
                yield from self._rows(cursor, run)

    def _rows(self, cursor: Iterable[Mapping[str, Any]], run: _Run) -> Iterator[RawLink]:
        for doc in cursor:
            run.docs += 1
            if run.past_limit:
                break  # the extra document: it proves the cut and is not read as a row
            row = extract_row(doc, self._fields)
            if isinstance(row, str):
                self._ctx.row_problem(run.diag, f"document {run.docs}: {row}")
                continue
            run.rows += 1
            run.text_values += row.text_value
            yield row.source, row.target, row.value, run.cleaner.clean(row.category)
            if run.rows == run.limits.max_rows:
                break  # one row past max_links: build_graph refuses it, so read no further
        run.report()
