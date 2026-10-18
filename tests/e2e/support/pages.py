# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``AppPage``: the base of the suites' page objects. The suites add their own subclasses.

A page object wraps one ``WatchedPage`` and one ``LiveServer`` and knows the shell that every page
of the app shares (docs/ui/shell.md). A subclass sets two class attributes and adds the locators
and actions of its page::

    class LibraryPage(AppPage):
        path = "/"
        name = "library"  # the value of main[data-page]

        def expect_ready(self) -> None:
            super().expect_ready()
            expect(self.tid("library-count")).to_be_visible()

* ``goto(suffix="")``      - open ``<server><path><suffix>`` (``suffix="?q=x"``), wait for
  ``expect_ready`` and return Playwright's response (its ``status`` is the HTTP status).
* ``expect_ready()``       - ``body[data-shell=ready]``, ``main[data-page=<name>]`` and
  ``data-loading=false``; override to add the page's own signals (and call ``super()``).
* ``tid(testid)``          - ``page.get_by_test_id``; ``heading`` is the page ``h1``.
* ``toasts()`` / ``expect_toast(text, kind=None)`` - the toast region: all toasts, or the first
  one with that text (str or regex), optionally with ``data-kind`` (``success``, ``error``, ...).
* ``nav(which)``           - ``nav-library`` / ``nav-new`` / ``nav-settings`` links.
* ``theme_button(value)``  - a button of the header theme switch (``system``, ``light``, ``dark``).
* ``expect_html_theme(value)`` - ``html[data-theme]``.
* ``remote_banner`` / ``read_only_banner`` - the banners of the remote and read-only servers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from playwright.sync_api import expect

from tests.e2e.support.uiwait import wait_idle, wait_page, wait_shell

if TYPE_CHECKING:
    import re

    from playwright.sync_api import Locator, Response

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

NavLink = Literal["library", "new", "settings"]
ThemeValue = Literal["system", "light", "dark"]
ToastKind = Literal["success", "error", "info", "warning"]


class AppPage:
    """One page of the app as seen by a test (see the module doc)."""

    path: ClassVar[str] = "/"
    name: ClassVar[str] = ""

    def __init__(self, page: WatchedPage, server: LiveServer) -> None:
        self.page = page
        self.server = server

    def tid(self, testid: str) -> Locator:
        return self.page.get_by_test_id(testid)

    @property
    def heading(self) -> Locator:
        return self.page.locator("#main h1")

    @property
    def remote_banner(self) -> Locator:
        return self.tid("remote-banner")

    @property
    def read_only_banner(self) -> Locator:
        return self.tid("read-only-banner")

    def url_for(self, suffix: str = "") -> str:
        return self.server.url_for(self.path) + suffix

    def goto(self, suffix: str = "") -> Response | None:
        response = self.page.goto(self.url_for(suffix))
        self.expect_ready()
        return response

    def expect_ready(self) -> None:
        wait_shell(self.page)
        if self.name:
            wait_page(self.page, self.name)
        wait_idle(self.page)

    def nav(self, which: NavLink) -> Locator:
        return self.tid(f"nav-{which}")

    def theme_button(self, value: ThemeValue) -> Locator:
        return self.tid("theme-switch").locator(f"[data-theme-value={value}]")

    def expect_html_theme(self, value: ThemeValue) -> None:
        expect(self.page.locator("html")).to_have_attribute("data-theme", value)

    def toasts(self) -> Locator:
        return self.tid("toast")

    def expect_toast(self, text: str | re.Pattern[str], kind: ToastKind | None = None) -> Locator:
        """Wait for a visible toast containing ``text`` (and of ``kind``) and return it."""
        toast = self.toasts().filter(has_text=text).first
        expect(toast).to_be_visible()
        if kind is not None:
            expect(toast).to_have_attribute("data-kind", kind)
        return toast
