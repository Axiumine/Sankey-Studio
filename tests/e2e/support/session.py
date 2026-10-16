# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``PageFactory``: the pages of ONE test, their failure artefacts and the clean-browser check.

``open(server, color_scheme=..., viewport=...)`` creates a fresh browser context for the test
(tracing on, CSP hook and collectors from ``PageWatch``) and returns its first ``WatchedPage``.
``finish(failed=...)`` runs at fixture teardown:

1. a protocol round trip per page delivers the events the browser already sent;
2. when the test failed, or the browser reported problems, ``.e2e-artifacts/<test-id>/`` (the
   directory ``$E2E_ARTIFACTS_DIR`` when that is set, read at import) gets a
   screenshot of every open page (``page-<context>-<page>.png``), the Playwright trace
   (``trace-<context>.zip``: ``playwright show-trace``) and ``problems-<context>.txt`` (every
   console, page error, network and CSP line, marked ALLOWED or PROBLEM). Git-ignored;
3. every context is closed (no leaked browser state, downloads removed);
4. a test that passed but left problems fails with the list (an error at teardown).
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from playwright.sync_api import Error as PlaywrightError

from tests.e2e.support.browser import ColorScheme, ContextSettings, new_context
from tests.e2e.support.watch import PageWatch

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, ViewportSize

    from tests.e2e.support.server import LiveServer
    from tests.e2e.support.watch import WatchedPage

ARTIFACTS_ENV: Final = "E2E_ARTIFACTS_DIR"
ARTIFACTS_DIR: Final = Path(
    os.environ.get(ARTIFACTS_ENV) or Path(__file__).resolve().parents[3] / ".e2e-artifacts"
)
SLUG_MAX: Final = 150


def artifact_slug(nodeid: str) -> str:
    """A directory name for a pytest node id (path separators and brackets become ``_``)."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid).strip("_")[-SLUG_MAX:]


class PageOpener(Protocol):
    """The ``open_page`` fixture: a watched page of a fresh context, pointed at ``server``."""

    def __call__(
        self, server: LiveServer, *, color_scheme: ColorScheme, viewport: ViewportSize
    ) -> WatchedPage: ...


@dataclass(slots=True)
class OpenedContext:
    context: BrowserContext
    watch: PageWatch


class PageFactory:
    """Creates the pages of one test and cleans up after them (see the module doc)."""

    def __init__(self, browser: Browser, artifacts: Path) -> None:
        self.browser = browser
        self.artifacts = artifacts
        self._opened: list[OpenedContext] = []

    def open(
        self, server: LiveServer, *, color_scheme: ColorScheme, viewport: ViewportSize
    ) -> WatchedPage:
        settings = ContextSettings(server.url, color_scheme, viewport)
        context = new_context(self.browser, settings)
        watch = PageWatch.for_context(context)
        context.tracing.start(screenshots=True, snapshots=True)
        self._opened.append(OpenedContext(context, watch))
        return watch.adopt(context.new_page())

    def finish(self, *, failed: bool) -> None:
        opened, self._opened = self._opened, []
        for item in opened:
            for page in item.context.pages:
                item.watch.flush(page)
        problems = [line for item in opened for line in item.watch.problems()]
        keep = failed or bool(problems)
        if keep:
            shutil.rmtree(self.artifacts, ignore_errors=True)
        for index, item in enumerate(opened):
            self._close(item, index, keep=keep)
        assert not problems or failed, "the browser reported problems:\n" + "\n".join(problems)

    def _close(self, item: OpenedContext, index: int, *, keep: bool) -> None:
        if keep:
            self.artifacts.mkdir(parents=True, exist_ok=True)
            self._screenshots(item.context, index)
            (self.artifacts / f"problems-{index}.txt").write_text(item.watch.report() + "\n")
            item.context.tracing.stop(path=self.artifacts / f"trace-{index}.zip")
        else:
            item.context.tracing.stop()
        item.context.close()

    def _screenshots(self, context: BrowserContext, index: int) -> None:
        for number, page in enumerate(context.pages):
            try:
                page.screenshot(path=self.artifacts / f"page-{index}-{number}.png")
            except PlaywrightError:
                continue  # the page is closed or crashed: the trace still has its history
