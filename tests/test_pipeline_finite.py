# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``_require_finite_totals``: which graphs are refused and how the error reads."""

from __future__ import annotations

import pytest

from sankey_studio import pipeline
from sankey_studio.errors import GraphBuildError
from tests.graph_support import make_graph

MESSAGE = "The flow sums are too large to draw: they exceed the float range."


def test_a_graph_whose_sum_overflows_in_the_middle_of_the_addition_is_refused() -> None:
    graph = make_graph([("a", "b", 1e308, None), ("c", "d", 1e308, None)])
    with pytest.raises(GraphBuildError) as caught:
        pipeline._require_finite_totals(graph)
    assert caught.value.message == MESSAGE
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_a_graph_with_an_infinite_value_is_refused_with_the_same_message() -> None:
    graph = make_graph([("a", "b", float("inf"), None)])
    with pytest.raises(GraphBuildError) as caught:
        pipeline._require_finite_totals(graph)
    assert caught.value.message == MESSAGE


def test_the_largest_sum_that_fits_is_accepted() -> None:
    half = 8.988465674311579e307
    pipeline._require_finite_totals(make_graph([("a", "b", half, None), ("c", "d", half, None)]))
