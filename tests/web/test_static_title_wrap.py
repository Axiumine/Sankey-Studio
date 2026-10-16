# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``core/title-wrap.js`` (long chart titles) run with node on the shipped file.

A title longer than the chart is cut at the figure's edge because Plotly draws it on one line, so
the client wraps it with ``<br>`` before drawing. What is pinned here: only ``<br>`` is ever
added, no HTML entity, emoji sequence or accented letter is split, a word longer than a line is
broken between characters, the top margin grows with the extra lines, and a title that fits is
left exactly as the server sent it. The drawing itself is checked in a real browser.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Final

import pytest

from sankey_studio.web.app import STATIC_DIR

if TYPE_CHECKING:
    from pathlib import Path

JS: Final = STATIC_DIR / "js"
NODE: Final = shutil.which("node")

SENTENCE: Final = (
    "Household budget for the whole year including every recurring bill and one off expense"
)
ZWJ: Final = chr(0x200D)
FAMILY: Final = chr(0x1F468) + ZWJ + chr(0x1F469) + ZWJ + chr(0x1F467)
ACCENTED: Final = "e" + chr(0x0301)
FLAG: Final = chr(0x1F1EE) + chr(0x1F1F9)

SCRIPT: Final = """
const [, , dir, payload] = process.argv;
const { wrapTitle, titleFit, wrapLayoutTitle, LINE_HEIGHT, DEFAULT_TITLE_PX } =
  await import(`${dir}/core/title-wrap.js`);
const cases = JSON.parse(payload);

const wrap = (text, width, fontSize) => wrapTitle(text, { width, fontSize });
const layoutOf = (text) => ({
  title: { text, font: { size: 16 }, x: 0, xref: "container", pad: { l: 16, t: 16 } },
  margin: { l: 16, r: 16, t: 52, b: 16 },
  height: 560,
});
const applied = structuredClone(layoutOf(cases.sentence));
const fit = wrapLayoutTitle(applied, 324);
const untouched = structuredClone(layoutOf("Budget 2026"));
const noFit = wrapLayoutTitle(untouched, 324);
const stringTitle = { title: cases.sentence, margin: { t: 40 } };
wrapLayoutTitle(stringTitle, 200);

process.stdout.write(JSON.stringify({
  constants: [LINE_HEIGHT, DEFAULT_TITLE_PX],
  empty: wrap("", 300),
  short: wrap("Budget 2026", 300),
  sentence: wrap(cases.sentence, 292, 16),
  roomy: wrap(cases.sentence, 3000, 16),
  narrow: wrap(cases.sentence, 120, 16),
  token: wrap("X".repeat(90), 200, 17),
  entities: wrap("&lt;".repeat(60), 150, 16),
  mixedEntities: wrap(`${"Tom &amp; Jerry &lt;b&gt;x&lt;/b&gt; ".repeat(4)}end`, 200, 16),
  family: wrap(cases.family.repeat(30), 160, 16),
  accented: wrap(cases.accented.repeat(80), 120, 16),
  flags: wrap(cases.flag.repeat(40), 120, 16),
  wide: wrap("W".repeat(30), 300, 16),
  slim: wrap("i".repeat(30), 300, 16),
  han: wrap("\\u6f22".repeat(30), 300, 16),
  forced: wrap("first line<br>second line<BR/>third", 3000, 16),
  tiny: wrap("ab cd ef", 5, 16),
  longest: wrap("word ".repeat(40), 324, 16),
  fitPlain: titleFit(layoutOf(cases.sentence), 324),
  fitRoomy: titleFit(layoutOf(cases.sentence), 3000),
  fitDefaults: titleFit({ title: { text: "x ".repeat(60) } }, 300),
  fitString: titleFit({ title: "x ".repeat(60), margin: { t: 30, r: 0 } }, 300),
  fitNone: [
    titleFit({}, 300),
    titleFit({ title: { text: "" } }, 300),
    titleFit({ title: {} }, 300),
    titleFit(layoutOf("x"), 0),
    titleFit(layoutOf("x"), -5),
    titleFit(undefined, 300),
  ],
  applied,
  fit,
  untouched,
  noFit,
  stringTitle,
}));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    if NODE is None:
        pytest.skip("node is not installed")
    script: Path = tmp_path_factory.mktemp("title_wrap") / "run.mjs"
    script.write_text(SCRIPT, encoding="utf-8")
    payload = json.dumps(
        {"sentence": SENTENCE, "family": FAMILY, "accented": ACCENTED, "flag": FLAG}
    )
    done = subprocess.run(  # noqa: S603 - fixed argv: node on a temp script and the shipped files
        [NODE, str(script), str(JS), payload],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (done.returncode, done.stderr) == (0, "")
    data: dict[str, Any] = json.loads(done.stdout)
    return data


def lines_of(wrapped: dict[str, Any]) -> list[str]:
    text: str = wrapped["text"]
    return text.split("<br>")


def test_a_title_that_fits_is_returned_as_it_came(result: dict[str, Any]) -> None:
    assert result["constants"] == [1.3, 17]
    assert result["empty"] == {"text": "", "lines": 1}
    assert result["short"] == {"text": "Budget 2026", "lines": 1}
    assert result["roomy"] == {"text": SENTENCE, "lines": 1}


def test_words_wrap_at_spaces_and_nothing_but_br_is_added(result: dict[str, Any]) -> None:
    wrapped = result["sentence"]
    lines = lines_of(wrapped)
    assert wrapped["lines"] == len(lines) > 1
    assert " ".join(lines) == SENTENCE
    assert all(line == line.strip() and "<" not in line for line in lines)
    narrow = lines_of(result["narrow"])
    assert len(narrow) > len(lines)
    assert " ".join(narrow) == SENTENCE


def test_a_line_is_never_longer_than_the_width_allows(result: dict[str, Any]) -> None:
    # 292 px at 16 px is 18.25 em: about 33 average characters, a few more when they are narrow.
    assert max(len(line) for line in lines_of(result["sentence"])) <= 40
    # "W" is 0.9 em and "i" 0.32 em: the same count of characters needs more or fewer lines.
    assert result["wide"]["lines"] > result["slim"]["lines"]
    han = lines_of(result["han"])
    assert [len(line) for line in han] == [17, 13]  # a full-width character is a little over 1 em


def test_a_word_longer_than_a_line_is_broken_between_characters(result: dict[str, Any]) -> None:
    token = lines_of(result["token"])
    assert len(token) > 2
    assert "".join(token) == "X" * 90
    assert max(len(line) for line in token) <= 17


def test_an_html_entity_is_never_split(result: dict[str, Any]) -> None:
    lines = lines_of(result["entities"])
    assert len(lines) > 2
    assert all(re.fullmatch(r"(?:&lt;)+", line) for line in lines)
    assert "".join(lines) == "&lt;" * 60
    mixed = " ".join(lines_of(result["mixedEntities"]))
    assert mixed == f"{'Tom &amp; Jerry &lt;b&gt;x&lt;/b&gt; ' * 4}end"
    for line in lines_of(result["mixedEntities"]):
        assert not re.search(r"&[^;\s]*$", line)
        assert not re.match(r"^[^&\s]*;", line)


def test_an_emoji_sequence_an_accented_letter_and_a_flag_stay_whole(
    result: dict[str, Any],
) -> None:
    family = lines_of(result["family"])
    assert len(family) > 1
    assert all(re.fullmatch(f"(?:{FAMILY})+", line) for line in family)
    accented = lines_of(result["accented"])
    assert len(accented) > 1
    assert all(re.fullmatch(f"(?:{ACCENTED})+", line) for line in accented)
    flags = lines_of(result["flags"])
    assert len(flags) > 1
    assert all(re.fullmatch(f"(?:{FLAG})+", line) for line in flags)


def test_a_br_that_is_already_in_the_title_stays_a_break(result: dict[str, Any]) -> None:
    assert result["forced"] == {"text": "first line<br>second line<br>third", "lines": 3}


def test_a_tiny_width_still_makes_progress(result: dict[str, Any]) -> None:
    assert result["tiny"]["text"].replace("<br>", " ").split() == ["ab", "cd", "ef"]
    longest = lines_of(result["longest"])
    assert len(longest) > 3
    assert all(line.split() and set(line.split()) == {"word"} for line in longest)


def test_the_top_margin_grows_by_one_line_height_per_extra_line(result: dict[str, Any]) -> None:
    fit = result["fitPlain"]
    assert fit["lines"] > 1
    assert fit["text"] == result["sentence"]["text"]
    assert fit["marginTop"] == 52 + (fit["lines"] - 1) * 21
    roomy = result["fitRoomy"]
    assert (roomy["text"], roomy["lines"], roomy["marginTop"]) == (SENTENCE, 1, 52)


def test_the_defaults_are_plotlys_own(result: dict[str, Any]) -> None:
    defaults = result["fitDefaults"]
    assert defaults["lines"] > 1
    assert defaults["marginTop"] == 100 + (defaults["lines"] - 1) * 23  # 17 px * 1.3, rounded up
    text = result["fitString"]
    assert text["lines"] > 1
    assert text["marginTop"] == 30 + (text["lines"] - 1) * 23


def test_there_is_nothing_to_fit_without_a_title_or_a_width(result: dict[str, Any]) -> None:
    assert result["fitNone"] == [None] * 6


def test_wrapping_a_layout_keeps_every_other_key(result: dict[str, Any]) -> None:
    layout = result["applied"]
    assert layout["title"] == {
        "text": result["fitPlain"]["text"],
        "font": {"size": 16},
        "x": 0,
        "xref": "container",
        "pad": {"l": 16, "t": 16},
    }
    assert layout["margin"] == {"l": 16, "r": 16, "t": result["fit"]["marginTop"], "b": 16}
    assert layout["height"] == 560
    assert result["fit"]["lines"] > 1


def test_a_title_that_fits_leaves_the_layout_untouched(result: dict[str, Any]) -> None:
    assert result["untouched"]["title"]["text"] == "Budget 2026"
    assert result["untouched"]["margin"]["t"] == 52
    assert result["noFit"] == {"text": "Budget 2026", "marginTop": 52, "lines": 1}


def test_a_plain_string_title_becomes_a_title_object(result: dict[str, Any]) -> None:
    layout = result["stringTitle"]
    assert layout["title"]["text"].count("<br>") >= 1
    assert " ".join(layout["title"]["text"].split("<br>")) == SENTENCE
    assert layout["margin"]["t"] > 40
