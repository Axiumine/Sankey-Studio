"""The shell every page shares (``templates/page.html``): head, header, banners, regions, scripts.

The markup is the contract of the frontend wave: the three navigation links and the theme switch
carry their ``data-testid`` names, ``main`` is ``app-root`` and carries ``data-page``, the banners
follow the boot flags, the live regions exist before any script runs, and every page loads the
shell script plus the module of its own page (``new`` and ``edit`` share ``editor``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

import pytest

from tests.web.test_pages_support import Page, parse, unversioned
from tests.web.test_routes_graphs_support import PLAIN, save

if TYPE_CHECKING:
    from tests.web.conftest import AppFactory, Mode, WebApp

SHELL: Final = "/static/js/core/shell.js"
THEME_INIT: Final = "/static/js/core/theme-init.js"
STYLES: Final = ["tokens", "base", "components", "layout"]
NAV_IDS: Final = {"/": "nav-library", "/graphs/new": "nav-new", "/settings": "nav-settings"}


class PageCase(NamedTuple):
    template: str
    page: str
    module: str
    current: str | None
    section: str | None


CASES = [
    PageCase("/", "library", "library", "/", None),
    PageCase("/graphs/new", "new", "editor", "/graphs/new", None),
    PageCase("/settings", "settings", "settings", "/settings", None),
    PageCase("/graphs/{id}", "viewer", "viewer", None, "/"),
    PageCase("/graphs/{id}/edit", "edit", "editor", None, "/"),
    PageCase("/compare?ids={id}", "compare", "compare", None, "/"),
]
IDS = [case.page for case in CASES]


def fetch(web: WebApp, case: PageCase) -> Page:
    graph_id = save(web, "Budget", *PLAIN).id
    return parse(web.client.get(case.template.format(id=graph_id)))


def one(page: Page, tag: str, **where: str) -> dict[str, str | None]:
    (attrs,) = page.find(tag, **where)
    return attrs


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_page_loads_the_theme_init_shell_and_its_own_module(
    web: WebApp, case: PageCase
) -> None:
    page = fetch(web, case)
    sources = [s.attrs for s in page.scripts if "src" in s.attrs]
    assert [unversioned(attrs["src"] or "") for attrs in sources] == [
        THEME_INIT,
        SHELL,
        f"/static/js/pages/{case.module}.js",
    ]
    assert [attrs.get("type") for attrs in sources] == [None, "module", "module"]
    assert [s.attrs["id"] for s in page.scripts if "src" not in s.attrs] == ["page-data"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_head_links_the_shared_and_the_page_style_sheets(web: WebApp, case: PageCase) -> None:
    page = fetch(web, case)
    sheets = [unversioned(a["href"] or "") for a in page.find("link", rel="stylesheet")]
    expected = [f"/static/css/{name}.css" for name in STYLES]
    assert sheets == [*expected, f"/static/css/pages/{case.module}.css"]
    icon = one(page, "link", rel="icon")
    assert (unversioned(icon["href"] or ""), icon["type"]) == (
        "/static/img/favicon.svg",
        "image/svg+xml",
    )


def test_the_head_declares_language_viewport_theme_and_theme_colour(web: WebApp) -> None:
    page = fetch(web, CASES[0])
    html = one(page, "html")
    assert html == {"lang": "en", "data-theme": "system", "data-theme-source": "server"}
    assert one(page, "meta", name="viewport")["content"] == "width=device-width, initial-scale=1"
    assert one(page, "meta", name="color-scheme")["content"] == "light dark"
    colours = {a["media"]: a["content"] for a in page.find("meta", name="theme-color")}
    assert colours == {
        "(prefers-color-scheme: light)": "#fcfcfb",
        "(prefers-color-scheme: dark)": "#1a1a19",
    }


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_navigation_has_the_test_ids_and_marks_the_current_page(
    web: WebApp, case: PageCase
) -> None:
    page = fetch(web, case)
    nav = [link for link in page.links if link.area == "nav"]
    assert [(link.href, link.testid) for link in nav] == list(NAV_IDS.items())
    assert one(page, "nav")["aria-label"] == "Main"
    current = [a["href"] for a in page.find("a", aria_current="page")]
    assert current == ([case.current] if case.current else [])
    section = [a["href"] for a in page.elements_with_class("is-section")]
    assert section == ([case.section] if case.section else [])


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_main_is_the_app_root_with_the_page_name_and_one_heading(
    web: WebApp, case: PageCase
) -> None:
    page = fetch(web, case)
    main = one(page, "main")
    assert main["data-page"] == case.page
    assert main["data-testid"] == "app-root"
    assert (main["id"], main["tabindex"]) == ("main", "-1")
    assert page.tags.count("h1") == 1
    assert one(page, "a", href="#main")["class"] == "skip-link"
    assert one(page, "div", id="page-root")["class"] == "page-root"
    assert one(page, "div", id="page-actions")["class"] == "page-actions"


def test_the_theme_switch_is_a_group_of_three_buttons(web: WebApp) -> None:
    page = fetch(web, CASES[0])
    group = one(page, "div", data_testid="theme-switch")
    assert (group["role"], group["aria-label"]) == ("group", "Colour theme")
    buttons = [a for a in page.elements_with_class(None, tag="button") if "data-theme-value" in a]
    assert [(b["data-theme-value"], b["type"]) for b in buttons] == [
        ("system", "button"),
        ("light", "button"),
        ("dark", "button"),
    ]
    assert all(b["aria-pressed"] == "false" for b in buttons)
    assert page.tags.count("button") == 3


def test_the_live_regions_and_the_loading_bar_exist_before_any_script_runs(web: WebApp) -> None:
    page = fetch(web, CASES[0])
    toast = one(page, "div", id="toast-region")
    assert (toast["role"], toast["aria-live"], toast["aria-label"]) == (
        "region",
        "polite",
        "Notifications",
    )
    assert "data-testid" not in toast
    assert one(page, "div", id="a11y-polite")["aria-live"] == "polite"
    assert one(page, "div", id="a11y-assertive")["aria-live"] == "assertive"
    loading = one(page, "div", data_testid="loading")
    assert loading["role"] == "progressbar"
    assert "hidden" in loading
    assert loading["aria-label"] == "Loading"


class BannerCase(NamedTuple):
    mode: Mode
    remote: bool
    read_only: bool


BANNERS = [
    BannerCase("local", remote=False, read_only=False),
    BannerCase("remote_read_only", remote=True, read_only=True),
    BannerCase("remote_writes", remote=True, read_only=False),
]


@pytest.mark.parametrize("case", BANNERS, ids=[c.mode for c in BANNERS])
def test_the_banners_follow_the_boot_flags(make_app: AppFactory, case: BannerCase) -> None:
    web = make_app(mode=case.mode)
    for path in ("/", "/graphs/new", "/settings"):
        page = parse(web.client.get(path))
        assert bool(page.find("div", data_testid="remote-banner")) is case.remote, path
        assert bool(page.find("div", data_testid="read-only-banner")) is case.read_only, path


def test_the_remote_banner_says_whether_changes_are_possible(make_app: AppFactory) -> None:
    writes = make_app(mode="remote_writes").client.get("/").text
    read_only = make_app(mode="remote_read_only").client.get("/").text
    assert "see and change your graphs" in writes
    assert "see your graphs" in read_only
    assert "see and change" not in read_only
    assert "Read-only." in read_only
    assert "Read-only." not in writes


def test_without_javascript_the_page_says_so_and_lists_the_graph_links(web: WebApp) -> None:
    stored = save(web, "Budget", *PLAIN)
    page = parse(web.client.get(f"/graphs/{stored.id}"))
    fallback = [link for link in page.links if link.area == "noscript"]
    assert [(link.href, link.text) for link in fallback] == [(f"/graphs/{stored.id}/edit", "Edit")]
    html = web.client.get("/").text
    assert "Sankey Studio needs JavaScript" in html
    assert page.tags.count("noscript") == 1
