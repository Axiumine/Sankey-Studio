"""``mongo_source``: query construction is pure, so every rule is tested without a client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, cast

import pytest

from sankey_studio.errors import UnsafeSourceError
from sankey_studio.models import AppSettings, MongoSource
from sankey_studio.sources.mongo_extract import FieldMap
from sankey_studio.sources.mongo_source import (
    BATCH_SIZE,
    Query,
    QueryLimits,
    build_query,
    limited_pipeline,
)
from tests.sources.test_mongo_fakes import Call, FakeMongo, as_collection

if TYPE_CHECKING:
    from tests.sources.conftest import SpecFactory

# --------------------------------------------------------------------------- limits


class LimitCase(NamedTuple):
    spec_limit: int
    max_links: int
    max_rows: int


LIMITS = {
    "far below the cap": LimitCase(10, 100, 101),
    "exactly max_links": LimitCase(100, 100, 101),
    "max_links + 1": LimitCase(101, 100, 101),
    "far above the cap": LimitCase(5_000, 100, 101),
    "the default limit under the default cap": LimitCase(10_000, 200_000, 200_001),
    "the largest limit under the largest cap": LimitCase(1_000_000, 5_000_000, 5_000_001),
}


@pytest.mark.parametrize("case", LIMITS.values(), ids=LIMITS)
def test_documents_are_limited_by_the_spec_and_rows_by_max_links_plus_one(
    case: LimitCase, mongo_spec: SpecFactory
) -> None:
    """Skipped documents do not count against ``max_links``, so the document limit is the spec's
    own; only the usable rows are capped (one row past ``max_links`` proves the cap was hit)."""
    spec = mongo_spec(limit=case.spec_limit)
    limits = QueryLimits.for_source(spec, AppSettings(max_links=case.max_links))
    assert (limits.limit, limits.fetch, limits.max_rows) == (
        case.spec_limit,
        case.spec_limit + 1,
        case.max_rows,
    )


class TimeCase(NamedTuple):
    spec_ms: int | None
    settings_ms: int
    expected: int


TIMES = {
    "the spec wins": TimeCase(2_000, 9_000, 2_000),
    "the spec wins even when larger": TimeCase(300_000, 500, 300_000),
    "the smallest spec value": TimeCase(100, 15_000, 100),
    "no spec value: the settings timeout": TimeCase(None, 9_000, 9_000),
    "the smallest settings timeout": TimeCase(None, 500, 500),
}


@pytest.mark.parametrize("case", TIMES.values(), ids=TIMES)
def test_max_time_comes_from_the_spec_or_the_settings(
    case: TimeCase, mongo_spec: SpecFactory
) -> None:
    spec = mongo_spec(max_time_ms=case.spec_ms)
    limits = QueryLimits.for_source(spec, AppSettings(mongo_timeout_ms=case.settings_ms))
    assert limits.max_time_ms == case.expected


def test_query_limits_defaults_and_shape(mongo_spec: SpecFactory) -> None:
    limits = QueryLimits.for_source(mongo_spec(), AppSettings())
    assert limits == QueryLimits(
        limit=10_000, max_time_ms=15_000, max_rows=200_001, batch_size=1_000
    )
    assert BATCH_SIZE == 1_000
    assert QueryLimits(limit=1, max_time_ms=1, max_rows=1).batch_size == BATCH_SIZE


# --------------------------------------------------------------------------- $limit rule


class PipelineCase(NamedTuple):
    pipeline: list[dict[str, Any]]
    limit: int
    expected: list[dict[str, Any]]


MATCH: dict[str, Any] = {"$match": {"kind": "x"}}

PIPELINES = {
    "empty": PipelineCase([], 10, [{"$limit": 10}]),
    "a match": PipelineCase([MATCH], 10, [MATCH, {"$limit": 10}]),
    "a smaller user limit stays": PipelineCase([MATCH, {"$limit": 5}], 10, [MATCH, {"$limit": 5}]),
    "an equal user limit stays": PipelineCase([MATCH, {"$limit": 10}], 10, [MATCH, {"$limit": 10}]),
    "a larger user limit gets ours too": PipelineCase(
        [MATCH, {"$limit": 11}], 10, [MATCH, {"$limit": 11}, {"$limit": 10}]
    ),
    "a limit that is not last gets ours": PipelineCase(
        [{"$limit": 5}, MATCH], 10, [{"$limit": 5}, MATCH, {"$limit": 10}]
    ),
    "a boolean limit is not a number": PipelineCase(
        [{"$limit": True}], 10, [{"$limit": True}, {"$limit": 10}]
    ),
    "a text limit is not a number": PipelineCase(
        [{"$limit": "5"}], 10, [{"$limit": "5"}, {"$limit": 10}]
    ),
    "a limit stage with company": PipelineCase(
        [{"$limit": 5, "$skip": 1}], 10, [{"$limit": 5, "$skip": 1}, {"$limit": 10}]
    ),
    "a skip is not a limit": PipelineCase([{"$skip": 5}], 10, [{"$skip": 5}, {"$limit": 10}]),
    "limit 1 under limit 1": PipelineCase([{"$limit": 1}], 1, [{"$limit": 1}]),
}


@pytest.mark.parametrize("case", PIPELINES.values(), ids=PIPELINES)
def test_limited_pipeline(case: PipelineCase) -> None:
    original = [dict(stage) for stage in case.pipeline]
    assert limited_pipeline(case.pipeline, case.limit) == case.expected
    assert case.pipeline == original  # the spec's own pipeline is never touched


class FetchCase(NamedTuple):
    pipeline: list[dict[str, Any]]
    expected: list[dict[str, Any]]


#: The spec limit is 10, so the server is asked for 11 documents: the extra one proves a cut.
FETCHES = {
    "no user limit": FetchCase([MATCH], [MATCH, {"$limit": 11}]),
    "a user limit below ours": FetchCase([MATCH, {"$limit": 10}], [MATCH, {"$limit": 10}]),
    "a user limit of exactly what is asked for": FetchCase(
        [MATCH, {"$limit": 11}], [MATCH, {"$limit": 11}]
    ),
    "a user limit one above what is asked for": FetchCase(
        [MATCH, {"$limit": 12}], [MATCH, {"$limit": 12}, {"$limit": 11}]
    ),
}


@pytest.mark.parametrize("case", FETCHES.values(), ids=FETCHES)
def test_an_aggregate_asks_for_one_document_past_the_spec_limit(
    case: FetchCase, mongo_spec: SpecFactory
) -> None:
    spec = mongo_spec(mode="aggregate", pipeline=case.pipeline, limit=10)
    limits = QueryLimits.for_source(spec, AppSettings())
    assert build_query(spec, FIELDS, limits).body == case.expected


@pytest.mark.parametrize("spec_limit", [1, 2, 10, 10_000, 1_000_000])
def test_a_find_asks_for_one_document_past_the_spec_limit(
    spec_limit: int, mongo_spec: SpecFactory
) -> None:
    """``limit + 1`` stays an ordinary int below any driver or server bound, also at the
    largest limit the spec accepts."""
    spec = mongo_spec(limit=spec_limit)
    limits = QueryLimits.for_source(spec, AppSettings())
    assert build_query(spec, FIELDS, limits).options["limit"] == spec_limit + 1


# --------------------------------------------------------------------------- build_query

FIELDS = FieldMap("source", "target", "value", None)
LIMITS_10 = QueryLimits(limit=10, max_time_ms=2_000, max_rows=11, batch_size=50)


def test_a_find_query_asks_for_the_projection_the_limit_and_the_time_cap(
    mongo_spec: SpecFactory,
) -> None:
    spec = mongo_spec(filter={"kind": "x"})
    assert build_query(spec, FIELDS, LIMITS_10) == Query(
        mode="find",
        body={"kind": "x"},
        projection={"source": 1, "target": 1, "value": 1, "_id": 0},
        options={"limit": 11, "max_time_ms": 2_000, "batch_size": 50},
    )


def test_an_aggregate_query_never_spills_to_disk(mongo_spec: SpecFactory) -> None:
    spec = mongo_spec(mode="aggregate", pipeline=[MATCH])
    query = build_query(spec, FIELDS, LIMITS_10)
    assert query == Query(
        mode="aggregate",
        body=[MATCH, {"$limit": 11}],
        projection=None,
        options={"allowDiskUse": False, "maxTimeMS": 2_000, "batchSize": 50},
    )
    assert query.options["allowDiskUse"] is False


def test_the_projection_follows_the_configured_fields(mongo_spec: SpecFactory) -> None:
    spec = mongo_spec(source_field="a.s", value_field=None, category_field="c")
    fields = FieldMap.from_spec(spec)
    query = build_query(spec, fields, LIMITS_10)
    assert query.projection == {"a.s": 1, "target": 1, "c": 1, "_id": 0}


def test_run_passes_the_filter_and_projection_positionally_to_find() -> None:
    fake = FakeMongo()
    query = Query("find", {"k": 1}, {"a": 1}, {"limit": 3, "max_time_ms": 100})
    cursor = query.run(as_collection(fake))
    assert fake.calls == [Call("find", ({"k": 1}, {"a": 1}), {"limit": 3, "max_time_ms": 100})]
    assert cast("Any", cursor) is fake.cursors[0]


def test_run_passes_the_pipeline_positionally_to_aggregate() -> None:
    fake = FakeMongo()
    query = Query("aggregate", [{"$limit": 3}], None, {"allowDiskUse": False})
    cursor = query.run(as_collection(fake))
    assert fake.calls == [Call("aggregate", ([{"$limit": 3}],), {"allowDiskUse": False})]
    assert cast("Any", cursor) is fake.cursors[0]


# --------------------------------------------------------------------------- second lock


def test_a_spec_that_skipped_validation_is_still_refused(mongo_spec: SpecFactory) -> None:
    """``model_construct`` bypasses the validators; ``build_query`` checks again."""
    base = mongo_spec().model_dump()
    find = MongoSource.model_construct(**{**base, "filter": {"$where": "1"}})
    with pytest.raises(UnsafeSourceError):
        build_query(find, FIELDS, LIMITS_10)
    agg = MongoSource.model_construct(**{**base, "mode": "aggregate", "pipeline": [{"$out": "x"}]})
    with pytest.raises(UnsafeSourceError):
        build_query(agg, FIELDS, LIMITS_10)
