# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers shared by the UI-B suites (library, compare, settings, theme, resilience, security).

* ``PHONE`` / ``DESKTOP`` - viewport values for ``@pytest.mark.parametrize("viewport", [...])``.
* ``overflows_horizontally(page)`` - True when the document is wider than the window.
* ``css_var(page, name)`` / ``body_background(page)`` - computed values of the live page;
  ``wait_background(page, colour)`` waits for the body to paint a colour (a theme change needs
  a frame).
* ``poll_js(page, expression, ...)`` - bounded polling of a JS expression (``page.evaluate`` only:
  ``wait_for_function`` is blocked by the page's CSP, UI.md quirk 1).
* ``download_text(page, click)`` - run ``click`` (a callable) and return ``(file name, text)`` of
  the download it triggers.
* ``save_for_review(page, name)`` - a screenshot in ``.e2e-artifacts/ui-b-review/`` for humans;
  ``contrast(a, b)`` / ``luminance(c)`` - WCAG maths on ``#rrggbb`` colours.
* ``query_of(url)`` - the query string of a URL as a dict of single values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from urllib.parse import parse_qsl, urlsplit

from tests.e2e.support.session import ARTIFACTS_DIR
from tests.e2e.support.waits import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page, ViewportSize

PHONE: Final[ViewportSize] = {"width": 390, "height": 844}
DESKTOP: Final[ViewportSize] = {"width": 1280, "height": 900}
TALL: Final[ViewportSize] = {"width": 1280, "height": 2600}

_OVERFLOW_JS = "document.documentElement.scrollWidth - document.documentElement.clientWidth"


def overflow_pixels(page: Page) -> int:
    """How many pixels the document is wider than the window (0 = no horizontal scroll)."""
    return int(page.evaluate(_OVERFLOW_JS))


def overflows_horizontally(page: Page) -> bool:
    return overflow_pixels(page) > 0


def css_var(page: Page, name: str) -> str:
    """The computed value of the custom property ``name`` (``--surface``) on ``<html>``."""
    script = "name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()"
    return str(page.evaluate(script, name))


def body_background(page: Page) -> str:
    return str(page.evaluate("getComputedStyle(document.body).backgroundColor"))


def wait_background(page: Page, colour: str) -> None:
    """Wait until the page body paints ``colour`` (``rgb(13, 13, 13)``).

    Reduced motion shortens transitions to 0.01 ms instead of removing them, so the computed value
    still shows the old colour for one frame after a theme change.
    """
    wait_until(lambda: body_background(page) == colour, what=f"the page background {colour}")


def poll_js(page: Page, expression: str, *, what: str, timeout: float = 10.0) -> Any:
    """Evaluate ``expression`` until it is truthy and return the value (bounded, no sleeps)."""
    return wait_until(lambda: page.evaluate(expression), timeout=timeout, what=what)


def download_text(page: Page, click: Callable[[], None]) -> tuple[str, str]:
    """Run ``click`` (which must start a download) and return ``(suggested name, file text)``."""
    with page.expect_download() as info:
        click()
    download = info.value
    path = download.path()
    return download.suggested_filename, path.read_text(encoding="utf-8")


REVIEW_DIR: Final = ARTIFACTS_DIR / "ui-b-review"
PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"


def save_for_review(page: Page, name: str) -> bytes:
    """Screenshot the window into ``.e2e-artifacts/ui-b-review/<name>.png`` for a human."""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    data = page.screenshot(path=REVIEW_DIR / f"{name}.png")
    assert data.startswith(PNG_MAGIC)
    return data


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """WCAG relative luminance of ``#rrggbb``."""
    red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio of two ``#rrggbb`` colours (1..21)."""
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def query_of(url: str) -> dict[str, str]:
    """The query parameters of ``url`` (last value wins)."""
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
