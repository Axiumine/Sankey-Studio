"""Helpers of ``tests/web/test_schemas*.py`` (no tests here): boundary cases and error digests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pydantic import BaseModel


class Case(NamedTuple):
    """One value for one field: ``error`` is the pydantic error type, ``None`` when accepted."""

    field: str
    value: object
    error: str | None = None


def gid(number: int) -> str:
    """A valid graph id (32 lower-case hex characters) that is the same for the same number."""
    return f"{number:032x}"


def digest(exc: pytest.ExceptionInfo[ValidationError]) -> list[tuple[tuple[int | str, ...], str]]:
    """``(location, error type)`` of every error: never the input, never the message."""
    return [(tuple(error["loc"]), error["type"]) for error in exc.value.errors()]


def check_case(model: type[BaseModel], case: Case, base: dict[str, Any] | None = None) -> None:
    """Build ``model`` with the one field of ``case`` (plus ``base``) and judge the outcome."""
    data = {**(base or {}), case.field: case.value}
    if case.error is None:
        built = model.model_validate(data)
        assert getattr(built, case.field) == case.value
        return
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    assert digest(caught) == [((case.field,), case.error)]
