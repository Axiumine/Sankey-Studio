"""The stored theme in the page, and bidirectional controls in names.

The page paints in the saved colour theme before any script runs (``<html data-theme>``, also in
the boot data), and ``data-theme-source`` says who wins: the server when it persists the theme, the
device cache when the server is read-only. A bidirectional override in a graph name must not reach
the heading, the title or the link labels (the boot data keeps the name exactly as stored).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

import pytest

from sankey_studio.models import AppSettings
from tests.web.test_pages_support import parse
from tests.web.test_routes_graphs_support import PLAIN, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode, WebApp

Theme = Literal["system", "light", "dark"]
STATIC_PAGES: Final = ["/", "/graphs/new", "/settings"]
OVERRIDE: Final = "\u202e"
ISOLATE: Final = "\u2067"
#: What a hostile name looks like: an override that reverses the extension, an unclosed isolate.
BIDI_NAME: Final = f"live {OVERRIDE}gpj.exe{ISOLATE}"
CLEAN_NAME: Final = "live gpj.exe"


@pytest.mark.parametrize("path", STATIC_PAGES)
@pytest.mark.parametrize("theme", ["system", "light", "dark"])
def test_a_page_is_rendered_in_the_stored_theme_and_says_so_in_the_boot_data(
    make_app: AppFactory, path: str, theme: Theme
) -> None:
    web = make_app(settings=AppSettings(theme=theme))
    page = parse(web.client.get(path))
    (html,) = page.find("html")
    assert (html["data-theme"], html["data-theme-source"]) == (theme, "server")
    assert page.data()["theme"] == theme


@pytest.mark.parametrize(
    ("mode", "source"),
    [("local", "server"), ("remote_writes", "server"), ("remote_read_only", "device")],
)
def test_the_theme_source_is_the_server_only_when_the_server_can_save_the_theme(
    make_app: AppFactory, mode: Mode, source: str
) -> None:
    web = make_app(mode=mode, settings=AppSettings(theme="dark"))
    (html,) = parse(web.client.get("/settings")).find("html")
    assert (html["data-theme"], html["data-theme-source"]) == ("dark", source)


def test_a_theme_saved_through_the_api_shows_on_the_next_page(web: WebApp) -> None:
    assert parse(web.client.get("/")).data()["theme"] == "system"
    current = web.client.get("/api/v1/settings").json()
    assert web.client.put("/api/v1/settings", json={**current, "theme": "dark"}).status_code == 200
    page = parse(web.client.get("/graphs/new"))
    assert page.find("html")[0]["data-theme"] == "dark"
    assert page.data()["theme"] == "dark"


def test_unreadable_settings_do_not_stop_the_pages_that_need_no_graphs(web: WebApp) -> None:
    web.config.data_dir.mkdir(parents=True, exist_ok=True)
    web.config.settings_file.write_text("{ not json", encoding="utf-8")
    for path in ("/graphs/new", "/settings"):
        response = web.client.get(path)
        assert response.status_code == 200, path
        page = parse(response)
        assert page.find("html")[0]["data-theme"] == "system"
        assert page.data()["theme"] == "system"


def test_bidi_controls_are_removed_from_the_heading_the_title_and_the_link_labels(
    web: WebApp,
) -> None:
    stored = save(web, BIDI_NAME, *PLAIN)
    for path, heading in [
        (f"/graphs/{stored.id}", CLEAN_NAME),
        (f"/graphs/{stored.id}/edit", f"Edit {CLEAN_NAME}"),
        (f"/compare?ids={stored.id}", "Compare graphs"),
        ("/", "Graphs"),
    ]:
        response = web.client.get(path)
        html = response.text
        assert OVERRIDE not in html, path
        assert ISOLATE not in html, path
        assert f"<h1>{heading}</h1>" in html, path
        assert f"<title>{heading} - Sankey Studio</title>" in html, path


def test_control_characters_are_removed_from_the_heading_the_title_and_the_link_labels(
    web: WebApp,
) -> None:
    stored = save(web, "bell\x07 esc\x1b[31mred\x7f", *PLAIN)
    clean = "bell esc[31mred"
    for path, heading in [
        (f"/graphs/{stored.id}", clean),
        (f"/graphs/{stored.id}/edit", f"Edit {clean}"),
    ]:
        html = web.client.get(path).text
        assert "\x07" not in html, path
        assert "\x1b" not in html, path
        assert "\x7f" not in html, path
        assert f"<h1>{heading}</h1>" in html, path
        assert f"<title>{heading} - Sankey Studio</title>" in html, path
    page = parse(web.client.get(f"/compare?ids={stored.id}"))
    assert [link.text for link in page.links if link.area == "noscript"] == [clean]
    (graph,) = page.data()["graphs"]
    assert graph["name"] == "bell\x07 esc\x1b[31mred\x7f"


def test_the_noscript_links_use_the_clean_name_and_the_boot_data_keeps_the_stored_one(
    web: WebApp,
) -> None:
    stored = save(web, BIDI_NAME, *PLAIN)
    page = parse(web.client.get(f"/compare?ids={stored.id}"))
    labels = [link.text for link in page.links if link.area == "noscript"]
    assert labels == [CLEAN_NAME]
    (graph,) = page.data()["graphs"]
    assert graph["name"] == BIDI_NAME


#: Only characters nobody can see: after the strip nothing is left to call the graph.
INVISIBLE_NAMES: Final = ["\x07", f"{OVERRIDE}{ISOLATE}", f"\x07{OVERRIDE} \x1b", "\x9f\x7f"]


@pytest.mark.parametrize("name", INVISIBLE_NAMES)
def test_a_name_with_nothing_visible_is_shown_as_untitled_graph(web: WebApp, name: str) -> None:
    stored = save(web, name, *PLAIN)
    for path, heading in [
        (f"/graphs/{stored.id}", "Untitled graph"),
        (f"/graphs/{stored.id}/edit", "Edit Untitled graph"),
    ]:
        html = web.client.get(path).text
        assert f"<h1>{heading}</h1>" in html, path
        assert f"<title>{heading} - Sankey Studio</title>" in html, path
    for path in ("/", f"/compare?ids={stored.id}"):
        page = parse(web.client.get(path))
        labels = [link.text for link in page.links if link.area == "noscript"]
        assert labels == ["Untitled graph"], path
    assert parse(web.client.get(f"/graphs/{stored.id}")).data()["graph"]["name"] == name


def test_a_name_with_visible_text_is_not_replaced(web: WebApp) -> None:
    stored = save(web, f"{OVERRIDE}Q3 \x07plan", *PLAIN)
    assert "<h1>Q3 plan</h1>" in web.client.get(f"/graphs/{stored.id}").text
