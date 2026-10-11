"""Wire models never echo their input; the form dependency forwards no context; no secret flag."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, SecretStr, ValidationError, field_validator

from sankey_studio.models import MongoConnection
from sankey_studio.util import mask_uri
from sankey_studio.web.schemas import (
    BootstrapOut,
    ConnectionOut,
    CopyReportOut,
    MongoConnectionIn,
    SettingsIn,
    SettingsOut,
    SettingsSaved,
    UploadForm,
    connection_out,
    forms,
)

if TYPE_CHECKING:
    from fastapi import Request

WIRE_MODELS = [
    BootstrapOut,
    MongoConnectionIn,
    SettingsIn,
    ConnectionOut,
    SettingsOut,
    CopyReportOut,
    SettingsSaved,
    UploadForm,
]
SECRET_URI = "mongodb://user:hunter2@db.example/"


@pytest.mark.parametrize("model", WIRE_MODELS, ids=lambda model: model.__name__)
def test_a_validation_error_never_shows_the_submitted_input(model: type[BaseModel]) -> None:
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"bogus": SECRET_URI, "overwrite": SECRET_URI, "name": SECRET_URI})
    text = str(caught.value)
    assert "hunter2" not in text
    assert "input_value" not in text
    assert "For further information" in text


def test_a_nested_connection_error_does_not_show_the_uri_either() -> None:
    body = {"mongo_connections": [{"name": "ok", "uri": SECRET_URI, "bogus": SECRET_URI}]}
    with pytest.raises(ValidationError) as caught:
        SettingsIn.model_validate(body)
    assert "hunter2" not in str(caught.value)
    assert "input_value" not in str(caught.value)


def test_a_connection_without_a_stored_secret_says_so() -> None:
    conn = MongoConnection.model_construct(
        name="empty", uri=SecretStr(""), default_database="flows"
    )
    out = connection_out(conn, hide_hosts=False)
    assert out.has_secret is False
    assert out.uri_masked == mask_uri("")
    assert connection_out(conn, hide_hosts=False).default_database == "flows"


class StrictForm(UploadForm):
    """An ``UploadForm`` whose one field fails with a ``ValueError`` (errors then carry a ctx)."""

    @field_validator("overwrite")
    @classmethod
    def _refuse(cls, _value: bool) -> bool:
        raise ValueError("refused")


class FakeRequest:
    """The one thing ``upload_form`` asks of a request: its form parts."""

    async def form(self) -> dict[str, Any]:
        return {}


def test_the_form_dependency_forwards_neither_context_input_url_nor_the_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forms, "UploadForm", StrictForm)
    request = cast("Request", FakeRequest())
    with pytest.raises(RequestValidationError) as caught:
        asyncio.run(forms.upload_form(request, True))
    errors = caught.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("body", "overwrite")
    assert errors[0]["type"] == "value_error"
    assert errors[0]["msg"] == "Value error, refused"
    assert set(errors[0]) == {"type", "loc", "msg"}
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_the_form_dependency_returns_the_validated_form() -> None:
    request = cast("Request", FakeRequest())
    assert asyncio.run(forms.upload_form(request, True)) == UploadForm(overwrite=True)
    assert asyncio.run(forms.upload_form(request, False)) == UploadForm(overwrite=False)
