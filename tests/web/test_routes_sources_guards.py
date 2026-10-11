"""Upload and delete behind the guards: read-only remote mode, CSRF, and concurrent uploads."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from sankey_studio.web.deps import MSG_READ_ONLY
from sankey_studio.web.routers.sources import router
from tests.web.conftest import SAME_ORIGIN, new_client
from tests.web.test_routes_sources_support import (
    FILES,
    disk_names,
    error_of,
    listed,
    put_file,
    upload,
)

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp

REFUSED = {"code": "read_only_mode", "message": MSG_READ_ONLY, "details": []}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([router])


@pytest.fixture
def read_only(make_app: AppFactory) -> WebApp:
    return make_app([router], mode="remote_read_only")


# --------------------------------------------------------------------------- read-only mode


def test_an_upload_in_read_only_mode_is_a_403_and_stores_nothing(read_only: WebApp) -> None:
    response = upload(read_only.client, "a.csv", b"x")
    assert response.status_code == 403
    assert error_of(response) == REFUSED
    assert disk_names(read_only) == []


def test_a_delete_in_read_only_mode_is_a_403_and_keeps_the_file(read_only: WebApp) -> None:
    planted = put_file(read_only, "keep.csv", b"keep")
    response = read_only.client.delete(f"{FILES}/keep.csv")
    assert response.status_code == 403
    assert error_of(response) == REFUSED
    assert planted.read_bytes() == b"keep"


def test_reads_stay_available_in_read_only_mode(read_only: WebApp) -> None:
    put_file(read_only, "keep.csv", b"a,b,1\n")
    assert listed(read_only.client) == ["keep.csv"]
    preview = read_only.client.get(f"{FILES}/keep.csv/preview")
    assert preview.status_code == 200
    assert preview.json() == {"name": "keep.csv", "lines": ["a,b,1"]}


def test_writes_are_allowed_in_remote_mode_with_writes(make_app: AppFactory) -> None:
    web = make_app([router], mode="remote_writes")
    assert upload(web.client, "a.csv", b"x").status_code == 201
    assert web.client.delete(f"{FILES}/a.csv").status_code == 204
    assert disk_names(web) == []


# --------------------------------------------------------------------------- CSRF


def test_a_multipart_upload_without_any_same_origin_signal_is_a_403(web: WebApp) -> None:
    response = upload(web.bare, "a.csv", b"x")
    assert response.status_code == 403
    assert error_of(response)["code"] == "forbidden"
    assert disk_names(web) == []


def test_a_multipart_upload_with_only_a_matching_origin_is_allowed(web: WebApp) -> None:
    client = new_client(web.app, {"Origin": "http://testserver"})
    assert upload(client, "a.csv", b"x").status_code == 201
    assert disk_names(web) == ["a.csv"]


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://localhost:9999"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
    ids=["other-port", "null", "cross-site"],
)
def test_a_cross_origin_upload_is_a_403(web: WebApp, headers: dict[str, str]) -> None:
    client = new_client(web.app, headers)
    assert upload(client, "a.csv", b"x").status_code == 403
    assert disk_names(web) == []


def test_a_delete_needs_the_same_origin_signal_too(web: WebApp) -> None:
    planted = put_file(web, "keep.csv")
    assert web.bare.delete(f"{FILES}/keep.csv").status_code == 403
    assert planted.exists()
    assert new_client(web.app, SAME_ORIGIN).delete(f"{FILES}/keep.csv").status_code == 204
    assert not planted.exists()


# --------------------------------------------------------------------------- races


def race(web: WebApp, names: list[str]) -> list[int]:
    """One upload per name at the same instant (a client per thread); the status codes."""
    barrier = threading.Barrier(len(names))
    statuses: list[int] = [0] * len(names)

    def send(index: int) -> None:
        client = new_client(web.app, SAME_ORIGIN)
        content = f"from upload {index}".encode()
        barrier.wait(timeout=30)
        statuses[index] = upload(client, names[index], content).status_code

    threads = [threading.Thread(target=send, args=(i,)) for i in range(len(names))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return statuses


def test_exactly_one_of_several_uploads_of_one_name_wins(web: WebApp) -> None:
    statuses = race(web, ["race.csv"] * 6)
    assert sorted(statuses) == [201, 409, 409, 409, 409, 409]
    winner = statuses.index(201)
    assert (
        web.services.sources_dir() / "race.csv"
    ).read_bytes() == f"from upload {winner}".encode()
    assert disk_names(web) == ["race.csv"]


def test_exactly_one_of_several_uploads_of_one_name_in_other_cases_wins(web: WebApp) -> None:
    statuses = race(web, ["race.csv", "RACE.csv", "Race.CSV", "rAcE.csv"])
    assert sorted(statuses) == [201, 409, 409, 409]
    assert len(disk_names(web)) == 1
