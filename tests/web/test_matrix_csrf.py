# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The CSRF matrix of SPEC section 6 against the FULL app, for every unsafe route of its table.

Every case below runs once per ``(method, path)`` in ``UNSAFE`` (20 routes), so a route added to
``ALL_ROUTERS`` joins the matrix without an edit. 403 ``forbidden`` and 415
``unsupported_media_type`` are answered by the middleware, before routing: the status does not
depend on the route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from tests.web.test_matrix_support import SAFE, UNSAFE, UPLOAD, Endpoint, ids

if TYPE_CHECKING:
    from tests.web.conftest import WebApp

JSON = {"Content-Type": "application/json"}
TEXT = {"Content-Type": "text/plain"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
MULTIPART = {"Content-Type": "multipart/form-data; boundary=x"}
HERE = {"Origin": "http://testserver"}
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
FORBIDDEN = {
    "error": {"code": "forbidden", "message": "Cross-origin request refused", "details": []}
}
UNSUPPORTED = {
    "error": {
        "code": "unsupported_media_type",
        "message": "The request body must be application/json",
        "details": [],
    }
}


class Case(NamedTuple):
    label: str
    headers: dict[str, str]
    body: bytes = b"{}"


#: Refused with 403 on every unsafe route (the upload route included).
FORBIDDEN_CASES = [
    Case("other port of an allowed hostname", {"Origin": "http://localhost:9999", **JSON}),
    Case("Origin null", {"Origin": "null", **JSON}),
    Case("foreign Origin", {"Origin": "http://evil.example", **JSON}),
    Case("other scheme", {"Origin": "https://testserver", **JSON}),
    Case("cross-site fetch metadata", {"Sec-Fetch-Site": "cross-site", **JSON}),
    Case("same-site is not same-origin", {"Sec-Fetch-Site": "same-site", **JSON}),
    Case("cross-site with the right Origin missing", {"Sec-Fetch-Site": "cross-site", **TEXT}),
    Case("no signal, text/plain", TEXT),
    Case("no signal, form", FORM),
    Case("no signal, no content type", {}),
    Case("no signal, multipart", MULTIPART),
    Case("no signal, empty body", {}, b""),
]
#: Same-origin signal but a body that is not JSON: 415 everywhere except multipart on the upload.
UNSUPPORTED_CASES = [
    Case("same-origin, text/plain", {**SAME_ORIGIN, **TEXT}),
    Case("same-origin, form", {**SAME_ORIGIN, **FORM}),
    Case("matching Origin, text/plain", {**HERE, **TEXT}),
    Case("matching Origin, form", {**HERE, **FORM}),
    Case("Sec-Fetch-Site none, text/plain", {"Sec-Fetch-Site": "none", **TEXT}),
]
#: Pass the guard on every unsafe route: whatever the route answers, it is not 403 or 415.
ALLOWED_CASES = [
    Case("JSON with no browser headers", JSON),
    Case("same-origin fetch", {**SAME_ORIGIN, **JSON}),
    Case("Sec-Fetch-Site none", {"Sec-Fetch-Site": "none", **JSON}),
    Case("matching Origin", {**HERE, **JSON}),
    Case("matching Origin and default port", {"Origin": "http://testserver:80", **JSON}),
]
MULTIPART_ROUTES = [UPLOAD]
OTHER_ROUTES = [e for e in UNSAFE if e != UPLOAD]


def send(web: WebApp, endpoint: Endpoint, case: Case) -> tuple[int, object]:
    response = web.bare.request(
        endpoint.method, endpoint.path, headers=case.headers, content=case.body
    )
    return response.status_code, response.json() if response.content else None


@pytest.mark.parametrize("endpoint", UNSAFE, ids=ids(UNSAFE))
@pytest.mark.parametrize("case", FORBIDDEN_CASES, ids=[c.label for c in FORBIDDEN_CASES])
def test_a_request_without_a_same_origin_proof_is_403(
    web: WebApp, endpoint: Endpoint, case: Case
) -> None:
    assert send(web, endpoint, case) == (403, FORBIDDEN)


@pytest.mark.parametrize("endpoint", UNSAFE, ids=ids(UNSAFE))
@pytest.mark.parametrize("case", UNSUPPORTED_CASES, ids=[c.label for c in UNSUPPORTED_CASES])
def test_a_same_origin_body_that_is_not_json_is_415(
    web: WebApp, endpoint: Endpoint, case: Case
) -> None:
    assert send(web, endpoint, case) == (415, UNSUPPORTED)


@pytest.mark.parametrize("endpoint", UNSAFE, ids=ids(UNSAFE))
@pytest.mark.parametrize("case", ALLOWED_CASES, ids=[c.label for c in ALLOWED_CASES])
def test_a_json_request_with_a_proof_reaches_the_route(
    web: WebApp, endpoint: Endpoint, case: Case
) -> None:
    status, body = send(web, endpoint, case)
    assert status not in {403, 415}
    assert body != FORBIDDEN
    assert body != UNSUPPORTED


@pytest.mark.parametrize("endpoint", OTHER_ROUTES, ids=ids(OTHER_ROUTES))
def test_multipart_is_refused_with_415_on_every_route_but_the_upload(
    web: WebApp, endpoint: Endpoint
) -> None:
    for headers in ({**HERE, **MULTIPART}, {**SAME_ORIGIN, **MULTIPART}):
        assert send(web, endpoint, Case("multipart", headers)) == (415, UNSUPPORTED)


@pytest.mark.parametrize("headers", [{**HERE, **MULTIPART}, {**SAME_ORIGIN, **MULTIPART}])
def test_multipart_with_a_same_origin_proof_reaches_the_upload_route(
    web: WebApp, headers: dict[str, str]
) -> None:
    empty_form = b"--x--\r\n"  # well-formed multipart without the file part
    status, body = send(web, UPLOAD, Case("upload", headers, empty_form))
    assert status == 422  # the route itself: the file part is missing
    assert isinstance(body, dict)
    assert body["error"]["code"] == "validation_error"


def test_the_upload_route_still_refuses_other_content_types(web: WebApp) -> None:
    for headers in ({**HERE, **TEXT}, {**HERE, **FORM}, {**SAME_ORIGIN, **TEXT}):
        assert send(web, UPLOAD, Case("upload", headers)) == (415, UNSUPPORTED)


@pytest.mark.parametrize("endpoint", SAFE, ids=ids(SAFE))
def test_a_cross_site_read_is_refused_under_api_only(web: WebApp, endpoint: Endpoint) -> None:
    response = web.bare.get(endpoint.path, headers={"Sec-Fetch-Site": "cross-site"})
    if endpoint.template.startswith("/api/"):
        assert (response.status_code, response.json()) == (403, FORBIDDEN)
    else:
        assert response.status_code != 403


@pytest.mark.parametrize("endpoint", SAFE, ids=ids(SAFE))
def test_reads_do_not_need_a_proof(web: WebApp, endpoint: Endpoint) -> None:
    for headers in ({}, {"Origin": "null"}, {"Origin": "http://evil.example"}):
        assert web.bare.get(endpoint.path, headers=headers).status_code != 403


def test_there_are_twenty_unsafe_routes_and_one_upload() -> None:
    assert len(UNSAFE) == 20
    assert [e.label for e in UNSAFE if "multipart" in e.template] == []
    assert UPLOAD in UNSAFE
    assert len(OTHER_ROUTES) == 19
