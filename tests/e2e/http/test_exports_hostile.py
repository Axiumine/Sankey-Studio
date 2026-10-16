# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""E2E A.4 (hostile text in the files): what a person's own words can never become in an export.

* the HTML page keeps its own structure: the name is the ``<title>`` text, never markup;
* the CSV cannot run in a spreadsheet: a cell that starts with ``= + - @`` gets a ``'`` in front;
* the figure of the JSON export carries every name entity-escaped (Plotly decodes it back), so a
  typed ``AT&amp;T`` is drawn as typed and ``<b>`` is never a tag.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING, Any, Final

import pytest

from tests.e2e.support.builders import csv_text, graph_draft, unique_name
from tests.e2e.support.clients import seed_graph
from tests.e2e.support.http_a_exports import assert_download, export
from tests.e2e.support.http_a_html import PageShape

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from tests.e2e.support.server import LiveServer

#: Closes the title, opens a script, a bold tag and a quote: all of it must stay text.
HOSTILE_NAME: Final = '</title><script>window.pwned=1</script><b>"&amp;'
HOSTILE_TITLE: Final = "</script><script>window.pwned=2</script><b>chart</b>"
FORMULAS: Final = ("=1+1", "+SUM(A1:A9)", "-2+3", "@SUM(1)", '=HYPERLINK("http://evil.example")')
PLAIN: Final = ("A=B", "Total-1", "a@b", "R+D", "Q1 - Q2")  # a trigger inside the text is inert


@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    """One server for the module: every graph here has its own name."""
    return module_server


def rows_of(text: str) -> list[list[str]]:
    return list(csv.reader(text.splitlines()))


# ------------------------------------------------------------------------------ html


@pytest.mark.parametrize("chart", ["sankey", "donut"])
def test_a_hostile_name_and_title_never_change_the_structure_of_the_html_page(
    api: httpx.Client, chart: str
) -> None:
    rows = [("Pay", "Rent", 10, "Housing"), ("Pay", "Food", 5, "Living")]
    benign = seed_graph(api, unique_name("Benign"), graph_draft(csv_text(rows)))
    hostile_draft = graph_draft(csv_text(rows), style={"title": HOSTILE_TITLE})
    hostile = seed_graph(api, f"{unique_name('H')} {HOSTILE_NAME}", hostile_draft)
    plain = export(api, benign["id"], format="html", chart=chart)
    answer = export(api, hostile["id"], format="html", chart=chart)
    assert_download(answer, "html")
    shape = PageShape(answer.text)
    assert shape.title == hostile["name"]  # the whole name, as text
    assert shape.tags == PageShape(plain.text).tags  # no extra script, bold or other element
    escaped = "&lt;/title&gt;&lt;script&gt;window.pwned=1&lt;/script&gt;&lt;b&gt;&quot;&amp;amp;"
    assert f"{escaped}</title>" in answer.text  # escaped in the source ...
    assert "<script>window.pwned" not in answer.text  # ... and nowhere else live


# ------------------------------------------------------------------------------ csv


def formula_graph(api: httpx.Client) -> dict[str, Any]:
    """Every formula as a source name AND as a category; plain look-alikes as targets."""
    rows = [
        (f, p, 10 + number, f) for number, (f, p) in enumerate(zip(FORMULAS, PLAIN, strict=True))
    ]
    return seed_graph(api, unique_name("Formulas"), graph_draft(csv_text(rows)))


def test_a_csv_cell_that_starts_like_a_formula_is_defused_in_every_column(
    api: httpx.Client,
) -> None:
    graph = formula_graph(api)
    answer = export(api, graph["id"], format="csv")
    assert_download(answer, "csv")
    rows = rows_of(answer.text)
    assert rows[0] == ["source", "target", "value", "category"]
    body = sorted(rows[1:], key=lambda row: float(row[2]))
    assert [row[0] for row in body] == [f"'{formula}" for formula in FORMULAS]
    assert [row[3] for row in body] == [f"'{formula}" for formula in FORMULAS]
    assert [row[1] for row in body] == list(PLAIN)  # a trigger that is not first is left alone
    assert [row[2] for row in body] == [str(float(10 + n)) for n in range(len(FORMULAS))]


def test_the_donut_csv_defuses_category_names_too(api: httpx.Client) -> None:
    graph = formula_graph(api)
    rows = rows_of(export(api, graph["id"], format="csv", chart="donut").text)
    assert rows[0] == ["category", "value", "share"]
    assert sorted(row[0] for row in rows[1:]) == sorted(f"'{formula}" for formula in FORMULAS)


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@"])
def test_each_formula_character_alone_is_enough_to_be_defused(
    api: httpx.Client, trigger: str
) -> None:
    graph = seed_graph(api, unique_name("One"), graph_draft(csv_text([(f"{trigger}x", "y", 1)])))
    [_, row] = rows_of(export(api, graph["id"], format="csv").text)
    assert row[:2] == [f"'{trigger}x", "y"]


# ------------------------------------------------------------------------------ figure labels


def labels_of(figure: dict[str, Any]) -> Sequence[str]:
    return list(figure["data"][0]["node"]["label"])


def test_the_figure_carries_names_entity_escaped_so_that_typed_entities_stay_literal(
    api: httpx.Client,
) -> None:
    rows = [("AT&T", "AT&amp;T", 10, "R&D"), ("AT&amp;T", "<b>x</b>", 5, "R&D")]
    graph = seed_graph(api, unique_name("Entities"), graph_draft(csv_text(rows)))
    figure = export(api, graph["id"], format="json").json()
    labels = labels_of(figure)
    assert {"AT&amp;T", "AT&amp;amp;T", "&lt;b&gt;x&lt;/b&gt;"} <= set(labels)
    assert not {"AT&T", "<b>x</b>"} & set(labels)  # never the raw text
    links = figure["data"][0]["link"]["customdata"]
    assert ("AT&amp;T", "AT&amp;amp;T", "R&amp;D") in {(row[0], row[1], row[5]) for row in links}
    donut = export(api, graph["id"], format="json", chart="donut").json()
    assert donut["data"][0]["labels"] == ["R&amp;D"]
