# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``POST /sources/files``: the multipart upload, its form field, names, caps and refusals."""

from __future__ import annotations

import io
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from fastapi import UploadFile

from sankey_studio.errors import SourceError
from sankey_studio.models import AppSettings
from sankey_studio.sources.files import SaveRequest, save_stream
from sankey_studio.web.routers.sources import router, upload_source_file
from sankey_studio.web.schemas import UploadForm
from tests.web.ids import stable_id
from tests.web.test_routes_sources_support import (
    FILES,
    MIB,
    disk_names,
    error_of,
    listed,
    raw_upload,
    upload,
)

if TYPE_CHECKING:
    from typing import IO

    from tests.web.conftest import AppFactory, WebApp


SAVE_STREAM = "sankey_studio.web.routers.sources.save_stream"


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([router])


@pytest.fixture
def small(make_app: AppFactory) -> WebApp:
    """An app whose uploads may be at most 1 MiB (``max_upload_mb`` = 1, the smallest)."""
    return make_app([router], settings=AppSettings(max_upload_mb=1))


def content_of(web: WebApp, name: str = "a.csv") -> bytes:
    return (web.services.sources_dir() / name).read_bytes()


# --------------------------------------------------------------------------- the happy path


def test_an_upload_is_stored_and_described(web: WebApp) -> None:
    response = upload(web.client, "flows.csv", b"a,b,12\n")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"name", "size", "modified"}
    assert (body["name"], body["size"]) == ("flows.csv", 7)
    assert datetime.fromisoformat(body["modified"]).tzinfo is not None
    assert content_of(web, "flows.csv") == b"a,b,12\n"
    assert disk_names(web) == ["flows.csv"]
    assert listed(web.client) == ["flows.csv"]


def test_the_upload_handler_gets_the_stream_and_the_live_settings(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[SaveRequest, IO[bytes], bytes]] = []

    def spy(request: SaveRequest, stream: IO[bytes]) -> Any:
        head = stream.read(3)
        stream.seek(0)
        seen.append((request, stream, head))
        return save_stream(request, stream)

    monkeypatch.setattr(SAVE_STREAM, spy)
    assert upload(web.client, "x.tsv", b"abcdef").status_code == 201
    [(request, stream, head)] = seen
    assert request == SaveRequest(web.config.effective_sources_dir, "x.tsv", 25 * MIB, False)
    assert isinstance(stream, tempfile.SpooledTemporaryFile)
    assert head == b"abc"


def test_the_overwrite_field_reaches_the_request(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    flags: list[bool] = []

    def spy(request: SaveRequest, stream: IO[bytes]) -> Any:
        flags.append(request.overwrite)
        return save_stream(request, stream)

    monkeypatch.setattr(SAVE_STREAM, spy)
    for value in ("true", "false", "1", "0"):
        upload(web.client, "o.csv", b"x", overwrite=value)
    assert flags == [True, False, True, False]


def test_a_missing_filename_is_an_error_not_a_crash(web: WebApp) -> None:
    file = UploadFile(io.BytesIO(b"x"), filename=None)
    with pytest.raises(SourceError, match=r"^filename is empty$"):
        upload_source_file(file, UploadForm(), web.services)
    assert disk_names(web) == []


# --------------------------------------------------------------------------- collisions


def test_a_taken_name_is_a_409_and_the_old_file_stays(web: WebApp) -> None:
    assert upload(web.client, "a.csv", b"old").status_code == 201
    response = upload(web.client, "a.csv", b"new")
    assert response.status_code == 409
    assert error_of(response) == {
        "code": "conflict",
        "message": "a file named 'a.csv' already exists",
        "details": [],
    }
    assert content_of(web) == b"old"
    assert disk_names(web) == ["a.csv"]


def test_names_that_differ_only_in_case_collide(web: WebApp) -> None:
    upload(web.client, "a.csv", b"old")
    response = upload(web.client, "A.CSV", b"new")
    assert response.status_code == 409
    assert error_of(response)["message"] == "a file named 'a.csv' already exists"
    assert disk_names(web) == ["a.csv"]


def test_overwrite_true_replaces_the_file(web: WebApp) -> None:
    upload(web.client, "a.csv", b"old")
    response = upload(web.client, "a.csv", b"newer", overwrite="true")
    assert response.status_code == 201
    assert response.json()["size"] == 5
    assert content_of(web) == b"newer"
    assert disk_names(web) == ["a.csv"]


def test_overwrite_false_is_the_same_as_no_field(web: WebApp) -> None:
    upload(web.client, "a.csv", b"old")
    assert upload(web.client, "a.csv", b"new", overwrite="false").status_code == 409
    assert content_of(web) == b"old"


def test_overwriting_with_another_case_replaces_the_file_under_its_own_name(web: WebApp) -> None:
    upload(web.client, "a.csv", b"old")
    response = upload(web.client, "A.CSV", b"new", overwrite="true")
    assert response.status_code == 201
    assert response.json()["name"] == "a.csv"
    assert disk_names(web) == ["a.csv"]
    assert content_of(web) == b"new"


# --------------------------------------------------------------------------- the form


@pytest.mark.parametrize(
    ("form", "where"),
    [({"overwrite": "maybe"}, "body.overwrite"), ({"overwite": "true"}, "body.overwite")],
    ids=["bad-value", "typo"],
)
def test_a_bad_form_field_is_a_422_and_nothing_is_stored(
    web: WebApp, form: dict[str, str], where: str
) -> None:
    response = upload(web.client, "a.csv", b"x", **form)
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert [d.split(":")[0] for d in error["details"]] == [where]
    assert disk_names(web) == []


def test_a_multipart_body_without_parts_lacks_the_file(web: WebApp) -> None:
    empty = b"--b--\r\n"
    headers = {"Content-Type": "multipart/form-data; boundary=b"}
    response = web.client.post(FILES, content=empty, headers=headers)
    assert response.status_code == 422
    assert error_of(response)["details"] == ["body.file: Field required"]
    assert disk_names(web) == []


def test_a_part_with_another_name_is_refused_and_nothing_is_stored(web: WebApp) -> None:
    response = web.client.post(FILES, files={"other": ("a.csv", b"x")})
    assert response.status_code == 422
    assert [d.split(":")[0] for d in error_of(response)["details"]] == ["body.other"]
    assert disk_names(web) == []


def test_a_json_body_to_the_upload_route_is_a_422_not_a_crash(web: WebApp) -> None:
    response = web.client.post(FILES, json={"file": "a.csv"})
    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


# --------------------------------------------------------------------------- names


class Name(NamedTuple):
    name: str
    status: int
    code: str


NAMES = [
    Name("x.exe", 400, "unsafe_source"),
    Name("noextension", 400, "unsafe_source"),
    Name("..csv", 400, "unsafe_source"),
    Name("a/b.csv", 400, "unsafe_source"),
    Name("../b.csv", 400, "unsafe_source"),
    Name("a\N{RIGHT-TO-LEFT OVERRIDE}b.csv", 422, "source_error"),
    Name("a\tb.csv", 422, "source_error"),
    Name("a" * 252 + ".csv", 422, "source_error"),
]


@pytest.mark.parametrize("case", NAMES, ids=[stable_id(c.name[:12]) for c in NAMES])
def test_an_unsafe_name_is_refused_before_anything_is_written(web: WebApp, case: Name) -> None:
    response = raw_upload(web.client, case.name)
    assert response.status_code == case.status
    assert error_of(response)["code"] == case.code
    assert disk_names(web) == []


@pytest.mark.parametrize("name", ["a" * 251 + ".csv", "R&D <b>.csv", "données ü.tsv", "x.SANKEY"])
def test_odd_but_legal_names_are_stored_as_they_are(web: WebApp, name: str) -> None:
    response = upload(web.client, name, b"x")
    assert response.status_code == 201
    assert response.json()["name"] == name
    assert disk_names(web) == [name]


# --------------------------------------------------------------------------- size caps


@pytest.mark.parametrize(("size", "status"), [(MIB, 201), (MIB + 1, 413)])
def test_the_file_cap_is_max_upload_mb_exactly(small: WebApp, size: int, status: int) -> None:
    response = upload(small.client, "big.csv", b"x" * size)
    assert response.status_code == status
    if status == 201:
        assert response.json()["size"] == size
        assert disk_names(small) == ["big.csv"]
        return
    assert error_of(response)["code"] == "payload_too_large"
    assert disk_names(small) == []


def test_a_body_beyond_the_framing_allowance_is_refused_before_it_is_read(small: WebApp) -> None:
    response = upload(small.client, "huge.csv", b"x" * (2 * MIB + 1024))
    assert response.status_code == 413
    assert error_of(response)["code"] == "payload_too_large"
    assert disk_names(small) == []


def test_the_cap_follows_the_setting_as_stored_now(small: WebApp) -> None:
    body = b"x" * (MIB + MIB // 2)
    assert upload(small.client, "a.csv", body).status_code == 413
    small.services.update_settings(AppSettings(max_upload_mb=2))
    assert upload(small.client, "a.csv", body).status_code == 201
    small.services.update_settings(AppSettings(max_upload_mb=1))
    assert upload(small.client, "b.csv", body).status_code == 413
    assert disk_names(small) == ["a.csv"]
