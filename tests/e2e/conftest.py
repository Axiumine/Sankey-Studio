"""Fixtures of the end-to-end suites: a real server, HTTP clients and a real browser.

Every test under ``tests/e2e`` is marked ``e2e`` automatically (``make test`` and ``make cov``
skip them, ``make e2e`` runs them). Tests that need a real MongoDB add ``@pytest.mark.mongo`` and
are left out of ``make e2e`` (``make e2e-mongo``, needs ``SANKEY_TEST_MONGO_URI``); those that need
a real replica set carry ``@pytest.mark.mongo_rs`` (``make e2e-mongo-rs``, needs
``SANKEY_TEST_MONGO_RS_URI``).

Servers (``support.server``; option reference in its docstring)
---------------------------------------------------------------
``make_server(**options) -> LiveServer``
    Function scope. Starts a server per call (fresh ``data_dir`` / ``sources_dir`` under
    ``tmp_path``); all of them are stopped at teardown (port closed asserted). Options:
    ``remote_mode``, ``allow_remote_writes``, ``allow_source_writes``, ``settings``,
    ``export_unavailable``, ``seed_mongo``, ``mongo_factory``.
    ``LiveServer.mongo`` is the ``E2EMongoClient`` behind every Mongo connection (mongomock plus
    the inspect calls; ``.unreachable = True`` = outage).
``live_server``
    Function scope. ``make_server()``: the default local server, fresh for every test.
``module_make_server(**options) -> LiveServer`` / ``module_server``
    Module scope: the same, shared by all tests of a module (cheaper). Use ONLY with tests that
    need no clean state (unique names per test, no counting of other tests' data). To make
    ``api`` / ``page`` / ``foreign`` / ``bare`` use it, override ``live_server`` in the module::

        @pytest.fixture
        def live_server(module_server: LiveServer) -> LiveServer:
            return module_server

``real_mongo_uri``
    The ``SANKEY_TEST_MONGO_URI`` value; skips the test (with the reason) when it is not set.

HTTP clients (``support.clients``), all bound to ``live_server``
-----------------------------------------------------------------
``api`` - ``httpx.Client`` sending ``Origin: <server url>``; ``foreign`` - ``Origin:
http://evil.example``; ``bare`` - no ``Origin`` (curl-style). Build more with
``make_client(server, origin=...)``.

Browser (``support.browser``, ``support.session``, ``support.watch``)
----------------------------------------------------------------------
``browser`` (session scope)
    System Chrome, else the bundled Chromium, else the whole test is skipped with the reason.
``color_scheme`` / ``viewport``
    Defaults ``"light"`` and ``{"width": 1280, "height": 900}``. Override per test with
    ``@pytest.mark.parametrize("color_scheme", ["dark"])`` or ``("viewport", [{"width": 390,
    "height": 844}])``.
``open_page(server, *, color_scheme, viewport) -> WatchedPage``
    A page in a fresh context for any server (the read-only variant, a second server). Contexts
    are traced and closed at teardown.
``page`` (``WatchedPage``)
    ``open_page(live_server, ...)``: reduced motion, ``en-US``, UTC, downloads accepted,
    ``base_url`` = the server. Console errors and warnings, page errors, CSP violations, failed
    requests and 4xx/5xx responses are collected; at teardown of a passing test there must be none
    left after ``page.allow_errors(...)`` / ``page.allow_http(status, path)`` (``support.watch``).
    A failing test (or a dirty browser) leaves a screenshot, the trace and the collected lines in
    ``.e2e-artifacts/<test-id>/`` (git-ignored; ``$E2E_ARTIFACTS_DIR`` moves it).
"""

from __future__ import annotations

import itertools
import os
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Unpack

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.conftest import REAL_MONGO_ENV
from tests.e2e.support.browser import (
    DEFAULT_VIEWPORT,
    EXPECT_TIMEOUT_MS,
    ColorScheme,
    launch_browser,
)
from tests.e2e.support.clients import FOREIGN_ORIGIN, make_client
from tests.e2e.support.server import LiveServer, ServerFactory, ServerOptions, running_server
from tests.e2e.support.session import ARTIFACTS_DIR, PageFactory, PageOpener, artifact_slug
from tests.e2e.support.shard import SHARD_ENV, parse_shard, split_items

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    import httpx
    from playwright.sync_api import Browser, ViewportSize

    from tests.e2e.support.watch import WatchedPage

E2E_DIR = Path(__file__).resolve().parent
_REPORTS = pytest.StashKey[dict[str, pytest.TestReport]]()


# ------------------------------------------------------------------------------ pytest hooks


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every test below ``tests/e2e`` as ``e2e``; with ``E2E_SHARD`` set, keep one shard.

    ``E2E_SHARD=2/5`` runs the second of five slices of the suite (``support.shard``; ``make e2e``
    starts the five at once).
    """
    ours = [item for item in items if E2E_DIR in item.path.parents]
    for item in ours:
        item.add_marker(pytest.mark.e2e)
    spec = os.environ.get(SHARD_ENV)
    if spec:
        _keep_shard(config, items, ours, spec)


def _keep_shard(
    config: pytest.Config, items: list[pytest.Item], ours: list[pytest.Item], spec: str
) -> None:
    try:
        shard = parse_shard(spec)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    functions = [item for item in ours if isinstance(item, pytest.Function)]
    _, dropped = split_items(functions, shard)
    if dropped:
        gone = set(dropped)
        items[:] = [item for item in items if item not in gone]
        config.hook.pytest_deselected(items=dropped)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Keep the setup and call reports on the item: fixtures decide on them at teardown."""
    report = yield
    item.stash.setdefault(_REPORTS, {})[report.when] = report
    return report


def item_failed(item: pytest.Item) -> bool:
    """True once the setup or the call of ``item`` has failed (usable in fixture teardown)."""
    reports = item.stash.get(_REPORTS, {})
    return any(report.failed for report in reports.values())


# ------------------------------------------------------------------------------ servers


def _factory(stack: ExitStack, base: Path) -> ServerFactory:
    numbers = itertools.count(1)

    def build(**options: Unpack[ServerOptions]) -> LiveServer:
        return stack.enter_context(running_server(base / f"server-{next(numbers)}", **options))

    return build


@pytest.fixture
def make_server(tmp_path: Path) -> Iterator[ServerFactory]:
    with ExitStack() as stack:
        yield _factory(stack, tmp_path)


@pytest.fixture
def live_server(make_server: ServerFactory) -> LiveServer:
    return make_server()


@pytest.fixture(scope="module")
def module_make_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServerFactory]:
    with ExitStack() as stack:
        yield _factory(stack, tmp_path_factory.mktemp("e2e-module"))


@pytest.fixture(scope="module")
def module_server(module_make_server: ServerFactory) -> LiveServer:
    return module_make_server()


@pytest.fixture
def real_mongo_uri() -> str:
    uri = os.environ.get(REAL_MONGO_ENV)
    if not uri:
        pytest.skip(f"needs {REAL_MONGO_ENV} (a MongoDB you started yourself: make mongo-up)")
    return uri


# ------------------------------------------------------------------------------ http clients


@pytest.fixture
def api(live_server: LiveServer) -> Iterator[httpx.Client]:
    with make_client(live_server) as client:
        yield client


@pytest.fixture
def foreign(live_server: LiveServer) -> Iterator[httpx.Client]:
    with make_client(live_server, origin=FOREIGN_ORIGIN) as client:
        yield client


@pytest.fixture
def bare(live_server: LiveServer) -> Iterator[httpx.Client]:
    with make_client(live_server, origin=None) as client:
        yield client


# ------------------------------------------------------------------------------ browser


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        launched, reason = launch_browser(pw)
        if launched is None:
            pytest.skip(reason)
        expect.set_options(timeout=EXPECT_TIMEOUT_MS)
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def color_scheme() -> ColorScheme:
    return "light"


@pytest.fixture
def viewport() -> ViewportSize:
    return {"width": DEFAULT_VIEWPORT["width"], "height": DEFAULT_VIEWPORT["height"]}


@pytest.fixture
def open_page(
    browser: Browser,
    request: pytest.FixtureRequest,
    make_server: ServerFactory,  # noqa: ARG001 - ordering only: pages close before servers stop
) -> Iterator[PageOpener]:
    factory = PageFactory(browser, ARTIFACTS_DIR / artifact_slug(request.node.nodeid))
    yield factory.open
    factory.finish(failed=item_failed(request.node))


@pytest.fixture
def page(
    open_page: PageOpener,
    live_server: LiveServer,
    color_scheme: ColorScheme,
    viewport: ViewportSize,
) -> WatchedPage:
    return open_page(live_server, color_scheme=color_scheme, viewport=viewport)
