# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Chrome launch and browser-context creation (plain Playwright sync API, no pytest-playwright).

``launch_browser(pw)`` tries the system Chrome first (``channel="chrome"``), then the Chromium that
Playwright downloaded, and returns ``(browser, None)``; when neither can start it returns
``(None, reason)`` and the ``browser`` fixture turns the reason into a skip. Chrome runs headless
with ``--no-sandbox --disable-dev-shm-usage`` and an English locale in its environment (native
widgets follow the OS language otherwise, docs/ui/testing.md, Browser launch notes).

``new_context(browser, settings)`` opens a context from a ``ContextSettings``: viewport 1280x900,
``en-US``, UTC, light colour scheme, reduced motion, downloads accepted, ``base_url`` set to the
server (so ``page.goto("/")`` works), default action timeout 15 s. The CSP policy is never
bypassed: it is part of what is under test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from playwright.sync_api import Error as PlaywrightError

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Playwright, ViewportSize

ColorScheme = Literal["light", "dark", "no-preference"]
CHROME_ARGS: Final = ["--no-sandbox", "--disable-dev-shm-usage"]
CHROME_ENV: Final = {"LANGUAGE": "en_US:en", "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
DEFAULT_VIEWPORT: Final[ViewportSize] = {"width": 1280, "height": 900}
ACTION_TIMEOUT_MS: Final = 15_000
EXPECT_TIMEOUT_MS: Final = 10_000


@dataclass(frozen=True, slots=True)
class ContextSettings:
    """What differs between the contexts of the tests (the rest is fixed by ``new_context``)."""

    base_url: str
    color_scheme: ColorScheme
    viewport: ViewportSize


def _environment() -> dict[str, str | float | bool]:
    return {**os.environ, **CHROME_ENV}


def _launch_chrome(pw: Playwright) -> Browser:
    return pw.chromium.launch(channel="chrome", headless=True, args=CHROME_ARGS, env=_environment())


def _launch_chromium(pw: Playwright) -> Browser:
    return pw.chromium.launch(headless=True, args=CHROME_ARGS, env=_environment())


def launch_browser(pw: Playwright) -> tuple[Browser | None, str]:
    """``(browser, "")`` for the first browser that starts, else ``(None, <why not>)``."""
    reasons: list[str] = []
    for label, launch in (
        ("system Chrome", _launch_chrome),
        ("bundled Chromium", _launch_chromium),
    ):
        try:
            return launch(pw), ""
        except PlaywrightError as exc:
            reasons.append(f"{label}: {exc.message.strip().splitlines()[0]}")
    return None, "no browser could be started (" + "; ".join(reasons) + ")"


def new_context(browser: Browser, settings: ContextSettings) -> BrowserContext:
    """A fresh context for one test; see the module doc for the fixed options."""
    context = browser.new_context(
        base_url=settings.base_url,
        viewport=settings.viewport,
        locale="en-US",
        timezone_id="UTC",
        color_scheme=settings.color_scheme,
        reduced_motion="reduce",
        accept_downloads=True,
    )
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    return context
