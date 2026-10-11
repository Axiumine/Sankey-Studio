"""E2E.md A.9, part 2: ``max_drawn_links`` - the figure shows the biggest links, says so, and warns.

Everything else (the entries table, the CSV export, the totals) keeps ALL links: the cap only
limits what is drawn. A figure with fewer links than the cap has no note and no warning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.support.builders import MANY_LINKS, graph_draft, many_links, unique_name
from tests.e2e.support.clients import json_of, make_client, seed_graph
from tests.e2e.support.http_b_limits import API, change_settings, drawn_values, note_texts

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer, ServerFactory

CAP = 50
NOTE = "Showing 50 of 300 links"


@pytest.fixture(scope="module")
def capped_server(module_make_server: ServerFactory) -> LiveServer:
    """One server with ``max_drawn_links`` = 50 for the tests that do not change the settings."""
    return module_make_server(settings={"max_drawn_links": CAP})


@pytest.fixture
def live_server(capped_server: LiveServer) -> LiveServer:
    return capped_server


def test_a_300_link_graph_draws_the_50_biggest_and_says_so(api: httpx.Client) -> None:
    bundle = json_of(api.post(f"{API}/preview", json=graph_draft(MANY_LINKS.csv)))
    stats = bundle["stats"]
    assert (stats["links"], stats["drawn_links"]) == (300, CAP)
    assert stats["total_in"] == MANY_LINKS.total  # the totals are those of ALL links
    assert note_texts(bundle) == [NOTE]  # visible in the figure itself, so exports carry it
    assert bundle["warnings"] == [NOTE]
    everything = sorted((row["value"] for row in bundle["entries"]), reverse=True)
    assert bundle["entries_total"] == len(everything) == 300  # the table keeps every link
    assert sorted(drawn_values(bundle), reverse=True) == everything[:CAP]  # the biggest ones


@pytest.mark.parametrize(
    ("links", "note"),
    [
        (CAP - 1, None),
        (CAP, None),
        (CAP + 1, "Showing 50 of 51 links"),
        (100, "Showing 50 of 100 links"),
    ],
)
def test_the_note_appears_with_the_first_link_over_the_cap(
    api: httpx.Client, links: int, note: str | None
) -> None:
    bundle = json_of(api.post(f"{API}/preview", json=graph_draft(many_links(links).csv)))
    assert len(drawn_values(bundle)) == min(links, CAP)
    assert bundle["stats"]["links"] == links
    assert note_texts(bundle) == ([note] if note else [])
    assert bundle["warnings"] == ([note] if note else [])


def test_the_exports_of_a_saved_graph_keep_every_link_and_the_figure_keeps_the_cap(
    api: httpx.Client,
) -> None:
    saved = seed_graph(api, unique_name("many"), graph_draft(MANY_LINKS.csv))
    export = f"{API}/graphs/{saved['id']}/export"
    csv = api.get(export, params={"format": "csv"}).text.splitlines()
    assert csv[0] == "source,target,value,category"
    assert len(csv) == 1 + 300  # the full list of links
    figure = json_of(api.get(export, params={"format": "json"}))
    assert len(figure["data"][0]["link"]["value"]) == CAP
    assert [a["text"] for a in figure["layout"]["annotations"]] == [NOTE]
    html = api.get(export, params={"format": "html"}).text
    assert NOTE in html


def test_the_saved_render_and_the_compare_grid_draw_the_same_50(api: httpx.Client) -> None:
    saved = seed_graph(api, unique_name("many"), graph_draft(MANY_LINKS.csv))
    rendered = json_of(api.get(f"{API}/graphs/{saved['id']}/render"))
    (card,) = json_of(api.get(f"{API}/compare/render", params={"ids": saved["id"]}))
    for bundle in (rendered, card):
        assert (bundle["stats"]["links"], bundle["stats"]["drawn_links"]) == (300, CAP)
        assert note_texts(bundle) == [NOTE]


def test_the_cap_is_a_live_setting_for_graphs_already_drawn(make_server: ServerFactory) -> None:
    with make_client(make_server(settings={"max_drawn_links": CAP})) as api:
        saved = seed_graph(api, unique_name("live"), graph_draft(MANY_LINKS.csv))
        render = f"{API}/graphs/{saved['id']}/render"
        assert json_of(api.get(render))["stats"]["drawn_links"] == CAP
        assert change_settings(api, max_drawn_links=400).status_code == 200
        wide = json_of(api.get(render))
        assert (wide["stats"]["drawn_links"], note_texts(wide), wide["warnings"]) == (300, [], [])
        assert change_settings(api, max_drawn_links=CAP).status_code == 200
        narrow = json_of(api.get(render))
        assert (narrow["stats"]["drawn_links"], note_texts(narrow)) == (CAP, [NOTE])
