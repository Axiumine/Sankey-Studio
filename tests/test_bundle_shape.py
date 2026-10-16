# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``RenderBundle`` / ``BundleStats``: every field is required and the counts are integers."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from sankey_studio.bundle import BundleStats, RenderBundle
from tests.test_bundle import bundle, stats

BUNDLE_FIELDS = [
    "figure",
    "legend",
    "donut_available",
    "donut",
    "donut_empty_reason",
    "categories",
    "category_names",
    "stats",
    "entries",
    "entries_total",
    "nodes",
    "warnings",
]
#: ``nodes`` is optional (only ``POST /preview`` fills it); every other field is required.
REQUIRED_FIELDS = [name for name in BUNDLE_FIELDS if name != "nodes"]
STATS_FIELDS = [
    "nodes",
    "links",
    "drawn_links",
    "total_in",
    "total_out",
    "layers",
    "category_count",
]
COUNTS = ["nodes", "links", "drawn_links", "layers", "category_count"]


def error_digest(exc: pytest.ExceptionInfo[ValidationError]) -> list[tuple[Any, str]]:
    return [(tuple(error["loc"]), error["type"]) for error in exc.value.errors()]


def test_the_model_fields_are_in_the_documented_order() -> None:
    assert list(RenderBundle.model_fields) == BUNDLE_FIELDS
    assert list(BundleStats.model_fields) == STATS_FIELDS


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_a_bundle_without_one_field_is_refused(field: str) -> None:
    complete = bundle().model_dump()
    del complete[field]
    with pytest.raises(ValidationError) as caught:
        RenderBundle.model_validate(complete)
    assert error_digest(caught) == [((field,), "missing")]


def test_a_bundle_without_nodes_has_an_empty_node_list() -> None:
    complete = bundle().model_dump()
    del complete["nodes"]
    assert RenderBundle.model_validate(complete).nodes == []
    assert bundle().nodes == []


@pytest.mark.parametrize("field", STATS_FIELDS)
def test_stats_without_one_field_are_refused(field: str) -> None:
    complete = stats().model_dump()
    del complete[field]
    with pytest.raises(ValidationError) as caught:
        BundleStats.model_validate(complete)
    assert error_digest(caught) == [((field,), "missing")]


@pytest.mark.parametrize("field", COUNTS)
def test_a_count_must_be_a_whole_number(field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        stats(**{field: 1.5})
    assert error_digest(caught) == [((field,), "int_from_float")]


def test_entries_total_must_be_a_whole_number() -> None:
    with pytest.raises(ValidationError) as caught:
        bundle(entries_total=1.5)
    assert error_digest(caught) == [(("entries_total",), "int_from_float")]


def test_the_counts_are_written_as_integers_and_the_totals_as_floats() -> None:
    text = stats(total_in=3, total_out=2).model_dump_json()
    written = json.loads(text)
    for field in COUNTS:
        assert isinstance(written[field], int)
    assert '"layers":2' in text
    assert '"total_in":3.0' in text
    assert '"total_out":2.0' in text
