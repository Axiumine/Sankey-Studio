# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``suggest_fields``: the ``_id`` key is never a fallback (a sampled ObjectId is an opaque key)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from bson import ObjectId

from sankey_studio.sources.mongo_inspect import CollectionRef, sample_documents
from sankey_studio.sources.mongo_suggest import FieldSuggestion, suggest_fields
from tests.sources.test_mongo_fakes import FakeMongo

if TYPE_CHECKING:
    from tests.sources.conftest import FakeCtxFactory

OID = "65a0000000000000000000a1"
REPRO = {"_id": OID, "origin_city": "Rome", "dest_city": "Paris", "pax": 120}


class Case(NamedTuple):
    docs: list[dict[str, Any]]
    expected: FieldSuggestion


def suggestion(
    source: str = "source",
    target: str = "target",
    value: str = "value",
    category: str | None = None,
) -> FieldSuggestion:
    return FieldSuggestion(source, target, value, category)


ID_CASES = {
    "the id comes first: the text fields after it are the source and the target": Case(
        [REPRO], suggestion("origin_city", "dest_city", "pax")
    ),
    "the id comes last": Case(
        [{"origin_city": "Rome", "dest_city": "Paris", "pax": 120, "_id": OID}],
        suggestion("origin_city", "dest_city", "pax"),
    ),
    "the id between the two": Case(
        [{"origin_city": "Rome", "_id": OID, "dest_city": "Paris", "pax": 120}],
        suggestion("origin_city", "dest_city", "pax"),
    ),
    "the id is the only text field": Case([{"_id": OID, "pax": 120}], suggestion(value="pax")),
    "one text field next to the id is the source": Case(
        [{"_id": OID, "city": "Rome", "pax": 120}], suggestion("city", "target", "pax")
    ),
    "the id alone": Case([{"_id": OID}], suggestion()),
    "a whole-number id is not the value either": Case(
        [{"_id": 7, "origin_city": "Rome", "dest_city": "Paris", "pax": 120}],
        suggestion("origin_city", "dest_city", "pax"),
    ),
    "a whole-number id is not taken when no other number exists": Case(
        [{"_id": 7, "origin_city": "Rome", "dest_city": "Paris"}],
        suggestion("origin_city", "dest_city"),
    ),
    "an id on every sampled document": Case(
        [{**REPRO, "_id": f"{OID[:-1]}{n}"} for n in range(3)],
        suggestion("origin_city", "dest_city", "pax"),
    ),
    "the id never takes a named role": Case(
        [{"_id": OID, "from": "a", "to": "b", "amount": 5, "type": "t"}],
        suggestion("from", "to", "amount", "type"),
    ),
    "a field called id (no underscore) is an ordinary field": Case(
        [{"id": "x1", "city": "Rome", "pax": 120}], suggestion("id", "city", "pax")
    ),
    "a field whose name only contains the id is an ordinary field": Case(
        [{"_id2": "x1", "city": "Rome", "pax": 120}], suggestion("_id2", "city", "pax")
    ),
}


@pytest.mark.parametrize("case", ID_CASES.values(), ids=ID_CASES)
def test_the_id_is_never_a_fallback(case: Case) -> None:
    assert suggest_fields(case.docs) == case.expected


def test_the_reported_repro_does_not_suggest_the_id() -> None:
    result = suggest_fields([REPRO])
    assert result.source == "origin_city"
    assert result.source != "_id"
    assert result.target != "_id"
    assert result.category != "_id"


def test_the_parts_of_a_compound_id_are_ordinary_fields() -> None:
    docs = [{"_id": {"from": "a", "to": "b"}, "n": 3}]
    assert suggest_fields(docs) == suggestion("_id.from", "_id.to", "n")


def test_a_sampled_object_id_is_not_suggested(mongo_fake_ctx: FakeCtxFactory) -> None:
    """End to end: the sample stringifies the ObjectId, and the suggestion still skips it."""
    doc = {**REPRO, "_id": ObjectId(OID)}
    ctx = mongo_fake_ctx(FakeMongo(docs=[doc]))
    sample = sample_documents(ctx, CollectionRef("test", "flows", "events"))
    assert sample[0]["_id"] == OID
    assert suggest_fields(sample) == suggestion("origin_city", "dest_city", "pax")
