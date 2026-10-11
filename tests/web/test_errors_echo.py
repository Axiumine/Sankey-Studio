"""A 422 never echoes what the caller sent (API.md section 1, "Input echo").

``validation_details`` keeps the location and the message of every pydantic error. The message of
almost every error type names a rule ("String should have at least 2 characters") or lists the
EXPECTED values ("Input should be 'a' or 'b'"); the one type that quotes the submitted value is a
discriminator tag that matches no variant (``union_tag_invalid``: "Input tag 'x' found using
'type' does not match any of the expected tags"). ``tag_message`` replaces it with a sentence made
of the expected tags. The table below drives real pydantic models with a hostile marker for every
error type a request model can raise, and asserts the marker never reaches the message. (A field
name or a dict key is part of the LOCATION and stays: ``body.<key>: Extra inputs are not
permitted``.) The request models have no UUID, e-mail or IP fields, the types whose messages
quote a character of the input.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, NamedTuple

import pytest
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from sankey_studio.models import GraphCreate
from sankey_studio.web.errors import tag_message, validation_details
from tests.web.conftest import SAME_ORIGIN, new_client

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from tests.web.conftest import AppFactory

MARK: Final = "ZZMARK7F3A"
JSON: Final = {"Content-Type": "application/json"}
TAGS: Final = "type must be one of: manual, text, mongo"
GRAPH_TYPES: Final = "body.source: " + TAGS


class Cat(BaseModel):
    type: Literal["cat"]


class Dog(BaseModel):
    type: Literal["dog"]


class Colour(Enum):
    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = 0


class Hostile(BaseModel):
    """One field per kind of rule a request model uses, all with defaults."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="ab", min_length=2, max_length=5, pattern=r"^[a-z]+$")
    number: int = 0
    ratio: float = Field(default=1, gt=0, lt=10)
    flag: bool = True
    choice: Literal["a", "b"] = "a"
    colour: Colour = Colour.RED
    items: list[str] = Field(default_factory=list, max_length=2)
    mapping: dict[str, int] = Field(default_factory=dict)
    pet: Annotated[Cat | Dog, Field(discriminator="type")] = Cat(type="cat")
    nested: Inner = Inner()
    when: datetime | None = None
    url: HttpUrl | None = None
    pair: tuple[int, int] = (1, 2)
    numbers: set[int] = Field(default_factory=set)


class Row(NamedTuple):
    label: str
    payload: dict[str, Any]
    error_types: frozenset[str]


def row(label: str, payload: dict[str, Any], *error_types: str) -> Row:
    return Row(label, payload, frozenset(error_types))


TABLE = [
    row("wrong type", {"text": 5}, "string_type"),
    row("not an int", {"number": MARK}, "int_parsing"),
    row("fraction", {"number": 1.5}, "int_from_float"),
    row("not a float", {"ratio": MARK}, "float_parsing"),
    row("not a bool", {"flag": MARK}, "bool_parsing"),
    row("not in the literals", {"choice": MARK}, "literal_error"),
    row("not in the enum", {"colour": MARK}, "enum"),
    row("too short", {"text": "a"}, "string_too_short"),
    row("too long", {"text": MARK * 40}, "string_too_long"),
    row("pattern", {"text": "AB1"}, "string_pattern_mismatch"),
    row("below the bound", {"ratio": -5}, "greater_than"),
    row("above the bound", {"ratio": 11}, "less_than"),
    row("too many items", {"items": [MARK, MARK, MARK]}, "too_long"),
    row("not a dict", {"mapping": MARK}, "dict_type"),
    row("not a list", {"items": MARK}, "list_type"),
    row("not a model", {"nested": MARK}, "model_type"),
    row("unknown tag", {"pet": {"type": MARK}}, "union_tag_invalid"),
    row("number as tag", {"pet": {"type": 5}}, "union_tag_invalid"),
    row("list as tag", {"pet": {"type": [MARK]}}, "union_tag_invalid"),
    row("no tag", {"pet": {}}, "union_tag_not_found"),
    row("not an object", {"pet": MARK}, "model_attributes_type"),
    row("bad datetime", {"when": MARK}, "datetime_from_date_parsing"),
    row("bad url", {"url": MARK}, "url_parsing"),
    row("bad url scheme", {"url": f"ftp://{MARK}"}, "url_scheme"),
    row("extra key", {MARK: 1}, "extra_forbidden"),
    row("bad dict value", {"mapping": {MARK: MARK}}, "int_parsing"),
    row("bad tuple", {"pair": [MARK, MARK]}, "int_parsing"),
    row("short tuple", {"pair": [1]}, "missing"),
    row("bad set item", {"numbers": [MARK]}, "int_parsing"),
    row("bad nested", {"nested": {"number": MARK, MARK: 1}}, "int_parsing", "extra_forbidden"),
]


def messages(errors: Iterable[Mapping[str, Any]]) -> list[str]:
    """The details of ``validation_details`` without their ``location:`` prefix."""
    errors = list(errors)
    details = validation_details(errors)
    assert len(details) == len(errors)
    out = []
    for error, detail in zip(errors, details, strict=True):
        where = ".".join(str(part) for part in error["loc"])
        prefix = f"{where}: " if where else ""
        assert detail.startswith(prefix)
        out.append(detail.removeprefix(prefix))
    return out


@pytest.mark.parametrize("case", TABLE, ids=lambda case: case.label)
def test_no_error_type_of_the_table_quotes_the_input(case: Row) -> None:
    with pytest.raises(ValidationError) as caught:
        Hostile.model_validate(case.payload)
    errors = caught.value.errors(include_input=False, include_url=False)
    assert {error["type"] for error in errors} == case.error_types
    for message in messages(errors):
        assert MARK not in message


def test_a_malformed_json_text_is_not_quoted_either() -> None:
    with pytest.raises(ValidationError) as caught:
        Hostile.model_validate_json(f'{{"text": "{MARK}')
    errors = caught.value.errors(include_input=False, include_url=False)
    assert [error["type"] for error in errors] == ["json_invalid"]
    assert MARK not in messages(errors)[0]


def test_the_tag_error_says_what_is_allowed_and_not_what_was_sent() -> None:
    with pytest.raises(ValidationError) as caught:
        Hostile.model_validate({"pet": {"type": MARK}})
    (error,) = caught.value.errors(include_input=False, include_url=False)
    assert MARK in error["msg"]  # pydantic's own wording quotes it
    assert validation_details([error]) == ["pet: type must be one of: cat, dog"]


def test_a_missing_tag_is_a_required_field() -> None:
    with pytest.raises(ValidationError) as caught:
        Hostile.model_validate({"pet": {}})
    assert validation_details(caught.value.errors()) == ["pet: type is required"]


class Tag(NamedTuple):
    label: str
    error: dict[str, Any]
    expected: str


TAGS_TABLE = [
    Tag(
        "invalid",
        {
            "type": "union_tag_invalid",
            "ctx": {"discriminator": "'kind'", "expected_tags": "'a', 'b'"},
        },
        "kind must be one of: a, b",
    ),
    Tag(
        "invalid with the tag in the context",
        {
            "type": "union_tag_invalid",
            "msg": f"Input tag '{MARK}' found using 'kind' does not match",
            "ctx": {"discriminator": "'kind'", "expected_tags": "'a'", "tag": MARK},
        },
        "kind must be one of: a",
    ),
    Tag("invalid without context", {"type": "union_tag_invalid"}, "tag is not valid"),
    Tag(
        "invalid without tags",
        {"type": "union_tag_invalid", "ctx": {"discriminator": "'kind'"}},
        "kind is not valid",
    ),
    Tag(
        "not found",
        {"type": "union_tag_not_found", "ctx": {"discriminator": "'kind'"}},
        "kind is required",
    ),
    Tag("not found without context", {"type": "union_tag_not_found"}, "tag is required"),
    Tag(
        "not found with a null context",
        {"type": "union_tag_not_found", "ctx": None},
        "tag is required",
    ),
]


@pytest.mark.parametrize("case", TAGS_TABLE, ids=lambda case: case.label)
def test_tag_message(case: Tag) -> None:
    assert tag_message(case.error) == case.expected
    assert MARK not in tag_message(case.error)


def test_only_the_tag_types_are_rewritten() -> None:
    errors: list[dict[str, Any]] = [
        {"loc": ("a",), "type": "union_tag_invalid", "msg": f"quotes {MARK}", "ctx": {}},
        {"loc": ("b",), "type": "value_error", "msg": "Value error, named reason"},
        {"loc": ("c",), "msg": "no type at all"},
        {"loc": (), "type": "union_tag_not_found", "msg": f"quotes {MARK}"},
    ]
    assert validation_details(errors) == [
        "a: tag is not valid",
        "b: Value error, named reason",
        "c: no type at all",
        "tag is required",
    ]


# ------------------------------------------------------------------------------ over HTTP

router = APIRouter()


@router.post("/api/v1/probe/graph")
def _graph(body: GraphCreate) -> dict[str, str]:
    return {"name": body.name}


@router.get("/api/v1/probe/model")
def _model() -> None:
    GraphCreate.model_validate({"name": "x", "source": {"type": MARK}})


@pytest.mark.parametrize("tag", [MARK, f"<{MARK}>", MARK * 500, 5, None, [MARK], {MARK: MARK}])
def test_an_unknown_source_type_lists_the_allowed_types_only(
    make_app: AppFactory, tag: object
) -> None:
    web = make_app([router])
    response = web.client.post(
        "/api/v1/probe/graph", json={"name": "x", "source": {"type": tag}}, headers=JSON
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "The request is not valid",
            "details": [GRAPH_TYPES],
        }
    }
    assert MARK not in response.text


def test_a_source_without_a_type_is_a_required_field(make_app: AppFactory) -> None:
    web = make_app([router])
    response = web.client.post(
        "/api/v1/probe/graph", json={"name": "x", "source": {}}, headers=JSON
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["body.source: type is required"]


def test_a_valid_source_type_is_untouched(make_app: AppFactory) -> None:
    web = make_app([router])
    source = {"type": "manual", "links": []}
    response = web.client.post(
        "/api/v1/probe/graph", json={"name": "x", "source": source}, headers=JSON
    )
    assert response.status_code == 200


def test_a_model_validated_inside_a_route_says_the_same(make_app: AppFactory) -> None:
    web = make_app([router])
    response = new_client(web.app, SAME_ORIGIN).get("/api/v1/probe/model")
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["source: " + TAGS]
    assert MARK not in response.text
