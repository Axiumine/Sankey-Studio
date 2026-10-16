# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``storage.common``: the behaviour both repositories share."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from sankey_studio.errors import ConflictError, StorageError
from sankey_studio.models import SCHEMA_VERSION, StyleSpec, TransformSpec
from sankey_studio.storage import common
from sankey_studio.storage.common import (
    MSG_EXISTS,
    MSG_STALE,
    MSG_UNREADABLE,
    PAGE_MAX,
    SEARCH_MAX,
    clamp_page,
    exists_error,
    new_definition,
    parse_definition,
    revised_definition,
    search_term,
    stale_error,
    summary_of,
    utc_now,
    validation_lines,
)
from tests.storage.support import ID_A, NOW, Spec, create_data, definition, update_data

# --------------------------------------------------------------------------- utc_now


def _frozen_datetime(microsecond: int, seen: list[object]) -> type[datetime]:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Frozen:
            seen.append(tz)
            return cls(2025, 1, 2, 3, 4, 5, microsecond, tzinfo=tz)

    return Frozen


@pytest.mark.parametrize(
    ("microsecond", "expected"),
    [(0, 0), (1, 0), (999, 0), (1000, 1000), (123_456, 123_000), (999_999, 999_000)],
)
def test_utc_now_is_cut_to_whole_milliseconds(
    monkeypatch: pytest.MonkeyPatch, microsecond: int, expected: int
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(common, "datetime", _frozen_datetime(microsecond, seen))
    result = utc_now()
    assert result.microsecond == expected
    assert (result.year, result.month, result.day) == (2025, 1, 2)
    assert (result.hour, result.minute, result.second) == (3, 4, 5)
    assert seen == [UTC]
    assert result.utcoffset() == timedelta(0)


def test_utc_now_is_aware_and_current() -> None:
    before = datetime.now(UTC)
    result = utc_now()
    assert result.tzinfo is not None
    assert before - timedelta(milliseconds=1) <= result <= datetime.now(UTC)


# --------------------------------------------------------------------------- search_term


class Term(NamedTuple):
    raw: str | None
    expected: str | None


@pytest.mark.parametrize(
    "case",
    [
        Term(None, None),
        Term("", None),
        Term("   ", None),
        Term("\n\t ", None),
        Term("abc", "abc"),
        Term("  a b  ", "a b"),
        Term("x" * (SEARCH_MAX - 1), "x" * (SEARCH_MAX - 1)),
        Term("x" * SEARCH_MAX, "x" * SEARCH_MAX),
        Term("x" * (SEARCH_MAX + 1), "x" * SEARCH_MAX),
        Term("  " + "x" * 250, "x" * SEARCH_MAX),
    ],
)
def test_search_term(case: Term) -> None:
    assert search_term(case.raw) == case.expected


def test_the_search_limit_is_two_hundred() -> None:
    assert SEARCH_MAX == 200


# --------------------------------------------------------------------------- clamp_page


@pytest.mark.parametrize(
    ("limit", "offset", "expected"),
    [
        (200, 0, (200, 0)),
        (1, 1, (1, 1)),
        (0, 0, (0, 0)),
        (-1, 5, (0, 5)),
        (5, -1, (5, 0)),
        (-9, -9, (0, 0)),
        (PAGE_MAX - 1, PAGE_MAX - 1, (PAGE_MAX - 1, PAGE_MAX - 1)),
        (PAGE_MAX, PAGE_MAX, (PAGE_MAX, PAGE_MAX)),
        (PAGE_MAX + 1, PAGE_MAX + 1, (PAGE_MAX, PAGE_MAX)),
        (PAGE_MAX + 1, 3, (PAGE_MAX, 3)),
        (3, PAGE_MAX + 1, (3, PAGE_MAX)),
        (2**63 - 1, 2**63, (PAGE_MAX, PAGE_MAX)),
        (2**64, 10**30, (PAGE_MAX, PAGE_MAX)),
        (-(2**64), -(10**30), (0, 0)),
    ],
)
def test_clamp_page(limit: int, offset: int, expected: tuple[int, int]) -> None:
    assert clamp_page(limit, offset) == expected


def test_the_page_cap_is_the_largest_signed_32_bit_integer() -> None:
    assert PAGE_MAX == 2_147_483_647


# --------------------------------------------------------------------------- definitions


def test_summary_copies_the_listing_fields() -> None:
    graph = definition(ID_A, "Budget", Spec("d", ("x", "y"), updated_at=NOW + timedelta(days=1)))
    summary = summary_of(graph)
    assert summary.id == ID_A
    assert (summary.name, summary.description) == ("Budget", "d")
    assert summary.tags == ["x", "y"]
    assert summary.tags is not graph.tags
    assert summary.source_type == "manual"
    assert summary.revision == 1
    assert summary.updated_at == NOW + timedelta(days=1)


def test_a_new_definition_starts_at_revision_one_with_a_fresh_id() -> None:
    data = create_data("Plan", Spec("about", ("t",), links=2))
    first, second = new_definition(data, NOW), new_definition(data, NOW)
    assert first.id != second.id
    assert len(first.id) == 32
    assert first.revision == 1
    assert first.schema_version == SCHEMA_VERSION
    assert first.created_at == first.updated_at == NOW
    assert (first.name, first.description, first.tags) == ("Plan", "about", ["t"])
    assert first.source == data.source
    assert first.transform == data.transform
    assert first.style == data.style


def test_a_revision_keeps_identity_and_bumps_the_counter() -> None:
    current = definition(ID_A, "old", spec=Spec("old text", ("old",)))
    later = NOW + timedelta(hours=2)
    data = update_data(1, "new", Spec("new text", ("new",), links=3))
    revised = revised_definition(current, data, later)
    assert revised.id == ID_A
    assert revised.created_at == current.created_at == NOW
    assert revised.updated_at == later
    assert revised.revision == 2
    assert revised.schema_version == SCHEMA_VERSION
    assert (revised.name, revised.description, revised.tags) == ("new", "new text", ["new"])
    assert revised.source == data.source
    assert revised.transform == data.transform
    assert revised.style == data.style


def test_a_revision_carries_the_new_transform_and_style() -> None:
    data = update_data(1).model_copy(
        update={
            "transform": TransformSpec(min_link_value=2.5, strict=True),
            "style": StyleSpec(color_mode="mono", title="T"),
        }
    )
    revised = revised_definition(definition(), data, NOW)
    assert revised.transform == TransformSpec(min_link_value=2.5, strict=True)
    assert revised.style == StyleSpec(color_mode="mono", title="T")


def test_a_new_definition_carries_the_transform_and_style() -> None:
    data = create_data("g").model_copy(
        update={
            "transform": TransformSpec(min_link_value=2.5, strict=True),
            "style": StyleSpec(color_mode="mono", title="T"),
        }
    )
    created = new_definition(data, NOW)
    assert created.transform == TransformSpec(min_link_value=2.5, strict=True)
    assert created.style == StyleSpec(color_mode="mono", title="T")


def test_new_and_revised_graphs_are_stamped_with_the_current_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common, "SCHEMA_VERSION", 2)
    assert new_definition(create_data("g"), NOW).schema_version == 2
    assert revised_definition(definition(), update_data(1), NOW).schema_version == 2


FOLDER = "f" * 32


def _in_folder(folder_id: str | None) -> Any:
    return definition(ID_A).model_copy(update={"folder_id": folder_id})


@pytest.mark.parametrize("folder_id", [None, FOLDER])
def test_the_summary_carries_the_folder(folder_id: str | None) -> None:
    assert summary_of(_in_folder(folder_id)).folder_id == folder_id


@pytest.mark.parametrize("folder_id", [None, FOLDER])
def test_a_new_definition_sits_in_the_folder_it_is_created_in(folder_id: str | None) -> None:
    assert new_definition(create_data("g"), NOW, folder_id).folder_id == folder_id


def test_a_new_definition_defaults_to_the_top_level() -> None:
    assert new_definition(create_data("g"), NOW).folder_id is None


@pytest.mark.parametrize("folder_id", [None, FOLDER])
def test_a_revision_keeps_the_folder_of_the_stored_graph(folder_id: str | None) -> None:
    revised = revised_definition(_in_folder(folder_id), update_data(1), NOW)
    assert revised.folder_id == folder_id


def test_the_revision_counter_follows_the_stored_graph_not_the_request() -> None:
    current = definition(spec=Spec(revision=7))
    assert revised_definition(current, update_data(7), NOW).revision == 8


# --------------------------------------------------------------------------- conflicts


def test_the_stale_error_carries_the_current_state() -> None:
    err = stale_error(3, NOW)
    assert isinstance(err, ConflictError)
    assert (
        err.message
        == MSG_STALE
        == "Graph was modified since you loaded it; reload it or save a copy"
    )
    assert (err.status_code, err.code) == (409, "conflict")
    assert (err.current_revision, err.current_updated_at) == (3, NOW)
    assert err.details == ["revision=3", f"updated_at={NOW.isoformat()}"]


def test_the_exists_error_names_the_taken_id() -> None:
    err = exists_error(4, NOW)
    assert err.message == MSG_EXISTS == "A graph with this id already exists"
    assert err.details == ["revision=4", f"updated_at={NOW.isoformat()}"]


@pytest.mark.parametrize("factory", [stale_error, exists_error])
def test_a_conflict_without_a_known_state_has_no_details(factory: Any) -> None:
    err = factory(None, None)
    assert err.details == []
    assert err.current_revision is None
    assert err.current_updated_at is None


# --------------------------------------------------------------------------- parse_definition


def _doc(**extra: object) -> dict[str, Any]:
    return {
        "id": ID_A,
        "name": "g",
        "source": {"type": "manual", "links": []},
        "created_at": NOW,
        "updated_at": NOW,
        **extra,
    }


def test_parse_definition_upgrades_then_validates() -> None:
    graph = parse_definition({**_doc(), "_id": ID_A})
    assert graph.id == ID_A
    assert graph.schema_version == 1


def test_parse_definition_refuses_a_newer_schema() -> None:
    with pytest.raises(StorageError) as info:
        parse_definition(_doc(schema_version=SCHEMA_VERSION + 1))
    assert info.value.message == "Stored graph was written by a newer version of sankey-studio"


def test_parse_definition_reports_invalid_content_without_echoing_it() -> None:
    with pytest.raises(StorageError) as info:
        parse_definition(_doc(name="", tags="not-a-list-SECRET"))
    assert info.value.message == MSG_UNREADABLE == "Stored graph is unreadable"
    assert "SECRET" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_parse_definition_rejects_naive_timestamps() -> None:
    naive = datetime(2025, 1, 1)  # noqa: DTZ001 - a naive datetime is the input under test
    with pytest.raises(StorageError, match="unreadable"):
        parse_definition(_doc(created_at=naive))


# --------------------------------------------------------------------------- validation_lines


class Narrow(BaseModel):
    """A model with a field error, a nested error and a model-level error."""

    model_config = ConfigDict(hide_input_in_errors=True)

    count: int = Field(ge=1)
    names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Narrow:
        if self.count == 7:
            raise ValueError("seven is unlucky")
        return self


def _errors_of(data: dict[str, Any]) -> ValidationError:
    with pytest.raises(ValidationError) as info:
        Narrow.model_validate(data)
    return info.value


def test_validation_lines_are_location_and_message() -> None:
    exc = _errors_of({"count": 0, "names": ["ok", 5]})
    assert validation_lines(exc, "root") == [
        "count: Input should be greater than or equal to 1",
        "names.1: Input should be a valid string",
    ]


def test_a_model_level_error_is_labelled_with_the_root() -> None:
    exc = _errors_of({"count": 7})
    assert validation_lines(exc, "thing") == ["thing: Value error, seven is unlucky"]
    assert validation_lines(exc, "other") == ["other: Value error, seven is unlucky"]


def test_validation_lines_never_hold_the_input() -> None:
    lines = validation_lines(_errors_of({"count": "SECRET-INPUT"}), "root")
    assert lines == ["count: Input should be a valid integer, unable to parse string as an integer"]
    assert "SECRET" not in " ".join(lines)
