# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The edits routes in remote mode: ``plan`` is pure and stays open, ``write`` persists.

Read-only remote server: plan answers 200 (``read_only_mode`` for a file or MongoDB source),
write answers 403 BEFORE the body is decoded. With ``--allow-remote-writes`` but without
``--allow-source-writes`` a file may be written and MongoDB may not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.edits.reasons import NOTICES
from sankey_studio.edits.target import write_target
from sankey_studio.models import AppSettings
from sankey_studio.web.deps import MSG_READ_ONLY
from sankey_studio.web.routers import edits
from tests.conftest import build_connection
from tests.test_edits_support import ADD, CSV, file_source, inline, mongo_source

if TYPE_CHECKING:
    from sankey_studio.models import SourceSpec
    from tests.web.conftest import AppFactory, WebApp

API: Final = "/api/v1/edits"
JSON: Final = {"Content-Type": "application/json"}
PAIR: Final = {"op": "set_category", "source": "a", "target": "b", "category": "Fun"}
SETTINGS: Final = AppSettings(mongo_connections=[build_connection()])


def body(source: SourceSpec, edit: dict[str, Any]) -> dict[str, Any]:
    return {"draft": {"source": source.model_dump(mode="json")}, "edit": edit}


def consenting(client: Any, source: SourceSpec) -> SourceSpec:
    """``source`` with a saved consent whose key comes from a ``plan`` answer."""
    key = client.post(f"{API}/plan", json=body(source, ADD)).json()["target_key"]
    pref = {"mode": "source", "target": key or "x"}
    return type(source).model_validate({**source.model_dump(), "write_back": pref})


def app(make_app: AppFactory, mode: Any) -> WebApp:
    web = make_app([edits.router, edits.writes_router], mode=mode, settings=SETTINGS)
    directory = web.config.effective_sources_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "flows.csv").write_text(CSV, encoding="utf-8")
    web.mongo["flows"]["events"].insert_one({"source": "a", "target": "b", "value": 1})
    return web


def test_plan_stays_open_on_a_read_only_server(make_app: AppFactory) -> None:
    web = app(make_app, "remote_read_only")
    pasted = web.client.post(f"{API}/plan", json=body(inline(), ADD))
    assert (pasted.status_code, pasted.json()["where"]) == (200, "draft")
    for source, edit in ((file_source(), ADD), (mongo_source(), PAIR)):
        outcome = web.client.post(f"{API}/plan", json=body(source, edit))
        assert outcome.status_code == 200
        assert outcome.json()["where"] == "graph"
        assert outcome.json()["reason"] == "read_only_mode"
        assert outcome.json()["notice"] == NOTICES["read_only_mode"]


@pytest.mark.parametrize("payload", [b"{}", b"", b"not json", b'{"edit": 1}', b"[1]", b"null"])
def test_write_is_403_before_the_body_is_decoded_on_a_read_only_server(
    make_app: AppFactory, payload: bytes
) -> None:
    web = app(make_app, "remote_read_only")
    response = web.client.post(f"{API}/write", content=payload, headers=JSON)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "read_only_mode"
    assert response.json()["error"]["message"] == MSG_READ_ONLY


def test_a_file_may_be_written_with_remote_writes(make_app: AppFactory) -> None:
    web = app(make_app, "remote_writes")
    source = consenting(web.client, file_source())
    response = web.client.post(f"{API}/write", json=body(source, ADD))
    assert response.status_code == 200
    assert response.json()["written"] is True
    assert (web.config.effective_sources_dir / "flows.csv").read_text().endswith("Gifts,50,Fun\n")


def test_mongodb_needs_allow_source_writes_on_top_of_remote_writes(make_app: AppFactory) -> None:
    web = app(make_app, "remote_writes")
    planned = web.client.post(f"{API}/plan", json=body(mongo_source(), PAIR)).json()
    assert (planned["where"], planned["reason"]) == ("graph", "read_only_mode")
    key = write_target(mongo_source(), web.services.settings())
    source = mongo_source(write_back={"mode": "source", "target": key})
    response = web.client.post(f"{API}/write", json=body(source, PAIR))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "read_only_mode"
    assert web.mongo["flows"]["events"].count_documents({"cat": "Fun"}) == 0
