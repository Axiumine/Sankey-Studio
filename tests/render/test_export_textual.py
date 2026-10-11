"""HTML and JSON exports of a figure."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

import plotly.io
import pytest

from sankey_studio.render.export import export_html, export_json
from sankey_studio.render.export.textual import PLOT_CONFIG
from sankey_studio.render.layout import FONT_FAMILY
from sankey_studio.render.palette import TOKENS
from sankey_studio.render.sankey import build_figure
from tests.graph_support import make_graph
from tests.render.support import budget, style

if TYPE_CHECKING:
    from sankey_studio.models import Theme

EVIL = "</script><script>alert(1)</script>"


def figure_with_payload() -> dict[str, Any]:
    graph = make_graph([(EVIL, "<img src=x onerror=alert(1)>", 1.0, "c")])
    return build_figure(graph, style(title=EVIL), "light")


def test_json_round_trips_and_never_contains_a_raw_script_close() -> None:
    figure = figure_with_payload()
    text = export_json(figure)
    assert json.loads(text) == figure
    assert "</script" not in text
    assert "<" not in text
    assert "u003c" in text


def test_json_of_a_plain_figure_is_compact() -> None:
    text = export_json({"data": [], "layout": {"height": 3}})
    assert text == '{"data":[],"layout":{"height":3}}'


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_html_is_a_standalone_page_with_the_theme_surface(theme: Theme) -> None:
    page = export_html(build_figure(budget(), style(), theme), title="Budget", theme=theme)
    assert page.startswith('<!DOCTYPE html>\n<html lang="en">')
    assert '<meta charset="utf-8">' in page
    assert "<title>Budget</title>" in page
    assert f"background: {TOKENS[theme].surface}" in page
    assert f"color: {TOKENS[theme].ink}" in page
    assert page.rstrip().endswith("</body>\n</html>")
    assert "Plotly.newPlot" in page


def test_inline_html_embeds_plotly_and_needs_no_network() -> None:
    page = export_html(build_figure(budget(), style(), "light"), title="t", theme="light")
    assert len(page) > 1_000_000
    assert 'src="http' not in page
    assert "cdnjs.cloudflare.com" not in page  # no MathJax fetch


def test_cdn_html_links_plotly_instead_of_embedding_it() -> None:
    figure = build_figure(budget(), style(), "light")
    page = export_html(figure, title="t", theme="light", include_plotlyjs="cdn")
    assert len(page) < 200_000
    assert 'src="https://cdn.plot.ly/' in page
    assert "cdnjs.cloudflare.com" not in page


def test_the_title_is_html_escaped() -> None:
    page = export_html(
        {"data": [], "layout": {}}, title=f'a & "b" {EVIL}', theme="light", include_plotlyjs="cdn"
    )
    assert (
        "<title>a &amp; &quot;b&quot; &lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;</title>"
        in page
    )
    assert page.count("<title>") == 1


def test_figure_payload_cannot_break_out_of_its_script_block() -> None:
    page = export_html(figure_with_payload(), title="t", theme="light", include_plotlyjs="cdn")
    assert "<img src=x" not in page
    assert "<script>alert(1)" not in page
    assert EVIL not in page


def test_the_page_is_not_wrapped_twice_and_the_figure_is_not_validated() -> None:
    odd = {"data": [{"type": "scatter", "x": [1], "bogus_property": 1}], "layout": {}}
    page = export_html(odd, title="t", theme="light", include_plotlyjs="cdn")
    assert page.count("<html") == 1
    assert page.count("<body") == 1
    assert page.count("<head") == 1
    assert '"template"' not in page
    assert "bogus_property" in page
    assert '"bogus_property":1' in export_json(odd)


def test_the_chart_options_hide_the_logo_and_follow_the_window() -> None:
    assert PLOT_CONFIG == {"displaylogo": False, "responsive": True}
    page = export_html({"data": [], "layout": {}}, title="t", theme="light", include_plotlyjs="cdn")
    assert '"displaylogo":false' in page.replace(" ", "")
    assert '"responsive":true' in page.replace(" ", "")


class Calls:
    """Replaces ``plotly.io.to_html`` / ``to_json`` and keeps the exact keyword arguments."""

    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    def to_html(self, figure: dict[str, Any], **kwargs: Any) -> str:
        self.kwargs.append({"figure": figure, **kwargs})
        return "<div>chart</div>"

    def to_json(self, figure: dict[str, Any], **kwargs: Any) -> str:
        self.kwargs.append({"figure": figure, **kwargs})
        return "{}"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    recorder = Calls()
    monkeypatch.setattr(plotly.io, "to_html", recorder.to_html)
    monkeypatch.setattr(plotly.io, "to_json", recorder.to_json)
    return recorder


@pytest.mark.parametrize(("mode", "plotlyjs"), [("inline", True), ("cdn", "cdn")])
def test_html_asks_plotly_for_a_fragment_without_validation(
    calls: Calls, mode: Literal["inline", "cdn"], plotlyjs: bool | str
) -> None:
    figure: dict[str, Any] = {"data": [], "layout": {}}
    export_html(figure, title="t", theme="light", include_plotlyjs=mode)
    assert calls.kwargs == [
        {
            "figure": figure,
            "config": PLOT_CONFIG,
            "include_plotlyjs": plotlyjs,
            "full_html": False,
            "validate": False,
        }
    ]
    assert calls.kwargs[0]["include_plotlyjs"] is plotlyjs


def test_json_is_serialised_without_validation(calls: Calls) -> None:
    figure: dict[str, Any] = {"data": [], "layout": {}}
    assert export_json(figure) == "{}"
    assert calls.kwargs == [{"figure": figure, "validate": False}]


def test_the_page_skeleton_is_exact(calls: Calls) -> None:
    page = export_html({"data": []}, title="T", theme="dark", include_plotlyjs="cdn")
    tokens = TOKENS["dark"]
    assert page == (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>T</title>\n"
        f"<style>html, body {{ height: 100%; margin: 0; background: {tokens.surface}; "
        f"color: {tokens.ink}; font-family: {FONT_FAMILY}; }}</style>\n"
        "</head>\n<body>\n<div>chart</div>\n</body>\n</html>\n"
    )
    assert len(calls.kwargs) == 1
