# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The sources router as a whole: its routes, the file listing and ``POST /sources/detect``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.routing import APIRoute

from sankey_studio.web.routers.sources import router
from sankey_studio.web.security import UPLOAD_PATH
from tests.web.test_routes_sources_support import (
    BASE,
    DETECT,
    FILES,
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


def test_the_router_serves_exactly_these_routes() -> None:
    served = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    }
    assert served == {
        ("GET", f"{BASE}/files"),
        ("POST", f"{BASE}/files"),
        ("DELETE", f"{BASE}/files/{{name:path}}"),
        ("GET", f"{BASE}/files/{{name:path}}/preview"),
        ("POST", f"{BASE}/detect"),
    }


def test_the_upload_route_is_the_one_the_body_limiter_knows() -> None:
    assert FILES == UPLOAD_PATH


# --------------------------------------------------------------------------- listing


def test_an_empty_sources_directory_lists_nothing_and_is_created(web: WebApp) -> None:
    assert not web.config.effective_sources_dir.exists()
    response = web.client.get(FILES)
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["Cache-Control"] == "no-store"
    assert web.config.effective_sources_dir.is_dir()


def test_files_are_listed_with_size_and_modification_time_in_name_order(web: WebApp) -> None:
    put_file(web, "b.csv", b"1234567")
    put_file(web, "A.tsv", b"x")
    put_file(web, "sub/n.json", b"{}")
    put_file(web, "notes.exe", b"nope")
    response = web.client.get(FILES)
    assert response.status_code == 200
    items = response.json()
    assert [(i["name"], i["size"]) for i in items] == [
        ("A.tsv", 1),
        ("b.csv", 7),
        ("sub/n.json", 2),
    ]
    assert all(set(i) == {"name", "size", "modified"} for i in items)
    stamp = datetime.fromisoformat(items[0]["modified"])
    assert stamp.tzinfo is not None
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 60


def test_symlinks_are_not_listed(web: WebApp, tmp_path: Path) -> None:
    put_file(web, "real.csv")
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"secret")
    (web.config.effective_sources_dir / "link.csv").symlink_to(outside)
    assert listed(web.client) == ["real.csv"]


def test_listing_works_in_remote_read_only_mode(make_app: AppFactory) -> None:
    web = make_app([router], mode="remote_read_only")
    put_file(web, "a.csv")
    assert listed(web.client) == ["a.csv"]


# --------------------------------------------------------------------------- detect

JSON_SAMPLE = '[{"source": "a", "target": "b", "value": 1}]'
SAMPLES = [
    ("a,b,c\n1,2,3\n", "csv"),
    ("a;b;c\n1;2;3\n", "csv"),
    ("a\tb\tc\n1\t2\t3\n", "tsv"),
    ("Income [100] Rent\nIncome [50] Food\n", "sankeymatic"),
    (JSON_SAMPLE, "json"),
    ('{"source": "a", "target": "b", "value": 1}\n', "json"),
    ("﻿" + JSON_SAMPLE, "json"),
    ("", "csv"),
    ("just words", "csv"),
]


@pytest.mark.parametrize(("sample", "expected"), SAMPLES, ids=[s[1] for s in SAMPLES])
def test_detect_names_the_format_of_a_sample(web: WebApp, sample: str, expected: str) -> None:
    response = web.client.post(DETECT, json={"sample": sample})
    assert response.status_code == 200
    assert response.json() == {"format": expected}


def test_only_the_head_of_a_long_sample_decides(web: WebApp) -> None:
    long_sample = JSON_SAMPLE + "x" * 200_000
    response = web.client.post(DETECT, json={"sample": long_sample})
    assert response.status_code == 200
    assert response.json() == {"format": "json"}
    tail_json = "a,b\n" * 2000 + JSON_SAMPLE
    assert web.client.post(DETECT, json={"sample": tail_json}).json() == {"format": "csv"}


def test_whitespace_in_the_sample_is_kept(web: WebApp) -> None:
    tab_first = "\t\ta\tb\n\t\t1\t2\n"
    assert web.client.post(DETECT, json={"sample": tab_first}).json() == {"format": "tsv"}


@pytest.mark.parametrize(
    "body",
    [{}, {"sample": None}, {"sample": 5}, {"sample": ["a"]}, {"sample": "a", "extra": 1}],
    ids=["missing", "null", "number", "list", "extra-field"],
)
def test_a_bad_detect_body_is_a_422(web: WebApp, body: dict[str, object]) -> None:
    response = web.client.post(DETECT, json=body)
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert error["details"][0].startswith("body.")


def test_a_422_for_detect_never_echoes_the_sample(web: WebApp) -> None:
    response = web.client.post(DETECT, json={"sample": "pasted-secret-text", "extra": 1})
    assert response.status_code == 422
    assert "pasted-secret-text" not in response.text


def test_detect_is_a_pure_computation_available_in_remote_read_only_mode(
    make_app: AppFactory,
) -> None:
    web = make_app([router], mode="remote_read_only")
    response = web.client.post(DETECT, json={"sample": "a,b\n1,2\n"})
    assert response.status_code == 200
    assert response.json() == {"format": "csv"}
    assert not web.config.effective_sources_dir.exists()


def test_detect_follows_the_json_only_rule_of_unsafe_routes(web: WebApp) -> None:
    text = {"Content-Type": "text/plain"}
    assert web.client.post(DETECT, content=b"x", headers=text).status_code == 415
    assert web.bare.post(DETECT, json={"sample": "a,b"}).status_code == 200
    assert web.client.get(DETECT).status_code == 405
