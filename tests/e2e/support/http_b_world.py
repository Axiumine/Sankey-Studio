"""``MongoWorld`` and ``FlowEnv``: one Mongo scenario, run on mongomock (A) or a real server (C).

The Mongo and storage flows of E2E.md A.6 / A.7 are written once (``http_b_mongo_flows``,
``http_b_storage_flows``) against a ``FlowEnv``: a live server, an HTTP client that records every
response (``Tape``) and a ``MongoWorld``. The only things that differ between the mongomock suite
(``tests/e2e/http``) and the real-Mongo suite (``tests/e2e/mongo``) are how the world is built:

* ``mongomock_world()`` - two in-memory clients behind the server's client factory: the good one
  answers every URI, except ``DEAD_URI`` which gets a client that is switched off (a Mongo server
  that is down). ``world.outage(True)`` switches the good one off too. The good server also holds
  the system databases and a neighbour database, like any real server.
* ``real_world(uri)`` - a real ``pymongo`` client for ``SANKEY_TEST_MONGO_URI`` and the
  production factory ``sankey_studio.mongo.default_factory``; ``DEAD_URI`` is a host name under the
  reserved ``.invalid`` TLD (it never resolves, nothing is dialled). ``world.drop()`` removes the
  uniquely named database at teardown. No other database is read or written.

Everything the scenarios store lives in ``world.database`` (``sankey_e2e_<8 hex>``): the source
collections, and the graph store when a scenario switches the storage backend to Mongo.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import unquote, urlsplit

import pytest
from pymongo import MongoClient

from sankey_studio.mongo import default_factory
from tests.e2e.support.builders import FLOW_DOCS, MONGO_URI
from tests.e2e.support.clients import make_client
from tests.e2e.support.http_b_tape import Tape, attach
from tests.e2e.support.mongo import E2EMongoClient

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

    import httpx

    from sankey_studio.mongo import ClientFactory
    from tests.e2e.support.server import LiveServer, ServerFactory

MAIN: Final = "main"
DEAD: Final = "dead"
#: Never resolves (RFC 6761): a connection to it fails without dialling anything.
DEAD_URI: Final = "mongodb://dead.invalid:27017"
DATA_COLLECTION: Final = "transfers"
DATABASE_PREFIX: Final = "sankey_e2e_"
#: How the documents of ``builders.FLOW_DOCS`` map to a link.
FLOW_FIELDS: Final = {
    "source_field": "from",
    "target_field": "to",
    "value_field": "amount",
    "category_field": "kind",
}
#: Databases the mongomock server holds besides the world's: the three system databases (never
#: listed by the app) and a neighbour (listed, like any other database of a shared server).
NEIGHBOUR: Final = "unrelated_project"
NOISE_DATABASES: Final = ("admin", "local", "config", NEIGHBOUR)
MOCK_TIMEOUT_MS: Final = 500
REAL_TIMEOUT_MS: Final = 2_000
REAL_PING_TIMEOUT_MS: Final = 5_000
MIN_SCANNED_PASSWORD: Final = 6
#: Other projects' MongoDBs on this machine listen here: never a target of these tests.
LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
FOREIGN_PORTS: Final = range(27017, 27020)
DEFAULT_MONGO_PORT: Final = 27017


@dataclass(frozen=True, slots=True)
class MongoWorld:
    """The MongoDB behind a test server, seen through the few operations the scenarios need.

    ``client`` is only ever used inside ``database`` (seed, count, drop). ``factory`` is what the
    server calls to open a connection. ``secrets`` are strings no response may contain.
    ``outage`` (mongomock only) switches the good server off and on.
    """

    uri: str
    database: str
    client: MongoClient[Any]
    factory: ClientFactory
    secrets: tuple[str, ...]
    timeout_ms: int
    outage: Callable[[bool], None] | None = None

    def insert(self, collection: str, docs: Iterable[Mapping[str, Any]]) -> None:
        """Insert copies of ``docs`` into ``collection`` of ``database``."""
        self.client[self.database][collection].insert_many([dict(doc) for doc in docs])

    def seed(self) -> None:
        """``builders.FLOW_DOCS`` (five documents, 3,000 in and out) in ``transfers``, once."""
        if not self.counts().get(DATA_COLLECTION):
            self.insert(DATA_COLLECTION, FLOW_DOCS)

    def counts(self) -> dict[str, int]:
        """``{collection: document count}`` of ``database``: what a scenario compares to prove
        that a refused request wrote nothing."""
        database = self.client[self.database]
        names = sorted(database.list_collection_names())
        return {name: database[name].count_documents({}) for name in names}

    def connection(self, name: str = MAIN, uri: str | None = None) -> dict[str, Any]:
        """A ``mongo_connections`` entry of ``PUT /settings`` (default: the world's URI)."""
        return {"name": name, "uri": uri or self.uri, "default_database": self.database}

    def source(self, **fields: Any) -> dict[str, Any]:
        """A ``mongo`` source over ``transfers`` (``find``); ``fields`` override any key."""
        base = {
            "type": "mongo",
            "connection": MAIN,
            "database": self.database,
            "collection": DATA_COLLECTION,
            "mode": "find",
            **FLOW_FIELDS,
        }
        return {**base, **fields}

    def draft(self, **fields: Any) -> dict[str, Any]:
        """A ``GraphDraft`` body over ``source(**fields)``."""
        return {"source": self.source(**fields), "transform": {}, "style": {}}

    def settings(self) -> dict[str, Any]:
        """The ``settings`` option of ``make_server``: a short timeout for the dead connection."""
        return {"mongo_timeout_ms": self.timeout_ms}

    def drop(self) -> None:
        """Drop ``database`` (and nothing else) and close the client."""
        if not self.database.startswith(DATABASE_PREFIX):
            raise AssertionError(f"refusing to drop {self.database!r}: not an e2e database")
        self.client.drop_database(self.database)
        self.client.close()


def unique_database() -> str:
    """``sankey_e2e_<8 hex>``: no other test, run or project uses it."""
    return f"{DATABASE_PREFIX}{uuid.uuid4().hex[:8]}"


def secrets_of(uri: str) -> tuple[str, ...]:
    """What no response may contain: ``user:password@`` and, when it is long enough not to occur
    by chance in ordinary text, the password alone. ``()`` for a URI without credentials."""
    parts = urlsplit(uri)
    if not parts.password:
        return ()
    password = unquote(parts.password)
    secrets = (f"{unquote(parts.username or '')}:{password}@",)
    return (password, *secrets) if len(password) >= MIN_SCANNED_PASSWORD else secrets


def mongomock_world() -> MongoWorld:
    """Two in-memory servers: the good one for every URI but ``DEAD_URI``, which is switched off."""
    good = E2EMongoClient(tz_aware=True)
    for name in NOISE_DATABASES:
        good[name]["something"].insert_one({"keep": "me"})
    dead = E2EMongoClient(tz_aware=True)
    dead.unreachable = True

    def factory(uri: str, _timeout_ms: int) -> MongoClient[Any]:
        return dead if "dead.invalid" in uri else good

    def outage(down: bool) -> None:
        good.unreachable = down

    return MongoWorld(
        uri=MONGO_URI,
        database=unique_database(),
        client=good,
        factory=factory,
        secrets=secrets_of(MONGO_URI),
        timeout_ms=MOCK_TIMEOUT_MS,
        outage=outage,
    )


def targets_foreign_mongo(uri: str) -> bool:
    """True for a loopback URI on 27017-27019 (the port 27017 is also the default of ``mongodb://``)."""
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:  # several hosts: no single port to judge
        return False
    if parts.scheme != "mongodb" or parts.hostname not in LOOPBACK_HOSTS:
        return False
    return (DEFAULT_MONGO_PORT if port is None else port) in FOREIGN_PORTS


def real_world(uri: str) -> MongoWorld:
    """A world on the real server at ``uri``; fails (does not skip) when it does not answer.

    The caller owns ``world.drop()``. ``uri`` is only read here: it comes from
    ``SANKEY_TEST_MONGO_URI``, which the user set on purpose. A loopback URI on 27017-27019 is
    refused (those are other projects' MongoDBs; the compose Mongo of this project is 27117).
    """
    if targets_foreign_mongo(uri):
        pytest.fail(
            "SANKEY_TEST_MONGO_URI points at 127.0.0.1:27017-27019; use `make mongo-up` (27117)"
        )
    client: MongoClient[Any] = MongoClient(
        uri,
        serverSelectionTimeoutMS=REAL_PING_TIMEOUT_MS,
        tz_aware=True,
    )
    try:
        client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - any driver error means the same: not reachable
        client.close()
        pytest.fail(
            f"SANKEY_TEST_MONGO_URI is set but the server did not answer: {type(exc).__name__}"
        )
    return MongoWorld(
        uri=uri,
        database=unique_database(),
        client=client,
        factory=default_factory,
        secrets=secrets_of(uri),
        timeout_ms=REAL_TIMEOUT_MS,
    )


# ------------------------------------------------------------------------------ the environment


@dataclass(frozen=True, slots=True)
class FlowEnv:
    """What a scenario runs against: the server, a recording client and the Mongo world."""

    server: LiveServer
    api: httpx.Client
    world: MongoWorld
    tape: Tape


@contextmanager
def open_env(
    make_server: ServerFactory, world: MongoWorld, settings: Mapping[str, Any] | None = None
) -> Iterator[FlowEnv]:
    """A server whose Mongo connections open through ``world.factory``, and a recording client.

    ``settings`` adds to the stored settings the server starts with (``{"max_links": 100}``)."""
    options = {**world.settings(), **(settings or {})}
    server = make_server(settings=options, mongo_factory=world.factory)
    with make_client(server) as api:
        yield FlowEnv(server, api, world, attach(api))
