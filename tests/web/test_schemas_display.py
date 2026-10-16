# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``styled``: the label switches of a render or export query applied to a saved style."""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest
from pydantic import ValidationError

from sankey_studio.models import StyleSpec
from sankey_studio.web.schemas import ExportQuery, RenderQuery
from tests.web.test_schemas_support import digest

Model = type[RenderQuery | ExportQuery]
MODELS: list[Model] = [RenderQuery, ExportQuery]
ALL_ON = {"show_values_in_labels": True, "donut": {"show_percent": True, "show_value": True}}
ALL_OFF = {"show_values_in_labels": False, "donut": {"show_percent": False, "show_value": False}}


class Pick(NamedTuple):
    """What the query chooses, the saved style, and the result as (labels, percent, value)."""

    query: dict[str, bool]
    saved: dict[str, Any]
    result: tuple[bool, bool, bool]


PICKS = [
    # each switch alone, over the defaults (labels off, percent on, value off)
    Pick({"node_values": True}, {}, (True, True, False)),
    Pick({"node_values": False}, {}, (False, True, False)),
    Pick({"donut_percent": False}, {}, (False, False, False)),
    Pick({"donut_percent": True}, {}, (False, True, False)),
    Pick({"donut_value": True}, {}, (False, True, True)),
    Pick({"donut_value": False}, {}, (False, True, False)),
    # all three at once
    Pick(
        {"node_values": True, "donut_percent": False, "donut_value": True}, {}, (True, False, True)
    ),
    Pick({"node_values": True, "donut_percent": True, "donut_value": True}, {}, (True, True, True)),
    # False overrides a saved True, one switch at a time
    Pick({"node_values": False}, ALL_ON, (False, True, True)),
    Pick({"donut_percent": False}, ALL_ON, (True, False, True)),
    Pick({"donut_value": False}, ALL_ON, (True, True, False)),
    Pick(
        {"node_values": False, "donut_percent": False, "donut_value": False},
        ALL_ON,
        (False, False, False),
    ),
    # True overrides a saved False
    Pick(
        {"node_values": True, "donut_percent": True, "donut_value": True},
        ALL_OFF,
        (True, True, True),
    ),
    # a switch that is not chosen keeps what the saved style says
    Pick({"node_values": True}, ALL_OFF, (True, False, False)),
    Pick({"donut_value": True}, ALL_OFF, (False, False, True)),
]


def flags(style: StyleSpec) -> tuple[bool, bool, bool]:
    return (style.show_values_in_labels, style.donut.show_percent, style.donut.show_value)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("case", PICKS, ids=repr)
def test_the_chosen_switches_win_and_the_others_keep_the_saved_style(
    model: Model, case: Pick
) -> None:
    saved = StyleSpec.model_validate(case.saved)
    assert flags(model.model_validate(case.query).styled(saved)) == case.result


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("saved", [{}, ALL_ON, ALL_OFF, {"title": "T", "donut": {"hole": 0.4}}])
def test_nothing_chosen_returns_the_very_same_style(model: Model, saved: dict[str, Any]) -> None:
    style = StyleSpec.model_validate(saved)
    assert model().styled(style) is style


def test_a_query_without_switches_but_with_other_parameters_changes_nothing() -> None:
    style = StyleSpec()
    assert RenderQuery(theme="dark").styled(style) is style
    assert ExportQuery(chart="donut", format="json", theme="dark", width=640).styled(style) is style


@pytest.mark.parametrize("model", MODELS)
def test_choosing_what_is_already_saved_gives_an_equal_style(model: Model) -> None:
    style = StyleSpec.model_validate(ALL_ON)
    result = model(node_values=True, donut_percent=True, donut_value=True).styled(style)
    assert result == style
    assert result is not style


def test_every_other_field_of_the_style_is_kept() -> None:
    saved = StyleSpec.model_validate(
        {
            "title": "Budget",
            "orientation": "v",
            "color_mode": "mono",
            "mono_color": "#336699",
            "node_colors": {"Salary": "#aa0000"},
            "category_colors": {"Income": "#00aa00"},
            "value_format": ",.1f",
            "value_suffix": "USD",
            "font_size": 20,
            "donut": {"basis": "initial", "max_slices": 3, "hole": 0.4, "sort": "name"},
        }
    )
    query = RenderQuery(node_values=True, donut_percent=False, donut_value=True)
    result = query.styled(saved)
    expected = saved.model_dump()
    expected["show_values_in_labels"] = True
    expected["donut"] = {**expected["donut"], "show_percent": False, "show_value": True}
    assert result.model_dump() == expected


def test_the_saved_style_is_never_changed() -> None:
    saved = StyleSpec()
    result = RenderQuery(node_values=True, donut_percent=False, donut_value=True).styled(saved)
    assert result is not saved
    assert flags(saved) == (False, True, False)
    assert saved == StyleSpec()
    assert flags(result) == (True, False, True)


def test_the_result_is_a_validated_style() -> None:
    result = ExportQuery(donut_value=True).styled(StyleSpec())
    assert isinstance(result, StyleSpec)
    assert StyleSpec.model_validate(result.model_dump()) == result


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("name", ["node_values", "donut_percent", "donut_value"])
def test_a_switch_that_is_not_a_boolean_is_refused(model: Model, name: str) -> None:
    with pytest.raises(ValidationError) as caught:
        model.model_validate({name: "perhaps"})
    assert digest(caught) == [((name,), "bool_parsing")]


@pytest.mark.parametrize("model", MODELS)
def test_an_unknown_switch_is_refused(model: Model) -> None:
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"donut_labels": True})
    assert digest(caught) == [(("donut_labels",), "extra_forbidden")]
