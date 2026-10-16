# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E: the edits API (``/edits/plan``, ``/edits/write``) on a live server.

The MongoDB scenarios live in ``tests.e2e.support.http_b_edit_flows`` and are shared with the
real-MongoDB suite (``tests/e2e/mongo/test_source_write_back.py``). Below: pasted text, manual
links and managed files over HTTP, and the remote-mode behaviour (read-only server, remote writes
without source writes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.edits.target import write_target
from sankey_studio.models import MongoSource
from tests.e2e.support.builders import BUDGET_CATEGORISED, graph_draft
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_b_edit_flows import (
    EDIT_SCENARIOS,
    PLAN,
    RENT,
    WRITE,
    category_of,
    check_a_read_only_user_keeps_the_edit_in_the_graph,
)
from tests.e2e.support.http_b_world import mongomock_world, open_env

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

    from tests.e2e.support.http_b_mongo_flows import Scenario
    from tests.e2e.support.http_b_world import FlowEnv
    from tests.e2e.support.server import LiveServer, ServerFactory

CATEGORISE = {"op": "set_category", "source": "Food", "target": "Groceries", "category": "Fresh"}
ADD = {"op": "add_entry", "source": "Savings", "target": "Holiday", "value": 90}


@pytest.fixture
def env(make_server: ServerFactory) -> Iterator[FlowEnv]:
    with open_env(make_server, mongomock_world()) as flow_env:
        yield flow_env


@pytest.mark.parametrize("scenario", EDIT_SCENARIOS)
def test_mongo_write_back(env: FlowEnv, scenario: Scenario) -> None:
    scenario(env)


def test_a_read_only_database_user_keeps_the_edit_in_the_graph(env: FlowEnv) -> None:
    check_a_read_only_user_keeps_the_edit_in_the_graph(env)


def draft(**source: Any) -> dict[str, Any]:
    return graph_draft(BUDGET_CATEGORISED.csv, source=source)


def edit_of(api: httpx.Client, route: str, draft_: dict[str, Any], edit: dict[str, Any]) -> Any:
    return api.post(route, json={"draft": draft_, "edit": edit})


def test_pasted_text_is_edited_in_the_draft_and_the_preview_agrees(
    live_server: LiveServer, api: httpx.Client
) -> None:
    outcome = json_of(edit_of(api, PLAN, draft(), ADD))
    assert (outcome["where"], outcome["consent"], outcome["written"]) == ("draft", "none", False)
    assert outcome["source"]["content"].endswith("Savings,Holiday,90,\n")
    again = json_of(api.post("/api/v1/preview", json={**draft(), "source": outcome["source"]}))
    assert again["stats"]["links"] == BUDGET_CATEGORISED.links + 1
    assert list(live_server.sources_dir.glob("*")) == []


def test_a_category_in_pasted_text_changes_the_cell_and_says_what_to_do_with_overrides(
    api: httpx.Client,
) -> None:
    outcome = json_of(edit_of(api, PLAN, draft(), CATEGORISE))
    assert (outcome["where"], outcome["changed"], outcome["override"]) == ("draft", 1, "drop")
    assert "Food,Groceries,500,Fresh" in outcome["source"]["content"]


def test_a_drag_rewrites_the_pasted_rows_and_pins_the_colours_it_would_move(
    api: httpx.Client,
) -> None:
    drag = {"op": "reorder", "order": ["Salary", "Freelance", "Budget", "Utilities", "Rent"]}
    outcome = json_of(edit_of(api, PLAN, draft(), drag))
    assert (outcome["where"], outcome["reason"]) == ("draft", None)
    assert "Budget,Utilities,260,Housing\nBudget,Rent,1200,Housing" in outcome["source"]["content"]
    pins = outcome["pins"]["node_colors"]
    assert pins
    assert all(colour.startswith("#") and len(colour) == 7 for colour in pins.values())
    styled = {"node_colors": pins}
    again = json_of(
        api.post("/api/v1/preview", json={**draft(), "source": outcome["source"], "style": styled})
    )
    assert again["stats"]["links"] == BUDGET_CATEGORISED.links


def test_manual_links_are_edited_in_the_draft(api: httpx.Client) -> None:
    manual = {"type": "manual", "links": [{"source": "a", "target": "b", "value": 4}]}
    body = {"draft": {"source": manual}, "edit": {"op": "add_entry", **_pair("b", "c")}}
    outcome = json_of(api.post(PLAN, json=body))
    assert outcome["where"] == "draft"
    assert [link["target"] for link in outcome["source"]["links"]] == ["b", "c"]


def _pair(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target, "value": 2}


def test_a_cycle_is_a_422_before_any_dialog(api: httpx.Client) -> None:
    cycle = {"op": "add_entry", "source": "Savings", "target": "Salary", "value": 1}
    response = edit_of(api, PLAN, draft(), cycle)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "graph_build_error"


def test_a_managed_file_is_edited_after_the_consent(
    live_server: LiveServer, api: httpx.Client
) -> None:
    path = live_server.sources_dir / "budget.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BUDGET_CATEGORISED.csv, encoding="utf-8")
    source = {"type": "text", "origin": "file", "path": "budget.csv", "format": "csv"}
    asked = json_of(edit_of(api, PLAN, {"source": source}, CATEGORISE))
    assert (asked["where"], asked["consent"], asked["target"]) == ("file", "ask", "budget.csv")
    assert path.read_text(encoding="utf-8") == BUDGET_CATEGORISED.csv
    pref = {"mode": "source", "target": asked["target_key"]}
    refused = edit_of(api, WRITE, {"source": source}, CATEGORISE)
    assert refused.status_code == 422
    done = json_of(edit_of(api, WRITE, {"source": {**source, "write_back": pref}}, CATEGORISE))
    assert (done["where"], done["written"], done["changed"]) == ("file", True, 1)
    assert "Food,Groceries,500,Fresh" in path.read_text(encoding="utf-8")
    bundle = json_of(api.post("/api/v1/preview", json={"source": source}))
    assert "Fresh" in bundle["category_names"], "the file is read again after the write"


def test_a_read_only_remote_server_plans_but_never_writes(make_server: ServerFactory) -> None:
    server = make_server(remote_mode=True)
    server.sources_dir.mkdir(parents=True, exist_ok=True)
    (server.sources_dir / "budget.csv").write_text(BUDGET_CATEGORISED.csv, encoding="utf-8")
    source = {"type": "text", "origin": "file", "path": "budget.csv", "format": "csv"}
    with make_client(server) as api:
        planned = json_of(edit_of(api, PLAN, {"source": source}, CATEGORISE))
        assert (planned["where"], planned["reason"]) == ("graph", "read_only_mode")
        assert "read-only" in planned["notice"]
        forced = edit_of(api, WRITE, {"source": source}, CATEGORISE)
        assert forced.status_code == 403
        assert forced.json()["error"]["code"] == "read_only_mode"
    assert (server.sources_dir / "budget.csv").read_text(encoding="utf-8") == BUDGET_CATEGORISED.csv


def test_remote_writes_unlock_files_but_not_mongodb(make_server: ServerFactory) -> None:
    world = mongomock_world()
    options = {**world.settings(), "mongo_connections": [world.connection()]}
    server = make_server(
        remote_mode=True,
        allow_remote_writes=True,
        settings=options,
        mongo_factory=world.factory,
    )
    world.seed()
    spec = MongoSource.model_validate(world.source())
    key = write_target(spec, server.services.settings())
    source = {**world.source(), "write_back": {"mode": "source", "target": key}}
    with make_client(server) as api:
        planned = json_of(edit_of(api, PLAN, {"source": world.source()}, RENT))
        assert (planned["where"], planned["reason"]) == ("graph", "read_only_mode")
        forced = edit_of(api, WRITE, {"source": source}, RENT)
        assert (forced.status_code, forced.json()["error"]["code"]) == (403, "read_only_mode")
    assert world.counts()["transfers"] == 5
    assert world.client[world.database]["transfers"].count_documents({"kind": "Fixed"}) == 0


def test_remote_source_writes_unlock_mongodb(make_server: ServerFactory) -> None:
    world = mongomock_world()
    options = {**world.settings(), "mongo_connections": [world.connection()]}
    server = make_server(
        remote_mode=True,
        allow_remote_writes=True,
        allow_source_writes=True,
        settings=options,
        mongo_factory=world.factory,
    )
    world.seed()
    spec = MongoSource.model_validate(world.source())
    key = write_target(spec, server.services.settings())
    source = {**world.source(), "write_back": {"mode": "source", "target": key}}
    with make_client(server) as api:
        planned = json_of(edit_of(api, PLAN, {"source": world.source()}, RENT))
        assert (planned["where"], planned["target_key"]) == ("mongo", key)
        done = json_of(edit_of(api, WRITE, {"source": source}, RENT))
        assert (done["where"], done["written"], done["changed"]) == ("mongo", True, 1)
    assert category_of(world, "Rent") == "Fixed"
