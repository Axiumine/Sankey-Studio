"""``Hold``: make chosen API requests of a page slow, deterministically, from inside the page.

``page.route`` handlers only run while the test calls into Playwright, so a request "held" there
cannot be released at an exact moment of the test. This helper installs an init script that wraps
``window.fetch`` instead: while a pattern is set, matching requests do not reach the network until
the test releases them. The page's own ``AbortController`` is honoured (an aborted request rejects
with ``AbortError`` exactly as a real fetch would), so "the app cancelled the stale request" is
observable as ``Hold.aborted(index)``.

Usage (install BEFORE the first ``goto``)::

    hold = Hold(page)  # or Hold(page, "/render"): hold from the very first load
    hold.start("/api/v1/preview")  # requests whose URL contains this text are held from now on
    ...  # provoke a request
    hold.wait_for(1)  # one request is being held (bounded poll)
    hold.release(0)  # let it go
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from tests.e2e.support.ui_b_common import poll_js

if TYPE_CHECKING:
    from playwright.sync_api import Page

INIT_SCRIPT: Final = """
(() => {
  const real = window.fetch.bind(window);
  const state = { pattern: __PATTERN__, held: [] };
  window.__hold = state;
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    if (state.pattern === null || !url.includes(state.pattern)) {
      return real(input, init);
    }
    return new Promise((resolve, reject) => {
      const entry = { url, aborted: false, released: false };
      entry.release = () => { entry.released = true; real(input, init).then(resolve, reject); };
      state.held.push(entry);
      const signal = init && init.signal;
      if (signal) {
        signal.addEventListener('abort', () => {
          entry.aborted = true;
          reject(new DOMException('The operation was aborted.', 'AbortError'));
        });
      }
    });
  };
})();
"""


class Hold:
    """Controls the held requests of one page (see the module doc)."""

    def __init__(self, page: Page, pattern: str | None = None) -> None:
        """Install the wrapper; ``pattern`` starts holding at once (also for the first load)."""
        self.page = page
        page.add_init_script(INIT_SCRIPT.replace("__PATTERN__", json.dumps(pattern)))

    def start(self, pattern: str) -> None:
        self.page.evaluate("pattern => { window.__hold.pattern = pattern; }", pattern)

    def wait_for(self, count: int) -> None:
        """Wait until ``count`` requests have been held since the start."""
        poll_js(self.page, f"window.__hold.held.length >= {count}", what=f"{count} held requests")

    def aborted(self, index: int) -> bool:
        return bool(self.page.evaluate("i => window.__hold.held[i].aborted", index))

    def release(self, index: int) -> None:
        self.page.evaluate("i => window.__hold.held[i].release()", index)
