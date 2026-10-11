"""``POST /settings/storage/test`` is bounded: at most 4 probes run at once, the next is a 503."""

from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest

from sankey_studio.errors import BusyError
from sankey_studio.models import AppSettings
from sankey_studio.mongo import MAX_CONCURRENT_PER_CONNECTION
from sankey_studio.services import Services
from sankey_studio.web.routers import settings as settings_module
from sankey_studio.web.routers.settings import (
    MAX_STORAGE_PROBES,
    MSG_PROBES_BUSY,
    router,
    storage_probe_slot,
)
from tests.conftest import build_connection
from tests.web.test_routes_settings_support import BASE, break_ping, error_of, put_body

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx2 import Response

    from tests.web.conftest import AppFactory, WebApp

STORAGE_TEST: Final = f"{BASE}/storage/test"
#: ``AppSettings.mongo_timeout_ms`` has a floor of 500: a waiting probe gives up after 0.5 s.
SHORT_WAIT_MS: Final = 500
#: Seconds the test itself waits for a thread; only a broken bound ever makes it wait that long.
PATIENCE_S: Final = 5.0
BUSY: Final = {"code": "busy", "message": MSG_PROBES_BUSY, "details": []}


class Gate:
    """A ``Services.test_storage`` that blocks until released, counting how many run at once."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Semaphore(0)
        self._lock = threading.Lock()
        self.running = 0
        self.peak = 0

    def hold(self) -> None:
        with self._lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        self.entered.release()
        try:
            assert self.release.wait(PATIENCE_S)
        finally:
            with self._lock:
                self.running -= 1


class Outcome(NamedTuple):
    """The answers that came while the probes were still blocked, and all of them at the end."""

    early: list[Response]
    final: list[Response]


@pytest.fixture
def web(make_app: AppFactory) -> WebApp:
    settings = AppSettings(mongo_connections=[build_connection()], mongo_timeout_ms=SHORT_WAIT_MS)
    return make_app([router], settings=settings)


@pytest.fixture(autouse=True)
def every_slot_is_free_afterwards(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield
    monkeypatch.undo()  # the real semaphore, even after a test that swapped it
    slots = settings_module._PROBE_SLOTS
    acquired = [slots.acquire(blocking=False) for _ in range(MAX_STORAGE_PROBES)]
    assert all(acquired)
    assert slots.acquire(blocking=False) is False
    for _ in range(MAX_STORAGE_PROBES):
        slots.release()


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Gate:
    blocking = Gate()

    def blocked(_services: Services, _settings: AppSettings) -> None:
        blocking.hold()

    monkeypatch.setattr(Services, "test_storage", blocked)
    return blocking


def run_probes(web: WebApp, gate: Gate, count: int) -> Outcome:
    """``count`` parallel probes; those the bound refuses answer while the others still block."""
    holders = min(count, MAX_STORAGE_PROBES)
    # The candidate asks for the longest wait there is: only the STORED timeout may count.
    body: dict[str, Any] = {**put_body(web.client), "mongo_timeout_ms": 300_000}
    with ThreadPoolExecutor(count) as pool:
        futures = [pool.submit(web.client.post, STORAGE_TEST, json=body) for _ in range(count)]
        try:
            for _ in range(holders):
                assert gate.entered.acquire(timeout=PATIENCE_S)
            refused = as_completed(futures, timeout=PATIENCE_S)
            early = [f.result() for f in itertools.islice(refused, count - holders)]
        finally:
            gate.release.set()
        return Outcome(early, [f.result(timeout=PATIENCE_S) for f in futures])


def test_the_bound_is_the_size_of_the_slots_of_one_mongo_connection() -> None:
    assert MAX_STORAGE_PROBES == MAX_CONCURRENT_PER_CONNECTION == 4


@pytest.mark.parametrize("count", [1, 3, 4, 5, 6, 10])
def test_at_most_the_bound_run_at_once_and_the_rest_are_a_503_busy(
    web: WebApp, gate: Gate, count: int
) -> None:
    outcome = run_probes(web, gate, count)
    refused = max(0, count - MAX_STORAGE_PROBES)
    assert gate.peak == min(count, MAX_STORAGE_PROBES)
    assert [r.status_code for r in outcome.early] == [503] * refused
    assert [error_of(r) for r in outcome.early] == [BUSY] * refused
    assert (
        sorted(r.status_code for r in outcome.final) == [200] * (count - refused) + [503] * refused
    )
    assert all(r.json() == {"ok": True} for r in outcome.final if r.status_code == 200)


def test_a_failed_probe_gives_its_slot_back(web: WebApp, monkeypatch: pytest.MonkeyPatch) -> None:
    break_ping(monkeypatch, web)
    body = {**put_body(web.client), "storage_backend": "mongo", "storage_connection": "test"}
    answers = [web.client.post(STORAGE_TEST, json=body) for _ in range(MAX_STORAGE_PROBES + 2)]
    assert [r.status_code for r in answers] == [503] * (MAX_STORAGE_PROBES + 2)
    assert {error_of(r)["code"] for r in answers} == {"storage_error"}


def test_a_candidate_that_fails_validation_takes_no_slot(web: WebApp) -> None:
    with ExitStack() as held:
        for _ in range(MAX_STORAGE_PROBES):
            held.enter_context(storage_probe_slot(SHORT_WAIT_MS))
        invalid = web.client.post(STORAGE_TEST, json={**put_body(web.client), "max_upload_mb": 0})
        assert invalid.status_code == 422
        assert error_of(invalid)["code"] == "validation_error"
        valid = web.client.post(STORAGE_TEST, json=put_body(web.client))
        assert valid.status_code == 503
        assert error_of(valid) == BUSY
    assert web.client.post(STORAGE_TEST, json=put_body(web.client)).status_code == 200


def test_a_refused_probe_never_reaches_the_storage(web: WebApp, gate: Gate) -> None:
    with ExitStack() as held:
        for _ in range(MAX_STORAGE_PROBES):
            held.enter_context(storage_probe_slot(SHORT_WAIT_MS))
        assert web.client.post(STORAGE_TEST, json=put_body(web.client)).status_code == 503
    assert gate.peak == 0


# --------------------------------------------------------------------------- the slot itself


def test_the_slot_context_hands_out_the_bound_and_then_refuses() -> None:
    with ExitStack() as held:
        for _ in range(MAX_STORAGE_PROBES):
            held.enter_context(storage_probe_slot(SHORT_WAIT_MS))
        with pytest.raises(BusyError) as info, storage_probe_slot(SHORT_WAIT_MS):
            pytest.fail("a fifth probe must not get a slot")
        assert (info.value.status_code, info.value.code) == (503, "busy")
        assert info.value.message == MSG_PROBES_BUSY
    with storage_probe_slot(SHORT_WAIT_MS):
        pass  # everything was handed back


def test_an_exception_inside_the_slot_releases_it() -> None:
    for _ in range(MAX_STORAGE_PROBES + 1):
        with pytest.raises(ZeroDivisionError), storage_probe_slot(SHORT_WAIT_MS):
            _ = 1 / 0


class Recorder:
    """Stands in for the semaphore: records the wait it was asked for and the releases."""

    def __init__(self, grant: bool) -> None:
        self.grant = grant
        self.timeouts: list[float] = []
        self.released = 0

    def acquire(self, timeout: float) -> bool:
        self.timeouts.append(timeout)
        return self.grant

    def release(self) -> None:
        self.released += 1


@pytest.mark.parametrize(("wait_ms", "seconds"), [(500, 0.5), (1500, 1.5), (15_000, 15.0)])
def test_the_wait_is_given_in_milliseconds(
    monkeypatch: pytest.MonkeyPatch, wait_ms: int, seconds: float
) -> None:
    recorder = Recorder(grant=True)
    monkeypatch.setattr(settings_module, "_PROBE_SLOTS", recorder)
    with storage_probe_slot(wait_ms):
        assert recorder.released == 0
    assert (recorder.timeouts, recorder.released) == ([seconds], 1)


def test_a_slot_that_was_not_granted_is_never_released(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder(grant=False)
    monkeypatch.setattr(settings_module, "_PROBE_SLOTS", recorder)
    with pytest.raises(BusyError), storage_probe_slot(SHORT_WAIT_MS):
        pytest.fail("not granted")
    assert (recorder.timeouts, recorder.released) == ([0.5], 0)
