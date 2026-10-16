# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""``chrome_descendants``: the Chrome processes started (directly or not) by this very process.

The image exports start Chrome through kaleido from the test process (the server runs in a
thread of it). A leak shows up as a process that is still a descendant of ``os.getpid()`` after
the exports are done. Only OUR descendants are looked at, never other users of the machine or
other test sessions that run a browser of their own at the same time.

A process is a browser by its kernel name (``/proc/<pid>/comm``, the program that was started),
NOT by its command line: Chrome rewrites its own command line into one string without NUL
separators, so ``argv[0]`` of its helpers is the whole line. One browser is a tree of about ten
processes; ``browser_roots`` counts the browsers (the processes whose parent is not a browser).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

PROC: Final = Path("/proc")
BROWSER_NAMES: Final = ("chrome", "chromium", "headless_shell")


def have_proc() -> bool:
    """True where ``/proc`` can be read (Linux)."""
    return (PROC / str(os.getpid()) / "stat").is_file()


def _parent_of(pid: int) -> int | None:
    try:
        stat = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None  # the process ended meanwhile
    return int(stat.rsplit(")", 1)[1].split()[1])  # "pid (name) state ppid ..."


def _name_of(pid: int) -> str:
    """The program name the kernel knows (at most 15 characters); ``""`` once it has ended."""
    try:
        return (PROC / str(pid) / "comm").read_text().strip().lower()
    except OSError:
        return ""


def descendants(root: int) -> set[int]:
    """Every process below ``root`` (children, grandchildren, ...)."""
    children: dict[int, list[int]] = {}
    for entry in PROC.iterdir():
        if entry.name.isdigit():
            parent = _parent_of(int(entry.name))
            if parent is not None:
                children.setdefault(parent, []).append(int(entry.name))
    found: set[int] = set()
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def chrome_descendants() -> set[int]:
    """The pids of this process's descendants whose program name looks like a Chrome."""
    names = {pid: _name_of(pid) for pid in descendants(os.getpid())}
    return {pid for pid, name in names.items() if any(mark in name for mark in BROWSER_NAMES)}


def roots_among(pids: set[int], parent_of: Callable[[int], int | None]) -> set[int]:
    """The members of ``pids`` whose parent is not a member: one per tree, i.e. per browser."""
    return {pid for pid in pids if parent_of(pid) not in pids}


def browser_roots() -> set[int]:
    """The Chrome processes that no other Chrome process started: one per browser."""
    return roots_among(chrome_descendants(), _parent_of)


class BrowserWatch:
    """Samples ``browser_roots()`` in a thread; ``peak`` is the most browsers seen at once.

    ``with BrowserWatch(ignore=before) as watch: ...`` counts only the browsers that were not
    there already (``ignore`` holds their root pids). The 10 ms sampling is far finer than the
    second a Chrome export takes.
    """

    def __init__(self, ignore: set[int], interval: float = 0.01) -> None:
        self.ignore = ignore
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, name="browser-watch", daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, len(browser_roots() - self.ignore))
            self._stop.wait(self.interval)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()
