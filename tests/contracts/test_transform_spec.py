"""Contract tests: ``TransformSpec`` bounds and the strict request models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sankey_studio.models import GraphCreate, StyleSpec, TransformSpec


def test_transform_node_maps_are_bounded_and_non_empty() -> None:
    with pytest.raises(ValidationError):
        TransformSpec(merge_nodes={"A": ""})
    with pytest.raises(ValidationError):
        TransformSpec(merge_nodes={"": "A"})
    with pytest.raises(ValidationError):
        TransformSpec(hide_nodes=[""])
    with pytest.raises(ValidationError):
        TransformSpec(merge_nodes={f"a{i}": "x" for i in range(5001)})
    assert TransformSpec(merge_nodes={" A ": " B "}).merge_nodes == {"A": "B"}


def test_top_links_replaces_ambiguous_max_links() -> None:
    assert TransformSpec().top_links is None
    assert TransformSpec(top_links=10).top_links == 10
    with pytest.raises(ValidationError):  # the old name must not silently survive
        TransformSpec.model_validate({"max_links": 10})


def test_requests_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GraphCreate.model_validate({"name": "n", "source": {"type": "manual"}, "bogus": 1})
    with pytest.raises(ValidationError):
        StyleSpec.model_validate({"colour_mode": "node"})
