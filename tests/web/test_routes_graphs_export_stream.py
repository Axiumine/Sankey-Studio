"""GET /graphs/export builds the bundle one graph at a time and counts UTF-8 bytes.

* Same bytes as ``json.dumps(bundle, indent=2)`` for text that is ASCII; other text stays as it is
  (``ensure_ascii=False``), so the size is the size the import measures.
* The cap is checked after each graph: a request for graphs that cannot fit stops at the first one
  that crosses it and never loads the rest, never holding more than the cap plus one graph.
* The cap boundary (cap accepted, cap + 1 byte refused) is measured on a fake repository that
  builds each graph when asked, with the cap constant patched small.
"""

from __future__ import annotations

import json
import tracemalloc
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest

from sankey_studio.errors import BundleError
from sankey_studio.models import GraphDefinition
from sankey_studio.storage.bundle import export_bundle
from sankey_studio.web.routers import graphs
from sankey_studio.web.routers.graphs import encode_bundle
from tests.web.test_routes_graphs_support import (
    API,
    BUDGET,
    PLAIN,
    code,
    put_graph,
    save,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from tests.web.conftest import AppFactory, WebApp

EXPORT: Final = f"{API}/graphs/export"
IMPORT: Final = f"{API}/graphs/import"
JSON_HEADERS: Final = {"Content-Type": "application/json"}
HUGE: Final = 1 << 40
MESSAGE: Final = "The export is larger than a bundle import accepts; export fewer graphs"
#: Letters, a two-byte letter and a four-byte emoji: one character is 1, 2 and 4 bytes of UTF-8.
UNITS: Final = ["a", "é", "\U0001f600"]


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    return make_app([graphs.router])


class FakeLibrary:
    """A repository that only answers ``get``: it builds each graph when asked and keeps none."""

    def __init__(self, count: int, chars: int, unit: str = "a") -> None:
        self.ids = [f"{number:032x}" for number in range(1, count + 1)]
        self.content = unit * chars
        self.loaded: list[str] = []

    def get(self, graph_id: str) -> GraphDefinition:
        self.loaded.append(graph_id)
        return GraphDefinition.model_validate(
            {
                "id": graph_id,
                "name": f"Graph {graph_id[-2:]}",
                "source": {
                    "type": "text",
                    "origin": "inline",
                    "format": "csv",
                    "content": self.content,
                },
                "created_at": "2026-01-01T12:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
            }
        )

    def size(self, count: int | None = None) -> int:
        """The bytes of the bundle of the first ``count`` graphs (all by default); not recorded."""
        mark = len(self.loaded)
        size = len(encode_bundle(self.get, self.ids[:count], HUGE))
        del self.loaded[mark:]
        return size

    def serve(self, web: WebApp, monkeypatch: pytest.MonkeyPatch, cap: int) -> None:
        """Make the library of ``web`` this fake one and the export cap ``cap`` bytes."""
        monkeypatch.setattr(web.services, "graphs", lambda: self)
        monkeypatch.setattr(graphs, "IMPORT_BODY_BYTES", cap)

    def export(self, web: WebApp, count: int | None = None) -> Any:
        return web.client.get(f"{EXPORT}?ids={','.join(self.ids[:count])}")


def dumps_of(web: WebApp, ids: list[str]) -> bytes:
    """What the document of ``ids`` is when it is built whole, the way it was before."""
    return json.dumps(export_bundle(web.services.graphs(), ids), indent=2).encode()


# ---------------------------------------------------------------- the bytes


def test_the_bytes_of_a_small_export_are_those_of_a_whole_json_dumps(web: WebApp) -> None:
    one = save(web, "Household", *BUDGET, description="Plan", tags=["home", "2026"])
    two = save(web, "Two", *PLAIN)
    three = put_graph(web, 3, "Three", tags=["x"])
    for ids in ([one.id], [two.id, one.id], [three, one.id, two.id, one.id]):
        response = web.client.get(f"{EXPORT}?ids={','.join(ids)}")
        assert response.status_code == 200
        assert response.content == dumps_of(web, ids)


def test_a_bundle_of_no_graph_is_still_a_json_document() -> None:
    body = encode_bundle(FakeLibrary(0, 0).get, [], HUGE)
    assert json.loads(body) == {
        "format": "sankey-studio/graphs",
        "version": 2,
        "graphs": [],
        "folders": [],
    }


def test_a_repeated_id_is_loaded_and_written_once() -> None:
    library = FakeLibrary(2, 3)
    first, second = library.ids
    body = encode_bundle(library.get, [second, first, second, first], HUGE)
    assert library.loaded == [second, first]
    assert [graph["id"] for graph in json.loads(body)["graphs"]] == [second, first]


# ---------------------------------------------------------------- the cap, on a fake library


class Boundary(NamedTuple):
    graphs: int
    unit: str


BOUNDARIES = [Boundary(graphs, unit) for graphs in (1, 2, 5) for unit in UNITS]


@pytest.mark.parametrize("case", BOUNDARIES, ids=lambda case: f"{case.graphs}-{ord(case.unit):x}")
def test_a_document_of_exactly_the_cap_is_served_and_one_byte_more_is_refused(
    web: WebApp, monkeypatch: pytest.MonkeyPatch, case: Boundary
) -> None:
    library = FakeLibrary(case.graphs, 150, case.unit)
    size = library.size()
    assert size > len(library.content) * len(case.unit)  # more than the text of the graphs
    library.serve(web, monkeypatch, size)
    served = library.export(web)
    assert served.status_code == 200
    assert len(served.content) == size
    assert served.headers["content-type"] == "application/json"
    library.serve(web, monkeypatch, size - 1)
    refused = library.export(web)
    assert refused.status_code == 422
    assert code(refused) == "bundle_error"
    error = refused.json()["error"]
    assert error["message"] == MESSAGE
    assert error["details"] == [f"limit_bytes={size - 1}"]
    assert "content-disposition" not in refused.headers


def test_the_size_counts_bytes_not_characters() -> None:
    library = FakeLibrary(1, 100, "\U0001f600")
    size = library.size()
    chars = len(encode_bundle(library.get, library.ids, HUGE).decode())
    assert size - chars == 300  # three more bytes than characters per emoji
    assert encode_bundle(library.get, library.ids, size)
    with pytest.raises(BundleError) as refused:
        encode_bundle(library.get, library.ids, size - 1)
    assert refused.value.message == MESSAGE
    assert refused.value.details == [f"limit_bytes={size - 1}"]  # the limit given, not the default
    assert chars < size - 1  # a count of characters would have let it through


def test_the_graphs_after_the_one_that_crosses_the_cap_are_never_loaded(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = FakeLibrary(20, 150)
    library.serve(web, monkeypatch, library.size(3))
    assert library.export(web, 3).status_code == 200  # three graphs fit exactly
    assert library.loaded == library.ids[:3]
    library.loaded.clear()
    assert library.export(web, 4).status_code == 422
    assert library.loaded == library.ids[:4]  # the fourth crossed the cap, nothing after it
    library.loaded.clear()
    assert library.export(web).status_code == 422
    assert library.loaded == library.ids[:4]


def test_every_graph_is_loaded_in_the_order_asked_when_all_fit(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = FakeLibrary(12, 20)
    library.serve(web, monkeypatch, library.size())
    wanted = list(reversed(library.ids))
    response = web.client.get(f"{EXPORT}?ids={','.join(wanted)}")
    assert response.status_code == 200
    assert library.loaded == wanted
    assert [graph["id"] for graph in response.json()["graphs"]] == wanted


# ---------------------------------------------------------------- memory


@pytest.fixture
def traced() -> Iterator[None]:
    tracemalloc.start()
    try:
        yield
    finally:
        tracemalloc.stop()


def peak_of(call: Callable[[], object]) -> int:
    """The most memory ``call()`` held at once above what was held before it."""
    tracemalloc.reset_peak()
    before = tracemalloc.get_traced_memory()[0]
    call()
    return tracemalloc.get_traced_memory()[1] - before


@pytest.mark.usefixtures("traced")
def test_a_refused_export_holds_the_cap_and_one_graph_not_the_whole_request(
    web: WebApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap = 256 * 1024
    library = FakeLibrary(60, 60_000)  # 3.6 MB of text asked for, 14 times the cap
    library.serve(web, monkeypatch, cap)
    whole = library.size()
    assert library.size(1) < cap < whole // 10
    peak = peak_of(lambda: library.export(web))
    assert library.loaded == library.ids[:5]  # four fit, the fifth crossed the cap
    assert peak < whole // 3  # the cap and the fifth graph in hand; held whole, it was 2 x whole
