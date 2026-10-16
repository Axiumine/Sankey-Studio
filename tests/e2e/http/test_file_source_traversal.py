# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.2 (file source, security): no name, link or special file reaches outside the sources dir.

One server for the module. Its sources directory holds a regular file, a symlink to a secret file
outside, a symlink to a directory outside, a dangling link and a FIFO; the secret text must never
appear in any answer and the files outside must still be there afterwards.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from tests.e2e.support.builders import BUDGET
from tests.e2e.support.clients import json_of, upload_source
from tests.e2e.support.http_a_raw import MULTIPART_TYPE, multipart_file, raw_request

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from tests.e2e.support.server import LiveServer

SECRET = f"TOPSECRET-{uuid.uuid4().hex}"
FILES = "/api/v1/sources/files"
LINKS = ["leak.csv", "linkdir/x.csv", "dangling.csv"]
SPECIAL = [*LINKS, "pipe.csv"]


@dataclass(frozen=True, slots=True)
class Planted:
    """The module's server and the secret files that live outside its sources directory."""

    server: LiveServer
    private: Path
    outside: Path

    def assert_intact(self) -> None:
        assert self.private.read_text() == f"{SECRET},B,1\n"
        assert self.outside.read_text() == f"{SECRET},B,1\n"


@pytest.fixture(scope="module")
def planted(module_server: LiveServer) -> Planted:
    sources = module_server.sources_dir
    home = sources.parent
    sources.mkdir(parents=True, exist_ok=True)  # the server creates it on first use
    (home / "outside").mkdir()
    private, outside = home / "private.csv", home / "outside" / "x.csv"
    for secret_file in (private, outside):
        secret_file.write_text(f"{SECRET},B,1\n")
    (sources / "ok.csv").write_text(BUDGET.csv)
    (sources / "leak.csv").symlink_to(private)
    (sources / "linkdir").symlink_to(home / "outside", target_is_directory=True)
    (sources / "dangling.csv").symlink_to(home / "nothing-here.csv")
    os.mkfifo(sources / "pipe.csv")
    return Planted(module_server, private, outside)


@pytest.fixture
def live_server(planted: Planted) -> LiveServer:
    return planted.server


def file_source(path: str) -> dict[str, Any]:
    return {"type": "text", "origin": "file", "path": path, "format": "csv"}


def test_the_listing_shows_regular_files_only(planted: Planted, api: httpx.Client) -> None:
    assert [item["name"] for item in json_of(api.get(FILES))] == ["ok.csv"]
    planted.assert_intact()


TRAVERSAL = [
    "../private.csv",
    "..%2fprivate.csv",
    "%2e%2e/private.csv",
    "%2e%2e%2fprivate.csv",
    "sub/../../private.csv",
    "ok.csv/../../private.csv",
    "..%5cprivate.csv",
    "%2fetc%2fpasswd",
    "/etc/passwd",
    "./ok.csv",
    "ok.csv/.",
    "sub//ok.csv",
    "ok%00.csv",
    "ok.csv%00.png",
]


@pytest.mark.parametrize("name", TRAVERSAL)
@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_a_traversal_name_is_refused_by_preview_and_delete(
    planted: Planted, method: str, name: str
) -> None:
    suffix = "/preview" if method == "GET" else ""
    answer = raw_request(planted.server, method, f"{FILES}/{name}{suffix}")
    assert answer.status == 400, answer.text
    assert answer.error_code == "unsafe_source"
    assert SECRET not in answer.text
    planted.assert_intact()
    assert (planted.server.sources_dir / "ok.csv").is_file()


@pytest.mark.parametrize("name", SPECIAL)
def test_links_and_special_files_are_refused_everywhere(
    planted: Planted, api: httpx.Client, name: str
) -> None:
    saved = api.post("/api/v1/graphs", json={"name": f"via {name}", "source": file_source(name)})
    graph_id = json_of(saved, 201)["id"]  # saving never touches the disk ...
    reads = [
        api.get(f"{FILES}/{name}/preview"),
        api.post("/api/v1/preview", json={"source": file_source(name)}),
        api.post("/api/v1/entries", json={"source": file_source(name)}),
        api.get(f"/api/v1/graphs/{graph_id}/render"),  # ... drawing it does
        api.get(f"/api/v1/graphs/{graph_id}/export", params={"format": "csv"}),
    ]
    for answer in reads:
        assert answer.status_code == 400, (answer.request.url, answer.text)
        assert answer.json()["error"]["code"] == "unsafe_source"
        assert SECRET not in answer.text
    assert api.delete(f"{FILES}/{name}").status_code == 400
    planted.assert_intact()
    assert os.path.lexists(
        planted.server.sources_dir / name.split("/", maxsplit=1)[0]
    )  # still planted


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../private.csv",
        "a/../b.csv",
        "a\\b.csv",
        "a\u0000.csv",
        "a//b.csv",
        "x" * 300,
    ],
    ids=["absolute", "dotdot", "inner-dotdot", "backslash", "nul", "empty-segment", "too-long"],
)
def test_a_graph_cannot_even_be_drawn_from_an_escaping_path(
    planted: Planted, api: httpx.Client, path: str
) -> None:
    for route in ("/api/v1/preview", "/api/v1/graphs"):
        body = {"source": file_source(path), "name": "escape"}
        refused = api.post(route, json=body)
        error = json_of(refused, 422)["error"]
        assert error["code"] == "validation_error"
        assert path not in refused.text or len(path) < 4  # the value is never echoed back
    assert [g for g in json_of(api.get("/api/v1/graphs"))["items"] if g["name"] == "escape"] == []
    planted.assert_intact()


def test_a_missing_file_is_a_404_that_does_not_reveal_the_host_path(
    planted: Planted, api: httpx.Client
) -> None:
    answer = api.post("/api/v1/preview", json={"source": file_source("nope.csv")})
    assert json_of(answer, 404)["error"]["code"] == "source_not_found"
    assert str(planted.server.sources_dir) not in answer.text


def test_a_saved_graph_never_follows_a_file_that_was_swapped_for_a_link(
    planted: Planted, api: httpx.Client
) -> None:
    name = f"swap-{uuid.uuid4().hex[:8]}.csv"
    upload_source(api, name, BUDGET.csv)
    graph = json_of(
        api.post("/api/v1/graphs", json={"name": "swap", "source": file_source(name)}), 201
    )
    render = f"/api/v1/graphs/{graph['id']}/render"
    assert json_of(api.get(render))["stats"]["links"] == BUDGET.links
    stored = planted.server.sources_dir / name
    stored.unlink()
    stored.symlink_to(planted.private)  # the next read would show the secret
    swapped = api.get(render)
    assert json_of(swapped, 400)["error"]["code"] == "unsafe_source"
    assert SECRET not in swapped.text
    assert SECRET not in api.get(f"{FILES}/{name}/preview").text
    stored.unlink()
    planted.assert_intact()


@dataclass(frozen=True, slots=True)
class OddName:
    """An upload file name (raw bytes) and the refusal it must get."""

    filename: bytes
    status: int
    code: str


ODD_NAMES = [
    pytest.param(OddName(b"x\x00.csv", 422, "source_error"), id="nul"),
    pytest.param(OddName(b"a\nb.csv", 422, "source_error"), id="newline"),
    pytest.param(OddName(b"..", 422, "source_error"), id="dotdot"),
    pytest.param(OddName(b".", 422, "source_error"), id="dot"),
    pytest.param(OddName(b"", 422, "source_error"), id="empty"),
    pytest.param(OddName(b"../up.csv", 400, "unsafe_source"), id="parent"),
    pytest.param(OddName(b"..\\up.csv", 400, "unsafe_source"), id="backslash"),
    pytest.param(OddName(b"/abs.csv", 400, "unsafe_source"), id="absolute"),
    pytest.param(OddName(b"%2e%2e/up.csv", 400, "unsafe_source"), id="encoded-parent"),
    pytest.param(OddName(b".csv", 400, "unsafe_source"), id="extension-only"),
]


@pytest.mark.parametrize("odd", ODD_NAMES)
def test_odd_upload_names_are_refused_and_store_nothing(
    planted: Planted, api: httpx.Client, odd: OddName
) -> None:
    answer = api.post(
        FILES, content=multipart_file(odd.filename), headers={"Content-Type": MULTIPART_TYPE}
    )
    assert (answer.status_code, answer.json()["error"]["code"]) == (odd.status, odd.code)
    assert [item["name"] for item in json_of(api.get(FILES))] == ["ok.csv"]
    stored = sorted(path.name for path in planted.server.sources_dir.iterdir())
    assert stored == ["dangling.csv", "leak.csv", "linkdir", "ok.csv", "pipe.csv"]
    assert not (planted.server.sources_dir.parent / "up.csv").exists()
