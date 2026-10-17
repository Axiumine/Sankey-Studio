# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Pure planner of the git-hook gate: which checks a hook or a pushed ref requires. No I/O.

Checks (the units that get a stamp), in the order they run:

* ``fast``       lint + typecheck + caps
* ``cov``        unit suite with 100% line and branch coverage
* ``memray``     memory-budget tests
* ``e2e``        end-to-end suite (5 shards)
* ``security``   semgrep-test + semgrep + trivy (the stamp key carries the UTC date)
* ``e2e-mongo``  both real-MongoDB selections against the project-local Mongo
* ``e2e-mongo-rs``  the same flows against the user's replica set (``SANKEY_TEST_MONGO_RS_URI``
                    from the environment or the repo-root ``.env``, read by the tests only)
* ``qodana``     a fresh ``make cov`` and then ``make qodana`` (before mutation: it fails sooner)
* ``mutation``   ``make mutate`` then ``make mutate-gate`` as one unit (never a stale mutants/)

Some checks need something from the machine that a 30 minute run should not discover at the end:
``Check.needs`` names the quick probes (``PREFLIGHTS``: Docker answers, ``QODANA_TOKEN`` is set,
the replica set answers) that run, in seconds and unstamped, before the first long check of a
run. A failing probe refuses the push or the commit at once.

Tiers are cumulative groups of checks (``release`` is everything):

* ``commit``   fast
* ``push``     commit + cov, memray, e2e
* ``main``     push + security
* ``release``  main + e2e-mongo, e2e-mongo-rs, qodana, mutation

A pushed ref needs the ``release`` tier when its REMOTE name is ``refs/heads/main`` or starts
with ``refs/tags/``, and the ``push`` tier otherwise. Deletions need nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

MONGO_ENV: Final = "SANKEY_TEST_MONGO_URI"
MONGO_URI: Final = "mongodb://127.0.0.1:27117"
MAIN_REF: Final = "refs/heads/main"
TAG_PREFIX: Final = "refs/tags/"


class Tier(StrEnum):
    COMMIT = "commit"
    PUSH = "push"
    MAIN = "main"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class Step:
    """One command of a check.

    ``junit`` steps get ``JUNIT=<report path>`` appended (the Makefile turns it into
    ``--junitxml``) and their reports are verified: any skipped test fails the step, except a
    skip whose reason contains one of ``allow_skips``. Every step runs with ``UV_LOCKED=1``
    except ``uv_locked=False`` ones (``uv run --no-project`` warns that the variable is useless).
    """

    argv: tuple[str, ...]
    junit: bool = False
    allow_skips: tuple[str, ...] = ()
    uv_locked: bool = True


@dataclass(frozen=True, slots=True)
class Check:
    """A stamped unit: its steps run in order and the first failure fails the check."""

    name: str
    steps: tuple[Step, ...]
    dated: bool = False
    mongo: bool = False
    offline_guard: bool = False
    needs: tuple[str, ...] = ()


def make(target: str, *, junit: bool = False, allow_skips: tuple[str, ...] = ()) -> Step:
    return Step(("make", target), junit=junit, allow_skips=allow_skips)


#: The 8 mongo-marked unit tests skip inside ``cov`` without the URI; ``e2e-mongo`` runs them.
COV_STEP: Final = make("cov", junit=True, allow_skips=(MONGO_ENV,))

DOCKER_PROBE: Final = "preflight-docker"
QODANA_PROBE: Final = "preflight-qodana"
RS_PROBE: Final = "preflight-rs"

#: The quick probes of the machine (never stamped, never part of a tier): ``make <name>``.
#: ``preflight-rs`` runs one cheap replica-set test, so a missing URI is a skip and fails.
PREFLIGHTS: Final[dict[str, Check]] = {
    check.name: check
    for check in (
        Check(DOCKER_PROBE, (make(DOCKER_PROBE),)),
        Check(QODANA_PROBE, (make(QODANA_PROBE),)),
        Check(RS_PROBE, (make(RS_PROBE, junit=True),)),
    )
}
PREFLIGHT_ORDER: Final = tuple(PREFLIGHTS)

CHECKS: Final[dict[str, Check]] = {
    check.name: check
    for check in (
        Check("fast", (make("lint"), make("typecheck"), Step(("make", "caps"), uv_locked=False))),
        Check("cov", (COV_STEP,)),
        Check("memray", (make("memray", junit=True),)),
        Check("e2e", (make("e2e", junit=True),)),
        Check(
            "security",
            (make("semgrep-test"), make("semgrep"), make("trivy")),
            dated=True,
            offline_guard=True,
            needs=(DOCKER_PROBE,),
        ),
        Check("e2e-mongo", (make("e2e-mongo", junit=True),), mongo=True, needs=(DOCKER_PROBE,)),
        # The replica set is the user's own (no Docker). Without its URI the tests skip, and a skip
        # fails the check; an unreachable set fails the tests. Either way the push is refused.
        Check("e2e-mongo-rs", (make("e2e-mongo-rs", junit=True),), needs=(RS_PROBE,)),
        Check("qodana", (COV_STEP, make("qodana")), needs=(DOCKER_PROBE, QODANA_PROBE)),
        Check("mutation", (make("mutate"), make("mutate-gate"))),
    )
}

CHECK_ORDER: Final = tuple(CHECKS)

TIER_CHECKS: Final[dict[Tier, tuple[str, ...]]] = {
    Tier.COMMIT: ("fast",),
    Tier.PUSH: ("fast", "cov", "memray", "e2e"),
    Tier.MAIN: ("fast", "cov", "memray", "e2e", "security"),
    Tier.RELEASE: CHECK_ORDER,
}


class UnknownNameError(ValueError):
    """A name that is neither a check nor a tier (the message lists the valid ones)."""


def resolve_names(names: Iterable[str]) -> tuple[str, ...]:
    """Tier and check names to a de-duplicated tuple of check names in run order."""
    wanted: set[str] = set()
    for name in names:
        if name in CHECKS:
            wanted.add(name)
        elif name in {tier.value for tier in Tier}:
            wanted.update(TIER_CHECKS[Tier(name)])
        else:
            known = ", ".join([*CHECKS, *(tier.value for tier in Tier)])
            raise UnknownNameError(f"unknown check or tier {name!r}; use one of: {known}")
    return tuple(name for name in CHECK_ORDER if name in wanted)


#: Files no check reads, so a change to them leaves every stamp valid: Markdown anywhere but
#: ``src/``, the images under ``docs/`` and the root ``LICENSE``. No test or script reads them (see
#: docs/quality.md, "Git hooks"); one that starts to must take its file type out of this rule.
INERT_IMAGE_SUFFIXES: Final = (".png", ".jpg", ".jpeg", ".gif", ".webp")
INERT_IMAGE_DIR: Final = "docs/"
INERT_FILE: Final = "LICENSE"
SHIPPED_DIR: Final = "src/"


def is_inert(path: str) -> bool:
    """True for a file no check reads: Markdown outside ``src/``, ``docs/`` images, ``LICENSE``."""
    lowered = path.lower()
    if lowered.startswith(SHIPPED_DIR):
        return False
    return (
        path == INERT_FILE
        or lowered.endswith(".md")
        or (lowered.startswith(INERT_IMAGE_DIR) and lowered.endswith(INERT_IMAGE_SUFFIXES))
    )


def scoped_key(entries: Iterable[str]) -> str:
    """The stamp key of a tree, from its ``git ls-tree -r -z`` entries without the inert files.

    ``<mode> <type> <sha>\t<path>`` per entry. Two trees that differ only in inert files (a new
    screenshot, an edited README) have the same key, so the stamps of the first count for the
    second; any other change, even a mode, gives another key.
    """
    kept = sorted(entry for entry in entries if entry and not is_inert(entry.partition("\t")[2]))
    return hashlib.sha256("\n".join(kept).encode()).hexdigest()


def stamp_key(check: Check, key: str, today: date) -> str:
    """File name of a stamp: the scoped key of the tree, plus the UTC date for a dated check."""
    return f"{key}.{today:%Y%m%d}" if check.dated else key


def is_zero_sha(sha: str) -> bool:
    return bool(sha) and set(sha) == {"0"}


@dataclass(frozen=True, slots=True)
class PushedRef:
    """One stdin line of the pre-push hook."""

    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str

    @property
    def is_delete(self) -> bool:
        return is_zero_sha(self.local_sha)


def parse_push_lines(text: str) -> list[PushedRef]:
    """Parse ``<local ref> <local sha> <remote ref> <remote sha>`` lines; bad input raises."""
    refs = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(" ")
        if len(parts) != 4 or not all(parts):
            raise ValueError(f"malformed pre-push line: {line!r}")
        refs.append(PushedRef(*parts))
    return refs


def tier_for_remote_ref(remote_ref: str) -> Tier:
    """``release`` for main and tags (by the name on the REMOTE side), ``push`` otherwise."""
    if remote_ref == MAIN_REF or remote_ref.startswith(TAG_PREFIX):
        return Tier.RELEASE
    return Tier.PUSH


@dataclass(frozen=True, slots=True)
class RefPlan:
    ref: PushedRef
    tier: Tier
    checks: tuple[str, ...]


def plan_push(refs: Iterable[PushedRef]) -> list[RefPlan]:
    """The checks each non-delete ref needs; deletions are left out."""
    plans = []
    for ref in refs:
        if ref.is_delete:
            continue
        tier = tier_for_remote_ref(ref.remote_ref)
        plans.append(RefPlan(ref, tier, TIER_CHECKS[tier]))
    return plans
