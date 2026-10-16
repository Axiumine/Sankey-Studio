# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""UUIDs as a real driver returns them: ``Binary`` subtype 4 (no ``uuidRepresentation`` set).

mongomock hands back ``uuid.UUID`` objects, so these tests decode with the real ``bson`` codec.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, NamedTuple

import bson
import pytest
from bson import Binary
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions

from sankey_studio.sources.mongo_extract import (
    MISSING,
    FieldMap,
    FieldRejectedError,
    RowParts,
    coerce_name,
    extract_row,
    uuid_from_binary,
)
from sankey_studio.sources.mongo_sample import JsonSanitizer
from tests.sources.test_mongo_fakes import FakeMongo

if TYPE_CHECKING:
    from tests.sources.conftest import FakeRunner, SpecFactory

FIRST = uuid.UUID("12345678-1234-5678-1234-567812345678")
SECOND = uuid.UUID("87654321-4321-8765-4321-876543218765")
THIRD = uuid.UUID("0a0b0c0d-0e0f-4a1b-8c2d-3e4f5a6b7c8d")
NOT_SINGLE = "is not a single text or number value"
STANDARD = CodecOptions[Any](uuid_representation=UuidRepresentation.STANDARD)


def decoded(value: uuid.UUID) -> Any:
    """``value`` after a round trip through the codec with the driver's default options."""
    return bson.decode(bson.encode({"id": value}, codec_options=STANDARD))["id"]


def test_the_driver_default_returns_a_uuid_as_binary_subtype_4() -> None:
    """The premise of everything below: without ``uuidRepresentation`` a UUID is ``Binary``."""
    value = decoded(FIRST)
    assert type(value) is Binary
    assert value.subtype == 4


class Wrapped(NamedTuple):
    value: object
    expected: object  # ``None``: the value itself, untouched


WRAPPED = {
    "subtype 4, 16 bytes": Wrapped(Binary(FIRST.bytes, 4), FIRST),
    "decoded by the driver": Wrapped(decoded(SECOND), SECOND),
    "legacy subtype 3 is ambiguous": Wrapped(Binary(FIRST.bytes, 3), None),
    "generic subtype 0": Wrapped(Binary(FIRST.bytes, 0), None),
    "subtype 4, 15 bytes": Wrapped(Binary(FIRST.bytes[:15], 4), None),
    "subtype 4, 17 bytes": Wrapped(Binary(FIRST.bytes + b"\x00", 4), None),
    "subtype 4, empty": Wrapped(Binary(b"", 4), None),
    "plain bytes": Wrapped(FIRST.bytes, None),
    "a uuid.UUID": Wrapped(FIRST, None),
    "text": Wrapped("x", None),
    "null": Wrapped(None, None),
    "missing": Wrapped(MISSING, None),
}


@pytest.mark.parametrize("case", WRAPPED.values(), ids=WRAPPED)
def test_only_a_well_formed_subtype_4_binary_becomes_a_uuid(case: Wrapped) -> None:
    result = uuid_from_binary(case.value)
    if case.expected is None:
        assert result is case.value
    else:
        assert isinstance(result, uuid.UUID)
        assert result == case.expected


def test_a_binary_uuid_is_a_usable_node_name() -> None:
    assert coerce_name(decoded(FIRST)) == "12345678-1234-5678-1234-567812345678"
    assert coerce_name(Binary(SECOND.bytes, 4)) == str(SECOND)


@pytest.mark.parametrize(
    "value",
    [
        Binary(FIRST.bytes, 3),
        Binary(FIRST.bytes, 0),
        Binary(FIRST.bytes[:15], 4),
        Binary(b"", 4),
    ],
    ids=["legacy subtype 3", "generic subtype 0", "short subtype 4", "empty subtype 4"],
)
def test_any_other_binary_is_still_not_a_name(value: Binary) -> None:
    with pytest.raises(FieldRejectedError) as info:
        coerce_name(value)
    assert str(info.value) == NOT_SINGLE


def test_a_row_of_binary_uuids_keeps_source_target_and_category_readable() -> None:
    fields = FieldMap("source", "target", "value", "category")
    doc = {
        "source": decoded(FIRST),
        "target": decoded(SECOND),
        "value": 2,
        "category": decoded(THIRD),
    }
    assert extract_row(doc, fields) == RowParts(
        str(FIRST), str(SECOND), 2.0, THIRD, text_value=False
    )


def test_a_binary_category_that_is_not_a_uuid_stays_for_the_cleaner_to_refuse() -> None:
    fields = FieldMap("source", "target", None, "category")
    other = Binary(b"abc", 0)
    row = extract_row({"source": "a", "target": "b", "category": other}, fields)
    assert isinstance(row, RowParts)
    assert row.category is other


def test_the_source_streams_binary_uuids_end_to_end(
    mongo_fake_run: FakeRunner, mongo_spec: SpecFactory
) -> None:
    docs = [
        {"source": decoded(FIRST), "target": decoded(SECOND), "value": 3, "kind": decoded(THIRD)},
        {"source": decoded(SECOND), "target": "end", "value": 1, "kind": Binary(b"abc", 0)},
    ]
    result = mongo_fake_run(FakeMongo(docs), mongo_spec(category_field="kind"))
    assert result.rows == [
        (str(FIRST), str(SECOND), 3.0, str(THIRD)),
        (str(SECOND), "end", 1.0, None),
    ]
    assert result.diag.warnings == [
        "Categories ignored (entries kept uncategorised): 1 not a single text/number value"
    ]
    assert result.diag.skipped == 0


class Shown(NamedTuple):
    value: Binary
    text: str


SAMPLED = {
    "subtype 4": Shown(Binary(FIRST.bytes, 4), str(FIRST)),
    "decoded by the driver": Shown(decoded(SECOND), str(SECOND)),
    "subtype 3": Shown(Binary(FIRST.bytes, 3), "<bytes 16>"),
    "generic": Shown(Binary(b"abc", 0), "<bytes 3>"),
    "short subtype 4": Shown(Binary(b"abc", 4), "<bytes 3>"),
}


@pytest.mark.parametrize("case", SAMPLED.values(), ids=SAMPLED)
def test_a_sample_shows_a_binary_uuid_as_text(case: Shown) -> None:
    out = JsonSanitizer().document({"id": case.value, "nested": {"ids": [case.value]}})
    assert out == {"id": case.text, "nested": {"ids": [case.text]}}
