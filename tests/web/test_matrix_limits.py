"""Query caps through the FULL app: the last value that passes and the first one that does not."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

import pytest

from tests.web.test_matrix_support import ENDPOINTS, UNKNOWN_ID, UNSAFE
from tests.web.test_routes_graphs_support import API, ids_of

if TYPE_CHECKING:
    from tests.web.conftest import WebApp


class Cap(NamedTuple):
    """``path`` with ``params``: ``ok`` is the status of the last passing value, ``over`` is 422."""

    label: str
    path: str
    ok_params: dict[str, Any]
    over_params: dict[str, Any]
    ok_status: int


CAPS = [
    Cap(
        "compare ids 12/13", f"{API}/compare/render", {"ids": ids_of(12)}, {"ids": ids_of(13)}, 404
    ),
    Cap(
        "export ids 200/201",
        f"{API}/graphs/export",
        {"ids": ids_of(200)},
        {"ids": ids_of(201)},
        404,
    ),
    Cap("compare page ids 12/13", "/compare", {"ids": ids_of(12)}, {"ids": ids_of(13)}, 200),
    Cap("list limit 200/201", f"{API}/graphs", {"limit": 200}, {"limit": 201}, 200),
    Cap("list limit 1/0", f"{API}/graphs", {"limit": 1}, {"limit": 0}, 200),
    Cap("list offset 0/-1", f"{API}/graphs", {"offset": 0}, {"offset": -1}, 200),
    Cap(
        "sample n 20/21",
        f"{API}/mongo/none/sample",
        {"database": "flows", "collection": "c", "n": 20},
        {"database": "flows", "collection": "c", "n": 21},
        404,
    ),
    Cap(
        "sample n 1/0",
        f"{API}/mongo/none/sample",
        {"database": "flows", "collection": "c", "n": 1},
        {"database": "flows", "collection": "c", "n": 0},
        404,
    ),
]


@pytest.mark.parametrize("cap", CAPS, ids=[c.label for c in CAPS])
def test_the_last_value_passes_and_the_next_is_a_422(web: WebApp, cap: Cap) -> None:
    passed = web.client.get(cap.path, params=cap.ok_params)
    over = web.client.get(cap.path, params=cap.over_params)
    assert passed.status_code == cap.ok_status
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "validation_error"


def test_a_query_parameter_nobody_declared_is_a_422(web: WebApp) -> None:
    for path in (f"{API}/graphs", f"{API}/graphs/export", f"{API}/compare/render"):
        response = web.client.get(path, params={"ids": ids_of(1), "bogus": "1"})
        assert response.status_code == 422, path


def test_the_entries_page_size_is_capped_at_500(web: WebApp) -> None:
    body = {"source": {"type": "manual", "links": []}}
    at_cap = web.client.post(f"{API}/entries", params={"limit": 500}, json=body)
    over = web.client.post(f"{API}/entries", params={"limit": 501}, json=body)
    assert (at_cap.status_code, over.status_code) == (200, 422)


class Wrong(NamedTuple):
    method: str
    path: str


WRONG = [
    Wrong("GET", f"{API}/preview"),
    Wrong("GET", f"{API}/entries"),
    Wrong("GET", f"{API}/export"),
    Wrong("POST", f"{API}/health"),
    Wrong("DELETE", f"{API}/tags"),
    Wrong("PATCH", f"{API}/graphs/{UNKNOWN_ID}"),
    Wrong("GET", f"{API}/graphs/{UNKNOWN_ID}/duplicate"),
    Wrong("PUT", f"{API}/graphs"),
    Wrong("POST", f"{API}/compare/render"),
    Wrong("POST", f"{API}/graphs/export"),
    Wrong("POST", "/"),
    Wrong("PUT", "/settings"),
    Wrong("DELETE", "/graphs/new"),
    Wrong("POST", "/static/vendor/plotly.min.js"),
]


@pytest.mark.parametrize("wrong", WRONG, ids=[f"{w.method} {w.path}" for w in WRONG])
def test_a_method_nobody_registered_is_a_405_envelope(web: WebApp, wrong: Wrong) -> None:
    response = web.client.request(wrong.method, wrong.path)
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_the_table_has_fourteen_unsafe_and_twenty_one_safe_endpoints() -> None:
    assert len(UNSAFE) == 14
    assert len(ENDPOINTS) - len(UNSAFE) == 21
