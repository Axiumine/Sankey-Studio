# Quality gates

Every change must pass these gates. They are all `make` targets. When a rule here and a looser
statement elsewhere disagree, this document wins. Related: [architecture.md](architecture.md),
[decisions.md](decisions.md), [e2e.md](e2e.md) (end-to-end tests).

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
* [Commit policy](#commit-policy)
* [Definition of done](#definition-of-done)

## Gates at a glance

| Gate | Command | Threshold |
|---|---|---|
| Code caps | `make caps` | file 500 lines, function 50, class 300, parameters 4 (`self` and `cls` are free), nesting 4; every `*.py` including tests and scripts; ratcheted against `.code-caps-baseline.json` |
| Lint and format | `make lint` | `ruff check` with `select = ["ALL"]` and `ruff format --check` on `src tests scripts` |
| Types | `make typecheck` | `mypy --strict` on Python 3.14 |
| Unit tests | `make test` | `pytest -m "not memory and not e2e"`, `filterwarnings = error`, no sleeps |
| End-to-end | `make e2e`, `make e2e-mongo` | `pytest -m "e2e and not mongo"`: the real app on an ephemeral loopback port driven over HTTP and by real Chrome; `e2e-mongo` runs the same flows against a real MongoDB; see [e2e.md](e2e.md) |
| Coverage | `make cov` | 100% line and branch of `src/sankey_studio` from the unit suite, slow tests included, e2e excluded |
| Memory | `make memray` | `limit_memory` budgets (pytest-memray) |
| Mutation | `make mutate`, `make mutate-gate` | mutmut 3.x score of at least 90 |
| Semgrep | `make semgrep-test`, `make semgrep` | rule tests green, no finding in `src` and `scripts` |
| Trivy | `make trivy` | no fixed HIGH or CRITICAL vulnerability in `uv.lock`, no secret, no misconfiguration, no forbidden licence |
| Qodana | `make qodana` | Ultimate Plus inspection; needs `QODANA_TOKEN` in a local `.env` |
| Aggregates | `make check`, `make ci`, `make full` | `check` = lint typecheck caps cov memray; `ci` = check plus security; `full` = ci plus mutate, mutate-gate and qodana |

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
`src/sankey_studio` (`fail_under = 100`), with slow tests included and e2e tests excluded: the gate must hold without a browser. Web templates and static
assets are not measured; page routes are covered by GET tests and exercised by the browser tests.

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

* **ruff** with `select = ["ALL"]` (documented exceptions in `pyproject.toml`), line length 100,
  `max-args = 4`, mccabe complexity 12. Under `web/**` only the type-checking import rules and
  unused-argument checks are relaxed, because FastAPI resolves annotations at runtime.
* **mypy** in strict mode on `src`, `tests` and `scripts`, with the pydantic plugin and the extra
  error codes `ignore-without-code`, `redundant-expr` and `truthy-bool`. plotly and kaleido ship no
  type information, so values they return are wrapped (`cast` or a typed local).
* **pytest** with `--strict-markers`, `--strict-config` and `filterwarnings = ["error"]`. There are no
  warning ignores; do not add one without a comment naming the package and the exact warning.
* Markers: `mongo` (needs a real MongoDB), `memory`, `slow`, `e2e`.

## Scanners

* **Semgrep** (`make semgrep`, `make semgrep-test`) runs in Docker through `scripts/semgrep.sh`.
  Project rules live in `.semgrep/rules/`; registry packs are added unless `SEMGREP_OFFLINE=1`. It
  scans `src` and `scripts`, writes `reports/semgrep.sarif` and prints a readable report. The rules:
  no shell=True, no eval or exec, no OS command injection, no pickle or unsafe YAML; MongoDB writes
  only in the graph store; no `$where`, `$function`, `$accumulator`, `$out` or `$merge` literals
  outside `mongo_safety.py`; no secrets in logs or exceptions; no outbound HTTP; no unsafe HTML
  (`Markup`, `|safe`, f-string `HTMLResponse`, inline scripts or handlers in templates, DOM XSS sinks
  in JavaScript); no CORS; no wildcard bind or hosts; regex only from escaped text or constants.
* **Trivy** (`make trivy`) runs the pinned `aquasec/trivy` image through `scripts/trivy.sh` with
  `trivy.yaml`: vulnerabilities in `uv.lock` (HIGH and CRITICAL, fixed ones), secrets,
  misconfigurations and forbidden licences (GPL-2.0, GPL-3.0, AGPL-3.0, SSPL-1.0). Accepted findings
  go in `.trivyignore` with a reason and an expiry; keep it empty unless a finding is triaged.
  `TRIVY_OFFLINE=1` reuses the cached database. Do not add or bump dependencies casually.
* **Qodana** (`make qodana`) runs the JetBrains Ultimate Plus linter in Docker through
  `scripts/qodana.sh`. It reads `QODANA_TOKEN` from a local `.env` (copy `.env.example`; `.env` is
  gitignored), keeps it in the process environment only, never prints it and uploads results to
  Qodana Cloud. Never read, print or copy `.env`. Run `make cov` first: only
  `reports/coverage/coverage.xml` is imported, as a copy in `.qodana/code-coverage` whose `<source>`
  is rewritten to the container path `/data/project`. The IDE needs a Python 3.14 interpreter,
  otherwise it reports valid `X | None` hints, dataclasses and `with lock:` blocks as errors. The
  container user cannot write its HOME and the host `.venv` points at host paths, so the
  `bootstrap` of `qodana.yaml` builds a fresh venv with `uv sync` in the container, into
  `.qodana/venv`; the script mounts that over `/data/project/.venv` and names its python in
  `QODANA_PYTHON_PATH`. The host `.venv` is never touched.
* **GitNexus** indexes the repository for code intelligence (`make gitnexus`, `make gitnexus-status`).
  Use its impact analysis before changing an existing symbol; see the generated block in `CLAUDE.md`.
* **Docker.** Docker is used only through `make semgrep`, `make semgrep-test`, `make trivy`,
  `make qodana` and the optional `make mongo-up` and `make mongo-down`.

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
  appears only under `src/sankey_studio/storage/`.
* No `pytest.mark.skip` and no `xfail`. `skipif` and `pytest.skip(...)` only for an absent external
  prerequisite (Chrome, `SANKEY_TEST_MONGO_URI`) and always with a reason.

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
  run when `SANKEY_TEST_MONGO_URI` is set and then create and drop a uniquely named database. The
  project-local Mongo from `make mongo-up` listens on `127.0.0.1:27117`, for example
  `SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117`.
* mongomock gaps (`$unionWith`, `$sortByCount`, `$bucketAuto`, Decimal128 comparison, `serverStatus`)
  are covered by pure `check_pipeline` unit tests or under the `mongo` marker.
* No sleeps. Use barriers, events or an injectable clock.
* Hypothesis is not installed; use parametrised tables.
* Build a `go.Figure` from a figure dict only in tests, as a schema check.

## Commit policy

Hooks are versioned in `.githooks` and enabled once per clone with `make hooks`
(`git config core.hooksPath .githooks`).

* `pre-commit` runs the code caps.
* `commit-msg` enforces `<type>(<scope>)!: <subject>`:
  * types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `style`;
  * scopes (optional, comma separated, for example `feat(web,ui): ...`): `core`, `sources`, `mongo`,
    `storage`, `settings`, `graph`, `render`, `export`, `web`, `ui`, `cli`, `security`, `e2e`,
    `tests`, `deps`, `tooling`, `docs`, `hooks`, `ci`, `release`;
  * `!` before the colon marks a breaking change;
  * subject of at most 150 characters, body of at most 10 lines of at most 150 characters;
  * commits written by an AI assistant are prefixed with the robot emoji and a space;
  * Merge, Revert and `fixup!`, `squash!`, `amend!` commits skip the format checks.
* **No AI attribution in commit messages.** The words Claude, anthropic, Sonnet, Opus and any
  `Co-Authored-By` trailer are rejected. The file names `CLAUDE.md` and `.claude/...` are fine.

## Definition of done

Before calling a change finished:

1. `make lint`, `make typecheck` and `make caps` are clean.
2. The tests you touched are green under `filterwarnings = error`, deterministic, with no sleeps, no
   network and no real Mongo unless marked.
3. `make cov` reports 100% line and branch coverage; new modules have tests that would fail if a
   boundary moved.
4. For changes that touch `src`, `scripts` or the frontend, `make semgrep-test semgrep` is clean; for
   dependency changes, `make trivy` is clean; for UI or API changes, `make e2e` is green or skipped
   with a reason.
5. Aggregates before a release: `make ci` and, last, `make full`.
