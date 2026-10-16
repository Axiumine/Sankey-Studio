# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Every line the gate prints on a refusal or a failure (templates for ``str.format``)."""

from __future__ import annotations

from typing import Final

BUSY: Final = "gate: another gate run holds {lock} ({holder}); wait for it to finish"
OFFLINE: Final = (
    "gate: refusing to run {check}: {name} is set; offline switches weaken the scans, unset it"
)
NOT_CHECKED_OUT: Final = (
    "gate: refusing to run checks: HEAD is not the commit being pushed\n"
    "gate:   {ref} ({sha}) needs {checks}; its tree is {tree} but the tree of HEAD is {head}\n"
    "gate: check it out ({checkout}) and push again"
)
DIRTY_TREE: Final = (
    "gate: refusing to run checks: the working tree is not clean "
    "(git status --porcelain --untracked-files=all):\n"
    "{lines}\n"
    "gate: commit your changes or stash them (git stash -u) and push again"
)
FAILED: Final = "gate: FAILED {check} (exit {code}); log: {log}"
CHANGED: Final = (
    "gate: FAILED {check}: the working tree changed while it ran, no stamp written; log: {log}"
)
JUNIT: Final = "gate: {check}: junit: {problem}"
MONGO_NOT_OURS: Final = (
    "gate: mongo: a project Mongo container may already exist (make mongo-absent failed) but does "
    "not answer yet; waiting {seconds} s for it, it is never stopped by the gate"
)
MONGO_DOWN: Final = "gate: {check}: the project MongoDB on 127.0.0.1:27117 did not answer"
PUSH_REFUSED: Final = (
    "gate: push refused: {check} failed (exit {code}); checks that passed keep their stamps"
)
MOVED: Final = (
    "gate: FAILED {check}: the working tree is no longer the one the run started with "
    "(tree or git status changed before the check began); nothing was run, no stamp written"
)
NOT_STAMPED: Final = (
    "gate: push refused: {check} passed but left no stamp for tree {tree}; run the push again"
)
PREFLIGHT_REFUSED: Final = (
    "gate: push refused: {probe} failed (exit {code}); no check was started. "
    "Fix what it reports and push again"
)
COMMIT_REFUSED: Final = "gate: commit refused: {check} failed (exit {code})"
COMMIT_NOT_RUN: Final = "gate: commit refused: {check} did not run (see the line above)"
MESSAGE_BAD: Final = "gate: commit message of {sha} is refused by .githooks/commit-msg:\n{output}"
MESSAGE_HOOK_UNUSABLE: Final = "{hook} cannot be run (bash or the hook is missing)"
INTERRUPTED: Final = "gate: interrupted (signal {signum}); no stamp written for the running check"
INTERNAL: Final = "gate: refusing: {error}"
PUSH_DRY_RUN: Final = "gate: git push --dry-run: nothing is run and nothing is pushed"
DRY_PENDING: Final = "gate: dry run: {count} check(s) would run, nothing was run"
