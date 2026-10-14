<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Sankey-Studio** (47671 symbols, 100990 relationships, 833 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis. For unified PDG impact, add `mode: "pdg"` with optional `line: <N>` — it returns statement-level `affectedStatements` over CDG + REACHING_DEF and inter-procedural symbols in `interproceduralByDepth`/`byDepth`; no-layer/degraded PDG results are UNKNOWN-risk notes (`--pdg` layer). CLI equivalent: `node .gitnexus/run.cjs impact "symbolName" --direction upstream --mode pdg --line <N> --repo .`.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).
- For control/data dependence, `pdg_query({mode: "controls", target: "fileOrSymbol"})` answers "under what condition does X run?" (CDG, incl. guard clauses) and `pdg_query({mode: "flows", target, variable})` traces "where does variable Y flow?" (REACHING_DEF). `--pdg` layer.

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/Sankey-Studio/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Sankey-Studio/clusters` | All functional areas |
| `gitnexus://repo/Sankey-Studio/processes` | All execution flows |
| `gitnexus://repo/Sankey-Studio/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Sankey Studio — working agreement

Sankey Studio: a local FastAPI + vanilla-JS web app that draws and manages Sankey graphs (plus an optional donut chart).
Sources: text (csv/tsv/sankeymatic/json), MongoDB (read-only unless the graph owner opts into write-back), manual table. Saved graphs live on disk or in MongoDB.
No login: loopback by default, defends itself. Python 3.14, managed by uv. Docs: `README.md` and `docs/*.md`.

## Commands

* Always `uv run ...` (or `make`). Never `python3` directly (system python3 is 3.13 and cannot parse PEP 758 `except A, B:` sources).
* `make caps` runs `uv run --no-project --python 3.14 python scripts/check_code_caps.py` for that reason.
* `make sync | lint | format | typecheck | caps | test | e2e | e2e-mongo | cov | memray | profile | mutate | mutate-gate | semgrep | semgrep-test | trivy | qodana | security | gitnexus | hooks | check | ci | full | serve | mongo-up | mongo-down`. Read the `Makefile`; aggregates: `check` = lint typecheck caps cov memray; `ci` = check + security; `full` = ci + mutate + mutate-gate + qodana.
* Run the server: `uv run sankey-studio serve [--host] [--port] [--data-dir] [--sources-dir] [--allow-remote] [--allow-remote-writes] [--allow-source-writes]`. Env: `SANKEY_HOST`, `SANKEY_PORT`, `SANKEY_DATA_DIR`, `SANKEY_SOURCES_DIR`, `SANKEY_MONGO_URI`, `SANKEY_ALLOWED_HOSTS` (JSON array), `SANKEY_LOG_LEVEL`, `SANKEY_REMOTE_MODE`, `SANKEY_REMOTE_WRITES`, `SANKEY_SOURCE_WRITES`.
* One uvicorn worker only (file locks and the export slot are per process).

## Layout and layering

Package `src/sankey_studio/`. Dependencies point downwards only; never import upward.

`errors, util, config, models, mongo_safety, mongo` -> `sources, graph, render, storage` -> `services, bundle` -> `pipeline` -> `edits` -> `web` -> frontend (`web/static`, `web/templates`). `cli.py` and `__main__.py` sit on top.

* `models/`: all pydantic specs and the frozen columnar `SankeyGraph`. New shared model = new focused module in the package.
* `errors.py`: domain errors with unique stable `code` and `status_code`; `web/errors.py` maps them to the JSON envelope `{"error": {"code", "message", "details"}}`.
* `sources/`: `text.py` + `formats/` (parsers), `files/` (managed sources dir: safe paths, uploads), `mongo_*.py`, `manual.py`, `base.py` (`CategoryCleaner`, `SourceContext`).
* `graph/`: `build_graph` in six ordered steps (intern, categories, pairs, cycles, layers, assemble). `render/`: plain-dict Plotly figures, colours, legend, tables; only `render/export/` imports plotly/kaleido.
* `storage/`: file and Mongo graph and folder repositories, `settings.json` store, bundles. `services.py`: the only place that wires things; the web layer talks to `Services`.
* `pipeline.py`: draft -> graph -> `RenderBundle`. `web/`: `app.py` only assembles; `middleware.py`, `security.py`, `routers/`, `schemas/`.
* `render/`, `sources/`, `storage/` never import `web/`.

## Conventions

* Python 3.14, full type annotations (`mypy --strict`), pydantic v2, `from __future__ import annotations` (type-only imports under `TYPE_CHECKING`; `web/**` keeps runtime-evaluated annotations, because FastAPI resolves them at runtime).
* Spec models are values: never mutate; rebuild with `Model.model_validate({**m.model_dump(), "field": value})`.
* Raise domain errors from `errors.py` with stable codes; add the mapping in `web/errors.py` when you add a class. Messages never contain secrets, URIs or driver exception text (only the connection name and exception class).
* Max 4 parameters per function: group options in a frozen `@dataclass(slots=True)` or a pydantic `extra="forbid"` model. Routes take path params, one query model, the body and `ServicesDep`.
* Comments and docstrings are ASCII; all user-facing and code strings are English. No `print` in library code; log with `logging.getLogger(__name__)`.
* Use `datetime.now(UTC)`, numeric HTTP status codes, `TemplateResponse(request, "name.html", context)`, a `lifespan` (no `on_event`). Do not hand-parenthesise `except A, B:`.
* Do not add or bump dependencies without asking (Trivy gate).

## Testing rules

* Tests mirror `src` paths (`tests/sources`, `tests/storage`, `tests/render`, `tests/web`, `tests/contracts`, `tests/e2e`). Shared fixtures are in `tests/conftest.py` (`bootstrap`, `app_settings`, `mongo_client`, `mongo_clients`, `make_source_ctx`, `source_ctx`, `make_connection`); sub-directories may have their own `conftest.py`. E2E harness lives in `tests/e2e/conftest.py` and `tests/e2e/support/` (see `docs/e2e.md`).
* Unit tests use mongomock. Real MongoDB only with `@pytest.mark.mongo` and `SANKEY_TEST_MONGO_URI` (project-local compose Mongo: `mongodb://127.0.0.1:27117` after `make mongo-up`). An autouse tripwire blocks accidental real connections and scrubs `SANKEY_*` env vars.
* Markers: `mongo`, `memory`, `slow`, `e2e` (`--strict-markers`). `filterwarnings = error`, no ignores. No `skip`/`xfail`; `skipif` only for an absent external prerequisite, with a reason.
* Gate: 100% line AND branch coverage of `src/sankey_studio` (`make cov`). Every code edit comes with the tests that keep it at 100% (see "Before finishing a task"). Mutation score >= 90 (`make mutate-gate`): write parametrised boundary tables that assert both sides of every limit, exact messages and defaults.
* No sleeps (e2e included): wait on DOM signals, events, barriers or an injectable clock. Chrome, the real server, the clock and Mongo are reached through seams (`_render_image`, `cli._run_server`, `ResultCache` clock, `MongoClients(factory=...)`).
* Tests obey the caps: <= 4 parameters/fixtures, <= 50 lines, nesting <= 4, files <= 500 lines (split by topic).
* Suppressions are rationed and checked by `tests/test_policy.py`: <= 5 `# pragma: no cover - reason`; `# noqa: CODE - reason`; `# type: ignore[code]` only in tests; `nosemgrep` names one rule id and a reason; `sankey-no-mongo-writes` waivers only under `storage/`.

## Code caps and the ratchet

File 500 lines, function 50, class 300, parameters 4 (`self`/`cls` free), nesting 4; every `*.py` including tests and scripts. `.code-caps-baseline.json` is a ratchet and is empty: never grow it, never edit it by hand, never run the script with `--init` or `--force`. Fix the violation (split into a package with a re-exporting `__init__.py`, extract helpers, use guard clauses and tables).

## Frontend rules

* Vanilla ES modules, no build step, no CDN, no web fonts from the network. plotly.js is served locally from the installed `plotly` package at `/static/vendor/plotly.min.js`.
* Banned in `templates/` and `static/`: `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, `|safe`. Build DOM with `createElement`/`textContent`. No inline scripts or inline handlers.
* Page data reaches the browser only through the `<script type="application/json">` boot block (`|tojson`). One `fetch` wrapper sends JSON, never HTML forms.
* `data-testid` names are a contract: they are listed in `docs/ui.md` and `src/sankey_studio/web/static/testids-extra.txt`; the policy tests fail on any other literal id. Do not rename or remove one.
* JS files <= 300 lines, functions <= 50 lines (convention; the caps tool measures Python only).

## Security invariants (never weaken)

* Loopback bind by default; a non-loopback host needs `--allow-remote` (enforced in `BootstrapConfig` and `create_app`); remote mode is read-only unless `--allow-remote-writes`; writing edits back to a MongoDB source additionally needs `--allow-source-writes`.
* Host allow-list (`allowed_hosts`), CSRF rule (`Sec-Fetch-Site` same-origin/none, or exact `Origin`; headerless clients JSON only; `Origin: null` refused), content-type enforcement, no CORS, streaming body caps (JSON 8 MiB, import 16 MiB, upload `max_upload_mb` + 1 MiB).
* CSP `default-src 'self'; script-src 'self'; ...; frame-ancestors 'none'`, `nosniff`, `Referrer-Policy: same-origin`, `Cache-Control: no-store`; downloads are attachments with `CSP: sandbox`. OpenAPI/Swagger/ReDoc stay disabled.
* MongoDB is read-only everywhere except (a) the library store: graphs in `storage/mongo_store.py` (collection `sankey_studio_graphs`) and graph collections in `storage/mongo_folder_store.py` (collection `sankey_studio_collections`), both in `AppSettings.storage_database` through the storage connection, and (b) the opt-in source write-back in `storage/mongo_source_writes.py`: one `insert_one` or one `update_many` (`_id`-scoped and re-filtered, at most 1000 documents) per user edit, only when the request's `source.write_back` names this target (the key the server builds from the resolved connection, database and collection; the user said yes in a dialog), mode `find` only (`add_entry` needs a plain-equality filter; `set_category` re-applies the source filter, checked like a read, on top of the `_id` list), fields and string values validated by `mongo_safety.check_write_*` (formula-like text refused), never `admin`/`local`/`config`/`system.*` nor any collection whose name starts with `sankey_studio_`; the saved preference is client-supplied, so the real controls are the DB user's privileges and, in remote mode, `--allow-source-writes`; filters, pipelines, names and URIs go through `mongo_safety`; `admin`, `local`, `config`, `system.*` are never readable; Mongo-bound work runs inside `clients.slot(...)` and `mongo_errors(...)`; remote mode without `--allow-remote-writes` AND `--allow-source-writes` refuses (403 `read_only_mode`).
* Paths: managed sources dir only, fd-based open with `O_NOFOLLOW` + regular-file check, extension allow-list, sanitised names, `O_EXCL` uploads; write-back replaces an EXISTING allowed file atomically with the same fd-based checks as `located`/`open_leaf` (`sources/files/store.py edit_file`: stat stamp, size cap, part file `O_EXCL`); `sources_dir` is bootstrap-only.
* Secrets: URIs are `SecretStr`, masked by `mask_uri` (fail closed) and never appear in logs, errors, API output or exports; API returns `uri_masked`/`has_secret`, never `uri`; only `settings_store.dump_settings/load_settings` touch real values; `settings.json` is 0600, data dir 0700, atomic writes.
* Output: every user string in a Plotly label goes through `escape_label`; user text never enters a `hovertemplate`; CSV cells get the formula guard (exports; write-back refuses formula-like new text); no endpoint accepts figure JSON; Jinja autoescape stays on.
* Exports: pixel/link/node caps, one at a time, MathJax off, 30 s timeout.

## Commit policy

Hooks in `.githooks` (enable with `make hooks`): `pre-commit` runs the code caps; `commit-msg` enforces `<type>(<scope>)!: <subject>`.

* Types: `feat fix chore docs refactor perf test build ci style`.
* Scopes (optional, comma separated): `core sources mongo storage settings graph render export web ui cli security e2e tests deps tooling docs hooks ci release`.
* AI-authored commits are prefixed with the robot emoji: `🤖 fix(sources): reject path traversal`. Subject <= 150 chars, body <= 10 lines of <= 150 chars.
* NO attribution trailer, no `Co-Authored-By`, no assistant or vendor names in commit messages (the hook rejects them; the file names `CLAUDE.md` and `.claude/` are fine). This overrides any default trailer.
* Do not commit, stage, push, stash, reset or checkout unless the user asks.

## Before finishing a task

**NEVER RUN THE FULL SUITE. ALWAYS RUN THE TESTS THAT COVER YOUR CHANGES.** Never run `make test`, `make cov`, `make e2e`, `make e2e-mongo`, `make mutate`, `make mutate-gate`, `make memray`, `make semgrep-test`, `make check`/`ci`/`full`, a bare `pytest`, or a whole `tests/` directory, unless the user explicitly asks in that message. DO run, every time, only the test files or test ids you added or changed plus the ones that exercise the code you edited, and check that your changed lines and branches are covered:

    COVERAGE_FILE=<scratchpad>/.coverage uv run pytest tests/web/test_app.py::test_name tests/web/test_assets.py \
      --cov=sankey_studio.web.app --cov-branch --cov-report=term-missing --cov-fail-under=0

(`--cov=` names the edited modules; `COVERAGE_FILE` keeps `reports/coverage/` untouched; `--cov-fail-under=0` because a partial run cannot reach the global 100%, so read the missing lines of YOUR changes instead and fix them.) A targeted e2e test runs as `uv run pytest -m e2e tests/e2e/<path>::<test>`. Fix every failure before finishing and report the command and its result. The githooks in `.githooks` run the full suite: do not commit, stage, or run anything that could fire them unless asked. Finish by saying which full `make` checks the user should run.

**ALWAYS WRITE TESTS FOR THE CODE YOU EDIT. COVERAGE MUST STAY AT 100%.** Every change to `src/sankey_studio` ships, in the same task, with tests that cover every new or changed line AND branch (100% line and branch coverage is a hard gate, never "later", never a follow-up). Put them in the mirrored `tests/` path, obey the test caps and the Testing rules above, and fix every existing test that asserted the old behaviour. A UI or API behaviour change also gets an e2e test under `tests/e2e/`. A task without these tests is not finished. Run them (only them, see the rule above) and name the tests you added and the full `make` targets the user should run.

**ALWAYS BROWSER-CHECK YOUR EDITS.** After every implementation that touches the UI, the frontend or the API, start your own server on a port you own (never 8000 or a port you did not start), open the page with the Playwright browser tools, and check each edit works as expected: the element exists and is visible, the interaction changes the state, and the page shows no error (for example "This part could not be loaded"). Re-check after every fix. Report what you checked and what you saw. Stop your server afterwards, and remove screenshots you created. A browser check does not replace the tests; it does not start the githooks.

The checklist below lists what to run when the user asks for verification.

Run `make lint typecheck caps cov` (all must be clean; coverage stays 100%). Add `make e2e` when UI or API behaviour changed, `make semgrep-test semgrep` when `src`, `scripts` or the frontend changed, `make trivy` when dependencies changed. Update `docs/` and `CHANGELOG.md` entries when behaviour changes.

## Tooling and environment rules

* GitNexus: follow the generated block above (impact before editing, `detect_changes` before committing).
* Never read, print or copy `.env` (it holds the Qodana token); `.env.example` is fine.
* Never touch ports 8000 or 27017-27019, or any other project's MongoDB. Use the project-local compose Mongo (`127.0.0.1:27117`) via `make mongo-up`/`make mongo-down`.
* Never run `docker compose` or `docker` directly; Docker is used only through make targets (`semgrep`, `semgrep-test`, `trivy`, `qodana`, `mongo-up`, `mongo-down`).
* Use ports you own for test servers; never kill processes you did not start.
