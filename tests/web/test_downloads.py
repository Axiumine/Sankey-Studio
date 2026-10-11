"""``content_disposition`` and ``download_response``: the Content-Disposition table and headers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

import pytest
from fastapi import APIRouter

from sankey_studio.web.security import Download, content_disposition, download_response
from tests.web.ids import stable_id

if TYPE_CHECKING:
    from starlette.responses import Response

    from tests.web.conftest import AppFactory


class Name(NamedTuple):
    name: str
    ext: str
    ascii_name: str
    utf8_name: str


def header(ascii_name: str, utf8_name: str) -> str:
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


NAMES = [
    Name("Budget 2026", "svg", "Budget_2026.svg", "Budget%202026.svg"),
    Name("report", "png", "report.png", "report.png"),
    Name("a.b-c_d", "csv", "a.b-c_d.csv", "a.b-c_d.csv"),
    Name("a\r\nSet-Cookie: x=1", "svg", "a_Set-Cookie_x_1.svg", "a%0D%0ASet-Cookie%3A%20x%3D1.svg"),
    Name('a"b', "svg", "a_b.svg", "a%22b.svg"),
    Name("a;b", "svg", "a_b.svg", "a%3Bb.svg"),
    Name("a\\b", "svg", "a_b.svg", "a%5Cb.svg"),
    Name("../etc/passwd", "svg", ".._etc_passwd.svg", "..%2Fetc%2Fpasswd.svg"),
    Name("it's (a) *name*", "svg", "it_s_a_name_.svg", "it%27s%20%28a%29%20%2Aname%2A.svg"),
    Name("graphé", "svg", "graph_.svg", "graph%C3%A9.svg"),
    Name("グラフ", "svg", "_.svg", "%E3%82%B0%E3%83%A9%E3%83%95.svg"),
    Name("\U0001f4c8 up", "html", "_up.html", "%F0%9F%93%88%20up.html"),
    Name("", "svg", "graph.svg", "graph.svg"),
    Name("   ", "svg", "_.svg", "%20%20%20.svg"),
    Name("\ud800", "svg", "_.svg", "%3F.svg"),
    Name("report", "s v;g", "report.svg", "report.svg"),
    Name("report", "../x", "report.x", "report.x"),
]


@pytest.mark.parametrize("case", NAMES, ids=lambda c: stable_id(c.name))
def test_content_disposition_table(case: Name) -> None:
    assert content_disposition(case.name, case.ext) == header(case.ascii_name, case.utf8_name)


@pytest.mark.parametrize("case", NAMES, ids=lambda c: stable_id(c.name))
def test_the_header_is_ascii_one_line_and_has_one_quoted_name(case: Name) -> None:
    value = content_disposition(case.name, case.ext)
    assert value.isascii()
    assert "\r" not in value
    assert "\n" not in value
    assert len(re.findall(r'filename="[^";\\]*"', value)) == 1
    assert value.count('"') == 2
    assert value.count(";") == 2


class Length(NamedTuple):
    chars: int
    kept: int


@pytest.mark.parametrize(
    "case", [Length(1, 1), Length(79, 79), Length(80, 80), Length(81, 80), Length(500, 80)]
)
def test_the_name_is_cut_at_80_characters(case: Length) -> None:
    value = content_disposition("n" * case.chars, "svg")
    assert value == header(f"{'n' * case.kept}.svg", f"{'n' * case.kept}.svg")


def test_the_cut_applies_after_the_fallback_substitution() -> None:
    # 100 spaces collapse to ONE underscore before the cut, so the 80 are not eaten by them
    assert content_disposition(" " * 100 + "x" * 100, "svg").startswith(
        'attachment; filename="_' + "x" * 79 + '.svg"'
    )


def test_download_response_headers_and_body() -> None:
    response = download_response(Download(b"<svg/>", "image/svg+xml", "My graph", "svg"))
    assert response.status_code == 200
    assert response.body == b"<svg/>"
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-disposition"] == header("My_graph.svg", "My%20graph.svg")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["content-length"] == "6"


def test_text_downloads_are_utf8() -> None:
    response = download_response(Download("a,b\né,1\n", "text/csv", "t", "csv"))
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.body == "a,b\né,1\n".encode()


router = APIRouter()


@router.get("/api/v1/probe/download")
def _download() -> Response:
    return download_response(Download("<html></html>", "text/html", 'x"y', "html"))


def test_a_served_download_keeps_its_sandbox_csp_and_gets_the_rest(make_app: AppFactory) -> None:
    response = make_app([router]).client.get("/api/v1/probe/download")
    assert response.headers.get_list("content-security-policy") == ["sandbox"]
    assert response.headers["content-disposition"] == header("x_y.html", "x%22y.html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "same-origin"
