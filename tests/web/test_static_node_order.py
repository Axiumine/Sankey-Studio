"""The node order of the chart (F4), run with node on the shipped files (no browser).

Pure functions of ``editor/chart/node-order.js`` (a drag becomes an order: swap in a column, other
columns untouched, ties, bad numbers, the drawn columns), the pointer logic of
``core/chart-nodes.js`` (a plain click is not a drag, a drag is forwarded once, the click Plotly
swallows comes back), and the glue of ``editor/chart/node-actions.js`` and ``order-dialog.js``.
The pages are checked in a real browser by ``tests/e2e/ui/test_chart_node_drag_ui.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

JS: Final = STATIC_DIR / "js"
HERE: Final = Path(__file__).parent
NODE: Final = shutil.which("node")
HEAD: Final = "const dir = process.argv[2];\nconst out = {};\n"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run_scenarios(folder: Path, *names: str) -> dict[str, Any]:
    """Run the ``.mjs`` scenario files ``names`` (they fill ``out``) and return ``out``."""
    assert NODE is not None
    script = folder / "run.mjs"
    body = "\n".join((HERE / name).read_text() for name in names)
    script.write_text(f"{HEAD}{body}\nprocess.stdout.write(JSON.stringify(out));\n")
    done = subprocess.run(  # noqa: S603 - fixed argv: node on a temp script and the shipped files
        [NODE, str(script), str(JS)], capture_output=True, text=True, check=False, timeout=60
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


@pytest.fixture(scope="module")
def pure(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_scenarios(tmp_path_factory.mktemp("node-order"), "static_node_order_pure.mjs")


def test_a_dragged_node_swaps_inside_its_column_and_nothing_else_moves(
    pure: dict[str, Any],
) -> None:
    assert pure["swap"] == ["b", "a", "e", "d", "c", "f"]
    assert pure["keep"] == ["a", "b", "c", "d", "e", "f"]


def test_a_tie_keeps_the_order_of_the_figure_and_layers_stay_ascending(
    pure: dict[str, Any],
) -> None:
    assert pure["ties"] == ["a", "b", "c", "d", "e", "f"]
    assert pure["layersAscending"] == ["y", "z", "x"]


def test_only_the_order_of_the_numbers_counts(pure: dict[str, Any]) -> None:
    # vertical bars scale by the wrong side (values above 1); zero and negative are numbers too
    assert pure["beyondOne"] == ["q", "p"]
    assert pure["negative"] == ["q", "p"]
    assert pure["zero"] == ["p", "q"]


def test_numbers_that_cannot_be_trusted_give_no_order(pure: dict[str, Any]) -> None:
    assert pure["refused"] == dict.fromkeys(
        ("short", "long", "nan", "infinite", "text", "nothing", "noNodes", "noCoords")
    )


def test_the_position_across_a_column_is_y_for_both_orientations(pure: dict[str, Any]) -> None:
    assert pure["axis"] == ["y", "y", "y"]


def test_the_drawn_order_groups_by_column_and_compares_by_position(pure: dict[str, Any]) -> None:
    assert pure["current"] == ["a", "d", "b", "c"]
    assert pure["layers"] == [
        {"layer": 0, "names": ["a"]},
        {"layer": 1, "names": ["b", "c"]},
    ]
    assert pure["names"] == ["b", "a"]
    assert pure["same"] == [True, False, False, True]


def test_a_node_without_an_outgoing_link_is_drawn_in_the_last_column(pure: dict[str, Any]) -> None:
    assert pure["visual"] == [
        {"name": "Salary", "layer": 0},
        {"name": "Budget", "layer": 1},
        {"name": "Rent", "layer": 3},
        {"name": "Food", "layer": 2},
        {"name": "Groceries", "layer": 3},
    ]
    assert pure["visualEmpty"] == [[], [], [{"name": "a", "layer": 0}]]


def test_bars_can_be_told_apart_and_moved_only_with_one_row_per_label(
    pure: dict[str, Any],
) -> None:
    assert pure["aligned"] == [True, False, False, False, False, False]
    assert pure["reorderable"] == [True, True, False, True, False]


@pytest.fixture(scope="module")
def events(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_scenarios(tmp_path_factory.mktemp("node-events"), "static_node_events.mjs")


def info(index: int, *, has_in: bool, has_out: bool, at: tuple[Any, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "hasIn": has_in,
        "hasOut": has_out,
        "clientX": at[0],
        "clientY": at[1],
    }


def test_a_plain_click_is_a_click_and_not_a_drag(events: dict[str, Any]) -> None:
    plain = events["plain"]
    assert plain["moves"] == []
    assert plain["clicks"] == [info(1, has_in=True, has_out=True, at=(101, 102))]


def test_a_drag_is_forwarded_once_after_the_release_and_is_not_a_click(
    events: dict[str, Any],
) -> None:
    drag = events["drag"]
    assert drag["clicks"] == 0
    assert drag["moves"] == [{"xs": [0, 0.1, 0.2], "ys": [0, 0.2, 0.4]}]


def test_four_pixels_are_a_click_and_more_is_a_drag(events: dict[str, Any]) -> None:
    assert events["threshold"] == {"MOVE_PX": 4, "edge": [1, 0], "over": [0, 1]}


def test_a_payload_without_one_number_per_label_is_ignored(events: dict[str, Any]) -> None:
    mismatch = events["mismatch"]
    assert mismatch["refused"] == 0
    assert mismatch["moves"] == 1
    assert mismatch["forwarded"]["ys"] == [0, 0.2, 0.4]
    assert events["noLabels"] == 0


def test_a_press_on_a_bar_tells_the_chart_before_anything_moves(events: dict[str, Any]) -> None:
    assert events["start"] == [True, True]


def test_a_press_off_the_bars_or_with_another_button_arms_nothing(events: dict[str, Any]) -> None:
    assert events["unarmed"] == {"moves": 0, "clicks": 0}


def test_plotlys_click_and_the_pointer_click_are_one_click_in_either_order(
    events: dict[str, Any],
) -> None:
    once = events["once"]
    assert [item["index"] for item in once["natural"]] == [2]
    assert [item["index"] for item in once["pointer"]] == [2]


def test_a_click_tells_the_index_the_flow_roles_and_the_pointer(events: dict[str, Any]) -> None:
    assert events["info"] == [
        info(1, has_in=True, has_out=False, at=(7, 8)),
        info(0, has_in=False, has_out=True, at=(7, 8)),
        info(2, has_in=False, has_out=True, at=(None, None)),
    ]


def test_links_empty_events_and_the_click_that_ends_a_drag_are_not_node_clicks(
    events: dict[str, Any],
) -> None:
    assert events["notClicks"] == 0
    assert events["forgotten"] == 0


def test_a_redraw_swaps_the_callbacks_and_never_stacks_listeners(events: dict[str, Any]) -> None:
    swap = events["swap"]
    assert swap["before"] == swap["after"] == [1, 1, 1, 1, 2]
    assert swap["log"] == ["new"]
    assert events["silent"] == "ok"


def test_detaching_stops_the_pointer_listeners_and_a_new_draw_attaches_again(
    events: dict[str, Any],
) -> None:
    detach = events["detach"]
    assert detach["attachedCount"] == 2
    assert detach["detached"] == [0, False]
    assert (detach["again"], detach["handlers"]) == (2, 2)
    assert events["cancel"] == 1


@pytest.fixture(scope="module")
def actions(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return run_scenarios(tmp_path_factory.mktemp("node-actions"), "static_node_actions.mjs")


def test_a_drag_becomes_an_order_of_the_drawn_columns(actions: dict[str, Any]) -> None:
    # Rent and Groceries share the last column: Groceries (0.1) now stands above Rent (0.9)
    assert actions["moved"] == [["Salary", "Budget", "Food", "Groceries", "Rent"]]
    assert actions["ignored"] == 0


def test_a_drag_is_compared_with_the_order_drawn_when_the_press_began(
    actions: dict[str, Any],
) -> None:
    full = ["Salary", "Budget", "Food", "Rent", "Groceries"]
    # dragged back into the array order: stored; dropped where it was: nothing
    assert actions["drawnBaseline"] == [full]
    assert actions["blind"] == 3


def test_only_aligned_bundles_can_be_clicked_and_only_free_bars_moved(
    actions: dict[str, Any],
) -> None:
    assert actions["capable"] == [
        ["function", "undefined", "undefined"],
        ["undefined", "undefined", "undefined"],
        ["undefined", "undefined", "undefined"],
        ["function", "function", "function"],
    ]
    assert actions["same"] is True


def test_the_click_hook_is_quiet_without_an_edit_engine_and_passes_the_node_row(
    actions: dict[str, Any],
) -> None:
    click = actions["click"]
    assert (click["quiet"], click["hook"]) == (None, None)
    assert click["heard"][0] == [
        5,
        {
            "index": 2,
            "hasIn": True,
            "hasOut": False,
            "clientX": 1,
            "clientY": 2,
            "node": {
                "name": "Rent",
                "layer": 2,
                "node_in": 0,
                "node_out": 0,
            },
        },
    ]
    assert click["heard"][1][1]["node"] is None


def test_the_wait_signal_lists_the_drawn_names_and_goes_away(actions: dict[str, Any]) -> None:
    assert actions["signal"] == {
        "set": "Salary|Budget|Rent|Food|Groceries",
        "cleared": False,
        "empty": False,
    }


def test_the_bars_are_read_from_the_drawing_across_their_column(actions: dict[str, Any]) -> None:
    coords = actions["coords"]
    assert coords["h"] == [120, 320, 25]
    assert coords["v"] == [20, 20, 60]
    # a bar without a known index or outside the list is skipped; a node left unread gives no answer
    assert (coords["missing"], coords["noRect"], coords["fractional"]) == (None, None, None)
    assert (coords["outside"], coords["unknown"], coords["negative"]) == ([0.5], [0.5], [0.5])


def test_the_dialog_lists_the_nodes_as_drawn_and_falls_back_to_the_figure_order(
    actions: dict[str, Any],
) -> None:
    columns = actions["columns"]
    assert columns["drawn"] == [
        {"layer": 0, "names": ["Salary"]},
        {"layer": 1, "names": ["Budget"]},
        {"layer": 2, "names": ["Food"]},
        {"layer": 3, "names": ["Groceries", "Rent"]},
    ]
    assert columns["blind"][3] == {"layer": 3, "names": ["Rent", "Groceries"]}
    assert columns["vertical"][3] == {"layer": 3, "names": ["Groceries", "Rent"]}
