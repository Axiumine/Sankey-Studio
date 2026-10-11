"""``wait_until``: bounded polling for conditions that are not in a browser.

Browser state is waited for with Playwright's ``expect`` / auto-wait (see ``uiwait``), never with
this helper and never with a sleep. ``wait_until`` is for the rest: a server that has started, a
file that appeared, an HTTP resource that reaches a state. It polls a probe until it returns a
truthy value and fails with a message that names what was awaited and the last value seen.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

#: Never set: ``wait`` is the bounded pause between two probes (the one place that pauses).
_TICK: Final = threading.Event()
DEFAULT_TIMEOUT_S: Final = 10.0
DEFAULT_INTERVAL_S: Final = 0.05


def wait_until[T](
    probe: Callable[[], T],
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    what: str = "the condition",
    interval: float = DEFAULT_INTERVAL_S,
) -> T:
    """Call ``probe`` until it returns a truthy value and return that value.

    Raises ``AssertionError`` (``timed out after Ns waiting for <what>; last value: ...``) once
    ``timeout`` seconds have passed. The probe runs at least once, also with ``timeout=0``.
    """
    deadline = time.monotonic() + timeout
    while True:
        value = probe()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"timed out after {timeout:g}s waiting for {what}; last: {value!r}"
            )
        _TICK.wait(interval)
