# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``GraphPage``, the body of ``GET /api/v1/graphs``: a closed model of exactly four fields."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sankey_studio.web.routers.graphs import GraphPage

PAGE = {"items": [], "total": 7, "limit": 5, "offset": 2}


def test_a_graph_page_holds_its_four_fields() -> None:
    page = GraphPage.model_validate(PAGE)
    assert page.model_dump() == PAGE


def test_a_graph_page_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted") as raised:
        GraphPage.model_validate({**PAGE, "next": 9})
    assert [error["loc"] for error in raised.value.errors()] == [("next",)]


@pytest.mark.parametrize("missing", sorted(PAGE))
def test_a_graph_page_needs_every_field(missing: str) -> None:
    body = {key: value for key, value in PAGE.items() if key != missing}
    with pytest.raises(ValidationError, match="Field required") as raised:
        GraphPage.model_validate(body)
    assert [error["loc"] for error in raised.value.errors()] == [(missing,)]
