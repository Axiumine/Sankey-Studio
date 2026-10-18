# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``PageWatch`` / ``WatchedPage``: nothing may go wrong in the browser, unless a test says so.

A ``PageWatch`` belongs to one browser context and listens on every page that is adopted into it:

* console messages of type ``error`` and ``warning``: ``console.error: <text> @ <url>``
* uncaught page exceptions: ``pageerror: <name>: <message>``
* failed requests, except ``net::ERR_ABORTED`` (a cancelled preview or a download):
  ``requestfailed: <METHOD> <url> <why>``
* responses with status >= 400: ``http <status>: <METHOD> <url>``
* Content-Security-Policy violations (``securitypolicyviolation`` events, reported through a
  binding that survives navigations): ``csp: <directive> <blocked uri> @ <page>``

Every line is kept in ``events`` (CSP lines in ``csp``). A line is a *problem* unless an allow
pattern matches it; the ``page`` fixture asserts that there are no problems and no CSP violations
at the end of every test that otherwise passed. CSP violations can never be allowed.

The allow-list is per test and every entry must carry a comment saying why the noise is expected
(docs/ui/testing.md lists the legitimate ones). Chrome prints every 4xx/5xx as a console error AND
Playwright reports the response, so an expected status needs both lines allowed:

* ``page.allow_http(409, "/api/v1/graphs/")`` - the console line and the response of status 409 on
  a URL containing the path;
* ``page.allow_errors(r"some regex", ...)`` - any lines (``re.search`` against the whole line).

``page.watch.matching(regex)`` returns the lines seen (allowed or not): assert that the expected
noise really happened, so an allow-list entry cannot go stale unnoticed.

``WatchedPage`` is the type of the ``page`` fixture: a real Playwright ``Page`` (``expect(page)``
works) with ``watch``, ``allow_errors``, ``allow_http`` and ``new_tab`` on top. ``new_tab`` opens
another page in the same context, watched by the same ``PageWatch``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, cast

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, ConsoleMessage, Request, Response

CSP_BINDING: Final = "__e2eCsp"
CSP_HOOK: Final = f"""
document.addEventListener('securitypolicyviolation', (event) => {{
  try {{
    window.{CSP_BINDING}(
      event.violatedDirective + ' ' + event.blockedURI + ' @ ' + event.documentURI);
  }} catch (error) {{}}
}});
"""
WATCHED_CONSOLE_TYPES: Final = frozenset({"error", "warning"})
ABORTED: Final = "ERR_ABORTED"
HTTP_ERROR_FROM: Final = 400
CHROME_RESOURCE_ERROR: Final = "Failed to load resource: the server responded with a status of"


class PageWatch:
    """The collectors of one browser context (see the module doc)."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.csp: list[str] = []
        self._allowed: list[re.Pattern[str]] = []

    @classmethod
    def for_context(cls, context: BrowserContext) -> PageWatch:
        """A watch wired to ``context``: the CSP hook runs in every page and frame of it."""
        watch = cls()
        context.expose_function(CSP_BINDING, watch.record_csp)
        context.add_init_script(CSP_HOOK)
        return watch

    # ------------------------------------------------------------------ collecting

    def adopt(self, page: Page) -> WatchedPage:
        """Listen on ``page`` and turn it into a ``WatchedPage`` (the same object)."""
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("crash", lambda crashed: self.events.append(f"crash: {crashed.url}"))
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)
        page.__class__ = WatchedPage
        watched = cast("WatchedPage", page)
        watched.watch = self
        return watched

    def record_csp(self, detail: str) -> None:
        self.csp.append(detail)

    def _on_console(self, message: ConsoleMessage) -> None:
        if message.type in WATCHED_CONSOLE_TYPES:
            where = message.location.get("url", "")
            self.events.append(f"console.{message.type}: {message.text} @ {where}")

    def _on_page_error(self, error: PlaywrightError) -> None:
        self.events.append(f"pageerror: {error.name}: {error.message}")

    def _on_request_failed(self, request: Request) -> None:
        failure = request.failure or "unknown failure"
        if ABORTED not in failure:
            self.events.append(f"requestfailed: {request.method} {request.url} {failure}")

    def _on_response(self, response: Response) -> None:
        if response.status >= HTTP_ERROR_FROM:
            request = response.request
            self.events.append(f"http {response.status}: {request.method} {response.url}")

    # ------------------------------------------------------------------ allow-list

    def allow_errors(self, *patterns: str) -> None:
        """Do not treat the lines matching any of the regexes (``re.search``) as problems."""
        self._allowed.extend(re.compile(pattern) for pattern in patterns)

    def allow_http(self, status: int, path: str = "") -> None:
        """Allow the ``status`` response for URLs containing ``path`` and Chrome's console line."""
        where = re.escape(path)
        self.allow_errors(
            rf"^http {status}: \w+ \S*{where}",
            rf"^console\.error: {re.escape(CHROME_RESOURCE_ERROR)} {status}\b.*{where}",
        )

    # ------------------------------------------------------------------ verdict

    def matching(self, pattern: str) -> list[str]:
        """The lines seen (allowed or not) that match the regex ``pattern``."""
        compiled = re.compile(pattern)
        return [line for line in self.events if compiled.search(line)]

    def problems(self) -> list[str]:
        """The lines no allow pattern matches, then the CSP violations."""
        loud = [line for line in self.events if not self._is_allowed(line)]
        return [*loud, *(f"csp: {line}" for line in self.csp)]

    def _is_allowed(self, line: str) -> bool:
        return any(pattern.search(line) for pattern in self._allowed)

    def report(self) -> str:
        """Every line, one per row, marked ``ALLOWED`` when an allow pattern covers it."""
        rows = [
            ("ALLOWED " if self._is_allowed(line) else "PROBLEM ") + line for line in self.events
        ]
        return "\n".join([*rows, *(f"PROBLEM csp: {line}" for line in self.csp)])

    def assert_clean(self) -> None:
        problems = self.problems()
        assert not problems, "the browser reported problems:\n" + "\n".join(problems)

    def flush(self, page: Page) -> None:
        """One protocol round trip, so events already sent by the browser are delivered."""
        try:
            page.evaluate("0")
        except PlaywrightError:
            return  # the page is closed or navigating away: nothing more will be reported


class WatchedPage(Page):
    """A Playwright ``Page`` plus the watcher API (see the module doc).

    Only ever created by ``PageWatch.adopt``, which switches the class of a real page: this body
    adds methods and the ``watch`` attribute, nothing else.
    """

    watch: PageWatch

    def allow_errors(self, *patterns: str) -> None:
        self.watch.allow_errors(*patterns)

    def allow_http(self, status: int, path: str = "") -> None:
        self.watch.allow_http(status, path)

    def new_tab(self) -> WatchedPage:
        """Another page of the same context, watched by the same ``PageWatch``."""
        return self.watch.adopt(self.context.new_page())
