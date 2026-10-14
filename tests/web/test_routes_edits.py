"""POST /api/v1/edits/plan and /edits/write over the HTTP surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.errors import StorageError
from sankey_studio.models import AppSettings
from sankey_studio.web.routers import edits
from tests.conftest import build_connection
from tests.test_edits_support import (
    ADD,
    CATEGORISE,
    CSV,
    file_source,
    inline,
    mongo_source,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

    from sankey_studio.models import SourceSpec
    from tests.web.conftest import AppFactory, WebApp

API: Final = "/api/v1/edits"
OUTCOME_KEYS: Final = {
    "where",
    "written",
    "consent",
    "reason",
    "notice",
    "target",
    "target_key",
    "changed",
    "source",
    "override",
    "pins",
}


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    settings = AppSettings(mongo_connections=[build_connection()])
    return make_app([edits.router, edits.writes_router], settings=settings)


def body(source: SourceSpec, edit: dict[str, Any]) -> dict[str, Any]:
    return {"draft": {"source": source.model_dump(mode="json")}, "edit": edit}


def error_of(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/json")
    return dict(response.json()["error"])


@pytest.fixture
def put_file(web: WebApp) -> Callable[[str, str], None]:
    def put(name: str, text: str) -> None:
        directory = web.config.effective_sources_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(text, encoding="utf-8")

    return put


def agreed(client: TestClient) -> SourceSpec:
    """``flows.csv`` with the preference the consent dialog stores (key from ``plan``)."""
    plan = client.post(f"{API}/plan", json=body(file_source(), ADD)).json()
    pref = {"mode": "source", "target": plan["target_key"]}
    return file_source(write_back=pref)


def test_plan_answers_the_outcome_for_pasted_text(client: TestClient) -> None:
    response = client.post(f"{API}/plan", json=body(inline(), ADD))
    assert response.status_code == 200
    outcome = response.json()
    assert set(outcome) == OUTCOME_KEYS
    assert (outcome["where"], outcome["changed"], outcome["written"]) == ("draft", 1, False)
    assert outcome["source"]["content"].endswith("Budget,Gifts,50,Fun\n")


def test_plan_asks_for_a_file_and_writes_nothing(
    web: WebApp, client: TestClient, put_file: Callable[[str, str], None]
) -> None:
    put_file("flows.csv", CSV)
    outcome = client.post(f"{API}/plan", json=body(file_source(), ADD)).json()
    assert (outcome["where"], outcome["consent"]) == ("file", "ask")
    assert (outcome["target"], outcome["target_key"]) == ("flows.csv", "file:flows.csv")
    assert (web.config.effective_sources_dir / "flows.csv").read_text() == CSV


def test_write_changes_the_file_after_the_consent(
    web: WebApp, client: TestClient, put_file: Callable[[str, str], None]
) -> None:
    put_file("flows.csv", CSV)
    plan = client.post(f"{API}/plan", json=body(file_source(), CATEGORISE)).json()
    pref = {"mode": "source", "target": plan["target_key"]}
    source = {**file_source().model_dump(mode="json"), "write_back": pref}
    response = client.post(f"{API}/write", json={"draft": {"source": source}, "edit": CATEGORISE})
    assert response.status_code == 200
    outcome = response.json()
    assert (outcome["written"], outcome["changed"], outcome["override"]) == (True, 1, "drop")
    assert "Budget,Food,640,Fun" in (web.config.effective_sources_dir / "flows.csv").read_text()


def test_write_without_consent_is_a_422_source_edit_refused(
    client: TestClient, put_file: Callable[[str, str], None]
) -> None:
    put_file("flows.csv", CSV)
    response = client.post(f"{API}/write", json=body(file_source(), ADD))
    assert response.status_code == 422
    assert error_of(response)["code"] == "source_edit_refused"


def test_a_graph_error_is_a_422_with_its_code(client: TestClient) -> None:
    cycle = {"op": "add_entry", "source": "Rent", "target": "Salary", "value": 5}
    response = client.post(f"{API}/plan", json=body(inline(), cycle))
    assert response.status_code == 422
    assert error_of(response)["code"] == "graph_build_error"


def test_a_missing_file_is_a_404(client: TestClient) -> None:
    response = client.post(f"{API}/plan", json=body(file_source("missing.csv"), ADD))
    assert response.status_code == 404
    assert error_of(response)["code"] == "source_not_found"


@pytest.mark.parametrize(
    "edit",
    [
        {"op": "delete"},
        {"op": "set_category", "source": "a", "target": "b"},
        {"op": "add_entry", "source": "a", "target": "a", "value": 1},
        {"op": "add_entry", "source": "a", "target": "b", "value": 0},
        {"op": "reorder", "order": ["a", "a"]},
        {"op": "reorder", "order": ["a"], "extra": 1},
    ],
)
@pytest.mark.parametrize("route", ["plan", "write"])
def test_a_malformed_edit_is_a_422_validation_error(
    client: TestClient, route: str, edit: dict[str, Any]
) -> None:
    response = client.post(f"{API}/{route}", json=body(inline(), edit))
    assert response.status_code == 422
    assert error_of(response)["code"] == "validation_error"


def test_a_failure_after_the_consent_is_a_503_and_leaves_the_file_alone(
    web: WebApp,
    client: TestClient,
    put_file: Callable[[str, str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    put_file("flows.csv", CSV)

    def broken(*_args: Any) -> int:
        raise StorageError("the file could not be written")

    monkeypatch.setattr("sankey_studio.edits.files.edit_file", broken)
    response = client.post(f"{API}/write", json=body(agreed(client), ADD))
    assert response.status_code == 503
    assert (web.config.effective_sources_dir / "flows.csv").read_text() == CSV


def test_a_mongo_edit_over_http(web: WebApp, client: TestClient) -> None:
    web.mongo["flows"]["events"].insert_one({"source": "a", "target": "b", "value": 1})
    response = client.post(
        f"{API}/plan", json=body(mongo_source(), {**CATEGORISE, "source": "a", "target": "b"})
    )
    assert response.status_code == 200
    assert response.json()["where"] == "mongo"
