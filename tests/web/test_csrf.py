"""The CSRF matrix of SPEC section 6: which unsafe requests pass, 403 or 415, and the GET rule."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi import APIRouter

from sankey_studio.web.security import UPLOAD_PATH

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

PATH = "/api/v1/probe"
JSON = {"Content-Type": "application/json"}
TEXT = {"Content-Type": "text/plain"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
MULTIPART = {"Content-Type": "multipart/form-data; boundary=x"}
HERE = {"Origin": "http://testserver"}
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

router = APIRouter()


@router.api_route(PATH, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route(UPLOAD_PATH, methods=["POST"])
@router.api_route("/page", methods=["GET", "POST"])
def _probe() -> dict[str, bool]:
    return {"ok": True}


class Case(NamedTuple):
    label: str
    method: str
    path: str
    headers: dict[str, str]
    body: bytes | None
    status: int


def post(label: str, headers: dict[str, str], status: int, path: str = PATH) -> Case:
    return Case(label, "POST", path, headers, b"{}", status)


MATRIX = [
    # the required matrix of SPEC section 6
    post("other port, allowed hostname", {"Origin": "http://localhost:9999", **JSON}, 403),
    post("Origin null", {"Origin": "null", **JSON}, 403),
    post("cross-site fetch metadata", {"Sec-Fetch-Site": "cross-site", **JSON}, 403),
    post("no signal, text/plain", TEXT, 403),
    Case("no signal, no content type", "POST", PATH, {}, None, 403),
    post("no signal, multipart upload", MULTIPART, 403, UPLOAD_PATH),
    post("matching Origin, multipart upload", {**HERE, **MULTIPART}, 200, UPLOAD_PATH),
    post("no signal, JSON", JSON, 200),
    # Sec-Fetch-Site
    post("same-origin", {"Sec-Fetch-Site": "same-origin", **JSON}, 200),
    post("same-origin, odd case", {"Sec-Fetch-Site": "Same-Origin", **JSON}, 200),
    post("none (user initiated)", {"Sec-Fetch-Site": "none", **JSON}, 200),
    post("same-site is not same-origin", {"Sec-Fetch-Site": "same-site", **JSON}, 403),
    post(
        "same-site, foreign Origin",
        {"Sec-Fetch-Site": "same-site", "Origin": "http://x.example", **JSON},
        403,
    ),
    post("same-origin but text/plain", {"Sec-Fetch-Site": "same-origin", **TEXT}, 415),
    post("empty Sec-Fetch-Site is not a signal", {"Sec-Fetch-Site": "", **JSON}, 403),
    # Origin: scheme, host and port must all equal the request's own
    post("matching Origin", {**HERE, **JSON}, 200),
    post("Origin with the default port", {"Origin": "http://testserver:80", **JSON}, 200),
    post("Origin host in upper case", {"Origin": "http://TESTSERVER", **JSON}, 200),
    post("other scheme", {"Origin": "https://testserver", **JSON}, 403),
    post("other port", {"Origin": "http://testserver:8000", **JSON}, 403),
    post("other host", {"Origin": "http://evil.example", **JSON}, 403),
    post("subdomain", {"Origin": "http://a.testserver", **JSON}, 403),
    post("empty Origin", {"Origin": "", **JSON}, 403),
    post("Origin with a path", {"Origin": "http://testserver/", **JSON}, 403),
    post("Origin with user info", {"Origin": "http://u@testserver", **JSON}, 403),
    post("Origin with empty user info", {"Origin": "http://@testserver", **JSON}, 403),
    post("Origin with a query", {"Origin": "http://testserver?x", **JSON}, 403),
    post("Origin with a fragment", {"Origin": "http://testserver#x", **JSON}, 403),
    post("Origin other scheme", {"Origin": "ftp://testserver", **JSON}, 403),
    post("Origin bad port", {"Origin": "http://testserver:abc", **JSON}, 403),
    post("Origin port out of range", {"Origin": "http://testserver:99999", **JSON}, 403),
    post("Origin bad address", {"Origin": "http://[::1", **JSON}, 403),
    # content type, once the origin is accepted
    post("same origin, text/plain", {**HERE, **TEXT}, 415),
    post("same origin, form", {**HERE, **FORM}, 415),
    post("same origin, multipart off the upload route", {**HERE, **MULTIPART}, 415),
    post("same origin, form on the upload route", {**HERE, **FORM}, 415),
    post("same origin, JSON on the upload route", {**HERE, **JSON}, 200, UPLOAD_PATH),
    post("same origin, no content type, a body", dict(HERE), 415),
    post("JSON with a charset", {**HERE, "Content-Type": "application/json; charset=utf-8"}, 200),
    post("JSON in upper case", {**HERE, "Content-Type": "Application/JSON"}, 200),
    post("a JSON look-alike", {**HERE, "Content-Type": "application/jsonx"}, 415),
    post("a +json type", {**HERE, "Content-Type": "application/vnd.x+json"}, 415),
    post("foreign Origin wins over a bad type", {"Origin": "http://evil.example", **TEXT}, 403),
    # unsafe methods without a body
    Case("POST without a body", "POST", PATH, dict(HERE), None, 200),
    Case("DELETE without a body", "DELETE", PATH, dict(HERE), None, 200),
    Case("DELETE without a body, no signal", "DELETE", PATH, {}, None, 403),
    Case("POST without a body, a text type", "POST", PATH, {**HERE, **TEXT}, None, 415),
    Case("POST without a body, a JSON type", "POST", PATH, {**HERE, **JSON}, None, 200),
    Case("PUT cross-site", "PUT", PATH, {"Sec-Fetch-Site": "cross-site", **JSON}, b"{}", 403),
    Case("PATCH cross-site", "PATCH", PATH, {"Sec-Fetch-Site": "cross-site", **JSON}, b"{}", 403),
    Case("PUT without any signal", "PUT", PATH, TEXT, b"{}", 403),
    Case("PATCH without any signal", "PATCH", PATH, TEXT, b"{}", 403),
    Case("DELETE cross-site", "DELETE", PATH, {"Sec-Fetch-Site": "cross-site"}, None, 403),
    Case("PUT same origin", "PUT", PATH, {**HERE, **JSON}, b"{}", 200),
    Case("PATCH same origin", "PATCH", PATH, {**HERE, **JSON}, b"{}", 200),
    Case(
        "every path is guarded",
        "POST",
        "/page",
        {"Origin": "http://evil.example", **JSON},
        b"{}",
        403,
    ),
    Case("an unknown path is guarded first", "POST", "/nope", TEXT, b"{}", 403),
]


@pytest.fixture
def probe(make_app: AppFactory) -> WebApp:
    return make_app([router])


@pytest.mark.parametrize("case", MATRIX, ids=lambda c: c.label)
def test_the_csrf_matrix(probe: WebApp, case: Case) -> None:
    response = probe.bare.request(case.method, case.path, headers=case.headers, content=case.body)
    assert response.status_code == case.status
    if case.status == 200:
        assert response.json() == {"ok": True}
    else:
        assert response.json() == (FORBIDDEN if case.status == 403 else UNSUPPORTED)


def test_a_refusal_carries_the_security_headers(probe: WebApp) -> None:
    response = probe.bare.post(PATH, headers={"Origin": "null", **JSON}, content=b"{}")
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_the_own_origin_follows_the_host_header(probe: WebApp) -> None:
    headers = {"Host": "localhost:5173", "Origin": "http://localhost:5173", **JSON}
    wrong_port = {"Host": "localhost:8765", "Origin": "http://localhost:5173", **JSON}
    ipv6 = {"Host": "[::1]:8765", "Origin": "http://[::1]:8765", **JSON}
    wrong_ipv6 = {"Host": "[::1]:8765", "Origin": "http://[::1]:5173", **JSON}
    assert probe.bare.post(PATH, headers=headers, content=b"{}").status_code == 200
    assert probe.bare.post(PATH, headers=wrong_port, content=b"{}").status_code == 403
    assert probe.bare.post(PATH, headers=ipv6, content=b"{}").status_code == 200
    assert probe.bare.post(PATH, headers=wrong_ipv6, content=b"{}").status_code == 403


def test_a_chunked_body_counts_as_a_body(probe: WebApp) -> None:
    untyped = probe.bare.post(PATH, headers=HERE, content=iter([b"{}"]))
    typed = probe.bare.post(PATH, headers={**HERE, **JSON}, content=iter([b"{}"]))
    assert "content-length" not in untyped.request.headers
    assert untyped.status_code == 415
    assert typed.status_code == 200


class Get(NamedTuple):
    label: str
    method: str
    path: str
    headers: dict[str, str]
    status: int


GETS = [
    Get("api, cross-site", "GET", PATH, {"Sec-Fetch-Site": "cross-site"}, 403),
    Get("api, cross-site in odd case", "GET", PATH, {"Sec-Fetch-Site": "Cross-Site"}, 403),
    Get("api, cross-site HEAD", "HEAD", PATH, {"Sec-Fetch-Site": "cross-site"}, 403),
    Get("api, same-site", "GET", PATH, {"Sec-Fetch-Site": "same-site"}, 200),
    Get("api, same-origin", "GET", PATH, {"Sec-Fetch-Site": "same-origin"}, 200),
    Get("api, none", "GET", PATH, {"Sec-Fetch-Site": "none"}, 200),
    Get("api, no signal (curl)", "GET", PATH, {}, 200),
    Get("api, foreign Origin only", "GET", PATH, {"Origin": "http://evil.example"}, 200),
    Get(
        "a page may be opened from anywhere", "GET", "/page", {"Sec-Fetch-Site": "cross-site"}, 200
    ),
    Get("/apix is not /api/", "GET", "/apix/y", {"Sec-Fetch-Site": "cross-site"}, 404),
]


@pytest.mark.parametrize("case", GETS, ids=lambda c: c.label)
def test_a_cross_site_get_of_the_api_is_refused(probe: WebApp, case: Get) -> None:
    response = probe.bare.request(case.method, case.path, headers=case.headers)
    assert response.status_code == case.status
    if case.status == 403 and case.method != "HEAD":
        assert response.json() == FORBIDDEN
