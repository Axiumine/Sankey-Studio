"""``PUT /settings?migrate=``: switching the graph store, the copy report and failures."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import FolderCreate
from sankey_studio.storage.files.codec import graph_filename
from sankey_studio.storage.migrate import MAX_UNREADABLE_IDS
from sankey_studio.web.routers.settings import router
from tests.storage.support import create_data
from tests.web.test_routes_settings_support import (
    BASE,
    break_ping,
    error_of,
    put_body,
    stored_uri,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from sankey_studio.models import AppSettings
    from tests.web.conftest import AppFactory, WebApp

STORE_DB = "store"
COLLECTION = "sankey_studio_graphs"


@pytest.fixture
def web(make_app: AppFactory, app_settings: AppSettings) -> WebApp:
    return make_app([router], settings=app_settings)


def add_graphs(web: WebApp, count: int) -> list[str]:
    """Save ``count`` graphs in the current (file) store; their ids."""
    repo = web.services.graphs()
    return [repo.create(create_data(f"graph {n}")).id for n in range(count)]


def to_mongo_body(client: TestClient) -> dict[str, Any]:
    return {
        **put_body(client),
        "storage_backend": "mongo",
        "storage_connection": "test",
        "storage_database": STORE_DB,
    }


def to_file_body(client: TestClient) -> dict[str, Any]:
    return {**put_body(client), "storage_backend": "file", "storage_connection": None}


def stored_in_mongo(web: WebApp) -> list[str]:
    return sorted(doc["_id"] for doc in web.mongo[STORE_DB][COLLECTION].find())


# --------------------------------------------------------------------------- switching


def test_a_switch_with_migrate_copies_every_graph_and_reports_it(web: WebApp) -> None:
    ids = add_graphs(web, 3)
    response = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    assert response.status_code == 200
    body = response.json()
    assert body["copy_report"] == {
        "copied": 3,
        "skipped": 0,
        "unreadable": 0,
        "unreadable_ids": [],
        "folders": 0,
        "folders_skipped": 0,
    }
    assert (body["settings"]["storage_backend"], body["settings"]["storage_database"]) == (
        "mongo",
        STORE_DB,
    )
    assert stored_in_mongo(web) == sorted(ids)
    assert web.services.graphs().count() == 3
    assert stored_uri(web) is not None


def test_a_switch_without_migrate_copies_nothing_and_deletes_nothing(web: WebApp) -> None:
    ids = add_graphs(web, 2)
    response = web.client.put(BASE, json=to_mongo_body(web.client))
    assert response.status_code == 200
    assert response.json()["copy_report"] is None
    assert response.json()["settings"]["storage_backend"] == "mongo"
    assert stored_in_mongo(web) == []
    assert web.services.graphs().count() == 0
    back = web.client.put(BASE, json=to_file_body(web.client))
    assert back.status_code == 200
    assert sorted(g.id for g in web.services.graphs().iter_definitions()) == sorted(ids)


def test_graphs_the_destination_already_has_are_skipped_not_overwritten(web: WebApp) -> None:
    add_graphs(web, 2)
    first = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    assert first.json()["copy_report"]["copied"] == 2
    assert web.client.put(BASE, json=to_file_body(web.client)).status_code == 200
    again = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    assert again.status_code == 200
    report = again.json()["copy_report"]
    assert (report["copied"], report["skipped"], report["unreadable"]) == (0, 2, 0)


def test_a_switch_with_migrate_copies_the_folders_and_counts_them(web: WebApp) -> None:
    folders = web.services.folders()
    parent = folders.create_folder(FolderCreate(name="Finance"))
    child = folders.create_folder(FolderCreate(name="Q3", parent_id=parent.id))
    graph = web.services.graphs().create(create_data("in a folder"), folder_id=child.id)
    response = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    report = response.json()["copy_report"]
    assert (report["copied"], report["folders"], report["folders_skipped"]) == (1, 2, 0)
    assert [f.name for f in web.services.folders().list_folders()] == ["Finance", "Q3"]
    assert web.services.graphs().get(graph.id).folder_id == child.id
    again = web.client.put(BASE, json=to_file_body(web.client))
    assert again.status_code == 200
    second = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    assert second.json()["copy_report"]["folders"] == 0
    assert second.json()["copy_report"]["folders_skipped"] == 2


# --------------------------------------------------------------------------- unreadable graphs


def damage(web: WebApp, graph_ids: list[str]) -> None:
    web.services.graphs()  # creates the graphs directory
    for graph_id in graph_ids:
        (web.config.graphs_dir / graph_filename(graph_id)).write_bytes(b"{broken")


def test_unreadable_graphs_are_counted_and_named_in_the_response(web: WebApp) -> None:
    add_graphs(web, 2)
    broken = [f"{n:032x}" for n in (0xB, 0xA)]
    damage(web, broken)
    response = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    assert response.status_code == 200
    assert response.json()["copy_report"] == {
        "copied": 2,
        "skipped": 0,
        "unreadable": 2,
        "unreadable_ids": sorted(broken),
        "folders": 0,
        "folders_skipped": 0,
    }
    assert web.services.settings().storage_backend == "mongo"
    assert all((web.config.graphs_dir / graph_filename(i)).exists() for i in broken)


def test_the_ids_of_unreadable_graphs_are_capped_but_the_count_is_not(web: WebApp) -> None:
    damage(web, [f"{n:032x}" for n in range(MAX_UNREADABLE_IDS + 2)])
    response = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    report = response.json()["copy_report"]
    assert report["unreadable"] == MAX_UNREADABLE_IDS + 2 == 52
    assert len(report["unreadable_ids"]) == MAX_UNREADABLE_IDS == 50
    assert report["unreadable_ids"] == [f"{n:032x}" for n in range(50)]
    assert report["copied"] == 0


# --------------------------------------------------------------------------- failures


def test_an_unreachable_destination_keeps_the_old_store_and_settings(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_graphs(web, 1)
    break_ping(monkeypatch, web)
    response = web.client.put(f"{BASE}?migrate=true", json=to_mongo_body(web.client))
    assert response.status_code == 503
    assert error_of(response) == {
        "code": "storage_error",
        "message": "MongoDB connection 'test' is unreachable",
        "details": [],
    }
    assert "hunter2" not in response.text
    assert web.services.settings().storage_backend == "file"
    assert web.services.graphs().count() == 1


def test_a_mongo_store_without_a_connection_is_refused(web: WebApp) -> None:
    body = {**to_mongo_body(web.client), "storage_connection": "nope"}
    response = web.client.put(BASE, json=body)
    assert response.status_code == 422
    assert error_of(response)["code"] == "settings_error"
    assert web.services.settings().storage_backend == "file"
