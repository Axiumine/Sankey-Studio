# Dependencies

This page says how Sankey Studio chooses, installs, watches and updates its dependencies, and what
happens when one is vulnerable. It describes what the repository does today. Where a rule is only a
convention that nothing checks, or a check that runs only on the maintainer's machine, the text says
so. Related: [quality.md](quality.md#scanners) (the
scanners), [release.md](release.md) (publishing), [../SECURITY.md](../SECURITY.md) (reports and
timelines), [decisions.md](decisions.md) (the reasons behind the main choices).

Contents

* [At a glance](#at-a-glance)
* [What counts as a dependency](#what-counts-as-a-dependency)
* [How dependencies are selected](#how-dependencies-are-selected)
* [How dependencies are obtained](#how-dependencies-are-obtained)
* [How dependencies are tracked and monitored](#how-dependencies-are-tracked-and-monitored)
* [How dependencies are updated](#how-dependencies-are-updated)
* [When a dependency is vulnerable](#when-a-dependency-is-vulnerable)
* [Adding, removing and replacing one](#adding-removing-and-replacing-one)
* [The workflows' own dependencies](#the-workflows-own-dependencies)
* [Limits](#limits)

## At a glance

| Question | Answer |
|---|---|
| Where do packages come from | PyPI, through uv. Every package in `uv.lock` has the PyPI registry as its source, except the project itself. |
| What fixes the versions | In the maintainer's environment, `uv.lock`: exact versions with sha256 hashes. `pyproject.toml` holds lower bounds only, and an install of the published package resolves from those. |
| Who may add or bump one | A contributor does not add or bump one in a pull request without agreeing it in an issue first ([CONTRIBUTING.md](../CONTRIBUTING.md#rules-for-code)); AI assistants are told to ask first. No test or script checks this. |
| What scans them | Trivy scans the runtime packages of `uv.lock` in the push gate of `main` and tags, on the maintainer's machine, and in GitHub Actions on every push to `main` and every pull request (`ci-security.yml`) and weekly (`trivy-weekly.yml`). Qodana is configured for dependency checks but excludes `uv.lock`. GitHub Dependabot alerts and security updates are switched on, and since 2026-10-17 GitHub's dependency graph lists the 76 locked packages (runtime and development), with no open alert (see below). |
| What blocks a push | On a machine with the hooks enabled, a push of `main` or a tag is refused for a Trivy finding of severity HIGH or CRITICAL (a vulnerability that has a fix, a secret, a misconfiguration). Trivy does not check the licences of the packages in `uv.lock`. |
| Is there CI | Hosted workflows run on every push to `main` and every pull request, but nothing requires them to pass: lint, strict types, the code caps and the unit tests with the coverage gate (`ci.yml`), the memory budgets (`ci.yml`), the browser and real-MongoDB end-to-end suites (`ci-e2e.yml`) and Semgrep and Trivy (`ci-security.yml`). Mutation testing runs hosted only when started by hand (`mutation.yml`). Other workflows publish a tagged release, run Trivy weekly, run CodeQL, run the OpenSSF Scorecard and fuzz the parsers. Qodana, the replica-set suite and the gate itself run only in the git hooks, which are client-side. |

## What counts as a dependency

**Runtime packages** are listed in `[project].dependencies` of `pyproject.toml`:

| Package | Used for |
|---|---|
| `fastapi`, `uvicorn` | the web application and its server |
| `jinja2` | the HTML templates |
| `pydantic`, `pydantic-settings` | the models and the settings |
| `pymongo` | the MongoDB driver |
| `plotly` | writing the figure dicts as JSON, and the plotly.js file the browser loads (see below) |
| `python-multipart` | the multipart upload route (FastAPI needs it for file uploads) |
| `kaleido` | static SVG and PNG export; it needs a Chrome or Chromium install at runtime |
| `choreographer` | kaleido's browser driver; listed because the export code imports its error classes |

The published wheel declares exactly these ten, as lower bounds. The rest:

* **Development packages** are in `[dependency-groups].dev`: ruff, mypy, pytest, pytest-cov,
  pytest-memray, memray, httpx, httpx2, mongomock, mutmut and playwright (`pytest-memray` and
  `memray` only on Linux and macOS). A dependency group is not part of the published package, so
  `pip install sankey-studio` does not install them.
* **The build requirement** is `hatchling>=1.27` in `[build-system].requires`.
* **Transitive packages** are everything else in `uv.lock`.
* **Things that are not Python packages.** plotly.js arrives inside the plotly package. Chrome or
  Chromium is needed for image export and is installed by the user (`uv run plotly_get_chrome` can
  fetch one, see [README.md](../README.md#run-from-a-checkout)). `node` runs the `.mjs` scripts that
  test the frontend; there is no `package.json`, no npm package and no JavaScript build step. The hosted
  browser jobs use the Google Chrome that GitHub's runner image carries; it is neither installed nor
  pinned by the repository.
  `make gitnexus` calls an external `gitnexus` command that the repository neither installs nor
  pins. The scanners and the project MongoDB run as Docker images (the hosted jobs use them too, and a
  MongoDB service container), and the workflows use GitHub Actions; both are covered below.

## How dependencies are selected

These are the rules the repository states.

* **Agree first.** The rule is to agree a new or bumped dependency before it goes in.
  [CONTRIBUTING.md](../CONTRIBUTING.md#rules-for-code) says: "Do not add or bump a dependency in a
  pull request without agreeing it in an issue first". [quality.md](quality.md#scanners) says "Do
  not add or bump dependencies casually", and the working agreement for AI assistants (`CLAUDE.md`,
  `AGENTS.md`) says "Do not add or bump dependencies without asking (Trivy gate)". The lead
  maintainer decides what goes into the project ([GOVERNANCE.md](../GOVERNANCE.md#roles)); the
  repository defines no further admission test, such as a minimum age or a maintenance status.
  Nothing checks the rule. A maintainer's review applies it to a contributor's pull request; a
  maintainer's own change has no second reviewer
  ([GOVERNANCE.md](../GOVERNANCE.md#changes-and-review)).
* **The licence lists.** The project is `GPL-3.0-only`. `qodana.yaml` carries a list headed
  "Licences that may appear in the dependency tree": MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause,
  ISC, PSF-2.0, MPL-2.0, Unlicense, 0BSD and Python-2.0. The same file prohibits GPL-2.0, GPL-3.0,
  AGPL-3.0 and SSPL-1.0, and `trivy.yaml` forbids the same four ("Mirrors licenseRules in
  qodana.yaml"). The files do not say why GPL-3.0 is prohibited for dependencies of a
  `GPL-3.0-only` project. The files say nothing about a licence that is on neither list. These lists
  are the project's intent: the repository does not show an automatic check of them for the
  packages in `uv.lock` (see [Trivy](#trivy) and [Qodana](#qodana)).
* **No network assets in the frontend.** The frontend is vanilla ES modules with no build step and
  no CDN ([CONTRIBUTING.md](../CONTRIBUTING.md#rules-for-code),
  [README.md](../README.md#security-model)). The Content-Security-Policy sets `default-src 'self'`
  and `script-src 'self'`, so a page loads no script from another origin (styles may also be inline,
  images may be `data:` or `blob:` URLs). The test `tests/web/test_templates_policy.py` fails on any
  asset in `templates/` or `static/` that leaves the origin (an external `<script src>`,
  `url(//...)`, `@import`), and Semgrep has a rule against outbound HTTP calls from Python in `src`
  and `scripts`. Kaleido runs with MathJax off, so an export does not fetch MathJax from a CDN
  ([ADR-20](decisions.md#adr-20-figures-are-plain-dicts)).
* **plotly.js comes from the installed plotly package.** No copy of plotly.js is committed. The
  route `GET /static/vendor/plotly.min.js` answers with the `plotly.min.js` that
  `plotly.offline.get_plotlyjs()` returns for the installed package (`web/routers/pages.py`), and it
  is registered before the `/static` mount so nothing shadows it. plotly.js therefore has no entry
  of its own in `uv.lock`: its version is the one the locked plotly ships, it changes when plotly
  does, and a scanner that reads `uv.lock` sees the `plotly` package and not the JavaScript library
  inside it.
* **It must fit the test setup.** The suite runs with `filterwarnings = error` and no ignores. A
  package whose import warns breaks every test, and `pyproject.toml` asks that an ignore carries a
  comment naming the package and the exact warning
  ([ADR-19](decisions.md#adr-19-test-tooling-and-lint-configuration) is the case of `httpx2`). A
  package without type hints needs a mypy override, as plotly and kaleido have. Python is 3.14 or
  newer (`requires-python`; `.python-version` pins 3.14).

## How dependencies are obtained

* **From PyPI, through uv.** The `source` of every package in `uv.lock` is
  `{ registry = "https://pypi.org/simple" }`; the one other entry is the project itself
  (`{ editable = "." }`). There are no git, URL or path dependencies. `make sync` runs
  `uv sync --all-extras`, which installs the runtime and the development dependencies
  ([README.md](../README.md#run-from-a-checkout)).
* **Ranges in `pyproject.toml`, exact versions in `uv.lock`.** The ranges are lower bounds only
  (`fastapi>=0.115`), with no upper cap. `uv.lock` (lock format `version = 1`, `revision = 3`)
  records the exact version of every package and the sha256 hash of each of its source archives and
  wheels, so an install from the lock is checked against those hashes.
* **The hooks refuse a stale lock.** Every step of the git hooks except `make caps` (which does
  not use the project environment) runs with `UV_LOCKED=1`, so a `pyproject.toml` that no longer
  matches `uv.lock` fails the check instead of rewriting the lock in the middle of a commit
  ([quality.md](quality.md#fail-closed-rules)). Commit the two files together.
* **Runtime, development and build are separate sets.** The runtime set is what the wheel declares;
  the `dev` group is for the maintainer and contributors and is not published. The build requirement
  `hatchling>=1.27` is not in `uv.lock`: the build tool resolves it when the package is built. The
  comment in `pyproject.toml` gives the reason for the floor: 1.27 is the first hatchling that reads
  a PEP 639 license expression and `license-files`.
* **A user's install does not use the lock.** The source distribution does not contain `uv.lock`
  (`[tool.hatch.build.targets.sdist]` lists the files), and the wheel carries the ranges. Someone
  who runs `uv tool install sankey-studio` or `pip install sankey-studio` gets the newest versions
  the ranges allow. The lock, and the Trivy scan of it, describe the environment the maintainer
  develops, tests and releases from.
* **Outside PyPI.** The Docker images are named by tag in the scripts and not by digest:
  `aquasec/trivy:0.75.0` (`scripts/trivy.sh`), `semgrep/semgrep:1.178.0` (`scripts/semgrep.sh`),
  `jetbrains/qodana-python:2026.2` (`qodana.yaml` and `scripts/qodana.sh`) and `mongo:8`
  (`docker-compose.yml`; this tag follows the 8.x line). The one exception is the MongoDB service
  container of `ci-e2e.yml`, `mongo:8` pinned by digest (resolved on 2026-10-18, refreshed by hand), so
  the hosted job and `docker-compose.yml` can run different 8.x builds. A tag changes by editing the file. Nothing
  in the repository watches these images, and the gate stamps do not record which image ran
  ([ADR-37](decisions.md#adr-37-git-hooks-are-the-one-place-the-checks-run)). Trivy fetches its
  vulnerability database, and Semgrep its registry rule packs (unless `SEMGREP_OFFLINE=1`), when
  they run. The `bootstrap` of `qodana.yaml` installs uv with `pip` without a version and then runs
  `uv sync --frozen`, so the packages come from `uv.lock` but the uv version does not.

## How dependencies are tracked and monitored

| Tool | Where it runs | When | Looks at | Effect |
|---|---|---|---|---|
| Trivy | the maintainer's machine, in Docker | the `security` check, on a push of `main` or a tag | the runtime packages of `uv.lock`, secrets, misconfigurations | refuses the push |
| Trivy, on push and pull request | GitHub Actions (`ci-security.yml`), same script and config | every push to `main` and every pull request to `main` | the same | a failed job that nothing requires; the SARIF file is kept as an artifact |
| Trivy, weekly | GitHub Actions (`trivy-weekly.yml`), same script and config | every Monday 05:23 UTC and on demand | the same | a failed run, e-mailed to the person who last changed the schedule |
| Qodana | the maintainer's machine, in Docker; results go to Qodana Cloud | the `qodana` check, on a push of `main` or a tag | configured for a dependency licence audit and vulnerable libraries; `uv.lock` is excluded, so what it reads is unverified | a failed check refuses the push |
| Dependabot alerts | GitHub | continuously | what GitHub's dependency graph lists: since 2026-10-17 the 76 locked packages, runtime and development | an alert on GitHub (none open on 2026-10-17) |
| Dependabot security updates | GitHub | when an alert has a fixed version | the same | a pull request proposing the bump |

### Trivy

`make trivy` runs `scripts/trivy.sh`, which runs the pinned `aquasec/trivy` image as `trivy fs`
over the repository root with `trivy.yaml`. The configuration says:

* **Scanners:** `vuln` (the vulnerabilities of the packages in `uv.lock`), `secret`, `misconfig` and
  `license`.
* **Severities:** CRITICAL and HIGH only, and `ignore-unfixed: true`, so a vulnerability without a
  fixed version is not reported. MEDIUM and LOW findings are neither reported nor gated by Trivy.
* **Development packages:** Trivy's documentation says it does not report development dependencies
  unless it is started with `--include-dev-deps`, and neither `trivy.yaml` nor `scripts/trivy.sh`
  sets that. For a `uv.lock` this means the packages that only the `dev` group pulls in (the
  linters, the test tools and their own dependencies) are left out of the vulnerability report. The
  gate covers the packages that the runtime dependencies pull in.
* **Licences:** GPL-2.0, GPL-3.0, AGPL-3.0 and SSPL-1.0 are listed as forbidden. Trivy's
  documentation says licence detection is not supported for `uv`, and the summary table that
  `make trivy` prints shows the Licenses column of `uv.lock` as not scanned. The forbidden list
  therefore cannot catch a Python package from `uv.lock`.
* **Exit code:** `exit-code: 1`, so a finding fails the check. `scripts/trivy.sh` first writes
  `reports/trivy.sarif` in a run that does not fail.
* **Skipped:** `.git`, `.venv` (so the installed environment is not scanned, only the lock), the
  editor, tool, cache and generated-output directories, and the local `.env` file.
* **Offline mode:** `TRIVY_OFFLINE=1` reuses the cached database. The hooks refuse to run
  `security` while any `*_OFFLINE` variable is set ([quality.md](quality.md#scanners)).

When it runs: `security` (Semgrep test, Semgrep, Trivy) is part of the release tier, which the hook
selects for a push whose remote ref is `refs/heads/main` or a tag. A commit or the push of another
branch does not run it. The stamp of a passed `security` check carries the UTC date, so it expires
at the end of that day: the Trivy database changes daily
([quality.md](quality.md#stamps)). The hooks are client-side only (`--no-verify` skips them) and the
hosted Trivy job (`ci-security.yml`) is only a report that nothing requires, so the hook is a gate that
stops mistakes and not a security boundary
([ADR-37](decisions.md#adr-37-git-hooks-are-the-one-place-the-checks-run)). In the hooks Trivy is not
scheduled: it runs at those pushes, or when someone runs `make trivy` (or `make gate-main`). The hosted job
runs it at every push to `main` and every pull request, and the weekly job below covers the time between
pushes.

### Weekly Trivy job

`.github/workflows/trivy-weekly.yml` runs `scripts/trivy.sh` on a GitHub runner every Monday (05:23 UTC)
and on demand (`workflow_dispatch`): the same `trivy.yaml`, the same pinned image and the same
`.trivyignore` as the push gate, so it has the same limits (HIGH and CRITICAL findings that have a fix,
the runtime packages only, no licence detection for uv). It scans `main` and needs no secret: the top-level
`permissions` is `{}` and the job has `contents: read`. A finding fails the run; GitHub then e-mails
the person who last changed the schedule, and the run shows as failed on the Actions tab. It does not
open a pull request or an issue. Two limits to know:

* The `trivy` job of `ci-security.yml` runs the same script on every push to `main` and every pull
  request, so a new advisory shows there only at the next push; the weekly run is what finds it in between.
* GitHub disables a scheduled workflow after 60 days without activity in the repository. For a finished
  project that gets few commits, the weekly scan can stop without anyone noticing; a push, or enabling
  the workflow again on the Actions tab, restarts it.
* It cannot be run from the maintainer's agents (Docker is used only through `make`), so its first run
  was on GitHub. Start it by hand with the Actions tab or `gh workflow run trivy-weekly.yml`.

### `.trivyignore`

An accepted finding goes in `.trivyignore`, one ID per line, in the form written in the file's
header:

```text
CVE-YYYY-NNNN exp:YYYY-MM-DD   # why this is not exploitable here
```

Every entry needs the reason and the expiry, and the file stays empty unless a finding is triaged.
`exp:` is Trivy's own syntax: after that date the finding is reported again. The reason-and-expiry
rule is a convention: no test or script checks it. At the time of writing the file has one entry:
`AVD-DS-0002`, the missing `USER` of `.clusterfuzzlite/Dockerfile` (the OSS-Fuzz builder image runs as
root by contract; expiry 2027-10-18).

### GitHub Dependabot

Dependabot alerts and Dependabot security updates are switched on in the repository settings. These
settings are on GitHub and are not part of the repository's files. The file
`.github/dependabot.yml` names the `uv` and `github-actions` ecosystems, and the `pip` and `docker`
ecosystems for `/.clusterfuzzlite` (the fuzz image, see below), all with
`open-pull-requests-limit: 0`, which turns off routine version-update pull requests, so Dependabot
proposes bumps only for known vulnerabilities. The lock and the lower bounds otherwise move when a
maintainer moves them.

Dependabot raises an alert only for packages that GitHub's dependency graph knows. On 2026-10-17,
after `dependabot.yml` was first pushed, the repository's dependency graph page still said "No
dependencies found" and the SBOM API listed only the repository itself. The next push, which also added a generated
`requirements.txt` (removed again afterwards, ADR-42), made GitHub run a Dependabot job named
`update-uv-graph`. Afterwards the SBOM API listed 76 packages (runtime and development tools),
GitHub's GraphQL API listed `uv.lock`, `pyproject.toml`, `requirements.txt` and the three workflow
files as parseable manifests, and no alert was open. The two changes arrived in one push, so it was
not tested which of them was needed; the copy was removed to keep one source, and the graph was
checked again afterwards: after the copy was removed and a new Dependabot job ran, it still lists the same
76 packages from `uv.lock` and `pyproject.toml`, so the `uv` entry in `dependabot.yml` is what makes GitHub read
the lock (ADR-42). On 2026-10-18 the SBOM API lists 79 entries: the Python packages of `uv.lock`, the GitHub
Actions the five workflows of that day used (the `github-actions` entry of `dependabot.yml` covers them) and the repository
itself; the manifests are `uv.lock`, `pyproject.toml` and the workflow files, and no alert is open. An empty list of alerts is still not proof that no
package is vulnerable: a vulnerability that GitHub's advisory database does not know, or that has no
fixed version, raises no alert.

### Qodana

`qodana.yaml` switches on the dependency licence audit (`CheckDependencyLicenses`) and the
vulnerable-library inspection (`VulnerableLibrariesGlobal`) and sets the failure thresholds of
critical, high and moderate problems to 0. It runs in the same push gate as Trivy, needs
`QODANA_TOKEN` in a local `.env`, and a push without the token fails. The same file lists `uv.lock`
among the paths excluded from the analysis, and no test shows that a forbidden licence or a
vulnerable package among the Python dependencies would fail the check. So the Trivy scan above is
the only dependency check of `uv.lock` that this page can describe as running.

## How dependencies are updated

There are two ways in, and one rule over both: no bump without agreement
([CONTRIBUTING.md](../CONTRIBUTING.md#rules-for-code)). The repository has no written procedure for
a bump; the steps below put the existing rules in order.

**A bump by a maintainer or a contributor.**

1. Agree it first: in an issue for a contributor, with the maintainer for an AI assistant.
2. Move the version: `uv lock --upgrade-package <name>` refreshes the package in `uv.lock`, and a
   lower bound in `pyproject.toml` is edited by hand. The repository has no wrapper script or
   `make` target for this and states no rule on when to raise a lower bound.
3. Commit `pyproject.toml` and `uv.lock` together, with the scope `deps` from the
   [commit policy](quality.md#commit-policy). A stale lock fails the gate.
4. Update [CHANGELOG.md](../CHANGELOG.md) and the page in `docs/` that describes any behaviour that
   changed ([CONTRIBUTING.md](../CONTRIBUTING.md#making-a-change)).
5. The change goes through the hooks like any other. The new lock changes the tree, so every check
   runs again at the next push, including the unit suite under `filterwarnings = error`; that suite
   and the end-to-end tests are what tests whether the new version works. On a push of `main` or a
   tag Trivy scans the new lock.

**A Dependabot pull request.** [GOVERNANCE.md](../GOVERNANCE.md#changes-and-review) describes the
review of changes from contributors; it does not mention automated pull requests, and the
repository has no procedure written for Dependabot pull requests. Two facts matter for it. GitHub
runs the unit-test job on a pull request, but not Trivy. And the hooks run on a push from a machine
that has them enabled: merging in the GitHub web interface does not pass through them. The rule
that "the hooks decide, not a person" ([quality.md](quality.md#definition-of-done)) is met only by
a push that went through the hooks.

**When Trivy refuses a push.** A finding of severity HIGH or CRITICAL (for example a
vulnerability with a fix) fails `security`, and the push of `main` or the tag is refused. The fix
is to bump the package. Only a finding that has been triaged as not exploitable goes into
`.trivyignore`, with its reason and expiry.
[CONTRIBUTING.md](../CONTRIBUTING.md#commits-and-the-git-hooks) asks that a hook is never bypassed
with `--no-verify`; nothing enforces that ([quality.md](quality.md#limits-and-rollback)).

## When a dependency is vulnerable

* **How it is found:** by Trivy on a push of `main` or a tag (HIGH and CRITICAL, with a fix, in the
  runtime packages), by a Dependabot alert on GitHub where its dependency graph covers the package,
  or by a private report ([SECURITY.md](../SECURITY.md#reporting-a-vulnerability)).
* **Does it affect Sankey Studio?** [SECURITY.md](../SECURITY.md#scope) puts out of scope
  "weaknesses in a dependency that do not affect Sankey Studio (report them upstream)". A weakness
  that does affect Sankey Studio is not excluded; report it as
  [SECURITY.md](../SECURITY.md#reporting-a-vulnerability) describes.
* **Timelines.** [SECURITY.md](../SECURITY.md#what-to-expect) promises an acknowledgement within 7
  days, a first assessment within 14 days, and a fix for a confirmed vulnerability of medium or
  higher severity within 60 days of the report, a critical one as soon as possible. They are targets
  for the maintainer, and a missed date will be explained in the advisory thread. These dates are
  written for reports. They do not say when the clock starts for a Dependabot alert or a Trivy
  finding, and the Trivy gate itself acts on HIGH and CRITICAL only.
* **The fix** is a bump (see above). While the project is 0.x only the latest release is
  supported, and SECURITY.md says a fix lands on `main` and ships as a new patch release
  ([SECURITY.md](../SECURITY.md#supported-versions), [release.md](release.md)). For a confirmed
  vulnerability SECURITY.md says the fix is published with a GitHub security advisory and a line in
  [CHANGELOG.md](../CHANGELOG.md).
* **No fix upstream.** Trivy does not report a vulnerability that has no fixed version, so the gate
  stays quiet about it. Removing or replacing the package (below) is the other way out.

## Adding, removing and replacing one

The repository has no separate procedure for these. The rules above apply, and the existing entries
show the form.

**Add.**

1. Agree it first (an issue for a contributor). The licence lists above are the only licence policy
   the repository has.
2. `uv add <name>` (runtime) or `uv add --group dev <name>` (development) updates `pyproject.toml`
   and `uv.lock`. The existing ranges are lower bounds, and an entry whose reason is not obvious has
   a comment, as `kaleido` and `httpx2` do.
3. If its import warns or it ships no type hints, handle that as described under
   [selection](#how-dependencies-are-selected).
4. Write the tests for the code that uses it; line and branch coverage of `src/sankey_studio` stays
   at 100% ([CONTRIBUTING.md](../CONTRIBUTING.md#rules-for-tests)).
5. A choice that shapes the design is written down as a decision record in
   [decisions.md](decisions.md) ([GOVERNANCE.md](../GOVERNANCE.md#decisions)).
6. Commit `pyproject.toml` and `uv.lock` together; the gates and Trivy then apply as above.

**Remove or replace.** Both change `pyproject.toml` and `uv.lock` like an add, so the same
agreement, tests and gates apply. Look for entries that were kept only for the package: a mypy
override, a `filterwarnings` entry or a `.trivyignore` line.

**The build requirement.** `hatchling` is changed in `[build-system].requires`. Check a build
without uploading with the commands in [release.md](release.md#checking-a-build-without-uploading).

## The workflows' own dependencies

There are ten workflows and one local composite action. `cflite_pr.yml` and `cflite_batch.yml` run the fuzz targets
([ADR-47](decisions.md#adr-47-fuzzing-runs-in-clusterfuzzlite-from-testsfuzz)). `.github/workflows/release.yml` runs on a push of a `v*` tag
([ADR-39](decisions.md#adr-39-releases-are-published-to-pypi-from-a-tag)); `trivy-weekly.yml` and
`scorecard.yml` run on a schedule, and the Scorecard also on a push to `main`
([ADR-40](decisions.md#adr-40-a-weekly-trivy-scan-and-the-openssf-scorecard-run-in-github-actions));
`codeql.yml` runs on a push to `main`, on a pull request to `main` and weekly ([ADR-43](decisions.md#adr-43-codeql-a-ruleset-on-main-and-signed-release-assets)).
Four more run the checks of the hooks hosted ([ADR-44](decisions.md#adr-44-a-hosted-ci-job-runs-the-unit-tests),
[ADR-48](decisions.md#adr-48-hosted-ci-runs-the-browser-memory-and-mongodb-suites-and-the-scanners),
[quality.md](quality.md#hosted-ci)): `ci.yml` (lint, types, caps, unit tests, memory budgets), `ci-e2e.yml` (browser
and real-MongoDB end-to-end tests) and `ci-security.yml` (Semgrep and Trivy) run on a push to `main`, on pull
requests and on demand, and `mutation.yml` runs only on demand. The local action
`.github/actions/no-skipped-tests` is part of the repository and needs no pin.

* **Actions are pinned to full commit SHAs**, with the version in a trailing comment:
  `actions/checkout`, `astral-sh/setup-uv`, `actions/setup-node`, `actions/upload-artifact`, `actions/download-artifact`,
  `pypa/gh-action-pypi-publish`, `ossf/scorecard-action` and `github/codeql-action` (`init`, `analyze` and `upload-sarif`). A moved tag
  cannot change which action code runs. A pin is bumped by hand (new SHA and new comment in the
  workflow file), and nothing in the repository watches
  for new versions: the `github-actions` entry in `dependabot.yml` allows security updates only.
* **The fuzz image is a second pin list.** The ClusterFuzzLite actions (`google/clusterfuzzlite/actions/build_fuzzers`
  and `run_fuzzers`) are pinned to the commit of `v1` like the other actions, but they start Docker
  images tagged `:v1` that the commit does not fix. `.clusterfuzzlite/Dockerfile` pins its base image
  (`gcr.io/oss-fuzz-base/base-builder-python`) and `uv` by digest and installs CPython 3.14.7. The project's
  runtime packages come from `uv.lock` (`uv sync --frozen --no-dev`, hash-checked), so the lock stays the one
  source of the application's dependencies (ADR-42). The fuzzing tools (`atheris`, `pyinstaller`) are listed in
  `.clusterfuzzlite/requirements.in` and pinned by hash in `.clusterfuzzlite/requirements.txt`, made with
  `uv pip compile --generate-hashes`; they are not in `pyproject.toml` or `uv.lock`, and the application never
  imports them. Dependabot reads that file and the Dockerfile (security updates only). The image runs as root,
  as the OSS-Fuzz builders do.
* **Least privilege.** The top-level `permissions` is `{}`, the build job has `contents: read`, and
  only the two upload jobs have `id-token: write`. Checkout uses `persist-credentials: false`, and
  the tag name reaches the shell through an environment variable and not by interpolation. No PyPI
  token exists: the upload uses trusted publishing. The two scheduled workflows also start from
  `permissions: {}`; the Trivy job has `contents: read` only, like every job of `ci.yml`, `ci-e2e.yml`,
  `ci-security.yml` and `mutation.yml`, and the Scorecard job adds `actions: read`,
  `security-events: write` and `id-token: write` to upload its report and publish its result.
* **The hosted test jobs fetch unpinned things too.** The runner image (`ubuntu-24.04` as GitHub keeps it)
  supplies Google Chrome and Docker; `setup-node` is given the major version 22 only, and `setup-uv` no uv
  version. The `semgrep`, `trivy` and `e2e-mongo` jobs pull Docker images without logging in (the scanners
  by the tag in their scripts, MongoDB by digest), and Semgrep fetches its registry rule packs and Trivy
  its database when they run. `uv sync --all-extras --locked` installs from `uv.lock` and fails if the lock
  is out of date. No cache is used.
* **Tools the build job fetches are not pinned.** `uv build` resolves `hatchling` at build time.
  `uvx twine check --strict` takes the current twine. The workflow sets no uv version for
  `setup-uv`, uses the `ubuntu-24.04` runner image as GitHub keeps it, and names only `--python
  3.14` (no patch version) for the wheel smoke test. That smoke test
  (`uv tool run --from ./dist/*.whl ...`) installs the wheel's dependencies from their ranges, as a
  user's install would, and not from `uv.lock`. So the repository does not claim that a rebuild
  gives byte-identical files. What it does give is a signed link between the published files and
  this repository and workflow ([release.md](release.md#verifying-a-release)).
* **The release workflow runs no tests and scans nothing.** The checks, Trivy included, run in the
  maintainer's git hooks when the tag is pushed, and those are client-side. The tests run in the hooks (all suites) and in the hosted `ci.yml`, `ci-e2e.yml` and `ci-security.yml` (all except Qodana and the replica-set suite).

## Limits

Collected in one place, so nothing here is read as a stronger promise than it is:

* The gates are git hooks. They are client-side, skipped by `--no-verify` or a clone without
  `make hooks`, and the hosted workflows (unit, browser, memory and MongoDB suites, Semgrep, Trivy) report but nothing requires
  them to pass: there is no required check or review on `main` (a ruleset blocks only deleting it and force-pushing to it).
* In the hooks Trivy runs only on a push of `main` or a tag; the hosted job runs it at every push to `main`
  and pull request, and the weekly job (which GitHub stops after 60
  days without repository activity) adds a scan between pushes; all three report HIGH and CRITICAL findings that have a
  fix, and only the hooks can refuse a push. By default it leaves out the packages that only the `dev` group needs.
* The repository does not show a working licence check of the Python packages in `uv.lock`: Trivy
  cannot detect them for uv, and `uv.lock` is excluded from the Qodana analysis. The licence lists
  state intent.
* The agree-first rule and the `.trivyignore` rule (reason and expiry) are conventions that nothing
  checks. A maintainer's own dependency change has no second reviewer.
* The lock describes the maintainer's environment, not the one a user's install resolves.
* Build requirements, twine, the uv version in the workflow, the runner image and the Docker images
  are not locked by `uv.lock`; the images are pinned by tag, not by digest (the MongoDB service container of
  `ci-e2e.yml` is pinned by digest), and the Google Chrome of the runner image is not pinned. Scanner databases and
  rule packs are fetched when a scan runs.
* Dependabot is switched on in GitHub's settings, outside the repository, and `dependabot.yml`
  limits it to security updates (no routine update pull requests). GitHub's dependency graph lists the
  locked packages since 2026-10-17 and no alert was open then. Between pushes of `main` or a tag the
  dependencies are watched by Dependabot's alerts and by the weekly Trivy job, which GitHub stops after
  60 days without repository activity (that does not stop Dependabot's alerts).
* There is no written admission test beyond agreement in an issue, the licence lists and the
  no-network-assets rule.
