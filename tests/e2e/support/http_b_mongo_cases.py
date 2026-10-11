"""The tables of the Mongo guard scenarios: unsafe sources and refused inspect requests.

Pure data (no I/O). ``UnsafeCase.build(database)`` returns the overrides of a ``world.source()``
(the cross-database forms name the world's own database); ``reason`` is a part of the message the
422 must carry. ``INSPECT_REFUSALS`` rows are ``(route, query, status, error code)`` under
``/api/v1/mongo/main``; the sentinel ``DB`` stands for the world's database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from tests.e2e.support.http_b_mongo_flows import aggregate
from tests.e2e.support.http_b_world import DATA_COLLECTION

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


@dataclass(frozen=True, slots=True)
class UnsafeCase:
    """A source that must be refused: ``build(database)`` -> source fields, the message part."""

    label: str
    build: Callable[[str], Mapping[str, Any]]
    reason: str


def _stage(stage: Mapping[str, Any]) -> Callable[[str], Mapping[str, Any]]:
    return lambda _db: aggregate(stage)


_JS = {"body": "function() { return 1 }", "args": [], "lang": "js"}
UNSAFE_CASES: Final = (
    UnsafeCase("out-collection", _stage({"$out": "smuggled"}), "$out is not allowed"),
    UnsafeCase(
        "out-other-database",
        lambda db: aggregate({"$out": {"db": db, "coll": "smuggled"}}),
        "$out is not allowed",
    ),
    UnsafeCase(
        "merge-collection", _stage({"$merge": {"into": "smuggled"}}), "$merge is not allowed"
    ),
    UnsafeCase(
        "merge-other-database",
        lambda db: aggregate({"$merge": {"into": {"db": db, "coll": "smuggled"}}}),
        "$merge is not allowed",
    ),
    UnsafeCase("where-in-find", lambda _db: {"filter": {"$where": "sleep(1)"}}, "$where is not"),
    UnsafeCase("where-in-match", _stage({"$match": {"$where": "true"}}), "$where is not"),
    UnsafeCase(
        "function-in-add-fields",
        _stage({"$addFields": {"x": {"$function": _JS}}}),
        "$function is not",
    ),
    UnsafeCase(
        "accumulator-in-group",
        _stage({"$group": {"_id": "$from", "x": {"$accumulator": _JS}}}),
        "$accumulator is not",
    ),
    UnsafeCase(
        "nested-facet",
        _stage({"$facet": {"a": [{"$facet": {"b": []}}]}}),
        "at most 1 $facet",
    ),
    UnsafeCase(
        "out-inside-facet",
        _stage({"$facet": {"a": [{"$out": "smuggled"}]}}),
        "$out is not allowed",
    ),
    UnsafeCase(
        "lookup-other-database",
        lambda db: aggregate(
            {
                "$lookup": {
                    "from": {"db": db, "coll": "x"},
                    "localField": "a",
                    "foreignField": "b",
                    "as": "z",
                }
            }
        ),
        "$lookup.from must be a collection name string",
    ),
    UnsafeCase(
        "lookup-system-collection",
        _stage(
            {"$lookup": {"from": "system.users", "localField": "a", "foreignField": "b", "as": "z"}}
        ),
        "system collections are not allowed",
    ),
    UnsafeCase(
        "lookup-pipeline-out",
        _stage(
            {"$lookup": {"from": DATA_COLLECTION, "pipeline": [{"$out": "smuggled"}], "as": "z"}}
        ),
        "$out is not allowed",
    ),
    UnsafeCase(
        "union-with-out",
        _stage({"$unionWith": {"coll": DATA_COLLECTION, "pipeline": [{"$out": "smuggled"}]}}),
        "$out is not allowed",
    ),
    UnsafeCase(
        "graph-lookup",
        _stage(
            {
                "$graphLookup": {
                    "from": DATA_COLLECTION,
                    "startWith": "$a",
                    "as": "z",
                    "connectFromField": "a",
                    "connectToField": "b",
                }
            }
        ),
        "$graphLookup is not allowed",
    ),
    UnsafeCase(
        "privileged-variable",
        _stage({"$project": {"x": "$$USER_ROLES"}}),
        "variable reference is not allowed",
    ),
)


#: The sentinel stands for the world's database in ``INSPECT_REFUSALS``.
DB: Final = "<database>"
#: ``(path under /mongo/main, query, status, error code)``
INSPECT_REFUSALS: Final[tuple[tuple[str, dict[str, Any], int, str], ...]] = (
    ("collections", {"database": "admin"}, 400, "unsafe_source"),
    ("collections", {"database": "local"}, 400, "unsafe_source"),
    ("collections", {"database": "config"}, 400, "unsafe_source"),
    ("collections", {"database": "a.b"}, 400, "unsafe_source"),
    ("collections", {"database": ""}, 422, "validation_error"),
    ("sample", {"database": "admin", "collection": "x"}, 400, "unsafe_source"),
    ("sample", {"database": DB, "collection": "system.users"}, 400, "unsafe_source"),
    ("sample", {"database": DB, "collection": "$cmd"}, 400, "unsafe_source"),
    ("sample", {"database": DB, "collection": DATA_COLLECTION, "n": 0}, 422, "validation_error"),
    ("sample", {"database": DB, "collection": DATA_COLLECTION, "n": 21}, 422, "validation_error"),
)
