"""``render_compare``: the shared category ranking spans EVERY card, in the same way for each."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sankey_studio.models import StyleSpec
from sankey_studio.pipeline import render_compare
from sankey_studio.render.palette import hue
from tests.test_pipeline_support import PipelineEnv, make_env, manual_draft

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pymongo import MongoClient

    from sankey_studio.bundle import RenderBundle


@pytest.fixture
def env(tmp_path: Path, mongo_client: MongoClient[Any]) -> Iterator[PipelineEnv]:
    with make_env(tmp_path, mongo_client) as value:
        yield value


def colors_of(bundle: RenderBundle) -> dict[str, str]:
    return {row.name: row.color for row in bundle.categories}


def test_a_category_that_only_a_later_card_has_still_ranks_over_all_cards(
    env: PipelineEnv,
) -> None:
    first = manual_draft(("a", "b", 2, "X"), ("a", "c", 1, "Y"))
    second = manual_draft(("a", "b", 10, "Y"))
    third = manual_draft(("a", "b", 50, "Z"))
    cards = render_compare(env.services, [first, second, third], "light")
    assert colors_of(cards[2]) == {"Z": hue("light", 0)}
    assert colors_of(cards[1]) == {"Y": hue("light", 1)}
    assert colors_of(cards[0]) == {"X": hue("light", 2), "Y": hue("light", 1)}


def test_the_overrides_of_the_first_card_win_over_those_of_the_others(env: PipelineEnv) -> None:
    first = manual_draft(("a", "b", 1, "X"), style=StyleSpec(category_colors={"X": "#111111"}))
    second = manual_draft(("a", "b", 1, "X"), style=StyleSpec(category_colors={"X": "#222222"}))
    cards = render_compare(env.services, [first, second], "light")
    assert colors_of(cards[0]) == {"X": "#111111"}
    assert colors_of(cards[1]) == {"X": "#111111"}
