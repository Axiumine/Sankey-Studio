# Contributing to Sankey Studio

Thank you for helping. Sankey Studio is a one-maintainer project, so replies can take a few days;
a short, focused change gets reviewed fastest.

## Ways to contribute

* **Report a bug or ask for a feature** in the
  [issue tracker](https://github.com/Axiumine/Sankey-Studio/issues). Say what you did, what you
  expected and what happened, plus the version or commit, your OS and browser, and the log lines or
  the error envelope `{"error": {"code", "message", "details"}}`. Never paste a connection string,
  password or private data; the application masks them, so please keep them out of reports too.
* **Report a security problem privately**, not in an issue: see [SECURITY.md](SECURITY.md).
* **Send a pull request** for a fix, a test, a doc improvement or a feature. The software is
  complete, so the maintainers add no features themselves, but feature pull requests are welcome,
  except support for SQL databases, which will not be accepted ([docs/roadmap.md](docs/roadmap.md)). For anything bigger than
  a small fix, open an issue first so we agree on the approach before you spend time on it.
* **Improve the docs**: [README.md](README.md) and [docs/](docs/) are part of the product.

Who decides, who has access and how review works is in [GOVERNANCE.md](GOVERNANCE.md); the
maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md). Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need Python 3.14, [uv](https://docs.astral.sh/uv/) and `make`. The end-to-end tests also need
Chrome or Chromium and `node`; the scanners (`make semgrep`, `trivy`, `qodana`) and the project
MongoDB (`make mongo-up`) need Docker.

```bash
git clone https://github.com/Axiumine/Sankey-Studio.git
cd Sankey-Studio
make sync    # uv sync --all-extras, and enables the versioned git hooks
make serve   # http://127.0.0.1:8765
```

Always run Python through `uv run ...` (or `make`), never the system `python3`: the sources use
Python 3.14 syntax such as `except A, B:` (PEP 758). The full list of `make` targets is in
[Development](README.md#development).

## Making a change

1. Fork the repository and branch from `main`.
2. Make the change, with the tests below.
3. Run `make lint typecheck caps`, then the tests for the code you touched, for example
   `uv run pytest tests/web/test_app.py --cov=sankey_studio.web.app --cov-branch --cov-report=term-missing --cov-fail-under=0`
   (a partial run cannot reach 100%, so read the missing lines of your own change). `make cov` runs
   the whole unit suite; `make e2e` runs the browser tests.
4. Update [CHANGELOG.md](CHANGELOG.md) and the page in [docs/](docs/) that describes the behaviour.
5. Open a pull request against `main` that says what changed and why, and links the issue.

The maintainer runs the slow gates (`cov`, `memray`, `e2e`, `security`, `mutation`) from the git hooks
before merging, so a pull request does not need to pass all of them before review, but it must not
break `make lint typecheck caps` and its own tests.

## Rules for code

These are enforced by tools, so a change that breaks them cannot be merged. The full text is in
[README.md](README.md#development), [docs/quality.md](docs/quality.md) and
[docs/architecture.md](docs/architecture.md).

* **Layering.** Package `src/sankey_studio/`; imports point downwards only (`errors`, `util`,
  `config`, `models`, `mongo*` -> `sources`, `graph`, `render`, `storage` -> `services`, `bundle` ->
  `pipeline` -> `edits` -> `web`). `render/`, `sources/` and `storage/` never import `web/`.
* **Typing and style.** Full annotations (`mypy --strict`), pydantic v2, `ruff` (`make format`
  fixes layout). Comments and docstrings are ASCII; user-facing text is English. No `print` in
  library code; log with `logging.getLogger(__name__)`.
* **Caps.** File 500 lines, function 50, class 300, at most 4 parameters, nesting 4, for every
  `*.py` including tests (`make caps`). Split or extract instead of asking for an exception.
* **Errors.** Raise a domain error from `errors.py` with a unique stable `code` and add its mapping in
  `web/errors.py`. Messages never contain secrets, URIs or driver exception text.
* **Dependencies.** Do not add or bump a dependency in a pull request without agreeing it in an
  issue first. After a bump run `make requirements` and commit `requirements.txt` with `uv.lock`
  (`make lint` fails otherwise). The runtime dependencies are pinned in `uv.lock` and scanned by Trivy
  in the push gate of `main` and tags; the details and the limits are in [docs/dependencies.md](docs/dependencies.md).
* **Frontend.** Vanilla ES modules, no build step, no CDN. No `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, `|safe`, inline scripts or inline
  handlers (Semgrep and the policy tests fail on them). `data-testid` names are a contract listed in
  [docs/ui.md](docs/ui.md); do not rename or remove one.
* **Security invariants.** Do not weaken the loopback default, the Host and CSRF checks, the CSP,
  the MongoDB read-only guard, path containment, secret masking or output escaping
  ([Security model](README.md#security-model)). A change near them needs a test for both sides of the
  limit.

## Rules for tests

* Every change to `src/sankey_studio` comes with tests that cover each new or changed line **and
  branch**: line and branch coverage of `src/sankey_studio` must stay at 100% (`make cov`).
* A UI or API behaviour change also gets an end-to-end test under `tests/e2e/`
  ([docs/e2e.md](docs/e2e.md)).
* Tests mirror the `src` paths, use the shared fixtures in `tests/conftest.py`, and obey the caps
  (at most 4 parameters/fixtures, 50 lines, nesting 4, 500 lines per file).
* Unit tests use mongomock. Real MongoDB only with `@pytest.mark.mongo`, against the project MongoDB
  (`make mongo-up`, then `SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117 make e2e-mongo`).
* No sleeps: wait on DOM signals, events or an injectable clock. No `skip`/`xfail`; `filterwarnings =
  error`.
* The mutation score must stay at or above 90 (`make mutate-gate`): write boundary tables that assert
  both sides of every limit, exact messages and defaults.

## Commits and the git hooks

`make hooks` (run by `make sync`) enables the hooks in `.githooks`: `pre-commit` runs lint, typecheck
and caps; `pre-push` runs the full gates. They are described in [Git hooks](README.md#git-hooks).

Commit messages follow `<type>(<scope>)!: <subject>` (types `feat fix chore docs refactor perf test
build ci style`; the scopes are listed in [Commit policy](README.md#commit-policy)); subject at most
150 characters, body at most 10 lines. Never bypass a hook with `--no-verify`.

## License

Sankey Studio is released under the GNU General Public License, version 3 only (`GPL-3.0-only`,
copyright Giovanni Manzoni). By sending a contribution you agree that it is licensed under the same
terms. Every `.py`, `.sh`, `.js`, `.mjs`, `.css` and template `.html` file under `src`, `tests` and
`scripts` starts with the two-line SPDX header; `uv run python scripts/license_header.py --apply` adds
it to a new file (and `tests/test_license_header.py` fails without it).
