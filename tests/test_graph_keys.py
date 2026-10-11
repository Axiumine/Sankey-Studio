"""``build_graph`` entry keys: three ids packed into one Python int, no collisions."""

from __future__ import annotations

import itertools

import pytest

from sankey_studio.graph.intern import (
    FIELD_BITS,
    FIELD_MASK,
    SOURCE_SHIFT,
    TARGET_SHIFT,
    pack_key,
    unpack_key,
)

NEAR = [0, 1, 2**20 - 1, 2**20, 2**20 + 1, 2**21 - 1, 2**21, 2**21 + 1, 2**32 - 1]


def test_layout_constants() -> None:
    assert FIELD_BITS == 32
    assert FIELD_MASK == 2**32 - 1
    assert SOURCE_SHIFT == 64
    assert TARGET_SHIFT == 32


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        ((0, 0, 0), 0),
        ((0, 0, 1), 1),
        ((0, 1, 0), 2**32),
        ((1, 0, 0), 2**64),
        ((1, 1, 1), 2**64 + 2**32 + 1),
        ((2**32 - 1, 2**32 - 1, 2**32 - 1), 2**96 - 1),
    ],
)
def test_pack_key_layout(ids: tuple[int, int, int], expected: int) -> None:
    assert pack_key(*ids) == expected
    assert unpack_key(expected) == ids


def test_keys_around_two_pow_20_and_21_are_unique_and_round_trip() -> None:
    seen: dict[int, tuple[int, int, int]] = {}
    for source, target, category in itertools.product(NEAR, NEAR, NEAR):
        ids = (source, target, category)
        key = pack_key(source, target, category)
        assert key not in seen
        seen[key] = ids
        assert unpack_key(key) == ids
    assert len(seen) == len(NEAR) ** 3
