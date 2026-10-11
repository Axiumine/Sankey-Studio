"""Pins found by the mutation pass: name/extension sanitising, host pattern, error handlers."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request

from sankey_studio.errors import ForbiddenError, UnsupportedMediaTypeError
from sankey_studio.web import errors, middleware
from sankey_studio.web.errors import ErrorBody, handle_model_validation, narrow, validation_details
from sankey_studio.web.middleware import CsrfGuard
from sankey_studio.web.security import (
    MSG_HOST_PATTERN,
    BodyLimits,
    Download,
    HeaderPolicy,
    content_disposition,
    host_pattern_problem,
)
from tests.web.ids import stable_id

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
    from starlette.types import Message, Scope


class Disposition(NamedTuple):
    name: str
    ext: str
    fallback: str
    utf8: str


DISPOSITIONS = [
    Disposition("a__b", "svg", "a__b.svg", "a__b.svg"),
    Disposition("a_ b", "svg", "a__b.svg", "a_%20b.svg"),
    Disposition("AZaz09", "svg", "AZaz09.svg", "AZaz09.svg"),
    Disposition("a.b-c_d", "svg", "a.b-c_d.svg", "a.b-c_d.svg"),
    Disposition("report", "SVG", "report.SVG", "report.SVG"),
    Disposition("report", "mp4", "report.mp4", "report.mp4"),
    Disposition("report", "A1z", "report.A1z", "report.A1z"),
    Disposition("report", "t.a r!", "report.tar", "report.tar"),
]


@pytest.mark.parametrize("case", DISPOSITIONS, ids=lambda c: stable_id(f"{c.name}.{c.ext}"))
def test_the_name_and_extension_keep_exactly_the_safe_characters(case: Disposition) -> None:
    expected = f"attachment; filename=\"{case.fallback}\"; filename*=UTF-8''{case.utf8}"
    assert content_disposition(case.name, case.ext) == expected


class HostCase(NamedTuple):
    pattern: str
    usable: bool


HOST_PATTERNS = [
    HostCase("[FE80::1]", usable=True),
    HostCase("[fe80::1]", usable=True),
    HostCase("[::ffff:1.2.3.4]", usable=True),
    HostCase("[::1.2]", usable=True),
    HostCase("[1:2]", usable=True),
    HostCase("[]", usable=False),
    HostCase("[::g]", usable=False),
    HostCase("::1]", usable=False),
    HostCase("[::1", usable=False),
    HostCase("[::1]x", usable=False),
]


@pytest.mark.parametrize("case", HOST_PATTERNS, ids=lambda c: c.pattern)
def test_the_ipv6_pattern_takes_hex_digits_colons_and_dots_in_brackets(case: HostCase) -> None:
    problem = host_pattern_problem(case.pattern)
    assert problem == (None if case.usable else MSG_HOST_PATTERN)


def test_the_host_pattern_message_is_the_one_operators_read() -> None:
    assert MSG_HOST_PATTERN == (
        "must be a bare host name or address: no scheme, port or path, a wildcard only as "
        "'*.example.com', an IPv6 address in brackets"
    )


def test_a_policy_without_api_headers_adds_none_on_the_api_either() -> None:
    policy = HeaderPolicy(everywhere=(("X-A", "1"),))
    assert policy.api_only == ()
    assert policy.api_prefix == "/api/"
    assert policy.for_path("/api/v1/x") == [("X-A", "1")]
    assert policy.for_path("/x") == [("X-A", "1")]


def test_a_validation_error_without_a_location_has_only_its_message() -> None:
    rows: list[dict[str, Any]] = [
        {"msg": "bad"},
        {"loc": ("a", 0, "b"), "msg": "worse"},
        {"loc": (), "msg": "last"},
    ]
    assert validation_details(rows) == ["bad", "a.0.b: worse", "last"]


class Named(BaseModel):
    name: str = Field(min_length=3)


class RecorderError(Exception):
    """Stands in for a pydantic ``ValidationError``: remembers how ``errors`` was asked."""

    def __init__(self) -> None:
        super().__init__("recorded")
        self.asked: dict[str, bool] = {}

    def errors(self, **kwargs: bool) -> list[dict[str, object]]:
        self.asked = kwargs
        return [{"loc": ("name",), "msg": "short", "input": "hunter2", "url": "https://x"}]


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


def test_the_model_error_handler_asks_pydantic_to_leave_input_and_url_out_and_keep_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(errors, "narrow", lambda exc, _kind: exc)
    recorder = RecorderError()
    response = asyncio.run(handle_model_validation(_request("/api/v1/x"), recorder))
    # the context stays: tag_message reads the expected tags from it (and nothing else)
    assert recorder.asked == {"include_input": False, "include_url": False}
    assert response.status_code == 422
    assert json.loads(bytes(response.body)) == {
        "error": {
            "code": "validation_error",
            "message": "The request is not valid",
            "details": ["name: short"],
        }
    }
    assert response.headers["cache-control"] == "no-store"
    assert "hunter2" not in bytes(response.body).decode()


def test_the_model_error_handler_answers_a_real_pydantic_error() -> None:
    with pytest.raises(ValidationError) as caught:
        Named.model_validate({"name": "ab"})
    response = asyncio.run(handle_model_validation(_request("/x"), caught.value))
    body = json.loads(bytes(response.body))
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "The request is not valid"
    assert body["error"]["details"] == ["name: String should have at least 3 characters"]
    assert "cache-control" not in response.headers


async def _no_receive() -> Message:
    return {"type": "http.disconnect"}


async def _no_send(_message: Message) -> None:
    return None


def test_a_fresh_counting_stream_has_neither_answered_nor_started() -> None:
    stream = middleware._CountingStream({"type": "http"}, _no_receive, _no_send, 10)
    assert stream.answered is False
    assert stream._over is False
    assert stream._started is False


def _post(headers: list[tuple[bytes, bytes]]) -> Scope:
    return {"type": "http", "method": "POST", "path": "/api/v1/x", "headers": headers}


def test_a_content_length_that_is_not_plain_zeros_announces_a_body() -> None:
    guard = CsrfGuard(Starlette(), ["testserver"])
    same_site = (b"sec-fetch-site", b"same-origin")
    for length, refused in [(b"X", True), (b"XX", True), (b"0X", True), (b"0", False)]:
        verdict = guard.verdict(_post([same_site, (b"content-length", length)]))
        assert isinstance(verdict, UnsupportedMediaTypeError) is refused, length


def test_an_origin_never_matches_a_request_that_has_no_host_header() -> None:
    guard = CsrfGuard(Starlette(), ["none"])
    json_type = (b"content-type", b"application/json")
    verdict = guard.verdict(_post([(b"origin", b"http://none"), json_type]))
    assert isinstance(verdict, ForbiddenError)
    with_host = _post([(b"origin", b"http://none"), (b"host", b"none"), json_type])
    assert guard.verdict(with_host) is None


def test_narrow_returns_the_same_exception_for_its_kind_and_refuses_any_other() -> None:
    error = ForbiddenError("no")
    assert narrow(error, ForbiddenError) is error
    assert narrow(error, Exception) is error
    with pytest.raises(TypeError, match=r"^expected KeyError, got ForbiddenError$"):
        narrow(error, KeyError)


VALUES: list[DataclassInstance] = [
    HeaderPolicy(everywhere=()),
    BodyLimits(),
    Download(b"", "text/plain", "name", "txt"),
    ErrorBody("code", "message"),
]


@pytest.mark.parametrize("value", VALUES, ids=lambda v: type(v).__name__)
def test_the_value_objects_of_the_web_core_are_frozen_and_slotted(value: DataclassInstance) -> None:
    first = dataclasses.fields(value)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, first, None)
    assert not hasattr(value, "__dict__")
