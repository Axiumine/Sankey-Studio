"""The upload form: the ``overwrite`` field next to the file part of a multipart request."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request, UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sankey_studio.web.errors import register_error_handlers
from sankey_studio.web.schemas import UPLOAD_FILE_FIELD, UploadForm, UploadFormDep, upload_form
from tests.web.test_schemas_support import digest


def upload(file: UploadFile, form: UploadFormDep) -> dict[str, Any]:
    return {"name": file.filename, "overwrite": form.overwrite}


def make_app(*, envelope: bool) -> FastAPI:
    """The upload route alone; ``envelope`` adds the error handlers of the real app."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.post("/upload")(upload)
    if envelope:
        register_error_handlers(app)
    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(make_app(envelope=False))


@pytest.fixture(scope="module")
def enveloped() -> TestClient:
    return TestClient(make_app(envelope=True))


def post(client: TestClient, data: dict[str, str] | None = None) -> Any:
    return client.post("/upload", files={"file": ("flows.csv", b"a,b,1\n")}, data=data)


def test_overwrite_defaults_to_false_and_the_file_part_is_called_file() -> None:
    assert UploadForm().overwrite is False
    assert UploadForm(overwrite=True).overwrite is True
    assert UPLOAD_FILE_FIELD == "file"


def test_unknown_form_fields_are_refused_by_the_model() -> None:
    with pytest.raises(ValidationError) as caught:
        UploadForm.model_validate({"overwrite": True, "name": "x"})
    assert digest(caught) == [(("name",), "extra_forbidden")]


@pytest.mark.parametrize(
    ("data", "overwrite"),
    [(None, False), ({"overwrite": "true"}, True), ({"overwrite": "false"}, False)],
)
def test_the_route_reads_overwrite_next_to_the_file(
    client: TestClient, data: dict[str, str] | None, overwrite: bool
) -> None:
    response = post(client, data)
    assert response.status_code == 200
    assert response.json() == {"name": "flows.csv", "overwrite": overwrite}


def test_a_bad_overwrite_value_is_a_422_on_the_body(client: TestClient) -> None:
    response = post(client, {"overwrite": "perhaps"})
    assert response.status_code == 422
    assert [(item["loc"], item["type"]) for item in response.json()["detail"]] == [
        (["body", "overwrite"], "bool_parsing")
    ]


def test_the_file_part_is_still_required(client: TestClient) -> None:
    response = client.post("/upload", data={"overwrite": "true"})
    assert response.status_code == 422
    assert [item["loc"] for item in response.json()["detail"]] == [["body", "file"]]


def test_a_misspelt_field_is_a_422_and_not_the_silent_default(client: TestClient) -> None:
    response = post(client, {"overwite": "true"})
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "extra_forbidden",
                "loc": ["body", "overwite"],
                "msg": "Extra inputs are not permitted",
            }
        ]
    }


def test_a_known_field_does_not_hide_an_unknown_one(client: TestClient) -> None:
    response = post(client, {"overwrite": "true", "zebra": "1", "apple": "2"})
    assert response.status_code == 422
    assert sorted(item["loc"][1] for item in response.json()["detail"]) == ["apple", "zebra"]


def test_a_second_file_part_under_another_name_is_refused(client: TestClient) -> None:
    files = {"file": ("flows.csv", b"a,b,1\n"), "junk": ("junk.csv", b"c,d,2\n")}
    response = client.post("/upload", files=files)
    assert response.status_code == 422
    assert [(item["loc"], item["type"]) for item in response.json()["detail"]] == [
        (["body", "junk"], "extra_forbidden")
    ]


def test_the_real_error_envelope_names_the_unknown_field(enveloped: TestClient) -> None:
    response = post(enveloped, {"overwite": "true"})
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "The request is not valid",
            "details": ["body.overwite: Extra inputs are not permitted"],
        }
    }
    assert post(enveloped, {"overwrite": "true"}).json() == {"name": "flows.csv", "overwrite": True}


class StubRequest:
    """The one thing ``upload_form`` asks of a request: its parsed multipart form."""

    def __init__(self, parts: dict[str, str]) -> None:
        self._parts = parts

    async def form(self) -> dict[str, str]:
        return self._parts


def test_the_dependency_called_without_the_field_keeps_the_safe_default() -> None:
    """Called directly (no FastAPI to fill the default in), the default is the dependency's own."""
    request = cast("Request", StubRequest({UPLOAD_FILE_FIELD: "flows.csv"}))
    assert asyncio.run(upload_form(request)).overwrite is False
    assert asyncio.run(upload_form(request, overwrite=True)).overwrite is True
