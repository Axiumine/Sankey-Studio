# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""The pure helpers of the library, viewer and compare pages, run with node on the shipped files.

Covered here: names that are empty once control characters are gone (``library/names.js``), the
address query of the library (``library/state.js`` ``readQuery``: stripped text, capped page), the
chart file names (``core/download.js``: one rule, applied once), the figure scrub of
``core/chart.js`` and the single list of modebar buttons that must never exist. The pages
themselves are checked in a real browser by the wave-3b scripts and by the e2e wave.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

if TYPE_CHECKING:
    from pathlib import Path

JS: Final = STATIC_DIR / "js"
NODE: Final = shutil.which("node")

SCRIPT: Final = """
const [, , dir] = process.argv;
const load = (file) => import(`${dir}/${file}`);
const names = await load("library/names.js");
const state = await load("library/state.js");
const download = await load("core/download.js");
const chart = await load("core/chart.js");
const text = await load("core/text.js");
const figure = await load("viewer/figure.js");
const parts = await load("viewer/parts.js");

const scrubbed = chart.scrubFigure(structuredClone({
  data: [{
    type: "sankey",
    node: { label: ["Sal\\u0007ary\\u202e", "Budget"], color: ["#123456"] },
    link: { value: [1, 2], customdata: [["a\\u001bb"]] },
  }],
  layout: {
    title: { text: "T\\u202eitle" },
    height: 400,
    annotations: [{ text: "x\\u007fy" }],
  },
}));
const typed = { data: [{ x: new Float64Array([1, 2]) }] };

process.stdout.write(JSON.stringify({
  untitled: names.UNTITLED,
  display: ["", "  ", "\\u202e\\u0007", "\\u200b", "a\\u202eb", "Budget"].map(names.displayName),
  shown: ["\\u202e", "\\u200b\\u200e", " ", "x"].map(names.isShown),
  withName: names.withDisplayName({
    id: "i", name: "\\u0007", tags: ["ok", "\\u202e\\u0007", " "], extra: 1,
  }),
  withoutTags: names.withDisplayName({ name: "x" }),
  query: [
    "?q=%07%E2%80%AE&tag=%07",
    "?q=%20rent%E2%80%AE%20&tag=demo",
    "?page=99999999999999999999",
    "?page=0",
    "?page=-3",
    "?page=abc",
    "?page=7",
    "?page=100000",
  ].map((search) => state.readQuery(search)),
  pageMax: state.PAGE_MAX,
  stems: [
    ["Budget", "sankey"], ["Budget", "donut"], ["Budget-donut", "donut"], ["Budget", undefined],
  ].map(([stem, kind]) => download.chartStem(stem, kind)),
  files: [
    ["Budget.svg", "sankey"], ["Budget.svg", "donut"], ["Budget-donut.svg", "donut"],
    ["Budget v1.2.csv", "donut"], ["noext", "donut"],
  ].map(([name, kind]) => download.chartFileName(name, kind)),
  clean: [
    download.cleanFilename("rep\\u202egpj.exe"),
    download.cleanFilename("\\u202e\\u0007"),
    download.cleanFilename("a/b\\\\c.svg"),
  ],
  disposition: [
    download.filenameFromDisposition(
      "attachment; filename=\\"a.svg\\"; filename*=UTF-8''b%20c-donut.svg",
    ),
    download.filenameFromDisposition(null, ""),
  ],
  suffixes: [
    "&lt;b&gt;$", "&amp;lt;", "a &amp; b", "", undefined,
  ].map((valuesuffix) => parts.valueSuffix({ data: [{ valuesuffix }] })),
  noData: parts.valueSuffix({}),
  scrubbed,
  typedKept: chart.scrubFigure(typed).data[0].x instanceof Float64Array,
  removed: chart.CHART_CONFIG.modeBarButtonsToRemove,
  override: figure.CHART_CONFIG_OVERRIDE,
  strip: text.stripBidi("a\\u0007b\\u007f\\u009fc\\td\\ne\\rf"),
}));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if NODE is None:
        pytest.skip("node is not installed")
    script: Path = tmp_path_factory.mktemp("lvc") / "run.mjs"
    script.write_text(SCRIPT, encoding="utf-8")
    done = subprocess.run(  # noqa: S603 - fixed argv: node on a temp script and the shipped files
        [NODE, str(script), str(JS)], capture_output=True, text=True, check=False, timeout=60
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


def test_a_name_with_nothing_left_to_show_reads_untitled_graph(result: dict[str, Any]) -> None:
    assert result["untitled"] == "Untitled graph"
    assert result["display"] == [
        "Untitled graph",
        "Untitled graph",
        "Untitled graph",
        "Untitled graph",
        "ab",
        "Budget",
    ]
    assert result["shown"] == [False, False, False, True]


def test_a_summary_gets_a_shown_name_and_only_shown_tags(result: dict[str, Any]) -> None:
    assert result["withName"] == {"id": "i", "name": "Untitled graph", "tags": ["ok"], "extra": 1}
    assert "tags" not in result["withoutTags"]


def test_the_library_query_loses_control_characters_and_caps_the_page(
    result: dict[str, Any],
) -> None:
    cap = result["pageMax"]
    assert [(item["q"], item["tag"], item["page"]) for item in result["query"]] == [
        ("", "", 1),
        ("rent", "demo", 1),
        ("", "", cap),
        ("", "", 1),
        ("", "", 1),
        ("", "", 1),
        ("", "", 7),
        ("", "", cap),
    ]


def test_a_donut_file_carries_the_suffix_exactly_once(result: dict[str, Any]) -> None:
    assert result["stems"] == ["Budget", "Budget-donut", "Budget-donut", "Budget"]
    assert result["files"] == [
        "Budget.svg",
        "Budget-donut.svg",
        "Budget-donut.svg",
        "Budget v1.2-donut.csv",
        "noext-donut",
    ]


def test_the_served_file_name_is_read_as_it_is_and_cleaned_of_bidi_controls(
    result: dict[str, Any],
) -> None:
    assert result["disposition"] == ["b c-donut.svg", ""]
    assert result["clean"] == ["repgpj.exe", "download", "a-b-c.svg"]


def test_the_figure_texts_lose_controls_but_not_their_numbers_or_colours(
    result: dict[str, Any],
) -> None:
    figure = result["scrubbed"]
    node = figure["data"][0]["node"]
    assert node == {"label": ["Salary", "Budget"], "color": ["#123456"]}
    assert figure["data"][0]["link"] == {"value": [1, 2], "customdata": [["ab"]]}
    assert figure["layout"]["title"] == {"text": "Title"}
    assert figure["layout"]["annotations"] == [{"text": "xy"}]
    assert figure["layout"]["height"] == 400
    assert result["typedKept"] is True


def test_strip_bidi_drops_c0_del_and_c1_but_keeps_white_space(result: dict[str, Any]) -> None:
    assert result["strip"] == "abc\td\ne\rf"


def test_the_cloud_buttons_are_removed_in_one_place(result: dict[str, Any]) -> None:
    assert {"sendDataToCloud", "sendChartToCloud"} <= set(result["removed"])
    assert result["override"] == {"displayModeBar": False}
    for path in (JS / "viewer").glob("*.js"):
        assert "sendChartToCloud" not in path.read_text(encoding="utf-8"), path.name


def test_the_unit_text_shown_in_the_page_is_what_the_person_typed(result: dict[str, Any]) -> None:
    assert result["suffixes"] == ["<b>$", "&lt;", "a & b", "", ""]
    assert result["noData"] == ""
