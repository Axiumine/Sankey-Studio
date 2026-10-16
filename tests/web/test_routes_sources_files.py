# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``DELETE /sources/files/{name}`` and ``GET /sources/files/{name}/preview``."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, NamedTuple

import pytest

from sankey_studio.web.routers.sources import router
from tests.web.test_routes_sources_support import (
    FILES,
    disk_names,
    error_of,
    listed,
    put_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.web.conftest import AppFactory, WebApp


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([router])


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    """A file outside the sources directory that no route may ever reveal or remove."""
    path = tmp_path / "secret.csv"
    path.write_bytes(b"top,secret,1\n")
    return path


class Probe(NamedTuple):
    """A request path (already percent-encoded) and the refusal it must get."""

    path: str
    status: int
    code: str


ESCAPES = [
    Probe("..%2Fsecret.csv", 400, "unsafe_source"),
    Probe("%2e%2e/%2e%2e/secret.csv", 400, "unsafe_source"),
    Probe("sub/..%2F..%2Fsecret.csv", 400, "unsafe_source"),
    Probe("a%5Cb.csv", 400, "unsafe_source"),
    Probe("a%00b.csv", 400, "unsafe_source"),
    Probe("%2Fetc%2Fpasswd.csv", 400, "unsafe_source"),
    Probe("notes.exe", 400, "unsafe_source"),
    Probe("sub//x.csv", 400, "unsafe_source"),
    Probe("missing.csv", 404, "source_not_found"),
    Probe("sub/missing.csv", 404, "source_not_found"),
]
IDS = [p.path for p in ESCAPES]


# --------------------------------------------------------------------------- delete


def test_a_file_is_deleted_with_a_204_and_an_empty_body(web: WebApp) -> None:
    put_file(web, "a.csv")
    put_file(web, "b.csv")
    response = web.client.delete(f"{FILES}/a.csv")
    assert response.status_code == 204
    assert response.content == b""
    assert listed(web.client) == ["b.csv"]


def test_a_file_in_a_subdirectory_is_deleted_by_its_relative_name(web: WebApp) -> None:
    put_file(web, "sub/deep/n.csv")
    assert listed(web.client) == ["sub/deep/n.csv"]
    assert web.client.delete(f"{FILES}/sub/deep/n.csv").status_code == 204
    assert listed(web.client) == []
    assert disk_names(web) == ["sub"]


def test_deleting_twice_is_a_404(web: WebApp) -> None:
    put_file(web, "a.csv")
    assert web.client.delete(f"{FILES}/a.csv").status_code == 204
    again = web.client.delete(f"{FILES}/a.csv")
    assert again.status_code == 404
    assert error_of(again)["code"] == "source_not_found"


@pytest.mark.parametrize("case", ESCAPES, ids=IDS)
def test_delete_refuses_escapes_and_unknown_names(web: WebApp, secret: Path, case: Probe) -> None:
    response = web.client.delete(f"{FILES}/{case.path}")
    assert response.status_code == case.status
    assert error_of(response)["code"] == case.code
    assert secret.read_bytes() == b"top,secret,1\n"


def test_delete_never_follows_a_symlink(web: WebApp, secret: Path) -> None:
    link = web.services.sources_dir() / "link.csv"
    link.symlink_to(secret)
    response = web.client.delete(f"{FILES}/link.csv")
    assert response.status_code == 400
    assert error_of(response)["code"] == "unsafe_source"
    assert link.is_symlink()
    assert secret.exists()


def test_delete_never_enters_a_symlinked_directory(web: WebApp, secret: Path) -> None:
    (web.services.sources_dir() / "sub").symlink_to(secret.parent, target_is_directory=True)
    response = web.client.delete(f"{FILES}/sub/secret.csv")
    assert response.status_code == 400
    assert secret.exists()


def test_delete_wants_the_delete_method_and_a_name(web: WebApp) -> None:
    put_file(web, "a.csv")
    assert web.client.get(f"{FILES}/a.csv").status_code == 405
    assert web.client.post(f"{FILES}/a.csv").status_code == 405
    assert disk_names(web) == ["a.csv"]


# --------------------------------------------------------------------------- preview


def test_a_preview_returns_the_first_lines(web: WebApp) -> None:
    put_file(web, "a.csv", b"source,target,value\r\nA,B,1\nC,D,2")
    response = web.client.get(f"{FILES}/a.csv/preview")
    assert response.status_code == 200
    assert response.json() == {
        "name": "a.csv",
        "lines": ["source,target,value", "A,B,1", "C,D,2"],
    }
    assert response.headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(("count", "shown"), [(49, 49), (50, 50), (51, 50), (500, 50)])
def test_a_preview_stops_at_fifty_lines(web: WebApp, count: int, shown: int) -> None:
    put_file(web, "long.csv", "".join(f"A,B,{n}\n" for n in range(count)).encode())
    lines = web.client.get(f"{FILES}/long.csv/preview").json()["lines"]
    assert len(lines) == shown
    assert lines[-1] == f"A,B,{shown - 1}"


@pytest.mark.parametrize(("length", "shown"), [(499, 499), (500, 500), (501, 500), (5000, 500)])
def test_a_preview_cuts_a_line_at_500_characters(web: WebApp, length: int, shown: int) -> None:
    put_file(web, "wide.csv", b"x" * length + b"\nnext\n")
    lines = web.client.get(f"{FILES}/wide.csv/preview").json()["lines"]
    assert [len(line) for line in lines[:1]] == [shown]
    assert lines[1:] == ["next"]


def test_a_preview_is_lenient_about_bytes_that_are_not_utf8(web: WebApp) -> None:
    put_file(web, "latin.csv", b"caf\xe9,b,1\n")
    response = web.client.get(f"{FILES}/latin.csv/preview")
    assert response.status_code == 200
    assert response.json()["lines"] == ["caf�,b,1"]


def test_markup_in_a_file_comes_back_as_plain_json_text(web: WebApp) -> None:
    put_file(web, "xss.csv", b"<script>alert(1)</script>,<b>,1\n")
    response = web.client.get(f"{FILES}/xss.csv/preview")
    assert response.json()["lines"] == ["<script>alert(1)</script>,<b>,1"]
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_a_file_in_a_subdirectory_and_one_named_like_the_route_can_be_previewed(
    web: WebApp,
) -> None:
    put_file(web, "sub/n.csv", b"1,2,3\n")
    put_file(web, "preview.csv", b"p,q,4\n")
    nested = web.client.get(f"{FILES}/sub/n.csv/preview")
    assert nested.json() == {"name": "sub/n.csv", "lines": ["1,2,3"]}
    named = web.client.get(f"{FILES}/preview.csv/preview")
    assert named.json() == {"name": "preview.csv", "lines": ["p,q,4"]}


def test_the_case_of_a_name_is_kept(web: WebApp) -> None:
    put_file(web, "Mixed.CSV", b"m,x,1\n")
    put_file(web, "Sub/Case.tsv", b"c,s,2\n")
    assert web.client.get(f"{FILES}/Mixed.CSV/preview").json()["lines"] == ["m,x,1"]
    assert web.client.get(f"{FILES}/Sub/Case.tsv/preview").json()["name"] == "Sub/Case.tsv"


def test_non_ascii_names_travel_percent_encoded(web: WebApp) -> None:
    put_file(web, "données ü.csv", b"a,b,1\n")
    response = web.client.get(f"{FILES}/donn%C3%A9es%20%C3%BC.csv/preview")
    assert response.status_code == 200
    assert response.json() == {"name": "données ü.csv", "lines": ["a,b,1"]}


@pytest.mark.parametrize("case", ESCAPES, ids=IDS)
def test_preview_refuses_escapes_and_unknown_names(web: WebApp, secret: Path, case: Probe) -> None:
    response = web.client.get(f"{FILES}/{case.path}/preview")
    assert response.status_code == case.status
    assert error_of(response)["code"] == case.code
    assert "top,secret" not in response.text
    assert secret.read_bytes() == b"top,secret,1\n"


def test_preview_never_follows_a_symlink(web: WebApp, secret: Path) -> None:
    (web.services.sources_dir() / "link.csv").symlink_to(secret)
    response = web.client.get(f"{FILES}/link.csv/preview")
    assert response.status_code == 400
    assert error_of(response)["code"] == "unsafe_source"
    assert "top" not in response.text


def test_preview_does_not_hang_on_a_fifo_and_refuses_it(web: WebApp) -> None:
    os.mkfifo(web.services.sources_dir() / "pipe.csv")
    response = web.client.get(f"{FILES}/pipe.csv/preview")
    assert response.status_code == 400
    assert error_of(response)["code"] == "unsafe_source"
    assert listed(web.client) == []


def test_preview_is_a_get_only_route(web: WebApp) -> None:
    put_file(web, "a.csv")
    assert web.client.post(f"{FILES}/a.csv/preview").status_code == 405
