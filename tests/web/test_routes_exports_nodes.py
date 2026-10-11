"""Image exports refuse a figure of more than 2000 nodes, on both export routes (SPEC section 6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from sankey_studio.web.routers import exports
from tests.web.test_routes_exports_support import (
    FakeRender,
    export_draft,
    export_saved,
    install_render,
)
from tests.web.test_routes_graphs_support import code, save_source

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, WebApp


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([exports.router])


@pytest.fixture
def render(monkeypatch: pytest.MonkeyPatch) -> FakeRender:
    return install_render(monkeypatch)


def star(nodes: int) -> dict[str, Any]:
    """An inline CSV of one source and ``nodes - 1`` targets: ``nodes`` nodes, fewer links."""
    lines = ["source,target,value", *(f"s,t{i},1" for i in range(nodes - 1))]
    return {"type": "text", "origin": "inline", "format": "csv", "content": "\n".join(lines)}


class Nodes(NamedTuple):
    nodes: int
    status: int


CASES = [Nodes(2000, 200), Nodes(2001, 422)]


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case.nodes))
def test_a_saved_image_of_more_than_2000_nodes_is_refused(
    web: WebApp, render: FakeRender, case: Nodes
) -> None:
    stored = save_source(web, "Star", star(case.nodes))
    response = export_saved(web, stored.id, format="png")
    assert response.status_code == case.status
    assert len(render.calls) == (1 if case.status == 200 else 0)
    if case.status == 422:
        assert code(response) == "export_too_large"
        assert f"{case.nodes} nodes" in response.json()["error"]["message"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case.nodes))
def test_a_draft_image_of_more_than_2000_nodes_is_refused(
    web: WebApp, render: FakeRender, case: Nodes
) -> None:
    response = export_draft(web, {"source": star(case.nodes)}, format="svg")
    assert response.status_code == case.status
    assert len(render.calls) == (1 if case.status == 200 else 0)
    if case.status == 422:
        assert code(response) == "export_too_large"


@pytest.mark.usefixtures("render")
@pytest.mark.parametrize("fmt", ["html", "json", "csv"])
def test_the_node_limit_of_images_does_not_apply_to_the_other_formats(
    web: WebApp, fmt: str
) -> None:
    stored = save_source(web, "Star", star(2001))
    assert export_saved(web, stored.id, format=fmt).status_code == 200
