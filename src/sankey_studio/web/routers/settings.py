"""Settings routes (prefix ``/api/v1/settings``).

* ``GET ""`` -> ``SettingsOut``: masked connection URIs and ``has_secret``, never a field called
  ``uri``; the read-only ``bootstrap`` block; in remote read-only mode the connection hosts and
  user names are hidden too.
* ``PUT ""?migrate=false`` with a ``SettingsIn`` body -> ``SettingsSaved`` (``settings`` as saved
  and ``copy_report`` or ``null``). A connection that sends no URI (or the masked one it was
  given) keeps its stored secret (``merge_settings``). ``migrate=true`` copies the saved graphs
  when the storage target changes; ``copy_report.unreadable`` counts the graphs that could not be
  copied and ``unreadable_ids`` names the first 50.
* ``POST /storage/test`` with a ``SettingsIn`` body -> ``{"ok": true}``: pings the storage target
  of that candidate without saving anything. ``POST /mongo/{name}/test`` -> ``{"ok": true,
  "latency_ms": ...}``: pings the stored connection ``name``. A failing probe is the usual error
  envelope (``storage_error`` 503 for an unreachable server, ``source_not_found`` 404 for an
  unknown connection name).

Every unsafe route here is a ``GuardedRoute`` (the router's ``route_class``): in remote mode
without ``--allow-remote-writes`` they answer 403 ``read_only_mode`` before FastAPI decodes the
body, so even an undecodable body is a 403 (the probes connect to URIs a caller supplies, so they
count as privileged). The handlers are plain ``def``: they do file and network I/O, which
Starlette runs in its worker thread pool.

Concurrency: ``PUT`` reads, merges, validates and saves inside ``services.settings_transaction()``
(one lock), so two saves never merge against the same stale snapshot and no rotated secret is
lost. ``POST /storage/test`` takes no settings lock (it saves nothing) but at most
``MAX_STORAGE_PROBES`` run at once in the whole process, like the slots of one Mongo connection:
another one waits up to ``mongo_timeout_ms`` and then answers 503 ``busy``. The Mongo probe uses
the connection's own slot and never needs the sources directory.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from sankey_studio.errors import BusyError
from sankey_studio.mongo import MAX_CONCURRENT_PER_CONNECTION
from sankey_studio.sources.mongo_source import require_connection
from sankey_studio.web.deps import ConfigDep, GuardedRoute, MongoContextDep, ServicesDep
from sankey_studio.web.schemas import (
    SettingsIn,
    SettingsOut,
    SettingsSaved,
    merge_settings,
    settings_out,
    settings_saved,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["MongoProbeOk", "ProbeOk", "router"]

router = APIRouter(prefix="/api/v1/settings", tags=["settings"], route_class=GuardedRoute)

#: Decimals kept of a measured round trip (a probe is not a benchmark).
LATENCY_DECIMALS = 1
#: Storage probes running at once, process-wide (a candidate can point anywhere, so there is no
#: connection to hang the bound on): the size of the slots of one Mongo connection.
MAX_STORAGE_PROBES = MAX_CONCURRENT_PER_CONNECTION
MSG_PROBES_BUSY = "Too many storage probes are running; try again shortly"
_PROBE_SLOTS = threading.BoundedSemaphore(MAX_STORAGE_PROBES)


class ProbeOk(BaseModel):
    """A probe that worked (a failing one is an error envelope instead)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True


class MongoProbeOk(ProbeOk):
    """A Mongo ``ping`` that worked, with its round trip in milliseconds."""

    latency_ms: float


@router.get("")
def read_settings(services: ServicesDep, config: ConfigDep) -> SettingsOut:
    return settings_out(services.settings(), config)


@contextmanager
def storage_probe_slot(wait_ms: int) -> Iterator[None]:
    """Hold one of ``MAX_STORAGE_PROBES`` slots; ``BusyError`` (503) after ``wait_ms``."""
    if not _PROBE_SLOTS.acquire(timeout=wait_ms / 1000):
        raise BusyError(MSG_PROBES_BUSY)
    try:
        yield
    finally:
        _PROBE_SLOTS.release()


@router.put("")
def save_settings(
    body: SettingsIn, services: ServicesDep, config: ConfigDep, migrate: bool = False
) -> SettingsSaved:
    with services.settings_transaction():  # the merge must read the latest stored settings
        merged = merge_settings(services.settings(), body)
        saved = services.update_settings(merged, migrate=migrate)
    return settings_saved(saved, config)


@router.post("/storage/test")
def probe_storage(body: SettingsIn, services: ServicesDep) -> ProbeOk:
    stored = services.settings()
    candidate = merge_settings(stored, body)  # invalid candidates fail before a slot is taken
    with storage_probe_slot(stored.mongo_timeout_ms):
        services.test_storage(candidate)
    return ProbeOk()


@router.post("/mongo/{name}/test")
def probe_mongo(name: str, ctx: MongoContextDep) -> MongoProbeOk:
    require_connection(ctx, name)  # no slot for a made-up name
    with ctx.mongo.slot(name):
        latency_ms = ctx.mongo.ping(name)
    return MongoProbeOk(latency_ms=round(latency_ms, LATENCY_DECIMALS))
