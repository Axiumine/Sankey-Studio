# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Shards of the e2e suite: ``E2E_SHARD=<n>/<count> pytest ...`` runs one slice of it.

``make e2e`` starts ``count`` pytest processes, one per shard, at the same time. The suite spends
its time waiting (real Chrome, HTTP round trips, one server per module on its own ephemeral
port), so the shards share the machine without getting in each other's way.

* A shard owns whole modules: the module-scoped servers (``module_make_server``) are started once,
  by the one shard that runs the module.
* Every shard computes the same assignment from the same collection (no coordination, no file),
  so every test runs in exactly one shard (``tests/e2e/test_harness_shard.py`` proves it).
* Modules are dealt out biggest first, each to the shard that is lightest so far. A test that
  drives a browser or exports with Chrome weighs ``HEAVY``, any other test ``LIGHT``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

SHARD_ENV: Final = "E2E_SHARD"
HEAVY: Final = 8
LIGHT: Final = 1
BROWSER_FIXTURES: Final = frozenset({"page", "open_page"})
_SPEC: Final = re.compile(r"([1-9][0-9]*)/([1-9][0-9]*)")


class Shardable(Protocol):
    """What a pytest item must offer: the file it lives in, its fixtures and its marks."""

    @property
    def path(self) -> Path: ...

    @property
    def fixturenames(self) -> list[str]: ...

    def get_closest_marker(self, name: str) -> object | None: ...


@dataclass(frozen=True, slots=True)
class Shard:
    """Shard ``number`` (1-based) of ``count``."""

    number: int
    count: int


def parse_shard(value: str) -> Shard:
    """Read ``"2/5"``; anything else (``"0/5"``, ``"6/5"``, ``"x"``) is a ``ValueError``."""
    found = _SPEC.fullmatch(value.strip())
    if found is None or int(found[1]) > int(found[2]):
        raise ValueError(f"{SHARD_ENV} must look like '2/5' (shard 2 of 5), got {value!r}")
    return Shard(int(found[1]), int(found[2]))


def weight_of(item: Shardable) -> int:
    """Rough cost of one test: browser and Chrome-export tests take seconds, the rest do not."""
    if any(item.get_closest_marker(name) is not None for name in ("mongo", "mongo_rs")):
        return 0  # left out of `make e2e` anyway
    browser = BROWSER_FIXTURES.intersection(item.fixturenames)
    return HEAVY if browser or item.get_closest_marker("slow") is not None else LIGHT


def module_owners(items: Iterable[Shardable], count: int) -> Mapping[Path, int]:
    """Module -> shard number (1-based): biggest module first, to the lightest shard."""
    weights: dict[Path, int] = defaultdict(int)
    for item in items:
        weights[item.path] += weight_of(item)
    loads = [0] * count
    owners: dict[Path, int] = {}
    for path, weight in sorted(weights.items(), key=lambda pair: (-pair[1], str(pair[0]))):
        lightest = min(range(count), key=lambda index: (loads[index], index))
        loads[lightest] += weight
        owners[path] = lightest + 1
    return owners


def split_items[T: Shardable](items: Sequence[T], shard: Shard) -> tuple[list[T], list[T]]:
    """``(kept, dropped)``: the tests of ``shard`` and all the others, each in collection order."""
    owners = module_owners(items, shard.count)
    kept = [item for item in items if owners[item.path] == shard.number]
    dropped = [item for item in items if owners[item.path] != shard.number]
    return kept, dropped
