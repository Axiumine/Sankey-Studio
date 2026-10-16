# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``ids=`` parsing: comma separated, trimmed, de-duplicated, bounded and pattern-checked."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sankey_studio.web.schemas import CompareQuery, IdsQuery, split_ids
from tests.web.test_schemas_support import digest, gid


def ids(*numbers: int) -> list[str]:
    return [gid(n) for n in numbers]


# --------------------------------------------------------------------------- split_ids


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", ["a"]),
        ("a,b", ["a", "b"]),
        (" a , b ", ["a", "b"]),
        ("a,b,a,c,b", ["a", "b", "c"]),
        (["a,b", "c"], ["a", "b", "c"]),
        (["a", "b,a"], ["a", "b"]),
        ([], []),
        ("", [""]),
        ("a,", ["a", ""]),
        ("a,,b", ["a", "", "b"]),
    ],
)
def test_split_ids(raw: object, expected: list[str]) -> None:
    assert split_ids(raw) == expected


@pytest.mark.parametrize("raw", [None, 5, 1.5, ("a", "b"), {"a"}, [1], ["a", 2], {"a": 1}])
def test_anything_else_is_left_to_pydantic(raw: object) -> None:
    assert split_ids(raw) is raw


# --------------------------------------------------------------------------- the bounds


IdModel = type[CompareQuery] | type[IdsQuery]


@pytest.mark.parametrize(
    ("model", "most"), [(CompareQuery, 12), (IdsQuery, 200)], ids=["compare", "export"]
)
def test_the_most_ids_are_accepted_and_one_more_is_not(model: IdModel, most: int) -> None:
    accepted = ",".join(ids(*range(most)))
    assert model.model_validate({"ids": accepted}).ids == ids(*range(most))
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"ids": ",".join(ids(*range(most + 1)))})
    assert digest(caught) == [(("ids",), "too_long")]


@pytest.mark.parametrize("model", [CompareQuery, IdsQuery])
def test_at_least_one_id_is_needed(model: IdModel) -> None:
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"ids": []})
    assert digest(caught) == [(("ids",), "too_short")]
    assert model.model_validate({"ids": gid(1)}).ids == ids(1)


def test_duplicates_do_not_count_towards_the_bound() -> None:
    thirteen = ids(*range(12)) + ids(0)
    assert CompareQuery.model_validate({"ids": ",".join(thirteen)}).ids == ids(*range(12))


def test_a_repeated_parameter_and_commas_mix() -> None:
    query = CompareQuery.model_validate({"ids": [f"{gid(1)},{gid(2)}", gid(3), gid(1)]})
    assert query.ids == ids(1, 2, 3)


def test_the_order_of_the_ids_is_kept() -> None:
    assert IdsQuery.model_validate({"ids": ",".join(ids(3, 1, 2))}).ids == ids(3, 1, 2)


# --------------------------------------------------------------------------- the pattern

BAD = [
    "x",
    "ABCDEF0123456789ABCDEF0123456789",
    "a" * 31,
    "a" * 33,
    "../etc/passwd",
    "g" * 32,
    ("0" * 31) + "\x00",
    "%2e%2e",
]


@pytest.mark.parametrize("bad", BAD)
def test_a_malformed_id_is_an_error_on_its_own_position(bad: str) -> None:
    with pytest.raises(ValidationError) as caught:
        IdsQuery.model_validate({"ids": f"{gid(1)},{bad}"})
    assert digest(caught) == [(("ids", 1), "string_pattern_mismatch")]


def test_an_empty_piece_is_malformed() -> None:
    for text in ("", f"{gid(1)},", f",{gid(1)}"):
        with pytest.raises(ValidationError) as caught:
            CompareQuery.model_validate({"ids": text})
        assert digest(caught)[0][1] == "string_pattern_mismatch"


def test_the_bound_error_does_not_echo_the_input() -> None:
    with pytest.raises(ValidationError) as caught:
        CompareQuery.model_validate({"ids": "not-an-id"})
    assert "not-an-id" not in str(caught.value)


def test_types_other_than_text_are_type_errors() -> None:
    with pytest.raises(ValidationError) as caught:
        CompareQuery.model_validate({"ids": 5})
    assert digest(caught) == [(("ids",), "list_type")]
    with pytest.raises(ValidationError) as caught:
        CompareQuery.model_validate({"ids": [1]})
    assert digest(caught) == [(("ids", 0), "string_type")]
