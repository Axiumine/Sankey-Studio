"""A bundle as a FastAPI response: the model is usable as a response model, alone and in a list.

No ``from __future__ import annotations`` here: FastAPI reads the route annotations at runtime.
"""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sankey_studio.bundle import RenderBundle
from sankey_studio.models import GraphDraft, ManualSource
from sankey_studio.pipeline import BundleOptions, assemble_bundle
from tests.render.support import budget, plain

DRAFT = GraphDraft(source=ManualSource())
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def make(plain_graph: bool = False) -> RenderBundle:
    return assemble_bundle(plain() if plain_graph else budget(), DRAFT, BundleOptions("light"))


@app.get("/one")
def one() -> RenderBundle:
    return make()


@app.get("/many")
def many() -> list[RenderBundle]:
    return [make(), make(plain_graph=True)]


def test_a_bundle_is_served_as_json_and_parses_back() -> None:
    response = TestClient(app).get("/one")
    assert response.status_code == 200
    assert RenderBundle.model_validate(response.json()) == make()
    body = response.json()
    assert body["donut_available"] is True
    assert body["stats"]["category_count"] == 4
    assert body["entries"][0] == {
        "source": "Salary",
        "target": "Budget",
        "value": 5000.0,
        "category": "Income",
        "mixed": False,
        "overridden": False,
    }


def test_a_list_of_bundles_is_served_in_order() -> None:
    response = TestClient(app).get("/many")
    assert response.status_code == 200
    cards = [RenderBundle.model_validate(item) for item in response.json()]
    assert [card.donut_available for card in cards] == [True, False]
    assert [card.donut_empty_reason for card in cards] == [None, "no_categories"]


def test_the_served_figure_is_the_figure_dict_untouched() -> None:
    served = TestClient(app).get("/one").json()["figure"]
    assert served == json.loads(json.dumps(make().figure))
