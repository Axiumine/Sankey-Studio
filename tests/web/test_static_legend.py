"""``withoutLegend`` of ``core/chart.js`` on real server figures, run with node on the shipped file.

The viewer and the editor list the legend entries as HTML under the chart, so they draw the Sankey
without the legend row the server puts in the figure. The client does not know the server's numbers:
these tests feed it real figures and compare the result with what the server draws without a legend
(the margin of ``margin(style, legend=False)``, a Sankey domain up to 1).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.render.donut import build_donut_figure
from sankey_studio.render.layout import margin
from sankey_studio.render.sankey import build_figure
from sankey_studio.web.app import STATIC_DIR
from tests.render.support import budget, style

if TYPE_CHECKING:
    from pathlib import Path

NODE: Final = shutil.which("node")

SCRIPT: Final = """
import { readFileSync } from "node:fs";
const [, , dir, file] = process.argv;
const chart = await import(`${dir}/core/chart.js`);
const figures = JSON.parse(readFileSync(file, "utf8"));
const out = {};
for (const [key, figure] of Object.entries(figures)) {
  const before = JSON.stringify(figure);
  const result = chart.withoutLegend(figure);
  out[key] = {
    result: result === figure ? null : result,
    same: result === figure,
    untouched: JSON.stringify(figure) === before,
  };
}
out.bare = chart.withoutLegend({ data: [{ type: "sankey" }], layout: { showlegend: true } });
out.empty = chart.withoutLegend({});
console.log(JSON.stringify(out));
"""


def _figures() -> dict[str, Any]:
    category = style(color_mode="category")
    return {
        "category": build_figure(budget(), category, "light"),
        "titled": build_figure(budget(), style(color_mode="layer", title="Budget"), "dark"),
        "node": build_figure(budget(), style(color_mode="node"), "light"),
        "donut": build_donut_figure(budget(), category, "light"),
    }


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if NODE is None:
        pytest.skip("node is not installed")
    folder: Path = tmp_path_factory.mktemp("legend")
    (folder / "run.mjs").write_text(SCRIPT, encoding="utf-8")
    (folder / "figures.json").write_text(json.dumps(_figures()), encoding="utf-8")
    done = subprocess.run(  # noqa: S603 - fixed argv: node on a temp script and the shipped files
        [NODE, str(folder / "run.mjs"), str(STATIC_DIR / "js"), str(folder / "figures.json")],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


@pytest.mark.parametrize(("key", "title"), [("category", ""), ("titled", "Budget")])
def test_the_legend_row_goes_and_the_margin_is_the_one_of_a_figure_without_legend(
    run: dict[str, Any], key: str, title: str
) -> None:
    figure = run[key]["result"]
    layout = figure["layout"]

    assert layout["showlegend"] is False
    assert layout["margin"] == margin(style(title=title), legend=False)
    assert len(figure["data"]) == 1
    assert figure["data"][0]["type"] == "sankey"
    assert figure["data"][0]["domain"] == {"x": [0, 1], "y": [0, 1]}


def test_everything_but_the_legend_is_kept(run: dict[str, Any]) -> None:
    drawn = build_figure(budget(), style(color_mode="category"), "light")
    figure = run["category"]["result"]

    assert figure["data"][0]["node"] == drawn["data"][0]["node"]
    assert figure["data"][0]["link"] == drawn["data"][0]["link"]
    assert figure["layout"]["height"] == drawn["layout"]["height"]
    assert figure["layout"]["font"] == drawn["layout"]["font"]


@pytest.mark.parametrize("key", ["category", "titled", "node", "donut"])
def test_the_figure_that_was_given_is_never_changed(run: dict[str, Any], key: str) -> None:
    assert run[key]["untouched"] is True


@pytest.mark.parametrize("key", ["node", "donut"])
def test_a_donut_and_a_figure_without_a_legend_row_come_back_as_they_are(
    run: dict[str, Any], key: str
) -> None:
    assert run[key]["same"] is True


def test_a_sparse_figure_still_loses_the_row_without_a_negative_margin(
    run: dict[str, Any],
) -> None:
    assert run["bare"] == {
        "data": [{"type": "sankey", "domain": {"y": [0, 1]}}],
        "layout": {"showlegend": False, "margin": {"t": 0}},
    }
    assert run["empty"] == {}
