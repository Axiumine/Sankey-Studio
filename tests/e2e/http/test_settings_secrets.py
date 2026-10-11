"""E2E A.1 (settings): the connection password appears in no response, log line or console text."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import (
    FLOWS_COLLECTION,
    FLOWS_DATABASE,
    MONGO_PASSWORD,
    MONGO_URI,
    mongo_settings,
    seed_flows,
)
from tests.e2e.support.clients import json_of, make_client
from tests.e2e.support.http_a_leaks import Recording, record
from tests.e2e.support.http_a_settings import connection, get_settings, keys_of, put_settings

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

MONGO_SOURCE = {
    "type": "mongo",
    "connection": "main",
    "database": FLOWS_DATABASE,
    "collection": FLOWS_COLLECTION,
    "mode": "find",
    "source_field": "from",
    "target_field": "to",
    "value_field": "amount",
}
CLIENT_LOGGERS = ("httpx", "httpcore")
PAGES = ["/", "/graphs/new", "/settings", "/compare"]


class Spy:
    """Everything that could carry the password: responses, log records, stdout and stderr."""

    def __init__(
        self,
        recording: Recording,
        caplog: pytest.LogCaptureFixture,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        self.recording = recording
        self.caplog = caplog
        self.capfd = capfd

    def server_log(self) -> str:
        """The formatted log records of the app and uvicorn (not the test client's own chatter)."""
        records = [r for r in self.caplog.records if not r.name.startswith(CLIENT_LOGGERS)]
        return "\n".join(self.caplog.handler.format(record) for record in records)

    def assert_nothing_leaked(self) -> None:
        assert self.recording.texts, "no response was recorded: the spy saw nothing"
        assert self.recording.leaks(MONGO_PASSWORD) == []
        assert self.recording.leaks(MONGO_URI) == []
        assert MONGO_PASSWORD not in self.server_log()
        captured = self.capfd.readouterr()
        assert MONGO_PASSWORD not in captured.out + captured.err


@pytest.fixture
def server(make_server: ServerFactory) -> LiveServer:
    return make_server(settings=mongo_settings("main"), seed_mongo=seed_flows)


@pytest.fixture
def spy(caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]) -> Spy:
    caplog.set_level(logging.DEBUG)
    return Spy(Recording(), caplog, capfd)


def visit_everything(api: httpx.Client, server: LiveServer) -> None:
    """Drive the routes that deal with a connection, good and bad, and the pages around them."""
    base = "/api/v1/mongo/main"
    assert api.get(f"{base}/databases").status_code == 200
    assert api.get(f"{base}/collections", params={"database": FLOWS_DATABASE}).status_code == 200
    sample = {"database": FLOWS_DATABASE, "collection": FLOWS_COLLECTION}
    assert api.get(f"{base}/sample", params=sample).status_code == 200
    body = {"name": "viaMongo", "source": MONGO_SOURCE}
    graph = json_of(api.post("/api/v1/graphs", json=body), 201)
    assert api.get(f"/api/v1/graphs/{graph['id']}/render").status_code == 200
    assert api.get("/api/v1/graphs/export", params={"ids": graph["id"]}).status_code == 200
    assert api.post("/api/v1/settings/mongo/main/test").status_code == 200
    server.mongo.unreachable = True
    for path in ("databases", "collections?database=flows"):
        assert api.get(f"{base}/{path}").status_code == 422
    assert api.post("/api/v1/settings/mongo/main/test").status_code == 503
    fresh = {"source": {**MONGO_SOURCE, "limit": 7}}  # not in the result cache: it must connect
    assert api.post("/api/v1/preview", json=fresh).status_code >= 400
    server.mongo.unreachable = False
    for page in PAGES:
        assert api.get(page).status_code == 200


def test_the_password_is_nowhere_while_every_connection_route_is_used(
    server: LiveServer, spy: Spy
) -> None:
    with make_client(server) as api:
        spy.recording.texts = record(api).texts
        settings = get_settings(api)
        assert "uri" not in set(keys_of(settings))
        visit_everything(api, server)
        rotated = {**settings, "mongo_connections": [connection(uri=MONGO_URI.replace("e2e", "x"))]}
        saved = put_settings(api, rotated)
        assert "uri" not in set(keys_of(saved))
        put_settings(api, {**rotated, "mongo_connections": [connection(uri=None)]})
        for bad in ("ftp://tester:hunter2@x/", f"mongodb://tester:{MONGO_PASSWORD}"):
            api.put(
                "/api/v1/settings", json={**settings, "mongo_connections": [connection(uri=bad)]}
            )
    spy.assert_nothing_leaked()


def test_a_brand_new_connection_is_not_echoed_in_any_later_answer(
    make_server: ServerFactory, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    server = make_server()
    with make_client(server) as api:
        recording = record(api)
        put_settings(api, {**get_settings(api), "mongo_connections": [connection()]})
        for path in ("/api/v1/settings", "/settings", "/api/v1/mongo/main/databases"):
            api.get(path)
        api.post("/api/v1/settings/mongo/main/test")
        api.post("/api/v1/settings/storage/test", json=get_settings(api))
    Spy(recording, caplog, capfd).assert_nothing_leaked()


@pytest.mark.parametrize("channel", ["response", "log", "stdout"])
def test_the_spy_does_notice_a_password_planted_in_each_channel(
    channel: str, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    """Control for the two tests above: a spy that cannot fail would prove nothing."""
    caplog.set_level(logging.DEBUG)
    recording = Recording(["GET /x 200\n\nbody"])
    spy = Spy(recording, caplog, capfd)
    spy.assert_nothing_leaked()
    planted = f"password is {MONGO_PASSWORD}"
    if channel == "response":
        recording.texts.append(planted)
    elif channel == "log":
        logging.getLogger("sankey_studio.control").warning(planted)
    else:
        print(planted)  # noqa: T201 - plants text on stdout for the spy to find
    with pytest.raises(AssertionError):
        spy.assert_nothing_leaked()
