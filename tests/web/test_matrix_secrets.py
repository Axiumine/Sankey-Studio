"""Secret hygiene on the FULL app: a saved Mongo password reaches no response and no log record.

The connection is saved through ``PUT /settings`` with the password ``hunter2``. Every route of the
table is then called, together with the requests that touch the connection (probes, inspection,
previews and exports over a Mongo source, a storage switch) while the driver fails with an
exception whose text carries the whole URI: nothing of the password may come back, whatever the
status, in a body or a header, and none of it may be logged (message, arguments or traceback).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from tests.web.test_matrix_support import ENDPOINTS
from tests.web.test_routes_graphs_support import API
from tests.web.test_routes_settings_support import key_names

if TYPE_CHECKING:
    from httpx2 import Response

    from tests.web.conftest import WebApp

PASSWORD: Final = "hunter2"
URI: Final = f"mongodb://admin:{PASSWORD}@prod.invalid:27017/?appName=sankey"
MASKED: Final = "mongodb://admin:***@prod.invalid:27017/?appName=sankey"
CONNECTION: Final = {"name": "prod", "uri": URI, "default_database": "flows"}
SOURCE: Final = {"type": "mongo", "connection": "prod", "database": "flows", "collection": "c"}
#: What the broken driver says: the whole URI, the way real driver errors sometimes do.
DRIVER_TEXT: Final = f"{URI} unreachable"


class Call(NamedTuple):
    method: str
    path: str
    body: dict[str, Any] | None = None


def storage_on_prod() -> dict[str, Any]:
    return {
        "storage_backend": "mongo",
        "storage_connection": "prod",
        "mongo_connections": [{"name": "prod", "default_database": "flows"}],
    }


def settings_with(connection: dict[str, Any]) -> dict[str, Any]:
    return {"mongo_connections": [connection]}


#: Requests that touch the connection or try to leak it (the table routes come on top).
EXTRA: Final = [
    Call("GET", f"{API}/settings"),
    Call("GET", f"{API}/mongo/prod/databases"),
    Call("GET", f"{API}/mongo/prod/collections?database=flows"),
    Call("GET", f"{API}/mongo/prod/sample?database=flows&collection=c&n=3"),
    Call("POST", f"{API}/settings/mongo/prod/test"),
    Call("POST", f"{API}/settings/storage/test", storage_on_prod()),
    Call("PUT", f"{API}/settings", storage_on_prod()),
    Call("PUT", f"{API}/settings?migrate=true", storage_on_prod()),
    Call("PUT", f"{API}/settings", settings_with({**CONNECTION, "uri": 123})),
    Call("PUT", f"{API}/settings", settings_with({"name": "x", "uri": f"{URI}&tlsInsecure=true"})),
    Call("PUT", f"{API}/settings", settings_with({"name": "x", "uri": f"{URI}\x00"})),
    Call("PUT", f"{API}/settings", settings_with({"name": "x", "uri": URI, "bogus": URI})),
    Call("POST", f"{API}/preview", {"source": SOURCE}),
    Call("POST", f"{API}/entries", {"source": SOURCE}),
    Call("POST", f"{API}/export?format=csv", {"source": SOURCE}),
    Call("POST", f"{API}/export?format=svg", {"source": SOURCE}),
    Call("POST", f"{API}/graphs", {"name": "From Mongo", "source": SOURCE}),
]


def explode(*_args: object, **_kwargs: object) -> None:
    raise ServerSelectionTimeoutError(DRIVER_TEXT)


@pytest.fixture
def armed(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> WebApp:
    """The app with the ``prod`` connection saved and a driver that fails with the whole URI."""
    saved = web.client.put(f"{API}/settings", json=settings_with(CONNECTION))
    assert saved.status_code == 200
    client_type, database_type = type(web.mongo), type(web.mongo.admin)
    monkeypatch.setattr(client_type, "list_databases", explode, raising=False)
    monkeypatch.setattr(client_type, "__getitem__", explode)
    monkeypatch.setattr(database_type, "command", explode)
    return web


def table_calls(saved_graph: str) -> list[Call]:
    """Every endpoint of the table once (placeholders filled, the saved graph's id used)."""
    return [
        Call(e.method, e.path.replace("0" * 32, saved_graph), {} if e.method != "GET" else None)
        for e in ENDPOINTS
    ]


def run(web: WebApp, calls: list[Call]) -> list[Response]:
    return [
        web.client.request(call.method, call.path, json=call.body)
        if call.body is not None
        else web.client.request(call.method, call.path)
        for call in calls
    ]


def saved_graph_on_mongo(web: WebApp) -> str:
    created = web.client.post(f"{API}/graphs", json={"name": "From Mongo", "source": SOURCE})
    assert created.status_code == 201
    return str(created.json()["id"])


def leaks(response: Response) -> list[str]:
    """Where in ``response`` the password (or the URI's credentials) shows up."""
    places = {"body": response.text, "headers": str(dict(response.headers))}
    return [name for name, text in places.items() if PASSWORD in text or "admin:hunter" in text]


def test_saving_the_connection_answers_with_the_masked_uri_only(web: WebApp) -> None:
    saved = web.client.put(f"{API}/settings", json=settings_with(CONNECTION))
    assert saved.status_code == 200
    assert saved.json()["settings"]["mongo_connections"] == [
        {
            "name": "prod",
            "uri_masked": MASKED,
            "has_secret": True,
            "default_database": "flows",
        }
    ]
    assert leaks(saved) == []
    assert "uri" not in key_names(saved.json())
    assert web.services.settings().connection("prod") is not None


def test_no_route_answers_with_the_password_while_the_driver_fails(armed: WebApp) -> None:
    graph_id = saved_graph_on_mongo(armed)
    calls = [*EXTRA, *table_calls(graph_id)]
    responses = run(armed, calls)
    bad = {f"{c.method} {c.path}": leaks(r) for c, r in zip(calls, responses, strict=True)}
    assert {name: where for name, where in bad.items() if where} == {}
    statuses = {r.status_code for r in responses}
    assert {200, 404, 422}.issubset(statuses)
    assert statuses & {500, 502, 503}  # the failing driver really was reached


def test_driver_failures_name_the_connection_and_nothing_else(armed: WebApp) -> None:
    probe = armed.client.post(f"{API}/settings/mongo/prod/test")
    databases = armed.client.get(f"{API}/mongo/prod/databases")
    for response in (probe, databases):
        assert response.status_code in {422, 503}
        message = response.json()["error"]["message"]
        assert "'prod'" in message
        assert "invalid" not in message  # not even the host of the URI
        assert "mongodb" not in message.lower().replace("mongodb connection", "")
        assert leaks(response) == []


def test_the_pages_never_embed_a_connection_string(armed: WebApp) -> None:
    graph_id = saved_graph_on_mongo(armed)
    paths = ["/", "/settings", f"/graphs/{graph_id}", f"/graphs/{graph_id}/edit"]
    for path in paths:
        page = armed.client.get(path)
        assert page.status_code == 200
        assert leaks(page) == []
        assert "mongodb://" not in page.text


def test_no_log_record_contains_the_password(
    armed: WebApp, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    graph_id = saved_graph_on_mongo(armed)
    run(armed, [*EXTRA, *table_calls(graph_id)])
    assert caplog.records  # the run logged something, so the check below is not vacuous
    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    for record in caplog.records:
        text = formatter.format(record)
        assert PASSWORD not in text, record.name
        assert PASSWORD not in str(record.args), record.name
    assert PASSWORD not in caplog.text
    assert "admin:hunter" not in caplog.text


def test_a_rejected_connection_string_is_not_echoed(web: WebApp) -> None:
    bodies = [
        settings_with({"name": "x", "uri": f"{URI}&tlsInsecure=true"}),
        settings_with({"name": "x", "uri": f"{URI}\x00"}),
        settings_with({"name": "x", "uri": "http://admin:hunter2@prod.invalid/"}),
        settings_with({"name": "x", "uri": 12345}),
        settings_with({"name": "x", "uri": [URI]}),
    ]
    for body in bodies:
        response = web.client.put(f"{API}/settings", json=body)
        assert response.status_code == 422
        assert leaks(response) == []
        assert URI not in response.text
    assert web.services.settings().mongo_connections == []


def test_the_secret_survives_a_round_trip_and_a_rename_without_being_shown(web: WebApp) -> None:
    web.client.put(f"{API}/settings", json=settings_with(CONNECTION))
    shown = web.client.get(f"{API}/settings")
    echoed = web.client.put(f"{API}/settings", json=shown.json())
    renamed = web.client.put(
        f"{API}/settings",
        json=settings_with({"name": "prod2", "previous_name": "prod", "default_database": "flows"}),
    )
    stored = web.services.settings().connection("prod2")
    assert [shown.status_code, echoed.status_code, renamed.status_code] == [200, 200, 200]
    assert stored is not None
    assert stored.uri.get_secret_value() == URI
    assert [leaks(r) for r in (shown, echoed, renamed)] == [[], [], []]
