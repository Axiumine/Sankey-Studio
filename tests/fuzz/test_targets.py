# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The fuzz targets stay runnable in the normal test run (no fuzzing engine is needed).

The fuzzing itself happens in ClusterFuzzLite. These tests keep the targets, their seeds and their
entry points from rotting in between: every seed runs clean, mutated seeds and random bytes raise
nothing but the errors the targets expect, and every target has an Atheris entry point.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from tests.fuzz.targets import TARGETS

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
ROUNDS = 400
TOKENS = (b'"', b"$", b"[", b"]", b"\n", b"\t", b",", b"\xff", b"\x00", b"1e", b"-", b"%", b"{")
SETUP = re.compile(r"atheris\.Setup\(sys\.argv, (\w+)\)")
IMPORT = re.compile(r"^import atheris$", re.MULTILINE)


def seeds_of(name: str) -> list[Path]:
    return sorted((CORPUS / name).iterdir())


SEEDS = [(name, path) for name in sorted(TARGETS) for path in seeds_of(name)]


def mutate(rng: random.Random, data: bytes) -> bytes:
    """One to four edits of ``data``: a byte replaced, a byte deleted or a token inserted."""
    out = bytearray(data)
    for _ in range(rng.randrange(1, 5)):
        at = rng.randrange(len(out) + 1)
        kind = rng.randrange(3)
        if kind == 0 and out:
            out[min(at, len(out) - 1)] = rng.randrange(256)
        elif kind == 1 and out:
            del out[min(at, len(out) - 1)]
        else:
            out[at:at] = rng.choice(TOKENS)
    return bytes(out)


@pytest.mark.parametrize(("name", "seed"), SEEDS, ids=[f"{n}/{p.name}" for n, p in SEEDS])
def test_a_seed_runs_clean(name: str, seed: Path) -> None:
    TARGETS[name](seed.read_bytes())


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_mutated_seeds_and_random_bytes_raise_nothing_unexpected(name: str) -> None:
    rng = random.Random(name)
    seeds = [path.read_bytes() for path in seeds_of(name)]
    for _ in range(ROUNDS):
        TARGETS[name](mutate(rng, rng.choice(seeds)))
        TARGETS[name](rng.randbytes(rng.randrange(0, 160)))


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_every_target_has_an_atheris_entry_point(name: str) -> None:
    source = (HERE / f"{name}_fuzzer.py").read_text(encoding="utf-8")
    setup = SETUP.search(source)
    assert setup is not None
    assert setup[1] == TARGETS[name].__name__
    assert "instrument_imports" in source


def test_only_the_entry_points_import_atheris() -> None:
    sources = {path.name: path.read_text(encoding="utf-8") for path in HERE.glob("*.py")}
    importers = {name for name, source in sources.items() if IMPORT.search(source)}
    assert importers == {f"{name}_fuzzer.py" for name in TARGETS}
