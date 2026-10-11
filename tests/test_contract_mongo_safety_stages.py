"""``mongo_safety``: pipeline stage shapes and the lookup / unwind / facet budgets."""

from __future__ import annotations

from typing import Any

import pytest

from sankey_studio.mongo_safety import INT64_MAX, check_pipeline
from tests.safety_support import message_of

COLL_INVALID = "invalid MongoDB collection name"


def test_stage_shape_errors_name_the_stage_index() -> None:
    expected = "pipeline stage {} must be an object with one key"
    assert message_of(check_pipeline, ["x"]) == expected.format(0)
    assert message_of(check_pipeline, [{"$match": {}}, {}]) == expected.format(1)
    assert message_of(check_pipeline, [{"$match": {}}, {"$match": {}, "$limit": 1}]) == (
        expected.format(1)
    )
    assert message_of(check_pipeline, [{"$match": {}}, {"$limit": 1}, [1]]) == expected.format(2)


def test_unknown_stage_is_named() -> None:
    expected = "pipeline stage $graphLookup is not allowed (read-only)"
    assert message_of(check_pipeline, [{"$graphLookup": {}}]) == expected
    assert message_of(check_pipeline, [{"$MATCH": {}}]) == (
        "pipeline stage $MATCH is not allowed (read-only)"
    )


def test_a_pipeline_must_be_a_list_of_stages() -> None:
    expected = "a pipeline must be a list of stages"
    assert message_of(check_pipeline, [{"$facet": {"a": {"$match": {}}}}]) == expected
    assert message_of(check_pipeline, [{"$lookup": {"from": "c", "pipeline": "x"}}]) == expected
    assert message_of(check_pipeline, [{"$unionWith": {"coll": "c", "pipeline": {}}}]) == expected


def test_a_tuple_pipeline_is_accepted_at_the_top_level_only() -> None:
    check_pipeline(({"$match": {"a": 1}},))
    expected = "a pipeline must be a list of stages"
    assert message_of(check_pipeline, [{"$facet": {"a": ({"$match": {}},)}}]) == expected


LOOKUP_SHAPE = "$lookup must be an object using only from/localField/foreignField/let/pipeline/as"


def test_lookup_accepts_every_documented_key_at_once() -> None:
    check_pipeline(
        [
            {
                "$lookup": {
                    "from": "c",
                    "localField": "a",
                    "foreignField": "b",
                    "let": {"x": "$a"},
                    "pipeline": [{"$match": {}}],
                    "as": "out",
                }
            }
        ]
    )
    check_pipeline([{"$lookup": {"from": "c"}}])


def test_lookup_shape_errors() -> None:
    assert message_of(check_pipeline, [{"$lookup": "c"}]) == LOOKUP_SHAPE
    assert message_of(check_pipeline, [{"$lookup": {"from": "c", "db": "d"}}]) == LOOKUP_SHAPE
    assert message_of(check_pipeline, [{"$lookup": {}}]) == (
        "$lookup.from must be a collection name string"
    )
    assert message_of(check_pipeline, [{"$lookup": {"from": 5}}]) == (
        "$lookup.from must be a collection name string"
    )
    assert message_of(check_pipeline, [{"$lookup": {"from": {"db": "a", "coll": "b"}}}]) == (
        "$lookup.from must be a collection name string"
    )
    assert message_of(check_pipeline, [{"$lookup": {"from": "system.users"}}]) == (
        "MongoDB system collections are not allowed"
    )


def test_union_accepts_a_name_or_coll_with_pipeline() -> None:
    check_pipeline([{"$unionWith": "flows"}])
    check_pipeline([{"$unionWith": {"coll": "flows"}}])
    check_pipeline([{"$unionWith": {"coll": "flows", "pipeline": [{"$match": {}}]}}])


def test_union_shape_errors() -> None:
    shape = "$unionWith must be a collection name or {coll, pipeline}"
    assert message_of(check_pipeline, [{"$unionWith": 5}]) == shape
    assert message_of(check_pipeline, [{"$unionWith": ["c"]}]) == shape
    assert message_of(check_pipeline, [{"$unionWith": {"coll": "c", "db": "d"}}]) == shape
    coll = "$unionWith.coll must be a collection name string"
    assert message_of(check_pipeline, [{"$unionWith": {}}]) == coll
    assert message_of(check_pipeline, [{"$unionWith": {"pipeline": []}}]) == coll
    assert message_of(check_pipeline, [{"$unionWith": {"coll": 5}}]) == coll
    system = "MongoDB system collections are not allowed"
    assert message_of(check_pipeline, [{"$unionWith": "system.profile"}]) == system
    assert message_of(check_pipeline, [{"$unionWith": ""}]) == COLL_INVALID


def test_facet_shape_errors() -> None:
    shape = "$facet must be an object of named pipelines"
    assert message_of(check_pipeline, [{"$facet": []}]) == shape
    assert message_of(check_pipeline, [{"$facet": "x"}]) == shape
    check_pipeline([{"$facet": {}}])
    check_pipeline([{"$facet": {"a": [{"$match": {}}], "b": []}}])


# --------------------------------------------------------------------------- counters


def lookup(name: str = "c") -> dict[str, Any]:
    return {"$lookup": {"from": name, "localField": "a", "foreignField": "b", "as": "x"}}


LOOKUPS_MESSAGE = "at most 3 $lookup/$unionWith stages are allowed"


@pytest.mark.parametrize("stage", [lookup(), {"$unionWith": "c"}, {"$unionWith": {"coll": "c"}}])
def test_each_lookup_like_stage_counts_once(stage: dict[str, Any]) -> None:
    check_pipeline([stage] * 3)
    assert message_of(check_pipeline, [stage] * 4) == LOOKUPS_MESSAGE


def test_lookups_and_unions_share_one_budget() -> None:
    union = {"$unionWith": "c"}
    check_pipeline([lookup(), lookup(), union])
    check_pipeline([union, union, lookup()])
    assert message_of(check_pipeline, [lookup(), lookup(), union, union]) == LOOKUPS_MESSAGE
    assert message_of(check_pipeline, [union, lookup(), union, lookup()]) == LOOKUPS_MESSAGE


def test_nested_pipelines_draw_on_the_same_budget() -> None:
    inner = {"$lookup": {"from": "c", "pipeline": [lookup(), lookup()], "as": "x"}}
    check_pipeline([inner])  # 1 + 2
    assert message_of(check_pipeline, [inner, lookup()]) == LOOKUPS_MESSAGE
    facet = {"$facet": {"a": [lookup(), lookup()], "b": [lookup(), lookup()]}}
    assert message_of(check_pipeline, [facet]) == LOOKUPS_MESSAGE
    union = {"$unionWith": {"coll": "c", "pipeline": [lookup(), lookup(), lookup()]}}
    assert message_of(check_pipeline, [union]) == LOOKUPS_MESSAGE


def test_unwind_budget() -> None:
    unwind = {"$unwind": "$a"}
    check_pipeline([unwind, unwind])
    expected = "at most 2 $unwind stages are allowed"
    assert message_of(check_pipeline, [unwind, unwind, unwind]) == expected
    nested_unwind = {"$lookup": {"from": "c", "pipeline": [unwind, unwind], "as": "x"}}
    check_pipeline([nested_unwind])
    assert message_of(check_pipeline, [nested_unwind, unwind]) == expected
    facet = {"$facet": {"a": [unwind], "b": [unwind]}}
    check_pipeline([facet])
    assert message_of(check_pipeline, [facet, unwind]) == expected


def test_facet_budget() -> None:
    facet: dict[str, Any] = {"$facet": {"a": [{"$match": {}}]}}
    check_pipeline([facet])
    expected = "at most 1 $facet stage is allowed"
    assert message_of(check_pipeline, [facet, facet]) == expected
    nested_facet = {"$lookup": {"from": "c", "pipeline": [facet], "as": "x"}}
    assert message_of(check_pipeline, [facet, nested_facet]) == expected
    assert message_of(check_pipeline, [{"$facet": {"a": [facet]}}]) == expected


def test_pipeline_walk_failures_come_before_stage_checks() -> None:
    assert message_of(check_pipeline, [{"$out": "x"}]) == (
        "MongoDB operator $out is not allowed (read-only)"
    )
    assert message_of(check_pipeline, [{"$match": {"a": INT64_MAX + 1}}]) == (
        "filter/pipeline integers must fit in 64 bits"
    )
