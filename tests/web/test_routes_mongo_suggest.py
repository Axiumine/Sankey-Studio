"""``GET /mongo/{name}/sample``: the suggested mapping is drawn from EVERY sampled document."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.web.test_routes_mongo_support import BASE, RigMongo, build_rig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sankey_studio.models import AppSettings
    from tests.web.test_routes_mongo_support import Rig

#: The first document has no amount and no kind: only the later ones carry them.
SPARSE_FIRST = [
    {"from": "Income", "to": "Rent"},
    {"from": "Income", "to": "Food", "amount": 400.5, "type": "variable"},
    {"from": "Income", "to": "Fun", "amount": 80, "type": "fixed"},
]


@pytest.fixture
def rig(tmp_path: Path, app_settings: AppSettings) -> Iterator[Rig]:
    yield from build_rig(tmp_path, RigMongo(), app_settings)


def test_the_suggestion_sees_fields_that_only_later_documents_have(rig: Rig) -> None:
    rig.fake.docs = SPARSE_FIRST
    response = rig.client.get(
        f"{BASE}/test/sample", params={"database": "flows", "collection": "links", "n": 3}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] == SPARSE_FIRST
    assert body["suggested"] == {
        "source": "from",
        "target": "to",
        "value": "amount",
        "category": "type",
    }


def test_a_lone_sparse_document_keeps_the_default_value_and_no_category(rig: Rig) -> None:
    rig.fake.docs = SPARSE_FIRST[:1]
    response = rig.client.get(
        f"{BASE}/test/sample", params={"database": "flows", "collection": "links", "n": 1}
    )
    assert response.status_code == 200
    assert response.json()["suggested"] == {
        "source": "from",
        "target": "to",
        "value": "value",
        "category": None,
    }
