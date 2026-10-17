# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Helpers shared by the text-source and managed-files test modules."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest

from sankey_studio.models import RawLink, TextSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from sankey_studio.sources.base import SourceContext


#: The stack of the thread ``in_small_stack`` uses: small enough for any decoder to run out of it.
SMALL_STACK: Final = 1 << 20


def in_small_stack[T](call: Callable[[], T]) -> T:
    """Run ``call`` in a thread whose stack is 1 MiB and return (or raise) what it does.

    Python guards deep recursion in C code (the JSON decoder) by the stack the thread really has.
    The process default is 8 MiB in a shell but larger, or unlimited, on some hosts (a hosted CI
    runner), and then a 100,000-deep document is decoded without error. A thread of a fixed small
    size makes the guard fire the same way everywhere.
    """
    outcome: list[T | Exception] = []

    def target() -> None:
        try:
            outcome.append(call())
        except Exception as exc:  # noqa: BLE001 - handed back and raised again in the caller
            outcome.append(exc)

    previous = threading.stack_size(SMALL_STACK)
    try:
        worker = threading.Thread(target=target)
        worker.start()
        worker.join()
    finally:
        threading.stack_size(previous)
    result = outcome[0]
    if isinstance(result, Exception):
        raise result
    return result


class Outcome(NamedTuple):
    """Everything one load produced."""

    rows: list[RawLink]
    warnings: list[str]
    skipped: int


def load(ctx: SourceContext, spec: TextSource) -> Outcome:
    diag = Diagnostics()
    rows = list(open_source(spec, ctx).iter_links(diag))
    return Outcome(rows, diag.finish(), diag.skipped)


def inline(ctx: SourceContext, content: str, **fields: Any) -> Outcome:
    """Load pasted ``content`` with the given ``TextSource`` fields."""
    return load(ctx, TextSource(content=content, **fields))


def of_file(ctx: SourceContext, path: str, **fields: Any) -> Outcome:
    """Load the managed file ``path`` (relative to the context's sources dir)."""
    return load(ctx, TextSource(origin="file", path=path, **fields))


def put(ctx: SourceContext, rel: str, data: bytes | str) -> Path:
    """Create ``rel`` under the context's sources dir (parents included)."""
    path = ctx.sources_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8", newline="")
    else:
        path.write_bytes(data)
    return path


def open_fd_count() -> int:
    """Number of descriptors this process holds (skips the test where /proc is absent)."""
    proc = Path("/proc/self/fd")
    if not proc.is_dir():
        pytest.skip("needs /proc/self/fd to count descriptors")
    return sum(1 for _ in proc.iterdir())


def message_of(call: Callable[[], object], error: type[Exception]) -> str:
    """The exact message of the ``error`` that ``call()`` raises."""
    with pytest.raises(error) as info:
        call()
    return str(info.value)


def record(monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str) -> list[dict[str, Any]]:
    """Wrap ``module.name`` so that the keyword arguments of every call are appended."""
    real: Callable[..., Any] = getattr(module, name)
    calls: list[dict[str, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, spy)
    return calls
