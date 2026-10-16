"""Self-tests of the shards ``make e2e`` runs in parallel (``support.shard`` and its conftest hook).

The promise: every e2e test runs in exactly one shard, a shard owns whole modules (module-scoped
servers start once), and a wrong ``E2E_SHARD`` is refused loudly instead of running nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pytest

from tests.e2e.support.shard import (
    HEAVY,
    LIGHT,
    SHARD_ENV,
    Shard,
    module_owners,
    parse_shard,
    split_items,
    weight_of,
)

ROOT: Final = Path(__file__).resolve().parents[2]
COLLECT_TIMEOUT_S: Final = 120
SHARDS: Final = 3


@dataclass(frozen=True, slots=True)
class FakeItem:
    """The three things a shard looks at in a pytest item."""

    path: Path
    fixturenames: list[str] = field(default_factory=list)
    marks: frozenset[str] = frozenset()

    def get_closest_marker(self, name: str) -> object | None:
        return name if name in self.marks else None


def module(name: str, light: int = 0, heavy: int = 0) -> list[FakeItem]:
    path = Path(f"tests/e2e/{name}.py")
    return [FakeItem(path) for _ in range(light)] + [
        FakeItem(path, ["page", "live_server"]) for _ in range(heavy)
    ]


# ------------------------------------------------------------------------------ the spec


@pytest.mark.parametrize(("text", "expected"), [("1/1", Shard(1, 1)), (" 3/5 ", Shard(3, 5))])
def test_a_shard_is_read_as_number_slash_count(text: str, expected: Shard) -> None:
    assert parse_shard(text) == expected


@pytest.mark.parametrize("text", ["", "0/5", "6/5", "2", "2/0", "a/b", "1/2/3", "-1/5", "1.5/5"])
def test_a_malformed_shard_is_refused_with_the_expected_shape(text: str) -> None:
    with pytest.raises(ValueError, match=r"E2E_SHARD must look like '2/5'"):
        parse_shard(text)


# ------------------------------------------------------------------------------ the weights


def test_browser_and_slow_tests_weigh_more_than_plain_http_tests() -> None:
    assert weight_of(FakeItem(Path("a.py"))) == LIGHT
    assert weight_of(FakeItem(Path("a.py"), ["page"])) == HEAVY
    assert weight_of(FakeItem(Path("a.py"), ["open_page"])) == HEAVY
    assert weight_of(FakeItem(Path("a.py"), ["api"], frozenset({"slow"}))) == HEAVY
    assert weight_of(FakeItem(Path("a.py"), ["api"], frozenset({"mongo"}))) == 0
    assert weight_of(FakeItem(Path("a.py"), ["page"], frozenset({"mongo_rs"}))) == 0


# ------------------------------------------------------------------------------ the split


def sample_items() -> list[FakeItem]:
    return [
        *module("big_ui", heavy=12),
        *module("middle_ui", heavy=6),
        *module("api_a", light=30),
        *module("api_b", light=20),
        *module("small", light=2),
    ]


@pytest.mark.parametrize("count", [1, 2, 3, 5, 8])
def test_every_test_lands_in_exactly_one_shard(count: int) -> None:
    items = sample_items()
    seen: list[FakeItem] = []
    for number in range(1, count + 1):
        kept, dropped = split_items(items, Shard(number, count))
        assert len(kept) + len(dropped) == len(items)
        seen.extend(kept)
    assert sorted(seen, key=id) == sorted(items, key=id)


def test_a_shard_owns_whole_modules_in_collection_order() -> None:
    items = sample_items()
    for number in (1, 2, 3):
        kept, _ = split_items(items, Shard(number, 3))
        owned = {item.path for item in kept}
        assert [item for item in items if item.path in owned] == kept
        others = [split_items(items, Shard(other, 3))[0] for other in (1, 2, 3) if other != number]
        assert all(owned.isdisjoint({item.path for item in group}) for group in others)


def test_the_biggest_modules_go_to_different_shards() -> None:
    owners = module_owners(sample_items(), 3)
    big, middle, api_a = (Path(f"tests/e2e/{name}.py") for name in ("big_ui", "middle_ui", "api_a"))
    assert len({owners[big], owners[middle], owners[api_a]}) == 3


def test_the_assignment_does_not_depend_on_the_collection_order() -> None:
    items = sample_items()
    assert module_owners(items, 4) == module_owners(list(reversed(items)), 4)


def test_more_shards_than_modules_leave_some_shards_empty_without_failing() -> None:
    items = module("only", light=3)
    sizes = [len(split_items(items, Shard(number, 4))[0]) for number in range(1, 5)]
    assert sorted(sizes) == [0, 0, 0, 3]


# ------------------------------------------------------------------------------ the real suite


def collect(shard: str | None) -> subprocess.Popen[str]:
    env = {key: value for key, value in os.environ.items() if key != SHARD_ENV}
    if shard is not None:
        env[SHARD_ENV] = shard
    command = [sys.executable, "-m", "pytest", "tests/e2e", "--collect-only", "-q", "-m"]
    command += ["e2e and not mongo and not mongo_rs", "-p", "no:cacheprovider"]
    return subprocess.Popen(  # noqa: S603 - a fixed argv of this interpreter, no shell
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )


def node_ids(process: subprocess.Popen[str]) -> list[str]:
    output, _ = process.communicate(timeout=COLLECT_TIMEOUT_S)
    assert process.returncode == 0, output
    return [line for line in output.splitlines() if line.startswith("tests/e2e/") and "::" in line]


def test_the_shards_of_the_real_suite_together_hold_each_test_exactly_once() -> None:
    processes = [collect(f"{number}/{SHARDS}") for number in range(1, SHARDS + 1)]
    everything = collect(None)
    per_shard = [node_ids(process) for process in processes]
    whole = node_ids(everything)
    joined = [node for ids in per_shard for node in ids]
    assert len(whole) > 100
    assert sorted(joined) == sorted(whole)
    assert len(set(joined)) == len(joined)
    assert all(per_shard), "a shard of the real suite is empty"


def test_a_bad_shard_value_stops_the_session_with_a_usage_error() -> None:
    process = collect("9/3")
    output, _ = process.communicate(timeout=COLLECT_TIMEOUT_S)
    assert process.returncode != 0
    assert "E2E_SHARD must look like '2/5'" in output, output
