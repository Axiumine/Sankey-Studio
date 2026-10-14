"""Edit models: ``AddEntry``, ``SetCategory``, ``ReorderNodes``, ``EditRequest``, outcomes."""

from __future__ import annotations

import math
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from sankey_studio.models import (
    SILENT_REASONS,
    AddEntry,
    EditOutcome,
    EditRequest,
    ManualSource,
    Reason,
    ReorderNodes,
    SetCategory,
    SourceEdit,
    StylePins,
    TextSource,
)

ADD: dict[str, Any] = {"op": "add_entry", "source": "Budget", "target": "Gifts", "value": 50}
SET: dict[str, Any] = {"op": "set_category", "source": "Budget", "target": "Rent", "category": None}
ORDER: dict[str, Any] = {"op": "reorder", "order": ["Salary", "Budget"]}
EDITS: TypeAdapter[Any] = TypeAdapter(SourceEdit)
DRAFT = {"source": {"type": "manual"}}


def message(exc: pytest.ExceptionInfo[ValidationError]) -> str:
    errors = exc.value.errors(include_input=False, include_context=False, include_url=False)
    assert len(errors) == 1
    return errors[0]["msg"]


def test_the_reason_list_has_25_stable_members() -> None:
    reasons = get_args(Reason)
    assert len(reasons) == 25
    assert len(set(reasons)) == 25
    assert "would_recolour" in reasons
    assert {"preference", "order_in_graph"} == SILENT_REASONS
    assert set(reasons) >= SILENT_REASONS
    assert isinstance(SILENT_REASONS, frozenset)


@pytest.mark.parametrize("value", [1e-300, 0.5, 1, 50, 1e300])
def test_a_positive_finite_value_is_accepted(value: float) -> None:
    assert AddEntry.model_validate({**ADD, "value": value}).value == value


@pytest.mark.parametrize("value", [0, -1, -1e-300, math.inf, -math.inf, math.nan, "x", None])
def test_other_values_are_refused(value: Any) -> None:
    with pytest.raises(ValidationError):
        AddEntry.model_validate({**ADD, "value": value})


def test_an_entry_needs_two_different_ends() -> None:
    with pytest.raises(ValidationError) as caught:
        AddEntry.model_validate({**ADD, "target": "Budget"})
    assert message(caught) == "Value error, source and target must differ"
    assert AddEntry.model_validate({**ADD, "target": "budget"}).target == "budget"


@pytest.mark.parametrize("field", ["source", "target"])
@pytest.mark.parametrize("name", ["", "   ", "x" * 201, "a\0b"])
def test_an_entry_end_is_a_valid_node_name(field: str, name: str) -> None:
    with pytest.raises(ValidationError):
        AddEntry.model_validate({**ADD, field: name})


def test_an_entry_category_is_optional_normalised_and_never_reserved() -> None:
    assert AddEntry.model_validate(ADD).category is None
    assert AddEntry.model_validate({**ADD, "category": "  Fun   time "}).category == "Fun time"
    assert AddEntry.model_validate({**ADD, "category": ""}).category is None
    assert AddEntry.model_validate({**ADD, "category": "x" * 100}).category == "x" * 100
    for bad in ("Other", "uncategorized", "x" * 101, "a\x00b"):
        with pytest.raises(ValidationError):
            AddEntry.model_validate({**ADD, "category": bad})


def test_set_category_needs_the_category_field_even_to_clear() -> None:
    assert SetCategory.model_validate(SET).category is None
    assert SetCategory.model_validate({**SET, "category": "Home"}).category == "Home"
    without = {k: v for k, v in SET.items() if k != "category"}
    with pytest.raises(ValidationError) as caught:
        SetCategory.model_validate(without)
    assert caught.value.errors()[0]["type"] == "missing"
    with pytest.raises(ValidationError):
        SetCategory.model_validate({**SET, "category": "Other"})


def test_reorder_accepts_unique_names_up_to_the_limit() -> None:
    assert ReorderNodes.model_validate(ORDER).order == ["Salary", "Budget"]
    assert ReorderNodes.model_validate({**ORDER, "order": []}).order == []
    full = [f"n{i}" for i in range(5_000)]
    assert len(ReorderNodes.model_validate({**ORDER, "order": full}).order) == 5_000
    with pytest.raises(ValidationError):
        ReorderNodes.model_validate({**ORDER, "order": [*full, "more"]})


def test_reorder_refuses_a_repeated_name() -> None:
    with pytest.raises(ValidationError) as caught:
        ReorderNodes.model_validate({**ORDER, "order": ["a", "b", "a"]})
    assert message(caught) == "Value error, order must not repeat a node name"


@pytest.mark.parametrize(
    ("data", "kind"), [(ADD, AddEntry), (SET, SetCategory), (ORDER, ReorderNodes)]
)
def test_the_op_tag_selects_the_edit(data: dict[str, Any], kind: type) -> None:
    assert type(EDITS.validate_python(data)) is kind


@pytest.mark.parametrize("op", ["", "delete", "ADD_ENTRY", None])
def test_an_unknown_op_is_refused(op: Any) -> None:
    with pytest.raises(ValidationError) as caught:
        EDITS.validate_python({**ADD, "op": op})
    assert caught.value.errors()[0]["type"] in {"union_tag_invalid", "union_tag_not_found"}


def test_a_missing_op_is_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        EDITS.validate_python({k: v for k, v in ADD.items() if k != "op"})
    assert caught.value.errors()[0]["type"] == "union_tag_not_found"


@pytest.mark.parametrize("data", [ADD, SET, ORDER])
def test_edits_forbid_unknown_fields(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EDITS.validate_python({**data, "extra": 1})


def test_a_request_carries_a_draft_and_one_edit() -> None:
    request = EditRequest.model_validate({"draft": DRAFT, "edit": ADD})
    assert isinstance(request.edit, AddEntry)
    assert isinstance(request.draft.source, ManualSource)
    for body in ({"draft": DRAFT}, {"edit": ADD}, {"draft": DRAFT, "edit": ADD, "x": 1}):
        with pytest.raises(ValidationError):
            EditRequest.model_validate(body)


def test_an_outcome_defaults() -> None:
    outcome = EditOutcome(where="draft")
    assert outcome.model_dump() == {
        "where": "draft",
        "written": False,
        "consent": "none",
        "reason": None,
        "notice": None,
        "target": None,
        "target_key": None,
        "changed": 0,
        "source": None,
        "override": None,
        "pins": None,
    }


def test_pins_are_hex_maps_that_can_be_empty() -> None:
    assert StylePins().empty
    assert not StylePins(node_colors={"a": "#112233"}).empty
    assert not StylePins(category_colors={"Red": "#112233"}).empty
    outcome = EditOutcome.model_validate(
        {"where": "draft", "pins": {"node_colors": {"a": "#112233"}}}
    )
    assert outcome.pins == StylePins(node_colors={"a": "#112233"})
    for bad in ({"node_colors": {"a": "red"}}, {"category_colors": {"A": "#12345"}}):
        with pytest.raises(ValidationError):
            StylePins.model_validate(bad)
    with pytest.raises(ValidationError):
        StylePins.model_validate({"surprise": {}})


@pytest.mark.parametrize("where", ["draft", "file", "mongo", "graph"])
def test_an_outcome_names_one_of_four_places(where: str) -> None:
    assert EditOutcome.model_validate({"where": where}).where == where


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("where", "cloud"),
        ("consent", "yes"),
        ("reason", "because"),
        ("override", "keep"),
        ("surprise", 1),
    ],
)
def test_an_outcome_refuses_other_words(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        EditOutcome.model_validate({"where": "file", field: value})


@pytest.mark.parametrize("reason", get_args(Reason))
def test_every_reason_is_accepted(reason: str) -> None:
    assert EditOutcome(where="graph", reason=reason).reason == reason  # type: ignore[arg-type]


def test_an_outcome_carries_the_target_key_and_the_new_source() -> None:
    outcome = EditOutcome.model_validate(
        {
            "where": "file",
            "written": True,
            "consent": "granted",
            "target": "budget/2025.csv",
            "target_key": "file:budget/2025.csv",
            "changed": 1,
            "override": "drop",
            "source": {"type": "text", "content": "a,b,1"},
        }
    )
    assert outcome.target_key == "file:budget/2025.csv"
    assert isinstance(outcome.source, TextSource)
    assert (outcome.written, outcome.consent, outcome.changed) == (True, "granted", 1)
    with pytest.raises(ValidationError):
        EditOutcome(where="file", changed="many")  # type: ignore[arg-type]
