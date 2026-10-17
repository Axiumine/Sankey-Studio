# Quality gates

Every change must pass these gates. They are all `make` targets, and the git hooks run them (see
[Git hooks](#git-hooks)): a commit runs the fast ones, a push runs the rest. When a rule here and a
looser statement elsewhere disagree, this document wins. Related: [architecture.md](architecture.md),
[decisions.md](decisions.md) (ADR-37 for the hooks), [e2e.md](e2e.md) (end-to-end tests).

Contents

* [Gates at a glance](#gates-at-a-glance)
* [Code caps](#code-caps)
* [Coverage](#coverage)
* [Mutation testing](#mutation-testing)
* [Memory budgets](#memory-budgets)
* [Static analysis](#static-analysis)
* [Scanners](#scanners)
* [Suppression policy](#suppression-policy)
* [Test conventions](#test-conventions)
* [Git hooks](#git-hooks)
* [Commit policy](#commit-policy)
* [Definition of done](#definition-of-done)

## Gates at a glance

| Gate | Command | Threshold | Runs in the hook |
|---|---|---|---|
| Code caps | `make caps` | file 500 lines, function 50, class 300, parameters 4 (`self` and `cls` are free), nesting 4; every `*.py` including tests and scripts; ratcheted against `.code-caps-baseline.json` | `fast`: pre-commit, pre-merge-commit, every pre-push |
| Lint and format | `make lint` | `ruff check` with `select = ["ALL"]` and `ruff format --check` on `src tests scripts` | `fast` |
| Types | `make typecheck` | `mypy --strict` on Python 3.14 | `fast` |
| Unit tests | `make test` | `pytest -m "not memory and not e2e"`, `filterwarnings = error`, no sleeps | none: `cov` runs the same selection |
| End-to-end | `make e2e`, `make e2e-mongo`, `make e2e-mongo-rs` | `pytest -m "e2e and not mongo and not mongo_rs"`: the real app on an ephemeral loopback port driven over HTTP and by real Chrome; `e2e-mongo` runs the same flows against a real MongoDB and then the mongo-marked unit tests; `e2e-mongo-rs` runs them against a replica set you run yourself (`SANKEY_TEST_MONGO_RS_URI`); see [e2e.md](e2e.md) | `e2e`: every pre-push. `e2e-mongo`: pre-push of `main` and tags. `e2e-mongo-rs`: pre-push of `main` and tags |
| Coverage | `make cov` | 100% line and branch of `src/sankey_studio` from the unit suite, slow tests included, e2e excluded | `cov`: every pre-push (`qodana` runs it again) |
| Memory | `make memray` | `limit_memory` budgets (pytest-memray) | `memray`: every pre-push |
| Mutation | `make mutate`, `make mutate-gate` | mutmut 3.x score of at least 90 | `mutation`: pre-push of `main` and tags |
| Semgrep | `make semgrep-test`, `make semgrep` | rule tests green, no finding in `src` and `scripts` | `security`: pre-push of `main` and tags |
| Trivy | `make trivy` | no fixed HIGH or CRITICAL vulnerability in the runtime packages of `uv.lock`, no secret, no misconfiguration | `security` |
| Qodana | `make qodana` | Ultimate Plus inspection; needs `QODANA_TOKEN` in a local `.env` | `qodana`: pre-push of `main` and tags; fails without the token |
| Aggregates | `make check`, `make ci`, `make full` | `check` = lint typecheck caps cov memray; `ci` = check plus security and e2e; `full` = ci plus mutate, mutate-gate and qodana | none: the hooks call the single targets (a push of `main` runs `full` plus `e2e-mongo`) |

The hooks fail on any skipped test, so a missing browser or database cannot turn a gate green (see
[Fail-closed rules](#fail-closed-rules)).

Python is 3.14 managed by uv; always run tools as `uv run ...` or through `make`. The sources use
PEP 758 syntax (`except A, B:` without parentheses), which Python 3.13 cannot parse, so never run the
repository's scripts with a bare `python3`.

## Code caps

Measured on the AST of every `*.py` in the repository, tests and scripts included. A value above the
cap is a violation.

| Cap | Limit | Notes |
|---|---|---|
| File | 500 lines | Split a module into a package with a re-exporting `__init__.py` |
| Function | 50 lines | Decorators included |
| Class | 300 lines | Decorators included |
| Parameters | 4 | `self` and `cls` are free; keyword-only parameters count |
| Nesting | 4 | if, for, while, try, with and match levels in one function; `elif` does not deepen |

`make caps` runs `uv run --no-project --python 3.14 python scripts/check_code_caps.py`. It uses a
3.14 interpreter on purpose: the system `python3` may be older and cannot parse the sources.

**Ratchet.** `.code-caps-baseline.json` lists tolerated violations and starts empty. A new or grown
violation fails the check and blocks the commit through the `pre-commit` hook. Never edit the baseline
to hide a violation and never run the script with `--init` or `--force`. `--update-baseline` only
ratchets the baseline down. Fix the code instead.

Design consequences:

* Bundle related options in a frozen `@dataclass(slots=True)` (domain code) or a pydantic model with
  `extra="forbid"` (web query and form models). A fifth value means a new option type, never a fifth
  parameter.
* FastAPI routes take path parameters, one query model, the body and a `Services` dependency.
* Use guard clauses, early returns and table-driven dispatch to keep nesting down.
* Tests obey the same caps: at most 4 parameters or fixtures per test, 50 lines, nesting 4, and 500
  lines per file. Split by topic; a parametrised table takes one `Case` object.
* JavaScript files stay at 300 lines or fewer and functions at 50 or fewer by convention (the caps
  tool only measures Python).

## Coverage

`make cov` runs `pytest -m "not memory and not e2e" --cov` with branch coverage on and writes the terminal report,
`reports/coverage/coverage.xml` and `reports/coverage/html/`. The gate is **100% line and branch** of
`src/sankey_studio` (`fail_under = 100`), with slow tests included and e2e tests excluded. The
threshold itself is reachable without a browser (the tests that need one skip), but the `cov` check
of the hooks fails on any skipped test, so it needs the prerequisites listed under
[Fail-closed rules](#fail-closed-rules). Web templates and static assets are not measured; page
routes are covered by GET tests and exercised by the browser tests.

* Aim for real assertions, not smoke calls. Every error branch is exercised by injecting failures
  with fakes (`PyMongoError`, `OSError`, `UnicodeDecodeError`, kaleido errors, `TimeoutError`).
* Code that needs Chrome, a real Mongo, a clock or a real server keeps a seam that tests
  monkeypatch: `render/export/images.py::_render_image`, `cli.py::_run_server`, the injectable clock
  of `ResultCache`, and `MongoClients(factory=...)`. Real-Chrome tests are extra and carry
  `@pytest.mark.slow`.
* `# pragma: no cover - <reason>` is allowed only for genuinely unreachable defensive code, with a
  reason, at most 5 in the whole repository. `if TYPE_CHECKING:`, `raise NotImplementedError`, bare
  `...` bodies and `if __name__ == "__main__":` are excluded by configuration.

## Mutation testing

`make mutate` runs mutmut 3.x over `src/sankey_studio`, excluding `cli.py` and `__main__.py` (and the
non-Python web assets). It runs the unit tests only (not e2e, slow or memory). `make mutate-gate`
folds the results into a score and fails below **90** (`scripts/mutation_gate.py --min-score 90`; add
`--by-module` for one line per module).

Write tests that fail when a boundary moves:

* Parametrised boundary tables that assert both sides of every limit: pydantic `ge`, `le` and
  `max_length`, `>` versus `>=`, off-by-one in parsers, caps and TTLs.
* Defaults, exact error codes and messages, ordering, and the exact arguments a fake received.
* Prefer one parametrised table over many near-identical tests. An equivalent mutant is acceptable
  only with a one-line justification.

Two blind spots of mutmut are covered by hand and must stay covered: it does not mutate decorated
functions (pydantic validators, properties, context managers) or module and class constants. So every
validator that carries its own message has an exact-message test, and constants that matter are
pinned by tests that assert their value.

## Memory budgets

`make memray` runs `pytest -m memory --memray --trace-python-allocators`. Tests carry
`@pytest.mark.memory` and `@pytest.mark.limit_memory(...)`. pytest-memray measures only the test body,
so inputs are built in module-scoped fixtures (with a warm-up fixture, because a cold plotly import
costs more than a warm one) and the function under test is called in the body. The budgets cover
`build_graph` on 100k and 200k links, `build_figure` on 20k links and parsing a 50k-row CSV.

`make profile` runs `scripts/profile_memory.py` (a synthetic 200k-link graph through graph building and
rendering) under `memray run`, prints `memray stats` and writes a flamegraph to
`.memray/bench-flamegraph.html`. Run plainly, the script prints the peak resident set size.

## Static analysis

* **CodeQL** (GitHub's default setup for Python and JavaScript, a repository setting and not a file)
  analyses the code on pushes to `main`, on pull requests and weekly; its findings appear in the
  repository's code scanning. It is not a gate (ADR-43).
* **ruff** with `select = ["ALL"]` (documented exceptions in `pyproject.toml`), line length 100,
  `max-args = 4`, mccabe complexity 12. Under `web/**` only the type-checking import rules and
  unused-argument checks are relaxed, because FastAPI resolves annotations at runtime.
* **mypy** in strict mode on `src`, `tests` and `scripts`, with the pydantic plugin and the extra
  error codes `ignore-without-code`, `redundant-expr` and `truthy-bool`. plotly and kaleido ship no
  type information, so values they return are wrapped (`cast` or a typed local).
* **pytest** with `--strict-markers`, `--strict-config` and `filterwarnings = ["error"]`. There are no
  warning ignores; do not add one without a comment naming the package and the exact warning.
* Markers: `mongo` (needs a real MongoDB), `mongo_rs` (needs a real replica set; `make
  e2e-mongo-rs`; only the `e2e-mongo-rs` check of the release gate selects it), `memory`, `slow`,
  `e2e`.

## Scanners

* **Semgrep** (`make semgrep`, `make semgrep-test`) runs in Docker through `scripts/semgrep.sh`.
  Project rules live in `.semgrep/rules/`; registry packs are added unless `SEMGREP_OFFLINE=1`. It
  scans `src` and `scripts`, writes `reports/semgrep.sarif` and prints a readable report. The rules:
  no shell=True, no eval or exec, no OS command injection, no pickle or unsafe YAML; MongoDB writes
  only in the library store (graphs and collections) and the opt-in source write-back, all under `storage/`; no `$where`, `$function`, `$accumulator`, `$out` or `$merge` literals
  outside `mongo_safety.py`; no secrets in logs or exceptions; no outbound HTTP; no unsafe HTML
  (`Markup`, `|safe`, f-string `HTMLResponse`, inline scripts or handlers in templates, DOM XSS sinks
  in JavaScript); no CORS; no wildcard bind or hosts; regex only from escaped text or constants.
  Two generic registry rules are excluded by id in `scripts/semgrep.sh` (inline waivers are
  forbidden in templates): `var-in-href` (hrefs come from a server-side constant table) and
  `var-in-script-tag` (the only variable in a script is the `application/json` boot block, encoded
  with `tojson`). The project rules and the template policy tests still cover those files.
* **Trivy** (`make trivy`) runs the pinned `aquasec/trivy` image through `scripts/trivy.sh` with
  `trivy.yaml`: vulnerabilities in `uv.lock` (HIGH and CRITICAL, fixed ones), secrets,
  misconfigurations. The configuration also lists forbidden licences (GPL-2.0, GPL-3.0, AGPL-3.0, SSPL-1.0), but Trivy
  cannot detect licences in a uv lock file, and it leaves out the packages only the `dev` group needs
  (see [dependencies.md](dependencies.md#trivy)). Accepted findings
  go in `.trivyignore` with a reason and an expiry; keep it empty unless a finding is triaged.
  `TRIVY_OFFLINE=1` reuses the cached database. The weekly GitHub Actions job `trivy-weekly.yml` runs the
  same script. Do not add or bump dependencies casually.
* **Qodana** (`make qodana`) runs the JetBrains Ultimate Plus linter in Docker through
  `scripts/qodana.sh`. It reads `QODANA_TOKEN` from a local `.env` (copy `.env.example`; `.env` is
  gitignored), keeps it in the process environment only, never prints it and uploads results to
  Qodana Cloud. Never read, print or copy `.env`. A missing token is a non-zero exit (2), so the
  `qodana` check of the hooks fails closed. Run `make cov` first (the `qodana` check does, right
  before `make qodana`): only `reports/coverage/coverage.xml` is imported, as a copy in `.qodana/code-coverage` whose `<source>`
  is rewritten to the container path `/data/project`. The IDE needs a Python 3.14 interpreter,
  otherwise it reports valid `X | None` hints, dataclasses and `with lock:` blocks as errors. The
  container user cannot write its HOME and the host `.venv` points at host paths, so the
  `bootstrap` of `qodana.yaml` builds a fresh venv with `uv sync` in the container, into
  `.qodana/venv`; the script mounts that over `/data/project/.venv` and names its python in
  `QODANA_PYTHON_PATH`. The host `.venv` is never touched.
* **GitNexus** indexes the repository for code intelligence (`make gitnexus`, `make gitnexus-status`).
  Use its impact analysis before changing an existing symbol; see the generated block in `CLAUDE.md`.
* **Docker.** Docker is used only through `make semgrep`, `make semgrep-test`, `make trivy`,
  `make qodana`, `make mongo-up`, `make mongo-down` and `make mongo-absent` (the `e2e-mongo` check of
  the hooks runs the last three itself).
* **Offline switches.** `SEMGREP_OFFLINE=1` and `TRIVY_OFFLINE=1` weaken the scans (the first drops
  the registry packs, the second reuses a stale database). The hooks refuse to run `security` while
  any `*_OFFLINE` variable is set.

## Suppression policy

Suppression comments are rationed and checked by `tests/test_policy.py`:

* `# noqa: CODE[, CODE] - <reason>` names the rule codes and says why on the same line. No bare
  `# noqa`, no file-level `# ruff: noqa`, no wildcard.
* `# type: ignore[code]` is allowed only in tests, only with an error code, and only to feed
  deliberately wrong input or prove that a frozen field refuses assignment. Never in `src` or
  `scripts`.
* `# pragma: no cover - <reason>`: see [Coverage](#coverage).
* `# pragma: no mutate block - <reason>` is allowed only on a `Protocol` class.
* `# nosemgrep: <rule-id> -- <reason>` names exactly one rule and a reason, sits on the line of the
  finding and is never used in templates or static files. The waiver of `sankey-no-mongo-writes`
  appears only under `src/sankey_studio/storage/`: in the graph store, the collection store and
  `mongo_source_writes.py` (the opt-in source write-back).
* No `pytest.mark.skip` and no `xfail`. `skipif` and `pytest.skip(...)` only for an absent external
  prerequisite (Chrome, `SANKEY_TEST_MONGO_URI`) and always with a reason. The hooks fail on any
  skipped test anyway, because a skip inside a gate is a gate that did not run. The one exception is
  the 8 mongo-marked unit tests inside `cov` (their skip reason names `SANKEY_TEST_MONGO_URI`); the
  `e2e-mongo` check runs them.

## Test conventions

* Tests mirror the source paths: `tests/sources`, `tests/storage`, `tests/render`, `tests/web`,
  `tests/contracts`, plus top-level `tests/test_*.py` for modules without a sub-directory. A
  `conftest.py` is added only inside a sub-directory.
* `tests/conftest.py` has autouse fixtures that remove every `SANKEY_*` environment variable and
  replace the pymongo client constructor with a tripwire, so no test can open a socket to a real
  server (both are skipped for `@pytest.mark.mongo`). Shared fixtures include `bootstrap`,
  `app_settings`, `mongo_client`, `mongo_clients`, `make_source_ctx`, `source_ctx` and
  `make_connection`.
* Unit tests use mongomock. A real MongoDB is used only by tests marked `@pytest.mark.mongo`, which
  run when `SANKEY_TEST_MONGO_URI` is set and then create and drop a uniquely named database (and by
  the replica-set suite marked `mongo_rs`, which uses the empty database named in
  `SANKEY_TEST_MONGO_RS_URI` and drops its collections; see [e2e.md](e2e.md#replica-set)). The
  project-local Mongo from `make mongo-up` listens on `127.0.0.1:27117`, for example
  `SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117`. The `e2e-mongo` check of the hooks sets it for
  its own steps only and removes it from every other child.
* mongomock gaps (`$unionWith`, `$sortByCount`, `$bucketAuto`, Decimal128 comparison, `serverStatus`)
  are covered by pure `check_pipeline` unit tests or under the `mongo` marker.
* No sleeps. Use barriers, events or an injectable clock.
* License header: every `.py`, `.sh`, `.js`, `.mjs`, `.css` and template `.html` under `src`,
  `tests` and `scripts` starts with `SPDX-License-Identifier: GPL-3.0-only` and
  `Copyright (C) 2026 Giovanni Manzoni` (comment syntax of the file type; a Jinja comment in
  templates, so the page output is unchanged). `uv run python scripts/license_header.py` lists
  the files without it and `--apply` writes it; `tests/test_license_header.py` runs the same
  check, so a new file without the header fails the unit suite. Data and config files, docs,
  the hook shims and the Semgrep fixtures carry no header; `LICENSE` and `pyproject.toml` cover them.
* Hypothesis is not installed; use parametrised tables.
* Build a `go.Figure` from a figure dict only in tests, as a schema check.

## Git hooks

The hooks in `.githooks` are the single place where the gates run ([decisions.md](decisions.md),
ADR-37): a commit runs the fast checks, a push runs the rest. Enable them with `make hooks` (which
`make sync` runs; it sets `core.hooksPath` to `.githooks`) and verify the setup with
`make hooks-check` (`core.hooksPath`, plus mode `100755` of the four hook files in the index and on
disk). `<common>` below is `git rev-parse --git-common-dir`: `.git/` in an ordinary clone, shared by
linked worktrees.

Three hooks are three-line bash shims, `pre-commit`, `pre-merge-commit` and `pre-push`:

```bash
#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"  # uv, also when git is started by a GUI
cd "$(git rev-parse --show-toplevel)" && exec uv run --no-project --python 3.14 python -m scripts.githook_gate pre-push "$@"
```

All logic is in `scripts/githook_gate.py` and the `scripts/githook_*.py` modules next to it (plan,
git, stamps, junit, runner, messages, exec, flows, push), standard library only and bound by the
code caps like every other script. `scripts/mongo_wait.py` pings the Mongo (it needs pymongo, so it
runs with `uv run python`). A shim whose `cd`, `uv` or Python fails exits non-zero, so a broken setup
refuses instead of passing. `commit-msg` stays a bash script.

### Hook map

| Hook | Fires on | Runs | Tree it vouches for |
|---|---|---|---|
| `commit-msg` | commit, amend, merge commit; not `rebase` or `cherry-pick` | the message format, see [Commit policy](#commit-policy) | none |
| `pre-commit` | commit, amend, the commit that concludes a conflicted merge | `fast` | the index (`git write-tree`) |
| `pre-merge-commit` | a clean `merge --no-ff`; not a fast-forward | `fast` | the index |
| `pre-push`, remote ref `refs/heads/main` or `refs/tags/*` | `git push origin main`, `git push origin feature:main`, a tag push | the messages of the new commits, then the `release` tier: `fast`, `cov`, `memray`, `e2e`, `security`, `e2e-mongo`, `e2e-mongo-rs`, `qodana`, `mutation` | the pushed commit (an annotated tag is peeled) |
| `pre-push`, any other remote ref | a branch push | the messages of the new commits, then the `push` tier: `fast`, `cov`, `memray`, `e2e` | the pushed commit |

* The tier follows the name on the REMOTE side of the refspec, so `git push origin feature:main` is a
  `release` push. Deleting a ref checks nothing; a push of nothing ("Everything up-to-date") prints
  `gate: nothing to check, no ref is created or updated` and passes.
* One push of several refs (`--all`, `--tags`) checks every ref; a check is looked up and run once
  per tree, however many refs share it.
* A `--no-ff` merge into an unmoved `main` has the same tree as the branch tip, so the stamps of the
  branch are reused.
* `rebase` and `cherry-pick` fire neither `pre-commit` nor `commit-msg`. `pre-push` covers them: it
  checks the messages of the new commits and the tree being pushed.

### Checks and tiers

A check is the unit that gets a stamp. Checks run in this order, one at a time, each through its
`make` target from the repository root. The Basis column says where a time comes from: *measured*
(timed while writing the gate), *documented* (stated in [e2e.md](e2e.md) before the gate existed),
*recorded locally, unverified* (read from a local artefact of an earlier run; no document states
it) or *unknown*:

| Check | Commands, in order | Time | Basis |
|---|---|---|---|
| `fast` | `make lint`, `make typecheck`, `make caps` | about 1 s warm, about 5 s with a cold mypy cache (lint 0.03 s, typecheck 0.18 s warm and 4.45 s cold, caps 0.59 s) | measured |
| `cov` | `make cov JUNIT=<report>` | about 91 s of summed test time in a local mutmut stats file of an earlier run (not a wall-clock measurement of `cov`); the coverage overhead is not known | recorded locally, unverified |
| `memray` | `make memray JUNIT=<report>` (5 tests) | not known | unknown |
| `e2e` | `make e2e JUNIT=<report>` (5 shards) | under 3 minutes (see [e2e.md](e2e.md#runtime-budget-and-flakiness); the changelog says about 90 s) | documented |
| `security` | `make semgrep-test`, `make semgrep`, `make trivy` | not known (Docker; a Trivy database refresh downloads about 120 MB) | unknown |
| `e2e-mongo` | start the project Mongo if it is not running, `make e2e-mongo JUNIT=<report>`, stop it again | not known | unknown |
| `e2e-mongo-rs` | `make e2e-mongo-rs JUNIT=<report>` against the replica set of `SANKEY_TEST_MONGO_RS_URI` (no Docker, nothing started or stopped) | about 85 s against a replica set on a LAN (95 tests, one local run) | measured once, locally |
| `qodana` | `make cov JUNIT=<report>` (fresh coverage), then `make qodana` | not known (a second coverage run, then a Qodana scan that uploads to Qodana Cloud) | unknown |
| `mutation` | `make mutate`, then `make mutate-gate` | about 19 minutes with 8 workers, from the file times of the last local run (`mutants/`) | recorded locally, unverified |

`qodana` runs before `mutation` on purpose: a missing token or a Qodana gate then fails before the
19 minute mutation run. `mutate` and `mutate-gate` are one check, so the gate never judges a stale
`mutants/`. Tiers are cumulative groups of checks:

| Tier | Checks | Used by |
|---|---|---|
| `commit` | `fast` | `pre-commit`, `pre-merge-commit`, `make gate-commit` |
| `push` | `commit` + `cov`, `memray`, `e2e` | `pre-push` of any ref except `main` and tags, `make gate-push` |
| `main` | `push` + `security` | `make gate-main` only |
| `release` | `main` + `e2e-mongo`, `e2e-mongo-rs`, `qodana`, `mutation` (all nine) | `pre-push` of `main` and tags, `make gate-release` |

**Runtime figures.** Measured: `fast`. Documented: `e2e` (under 3 minutes). Recorded locally and
unverified: the unit suite (about 91 s of test time) and `mutation` (about 19 minutes). Unknown:
`memray`, `security`, `e2e-mongo`, `qodana`, the coverage overhead and every total. On these figures
a `push` run takes about 5 minutes plus `memray` and the coverage overhead, and a `release` run
about 25 minutes plus the four unknown checks; plan for 30 minutes or more. The first real runs measure the unknown ones: every check
prints `gate: <check>: ok in 123.4s` and stores the time of the whole check and of each step in its
stamp (`duration_s`, `steps[].duration_s`). Read them from the output or the stamp and replace the
unknown cells of the table above.

Deliberately not bound to a hook: `make test` (a subset of `cov`), `make e2e-serial` (the same tests
as `e2e` in one process), `make profile` (no pass or fail), `make format` (it rewrites files;
`make lint` checks the format).

### Stamps

* **Where.** `<common>/hook-stamps/<check>/<key>`. The key is a digest of the tree of the commit being
  checked WITHOUT the files no check reads: Markdown outside `src/`, images under `docs/` and the
  root `LICENSE` (`is_inert` in `scripts/githook_plan.py`; no test or script reads them, and one
  that starts to must take its file type out of that rule). A README edit, a new screenshot or a
  license edit therefore keeps every stamp; any other change, a mode included, voids them. For `security` it is `<key>.<YYYYMMDD>` with the UTC date, so that stamp expires at the
  end of the UTC day (the Semgrep packs and the Trivy database change daily). A stamp is keyed on the
  tree, not on the commit: amend, rebase and cherry-pick keep their stamps when the tree is the same.
  It does not record the environment (installed packages, Docker images, Chrome); `uv.lock` is part
  of the tree, so a dependency change changes the key.
* **Content.** JSON: `version` (1), `check`, `key`, `tree`, `finished_utc`, `duration_s` and `steps`
  (`argv`, `exit`, `duration_s` of each step). It is written to a temporary file in the same
  directory, synced and renamed, so a reader sees all of it or none of it. A missing, unreadable or
  foreign stamp (wrong version, or a check or key that differs from its path) counts as missing and
  the check runs.
* **When one is written.** Only after every step exited 0, the JUnit reports are clean, and the tree
  and `git status --porcelain --untracked-files=all` are the same after the run as before it, and
  the run vouches for a known tree. `pre-push` runs only on a clean tree equal to the pushed one, so
  it always stamps. `pre-commit` and `pre-merge-commit` stamp only when the working tree equals the
  index; otherwise the check still runs and passes, and prints `(not stamped: the working tree
  differs from the index)`. `make gate-*` stamps only on a clean tree (`not stamped: the working tree
  is not clean`). A tree that changes during a run is a failure: `gate: FAILED <check>: the working
  tree changed while it ran, no stamp written`.
* **Logs and lock.** The output of the last run of a check is `<common>/hook-logs/<check>.log`
  (rewritten each run; every step starts with a `$ <command>` line), and its JUnit reports are under
  `<common>/hook-logs/<check>.junit/`. One gate runs at a time: every run that has something to
  execute, a commit included, takes an exclusive `flock` on `<common>/hook-gate.lock` and writes its
  holder (`pid N, <command>, started <UTC>`) there. The lock is released when the process ends, even
  if it is killed; the empty file stays.
* **Nothing is written into the working tree.** Stamps and logs live under `<common>`, and `.memray/`
  and `htmlcov/` are git-ignored, so a gate run leaves a clean tree clean.

### Fail-closed rules

* **A skipped test fails the check.** The JUnit reports of `cov`, `memray`, `e2e`, `e2e-mongo`, `e2e-mongo-rs` and
  `qodana`'s coverage run are read after the run. Any `skipped` test fails it, except in `cov` and
  `qodana` a skip whose reason names `SANKEY_TEST_MONGO_URI` (the 8 mongo-marked unit tests; the
  `e2e-mongo` check runs them). A missing report, a report that was cut off and a run with no test
  case fail too. This is what keeps "no Chrome", "no Mongo" and "no replica set" from turning `e2e`,
  `e2e-mongo` and `e2e-mongo-rs` green. It also makes the machine part of the gate. To pass `cov` a machine needs Chrome or
  Chromium (the slow unit tests that draw SVG and PNG), `node` (a dozen unit modules under
  `tests/web` run the frontend modules with it), `bash`, and a Linux-style `/proc` and `/dev/null`
  (the descriptor-leak and path tests). `e2e` needs Chrome, `e2e-mongo` needs Docker and the
  project Mongo, `e2e-mongo-rs` needs `SANKEY_TEST_MONGO_RS_URI` and a reachable replica set. On macOS, or without `node`, the push gate fails with `gate: cov: junit: skipped
  test ... (node is not installed)`: install the prerequisite, the skip is the failure.
* **Offline switches are refused.** When `security` is about to run and any environment variable
  ending in `_OFFLINE` is set to something other than empty or `0`, the gate refuses and names it.
  Only `SEMGREP_OFFLINE` and `TRIVY_OFFLINE` change a scan today, but the match is by suffix on
  purpose: a gate with a list of known switches cannot catch the next one, so a global `UV_OFFLINE=1`
  is refused too (unset it for the push). A commit and a push that needs no `security` run are never
  refused for it. There are no waiver variables.
* **Qodana needs its token.** `scripts/qodana.sh` exits 2 without `QODANA_TOKEN`, and the `qodana`
  check fails. The gate never opens `.env`.
* **The child environment is scrubbed.** Every check starts with the hook's own environment minus
  git's local variables (`GIT_DIR`, `GIT_INDEX_FILE`, `GIT_WORK_TREE` and the rest of
  `git rev-parse --local-env-vars`, so a test that runs `git init` cannot touch the real
  repository), minus `PYTEST_ADDOPTS` and `SANKEY_TEST_MONGO_URI`. `~/.local/bin` comes first on
  `PATH`, and `UV_LOCKED=1` makes a stale `uv.lock` fail the check instead of being rewritten in the
  middle of a commit (`make caps` runs without it, because `uv run --no-project` warns about it).
* **Replica set for `e2e-mongo-rs`.** The gate starts nothing and sets nothing: it runs
  `make e2e-mongo-rs` with the hook's own environment, in which `SANKEY_TEST_MONGO_RS_URI` passes
  through (`SANKEY_TEST_MONGO_URI` is scrubbed as for every check). The tests find the URI in that
  variable or in the repo-root dotenv file, and take only that key (the gate itself never opens
  the file). Without a URI the tests skip and the skip fails the check (`gate: e2e-mongo-rs: junit:
  skipped test ... (needs SANKEY_TEST_MONGO_RS_URI ...)`); a URI that does not answer fails the
  tests (`SANKEY_TEST_MONGO_RS_URI is set but the server did not answer: <error type>`). Either
  way a push of `main` or a tag is refused until the cluster is reachable. The database named in
  the URI must be empty (a used one fails the test and nothing is touched); its collections are
  dropped at teardown.
* **Mongo for `e2e-mongo`.** One ping of `127.0.0.1:27117`. If it answers, the gate says so and
  leaves the Mongo running. If not, a booting container of yours would look the same, so the gate
  asks Docker through `make mongo-absent` (exit 0 only when Docker answers and no project container
  is running). Only on 0 does it run `make mongo-up`, wait up to 60 s, and run `make mongo-down` in a
  `finally` (also after a signal): that Mongo is the gate's. Otherwise (a container that is still
  booting, or Docker not answering) it waits up to 60 s for the Mongo and never starts or stops
  anything. A Mongo that does not answer fails the check (`gate: e2e-mongo: the project MongoDB on
  127.0.0.1:27117 did not answer`); a failing `make mongo-up` (compose error) fails it at once,
  without the 60 s wait. Only that check gets `SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117`.
* **Signals stop the work.** SIGTERM, SIGINT and SIGHUP stop the child's process group: TERM, then
  up to 10 s for the whole group to end (a docker client or a browser driver still needs a moment
  after `make` has died), then KILL. No stamp is written and the gate exits with `128 + N`. A
  leftover child is killed.
* **Errors refuse.** A malformed ref line, an unknown check name, a failing git call, an OS error
  (a stamp, log or lock file the gate cannot create or open) or any other error of the gate exits 1
  with one line (`gate: refusing: ...`); an uncaught exception exits non-zero too. Before a check
  that will be stamped starts, the gate creates its stamp directory and a probe file in it, so an
  unwritable `<common>/hook-stamps` fails at once and not after a long `cov` or `e2e` run.
* **A dry run cannot bypass.** With `SANKEY_GATE_DRY_RUN=1` a hook prints the plan and runs nothing,
  and exits 0 only when nothing would have to run (otherwise 1 and `gate: dry run: N check(s) would
  run, nothing was run`). `pre-push` still applies `.githooks/commit-msg` to the new commits in a
  dry run (it only reads), so a refused message makes a dry run exit 1 even when every stamp exists. git runs `pre-push` for `git push --dry-run` (or `-n`) too and passes no
  flag, so `pre-push` reads the command lines of its ancestors (`/proc`, Linux) for the nearest
  `git push` and parses its options the way git does (`-n`, `--dry-run`, abbreviations, grouped
  flags, `--no-dry-run`). It then behaves as with `SANKEY_GATE_DRY_RUN=1` and says `gate: git push
  --dry-run: nothing is run and nothing is pushed`: no check runs and no stamp is written, and git
  reports the push as failed while work is pending. A wrong guess can only turn a push into a dry
  run, never a dry run into a pass. Without `/proc` the hook cannot tell and acts as for a real push.

### What `pre-push` does, in order

1. Reads git's ref lines from stdin (a malformed line refuses), drops deletions, and takes the tree of
   each pushed commit and the tier from the remote ref name.
2. Checks the message of every new commit (`git rev-list <local> --not --remotes=<remote>`, plus the
   remote's own sha) with `.githooks/commit-msg` itself, and reports every refused message. Any
   refusal ends the hook with 1 before a long check starts.
3. Looks up the stamp of every (check, key) the tiers need, once per pair. If none is missing it
   prints `gate: every required check has a stamp for the pushed tree(s)` and passes.
4. Before it runs any missing check, it refuses when an `*_OFFLINE` variable is set and `security`
   is among them, when HEAD is not the pushed commit (the tree of HEAD must equal the pushed tree),
   or when `git status --porcelain --untracked-files=all` is not empty. It never runs checks on a
   tree that is not the pushed one.
5. Takes the lock and runs the missing checks in the order of the table, one at a time, checking
   the stamp again before each. Each check starts only if HEAD's tree is still the pushed tree and
   the status is still empty (`gate: FAILED <check>: the working tree is no longer the one the run
   started with`), and a check that passed must have left its stamp. The first failure prints
   `gate: FAILED ...` and `gate: push refused: ...` and ends with 1. The stamps of the checks that finished stay, so a
   retry resumes where it stopped, and a dropped connection or a killed run loses nothing that
   finished.

### Reading a refusal

Every line the gate prints starts with `gate:`; a plan starts with `plan:`. The hook exits 1 on
every refusal, whatever the exit code of the failed command (that code is in the `FAILED` line).

| Message | Meaning and what to do |
|---|---|
| `gate: FAILED <check> (exit N); log: <path>` | A command of the check failed. Read the log, fix the cause, commit or push again. The checks that passed keep their stamps |
| `gate: <check>: junit: skipped test <id> (<reason>)` | A test was skipped. Fix the reason (install Chrome, start the Mongo); the skip is the failure |
| `gate: <check>: junit: no junit report was written to <dir>`, `report is not terminated`, `the junit reports hold no testcase` | The test run did not complete or ran nothing. Read the log |
| `gate: FAILED <check>: the working tree changed while it ran, no stamp written` | Something edited a file during the run (an editor, a formatter, another process). Leave the tree alone and run again |
| `gate: refusing to run checks: HEAD is not the commit being pushed` | The pushed commit is not checked out. The next line gives the `git checkout` command; check it out and push again |
| `gate: refusing to run checks: the working tree is not clean` | Up to 20 `git status` lines follow. Commit them, or `git stash -u`, and push again |
| `gate: another gate run holds <lock> (<holder>); wait for it to finish` | A push gate or `make gate-*` is running (a commit is refused too). Wait for it; its stamps then make your run shorter |
| `gate: refusing to run security: <NAME> is set; offline switches weaken the scans, unset it` | Unset the variable |
| `gate: e2e-mongo: the project MongoDB on 127.0.0.1:27117 did not answer` | `make mongo-up` failed (it then fails at once) or the Mongo did not come up in 60 s, or something else holds port 27117. Look at `<common>/hook-logs/e2e-mongo.log` |
| `gate: e2e-mongo-rs: junit: skipped test ... (needs SANKEY_TEST_MONGO_RS_URI ...)` | The replica-set URI is in neither the environment of the hook nor the repo-root dotenv file. Set `SANKEY_TEST_MONGO_RS_URI` there and push again |
| `SANKEY_TEST_MONGO_RS_URI is set but the server did not answer: <error type>` (in `<common>/hook-logs/e2e-mongo-rs.log`) | The replica set is not reachable from this machine (LAN, VPN, a stopped member). Fix that, or push `main` from a machine that reaches it |
| `gate: mongo: a project Mongo container may already exist (make mongo-absent failed) ...` | Not a failure. The Mongo did not answer the first ping and Docker did not confirm that no container is running, so the gate waits for it and never stops it |
| `gate: FAILED <check>: the working tree is no longer the one the run started with ...` | HEAD moved or a file changed between two checks of one run, before this one began. Nothing was run and no stamp was written; leave the tree alone and run again |
| `gate: push refused: <check> passed but left no stamp for tree <tree>; run the push again` | A check exited 0 and the stamp file is not there (a disk problem). Run the push again |
| `gate: commit message of <sha> is refused by .githooks/commit-msg:` | The hook's own output follows. Reword the commit (`git commit --amend`, or `git rebase -i`), then push again |
| `gate: push refused: <check> failed (exit N); checks that passed keep their stamps` | The last line of a failed push gate. Look above it for `FAILED` |
| `gate: commit refused: <check> failed (exit N)` | The same for a commit |
| `gate: commit refused: <check> did not run (see the line above)` | The gate refused to start the check (a busy lock or an offline switch; the line above says which), so nothing failed. Fix that and commit again |
| `gate: git push --dry-run: nothing is run and nothing is pushed` | `pre-push` was started by `git push --dry-run` or `-n`: the plan follows, no check runs. The push counts as failed while checks are pending |
| `gate: interrupted (signal N); no stamp written for the running check` | The run was stopped. Run it again |
| `gate: refusing: <error>` | The gate itself failed: an unknown check name, a git command that failed, a malformed ref line, or an OS error such as `[Errno 13] Permission denied: '<common>/hook-stamps/...'` (fix the permissions of `<common>/hook-stamps`, `hook-logs` and `hook-gate.lock`) |

### Using the gate by hand

```bash
make gate-push                  # fast, cov, memray, e2e on the tree of HEAD; leaves stamps if the tree is clean
make gate-release               # all nine checks; the later push of main or a tag then returns at once
uv run --no-project --python 3.14 python -m scripts.githook_gate plan release     # which checks have a stamp
uv run --no-project --python 3.14 python -m scripts.githook_gate run cov --force   # run one check again
uv run --no-project --python 3.14 python -m scripts.githook_gate hooks-check       # what make hooks-check runs
```

`run` and `plan` take check names or tier names. Run `make gate-release` before a push of `main`
or a tag when you can: the push itself then finds every stamp and returns at once, and no SSH
connection waits idle through a long hook. While a hook runs, git has already opened the connection
to the remote; whether it survives 30 minutes of idle time is untested. If it drops, the push fails
after the hook and the stamps are kept, so the next push returns at once.

### Agents

Agents never run the gates by hand: not `make gate-*`, not the aggregates, not `make cov`, `make e2e`
or the other heavy targets (see `CLAUDE.md`). They run `make lint typecheck caps` and the tests they
wrote or that exercise their edit. When the user asks for a commit or a push, the hook runs the
gates. A push can take 30 minutes or more and an agent's foreground shell call stops after 10, so
the agent starts `git push` with `run_in_background` and waits for the completion notification. On a
failure it reads the `gate:` lines and the log, fixes the cause and pushes again. When the gate
refuses before running a check (`gate: refusing to run checks: ...`: HEAD is not the pushed commit,
or the working tree is not clean) it stops and reports to the user: the advice in that message
(`git checkout`, commit, `git stash -u`) is for the user, and agents do not commit, stash or check
out unasked. It never uses
`--no-verify`, never sets or overrides `core.hooksPath` (only `make hooks` and `make sync` set it; also never as
`git -c core.hooksPath=...`),
never touches `<common>/hook-stamps/` or `<common>/hook-logs/`, and never sets a variable to weaken
a check. These are working rules, not technical barriers.

### Limits and rollback

* **Not a security boundary.** The hooks live in the clone. `git commit --no-verify`,
  `git push --no-verify`, `git -c core.hooksPath=/dev/null ...`, a fresh clone before `make hooks`
  and a tool that does not run hooks all skip them. The project runs no CI on commits and has no server-side check
  (its workflows publish a tagged release ([release.md](release.md)), scan the dependencies weekly and
  score the repository; none of them runs the tests);
  the only hard stop would be a rule on the remote that requires a check or a review, and none was
  added: the ruleset on `main` blocks deleting it and force-pushing to it, nothing more (ADR-37, ADR-43). The hooks catch mistakes, not a determined person.
* **A killed gate can leave Mongo up.** A SIGKILL skips the `finally` that runs `make mongo-down`;
  the next `e2e-mongo` run then finds the Mongo already running and leaves it alone. Stop it with
  `make mongo-down`.
* **A killed gate leaves its children running.** SIGKILL of the gate (not SIGTERM, SIGINT or
  SIGHUP, which stop the child's process group) orphans the running check: its `make` and tests go
  on, and the `flock` is released at once, so the next gate run can start while the orphan still
  runs. The text in `hook-gate.lock` is then stale. Find the orphan with `ps` and stop it.
* **Killing only `git` does not stop the gate.** The hook is a child of `git push` or `git commit`;
  if just that process is killed, the gate runs to the end and still writes its stamps, which the
  next run then uses.
* **Partial staging validates the working tree.** Every check reads the files on disk, not the
  index. After `git add -p` the commit is allowed, but its `fast` run is not stamped
  (`not stamped: the working tree differs from the index`); `pre-push` checks the committed tree
  again.
* **A commit during a push gate is refused.** A new commit has a new tree, so its `fast` check has to
  run, and it cannot take the lock. Wait for the gate to finish.
* **Rollback.** `git config --unset core.hooksPath` disables every hook of the clone (`make hooks`
  turns them on again). `rm -rf "$(git rev-parse --git-common-dir)/hook-stamps"
  "$(git rev-parse --git-common-dir)/hook-logs"` clears the stamps and logs. One `git revert` of the
  commit that added the hooks removes the code.

## Commit policy

Hooks are versioned in `.githooks` and enabled once per clone with `make hooks`
(`git config core.hooksPath .githooks`; `make sync` runs it). What each hook runs is in
[Git hooks](#git-hooks).

* `pre-commit` and `pre-merge-commit` run `fast` (lint, typecheck, caps) on the tree about to be
  committed; `pre-push` runs the rest.
* `commit-msg` enforces `<type>(<scope>)!: <subject>`:
  * types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `style`;
  * scopes (optional, comma separated, for example `feat(web,ui): ...`): `core`, `sources`, `mongo`,
    `storage`, `settings`, `graph`, `render`, `export`, `web`, `ui`, `cli`, `security`, `e2e`,
    `tests`, `deps`, `tooling`, `docs`, `hooks`, `ci`, `release`;
  * `!` before the colon marks a breaking change;
  * subject of at most 150 characters, body of at most 10 lines of at most 150 characters;
  * commits written by an AI assistant are prefixed with the robot emoji and a space;
  * Merge, Revert and `fixup!`, `squash!`, `amend!` commits skip the format checks.
* `pre-push` runs this same hook on the message of every new commit, so commits made by `rebase` or
  `cherry-pick` (which do not fire `commit-msg`) are checked before they leave the clone.
* **No AI attribution in commit messages.** The words Claude, anthropic, Sonnet, Opus and any
  `Co-Authored-By` trailer are rejected. The file names `CLAUDE.md` and `.claude/...` are fine.

## Definition of done

Before calling a change finished:

1. `make lint`, `make typecheck` and `make caps` are clean (`pre-commit` runs them again).
2. The tests you touched are green under `filterwarnings = error`, deterministic, with no sleeps, no
   network and no real Mongo unless marked. Run only those tests and the ones that exercise your
   edit (the targeted command is in `CLAUDE.md`); the hooks run the full suites.
3. Coverage stays at 100% line and branch; new modules have tests that would fail if a boundary
   moved. Read the missing lines of your own changes in a targeted `--cov` run; the `cov` check of
   `pre-push` enforces the whole gate.
4. For changes that touch `src`, `scripts` or the frontend, Semgrep is clean; for dependency
   changes, Trivy is clean; for UI or API changes, the e2e suite is green. These are the `security`
   and `e2e` checks of `pre-push`, and a skipped e2e test fails the check, so "skipped with a reason"
   is no longer a way to pass.
5. The hooks decide, not a person: a push of a branch must pass `fast`, `cov`, `memray` and `e2e`; a
   push of `main` or a tag must also pass `security`, `e2e-mongo`, `e2e-mongo-rs`, `qodana` and `mutation`.
   `make gate-push` and `make gate-release` run the same checks earlier by hand and leave the stamps
   that the push then finds. `make ci` and `make full` remain one-shot aggregates for a person at a
   terminal (`make full` does not include `e2e-mongo`).
