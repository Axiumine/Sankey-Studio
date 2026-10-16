# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Location labels of model-level errors in bundle import."""

from __future__ import annotations

from typing import NoReturn

import pytest
from pydantic import ValidationError

from sankey_studio.storage import bundle
from sankey_studio.storage.bundle import GRAPH_ROOT, _ItemError, _parse


class _Refusing:
    """``GraphDefinition`` stand-in whose validation fails with a model-level error."""

    @staticmethod
    def model_validate(_doc: object) -> NoReturn:
        raise ValidationError.from_exception_data(
            "GraphDefinition",
            [{"type": "value_error", "loc": (), "input": {}, "ctx": {"error": ValueError("boom")}}],
        )


def test_an_error_without_a_location_is_labelled_with_the_graph_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bundle, "GraphDefinition", _Refusing)
    with pytest.raises(_ItemError) as info:
        _parse({"name": "x"})
    assert GRAPH_ROOT == "graph"
    assert str(info.value) == "graph: Value error, boom"
