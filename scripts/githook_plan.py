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

Tiers are cumulative groups of checks (``release`` is everything):

* ``commit``   fast
* ``push``     commit + cov, memray, e2e
* ``main``     push + security
* ``release``  main + e2e-mongo, e2e-mongo-rs, qodana, mutation

A pushed ref needs the ``release`` tier when its REMOTE name is ``refs/heads/main`` or starts
with ``refs/tags/``, and the ``push`` tier otherwise. Deletions need nothing.
"""

from __future__ import annotations

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


def make(target: str, *, junit: bool = False, allow_skips: tuple[str, ...] = ()) -> Step:
    return Step(("make", target), junit=junit, allow_skips=allow_skips)


#: The 8 mongo-marked unit tests skip inside ``cov`` without the URI; ``e2e-mongo`` runs them.
COV_STEP: Final = make("cov", junit=True, allow_skips=(MONGO_ENV,))

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
        ),
        Check("e2e-mongo", (make("e2e-mongo", junit=True),), mongo=True),
        # No Docker: the replica set is the user's own. Without its URI the tests skip, and a skip
        # fails the check; an unreachable set fails the tests. Either way the push is refused.
        Check("e2e-mongo-rs", (make("e2e-mongo-rs", junit=True),)),
        Check("qodana", (COV_STEP, make("qodana"))),
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


def stamp_key(check: Check, tree: str, today: date) -> str:
    """File name of a stamp: the tree hash, plus the UTC date for a dated check."""
    return f"{tree}.{today:%Y%m%d}" if check.dated else tree


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
