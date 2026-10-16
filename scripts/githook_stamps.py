# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Stamps (proof that a check passed on a tree) and the one-gate-at-a-time lock.

A stamp is a small JSON file at ``<git-common-dir>/hook-stamps/<check>/<key>`` where ``key`` is
the tree hash (plus ``.YYYYMMDD`` in UTC for a dated check). It is written through a temporary
file in the same directory and ``rename``, so a reader sees all of it or none of it.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from types import TracebackType

STAMP_VERSION = 1


@dataclass(frozen=True, slots=True)
class StepTiming:
    argv: tuple[str, ...]
    exit_code: int
    duration_s: float


@dataclass(frozen=True, slots=True)
class Stamp:
    check: str
    key: str
    tree: str
    finished_utc: str
    duration_s: float
    steps: tuple[StepTiming, ...]

    def to_json(self) -> str:
        payload = {
            "version": STAMP_VERSION,
            "check": self.check,
            "key": self.key,
            "tree": self.tree,
            "finished_utc": self.finished_utc,
            "duration_s": round(self.duration_s, 3),
            "steps": [
                {"argv": list(s.argv), "exit": s.exit_code, "duration_s": round(s.duration_s, 3)}
                for s in self.steps
            ],
        }
        return json.dumps(payload, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Parse a stamp; anything unexpected raises ``ValueError`` (the caller re-runs)."""
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("version") != STAMP_VERSION:
            raise ValueError("not a version 1 stamp")
        steps = tuple(
            StepTiming(tuple(map(str, s["argv"])), int(s["exit"]), float(s["duration_s"]))
            for s in data["steps"]
        )
        return cls(
            str(data["check"]),
            str(data["key"]),
            str(data["tree"]),
            str(data["finished_utc"]),
            float(data["duration_s"]),
            steps,
        )


@dataclass(frozen=True, slots=True)
class StampStore:
    base: Path

    def path(self, check: str, key: str) -> Path:
        return self.base / check / key

    def read(self, check: str, key: str) -> Stamp | None:
        """The stamp for ``check`` and ``key``; missing, unreadable or foreign files give None."""
        try:
            stamp = Stamp.from_json(self.path(check, key).read_text(encoding="utf-8"))
        except OSError, ValueError, KeyError, TypeError:
            return None
        return stamp if (stamp.check, stamp.key) == (check, key) else None

    def prepare(self, check: str) -> None:
        """Create the directory of ``check`` and prove a file can be made in it (else OSError).

        Called before a check runs, so a stamp directory that cannot be written fails at once
        and not after a long ``cov`` or ``e2e`` run.
        """
        directory = self.base / check
        directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=directory, prefix=".probe-")
        os.close(fd)
        Path(name).unlink()

    def write(self, stamp: Stamp) -> Path:
        """Atomically create the stamp file (temp file in the same directory, fsync, rename)."""
        target = self.path(stamp.check, stamp.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(stamp.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(target)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        return target


class GateBusyError(RuntimeError):
    """Another gate run holds the lock; the message names the holder."""


class GateLock:
    """Exclusive ``flock`` on a file in the git common dir; the holder writes who it is."""

    def __init__(self, path: Path, holder: str) -> None:
        self.path = path
        self.holder = holder
        self._fd: int | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held_by = os.pread(fd, 4096, 0).decode("utf-8", "replace").strip() or "unknown holder"
            os.close(fd)
            raise GateBusyError(held_by) from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{self.holder}\n".encode(), 0)
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            os.ftruncate(self._fd, 0)
            os.close(self._fd)
            self._fd = None
