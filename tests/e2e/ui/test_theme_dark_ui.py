"""E2E.md B.9, dark mode: tokens, chart surfaces and the palette, plus screenshots for a human.

The truth about colours lives in ``sankey_studio.render.palette``. The page's CSS custom properties
and the figure Plotly draws must both agree with it in each theme, and no colour outside it may
appear in a chart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

import pytest
from playwright.sync_api import expect

from sankey_studio.render import palette
from tests.e2e.support.builders import BUDGET_CATEGORISED, LAYERED, graph_draft, unique_name
from tests.e2e.support.clients import make_client, seed_graph
from tests.e2e.support.ui_b_common import (
    REVIEW_DIR,
    contrast,
    css_var,
    save_for_review,
    wait_background,
)
from tests.e2e.support.ui_b_compare import ComparePage
from tests.e2e.support.ui_b_library import LibraryPage
from tests.e2e.support.ui_b_settings import SettingsPage, wait_theme_saved
from tests.e2e.support.ui_b_viewer import (
    ViewerPage,
    expect_chart_theme,
    figure_colours,
    figure_surface,
)
from tests.e2e.support.uiwait import wait_chart

if TYPE_CHECKING:
    import httpx

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

Theme = Literal["light", "dark"]
THEMES: Final[tuple[Theme, Theme]] = ("light", "dark")
PLANE: Final = {"light": "rgb(249, 249, 247)", "dark": "rgb(13, 13, 13)"}
TOKEN_VARS: Final = {
    "--surface": "surface",
    "--ink": "ink",
    "--ink-secondary": "ink_secondary",
    "--muted": "muted",
    "--gridline": "gridline",
    "--baseline": "baseline",
}


@pytest.fixture
def graph_id(api: httpx.Client) -> str:
    draft = graph_draft(BUDGET_CATEGORISED.csv, style={"color_mode": "category"})
    return str(seed_graph(api, unique_name("Dark"), draft, tags=["review"])["id"])


@pytest.fixture
def viewer(page: WatchedPage, live_server: LiveServer, graph_id: str) -> ViewerPage:
    return ViewerPage(page, live_server, graph_id)


def allowed_colours(theme: Theme) -> set[str]:
    tokens = palette.TOKENS[theme]
    neutral = {palette.UNCATEGORIZED_COLOR, palette.NODE_NEUTRAL, palette.OTHER_COLOR[theme]}
    return {c.lower() for c in (*palette.CATEGORICAL[theme], *vars_of(tokens), *neutral)}


def vars_of(tokens: palette.Tokens) -> tuple[str, ...]:
    return (
        tokens.surface,
        tokens.ink,
        tokens.ink_secondary,
        tokens.muted,
        tokens.gridline,
        tokens.baseline,
    )


# ------------------------------------------------------------------------------ CSS tokens


def test_the_css_tokens_are_the_palette_modules_tokens_and_stay_readable_in_each_theme(
    viewer: ViewerPage,
) -> None:
    viewer.goto()
    seen: dict[str, dict[str, str]] = {}
    for theme in THEMES:
        viewer.theme_button(theme).click()
        viewer.expect_html_theme(theme)
        wait_background(viewer.page, PLANE[theme])
        tokens = palette.TOKENS[theme]
        seen[theme] = {name: css_var(viewer.page, name) for name in TOKEN_VARS}
        for variable, field in TOKEN_VARS.items():
            assert seen[theme][variable] == getattr(tokens, field), f"{theme} {variable}"
        surface = seen[theme]["--surface"]
        assert contrast(seen[theme]["--ink"], surface) >= 7  # body text
        assert contrast(seen[theme]["--ink-secondary"], surface) >= 4.5  # secondary text
        assert contrast(seen[theme]["--muted"], surface) >= 3  # borders and icons
        assert contrast(seen[theme]["--ink"], css_var(viewer.page, "--plane")) >= 7
        heading = viewer.page.evaluate("getComputedStyle(document.querySelector('#main h1')).color")
        assert heading == ("rgb(240, 239, 236)" if theme == "dark" else "rgb(11, 11, 11)")
    assert seen["light"]["--surface"] != seen["dark"]["--surface"]
    assert seen["light"]["--ink"] != seen["dark"]["--ink"]
    wait_theme_saved(viewer.page, "dark")


# ------------------------------------------------------------------------------ the charts


def test_the_chart_surfaces_follow_the_theme_and_every_colour_comes_from_the_palette(
    viewer: ViewerPage,
) -> None:
    viewer.goto()
    for theme in THEMES:
        viewer.theme_button(theme).click()
        expect_chart_theme(viewer.sankey, theme)
        tokens = palette.TOKENS[theme]
        assert figure_surface(viewer.sankey) == (tokens.surface, tokens.ink)
        sankey = figure_colours(viewer.sankey)
        viewer.show_donut()
        expect_chart_theme(viewer.donut, theme)
        assert figure_surface(viewer.donut) == (tokens.surface, tokens.ink)
        donut = figure_colours(viewer.donut)
        allowed = allowed_colours(theme)
        assert sankey <= allowed, f"not from the palette: {sorted(sankey - allowed)}"
        assert donut <= allowed, f"not from the palette: {sorted(donut - allowed)}"
        hues = {c.lower() for c in palette.CATEGORICAL[theme]}
        assert len(sankey & hues) >= 4  # the five categories really wear their hues
        other: Theme = "dark" if theme == "light" else "light"
        other_hues = {c.lower() for c in palette.CATEGORICAL[other]}
        assert not (sankey | donut) & (other_hues - hues), "hues of the other theme leaked in"
        viewer.tid("chart-tab-sankey").click()
        wait_chart(viewer.page)
    wait_theme_saved(viewer.page, "dark")


@pytest.mark.parametrize("color_scheme", ["dark"])
def test_a_dark_device_with_the_system_theme_draws_dark_charts_from_the_first_paint(
    viewer: ViewerPage,
) -> None:
    viewer.goto()
    viewer.expect_html_theme("system")
    expect_chart_theme(viewer.sankey, "dark")
    assert figure_surface(viewer.sankey)[0] == palette.TOKENS["dark"].surface
    viewer.page.emulate_media(color_scheme="light")  # the device switches while the page is open
    expect_chart_theme(viewer.sankey, "light")
    assert figure_surface(viewer.sankey)[0] == palette.TOKENS["light"].surface


# ------------------------------------------------------------------------------ for human eyes


def test_screenshots_of_every_page_are_saved_for_review_in_both_themes(
    page: WatchedPage, live_server: LiveServer, graph_id: str
) -> None:
    with make_client(live_server) as api:
        other_id = str(seed_graph(api, unique_name("Second"), graph_draft(LAYERED.csv))["id"])
    library = LibraryPage(page, live_server)
    viewer = ViewerPage(page, live_server, graph_id)
    compare = ComparePage(page, live_server)
    settings = SettingsPage(page, live_server)
    for theme in THEMES:
        library.goto()
        library.theme_button(theme).click()
        wait_background(page, PLANE[theme])
        wait_theme_saved(page, theme)  # the click saves in the background; do not navigate away yet
        shots = {"library": save_for_review(page, f"library-{theme}")}
        viewer.goto()
        expect_chart_theme(viewer.sankey, theme)
        shots["viewer"] = save_for_review(page, f"viewer-{theme}")
        viewer.show_donut()
        shots["donut"] = save_for_review(page, f"viewer-donut-{theme}")
        compare.open_ids([graph_id, other_id])
        expect(compare.cards).to_have_count(2)
        expect(compare.cards.get_by_test_id("sankey-chart").last).to_have_attribute(
            "data-ready", "true"
        )
        shots["compare"] = save_for_review(page, f"compare-{theme}")
        settings.goto()
        shots["settings"] = save_for_review(page, f"settings-{theme}")
        assert all(len(data) > 5_000 for data in shots.values()), "a screenshot is blank"
        assert len({hash(data) for data in shots.values()}) == len(shots)  # five different pages
        assert (REVIEW_DIR / f"settings-{theme}.png").is_file()
        expect(page.locator("html")).to_have_attribute("data-theme", theme)
