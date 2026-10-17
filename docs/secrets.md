# Secrets

This page covers the project's own credentials and the way the application treats the MongoDB
connection strings of the people who run it: which secrets the project has, where they live, who
may hold them, what keeps them out of the repository, and what to do when one is exposed. Related:
[SECURITY.md](../SECURITY.md) (reporting a vulnerability), [GOVERNANCE.md](../GOVERNANCE.md#access)
(who gets access), [release.md](release.md) (publishing), [quality.md](quality.md#scanners) (the
scanners), [architecture.md](architecture.md#security-design) and [decisions.md](decisions.md) (the
ADRs are linked where they apply).

Contents

* [In short](#in-short)
* [Inventory](#inventory)
* [Storage rules](#storage-rules)
* [Access and the release workflow](#access-and-the-release-workflow)
* [Prevention and detection](#prevention-and-detection)
* [What must never be committed or logged](#what-must-never-be-committed-or-logged)
* [How the application handles MongoDB URIs](#how-the-application-handles-mongodb-uris)
  * [The credentials file](#the-credentials-file)
* [Rotation and revocation](#rotation-and-revocation)
* [If a secret is exposed](#if-a-secret-is-exposed)
* [Limits](#limits)

## In short

* The project has two secrets of its own: the Qodana token and the URI of the test replica set.
  Both are kept in a gitignored `.env` in the lead maintainer's checkout (either can also be given
  through the process environment). Neither is needed to run or build the application, to run the
  unit suite or to run the main end-to-end suite; they are needed by two checks of the gate that
  runs when `main` or a tag is pushed, and by the two preflight probes that look for them first.
* The project has no PyPI token and no GitHub Actions secret. Releases use PyPI trusted publishing
  (OIDC), so no publishing credential is stored in the repository or in the GitHub settings.
* The checks that guard against secrets are Trivy, Semgrep (the registry pack `p/secrets` and two
  project rules), unit and end-to-end tests that scan responses and logs for a test password, and
  GitHub secret scanning with push protection. Trivy and Semgrep run in the git hooks, which are
  client-side and can be bypassed, and only for a push of `main` or a tag. The hosted CI runs only the unit tests.
  See [Limits](#limits).
* The application keeps the connection strings of its users in `credentials.json`, a file apart
  from `settings.json` (always mode 0600, in a directory it creates with mode 0700), and never
  returns them or writes them to its own log lines: the API gives `uri_masked` and `has_secret`, and
  the application's log lines carry the connection name only. The file can be replaced while the
  server runs ([The credentials file](#the-credentials-file)).
* There is no rotation schedule. A secret is replaced when it is exposed or suspected to be.

## Inventory

### Secrets of the project

| Secret | What it opens | Where it lives | Used by |
|---|---|---|---|
| `QODANA_TOKEN` | The Qodana Cloud project token for the Ultimate Plus licence; results are uploaded to Qodana Cloud | `.env` at the repository root of the lead maintainer's checkout (gitignored), or the process environment. `.env.example` names the key with an empty value | `scripts/qodana.sh` (`make qodana`, `make preflight-qodana`) and the `qodana` check of a push of `main` or a tag |
| `SANKEY_TEST_MONGO_RS_URI` | A MongoDB user on a replica set that the maintainer runs. The tests use only the database named in the URI path, which must be empty | The process environment, else the same `.env` ([e2e.md](e2e.md#replica-set) shows the form; `.env.example` does not list this key) | `tests/e2e/mongo_rs` (`make e2e-mongo-rs`, `make preflight-rs`) and the `e2e-mongo-rs` check of a push of `main` or a tag |

Day-to-day work needs neither. The unit tests use mongomock, an autouse guard removes the `SANKEY_*`
variables from the environment of every test (a test marked `mongo` or `mongo_rs` keeps its one
variable), and a tripwire refuses a real MongoDB connection (see
[Test conventions](quality.md#test-conventions)). Only the `mongo_rs` end-to-end tests and the
Qodana run use these two secrets.

### What the project does not have

| Kind | State on 2026-10-17 | How to check again |
|---|---|---|
| PyPI or TestPyPI API token | None ([ADR-39](decisions.md#adr-39-releases-are-published-to-pypi-from-a-tag)). Uploads use trusted publishing | The API tokens list in the account settings of PyPI and TestPyPI (the account owner sees it). The provenance page of a published file, for example `https://pypi.org/integrity/sankey-studio/0.1.0/sankey_studio-0.1.0-py3-none-any.whl/provenance`, names the publisher: repository, workflow and environment |
| Repository Actions secrets | 0 | `gh api repos/Axiumine/Sankey-Studio/actions/secrets --jq .total_count` |
| Secrets of the `pypi` and `testpypi` environments | 0 each | `gh api repos/Axiumine/Sankey-Studio/environments/pypi/secrets --jq .total_count` (and `testpypi`) |
| Dependabot secrets, organization Actions secrets | 0 | `gh api repos/Axiumine/Sankey-Studio/dependabot/secrets --jq .total_count`, `gh api orgs/Axiumine/actions/secrets --jq .total_count` |
| Deploy keys, webhooks | 0 | `gh api repos/Axiumine/Sankey-Studio/keys --jq length`, `.../hooks --jq length` |

Only the maintainers can run the `gh api` commands: they read the settings of the repository and
of the organization. The release workflow does not use the `secrets` context at all.

### Powers that behave like secrets

These are not files in the repository, but whoever holds them can act as the project, so they are
listed here and covered by [Rotation and revocation](#rotation-and-revocation):

* **The maintainers' accounts.** The two owners' accounts on GitHub (the organization requires
  two-factor authentication, [GOVERNANCE.md](../GOVERNANCE.md#access)) and the lead maintainer's
  account on PyPI. The PyPI project and the approval of a release are held by the lead maintainer
  ([MAINTAINERS.md](../MAINTAINERS.md)).
* **The trusted publisher** registered on PyPI and TestPyPI: owner `Axiumine`, repository
  `Sankey-Studio`, workflow `release.yml`, environment `pypi` or `testpypi`
  ([release.md](release.md#one-time-setup)). The workflow asks GitHub for a short-lived identity
  token, and PyPI accepts it only from that repository, workflow and environment.
* **The signing key** of the maintainer's commits and release tags (SSH signatures). The private
  part is held by the maintainer and is not in the repository; the public key is registered with
  the GitHub account, which is why GitHub shows the commits and the release tag as verified.

## Storage rules

* A project secret goes in the `.env` at the root of the lead maintainer's checkout or in the
  process environment of whoever runs the gate, and nowhere else. `.gitignore` excludes `.env` and
  `.env.*` and re-includes `.env.example`, which holds the key name and no value. As far as the
  scanners below can tell, the repository holds no real credential.
* Never copy a secret into the repository, a commit message, an issue, a pull request, a document,
  a chat, a test fixture or a GitHub setting. Fixtures use made-up values (for example the user
  `u`, the password `pw` and the host `cluster0.abc.mongodb.net` in `tests/test_util.py`).
* Two programs read `.env`, and they read it differently. `scripts/qodana.sh` sources the whole file
  into its own process (so every variable in the file, the replica-set URI included when it is kept
  there, is in the environment of the Qodana run); it never prints it, never writes it to a file
  and never puts it on a command line. `tests/e2e/support/rs_env.py` takes one key only, see the
  next point. The hook gate never opens `.env` ([Fail-closed rules](quality.md#fail-closed-rules)),
  and `CLAUDE.md` tells agent sessions not to read, print or copy it
  ([Scanners](quality.md#scanners)); that is an instruction, not a technical block. The application
  itself does not read `.env`: it reads `SANKEY_*` environment variables and its flags only. Docker
  Compose, which `make mongo-up` runs, loads a `.env` from the project directory for variable
  interpolation by default; `docker-compose.yml` uses no variable, so nothing from it reaches the
  container.
* The scanners are told to skip `.env` (Trivy in `trivy.yaml`, Semgrep in `.semgrepignore`, Qodana
  in `qodana.yaml`), but they run in Docker with the checkout mounted, so the file is present in
  their containers and the skip is a configuration, not an absence.
* The tests read exactly one key from it. `tests/e2e/support/rs_env.py` takes
  `SANKEY_TEST_MONGO_RS_URI` from the environment, else parses `.env` for that key alone, because
  the file also holds the Qodana token and no test may see it. The value goes to the caller: it is
  not logged, not printed and not copied into `os.environ`.
* Keep `.env` readable by its owner only.

## Access and the release workflow

**Who holds what.** The two project secrets are held by the lead maintainer. The people listed in
[MAINTAINERS.md](../MAINTAINERS.md) are the only ones with access to the repository settings, the
organization and the PyPI project; the PyPI project and the approval of a release are the lead
maintainer's alone for now. Contributors have no access and need none: no workflow runs on a
pull request (the release workflow runs when a `v*` tag is pushed; the other two run on a schedule, on a push
to `main` or when branch protection changes). Write access, two-factor authentication and
removal of access are described in [GOVERNANCE.md](../GOVERNANCE.md#access); access is removed at
once if an account may be compromised.

**The release workflow** (`.github/workflows/release.yml`) is built so that a compromised step has
little to take:

* `permissions: {}` at the top; the `build` job gets `contents: read`; only the two upload jobs get
  `id-token: write`, and they get nothing else.
* The checkout uses `persist-credentials: false`, so the repository token is not left in the
  checkout. Every action is pinned to a full commit SHA. The tag name reaches the shell through an
  environment variable and is never interpolated into a command line.
* The default workflow permission of the repository is `read`, and workflows cannot approve pull
  request reviews.
* The `testpypi` and `pypi` environments deploy only from tags that match `v*`, and `pypi` has one
  required reviewer. Neither environment holds a secret or a variable.

**Accepted risks.** [ADR-39](decisions.md#adr-39-releases-are-published-to-pypi-from-a-tag)
accepts that whoever can push a `v*` tag starts the build and the TestPyPI upload, that the required
reviewer of the `pypi` environment is the second lock before PyPI, and that the workflow trusts the
tag's commit as the maintainer pushed it, because the hooks that check the tree are client-side.
That lock is a deliberate pause, not a second person: GitHub is not set to stop a reviewer from
approving a run they started (`prevent_self_review` is off), and repository administrators may
bypass the environment's protection rules (the setting is on). The workflow runs no tests. A
ruleset stops a `v*` tag from being deleted or moved ([release.md](release.md#one-time-setup)); it does not stop
anyone with write access from creating one. A second ruleset protects `main` against deletion and
force-push, nothing else.

## Prevention and detection

| Layer | Where it runs | What it covers | What it does not cover |
|---|---|---|---|
| `.gitignore` | Every clone | `.env` and `.env.*` (not `.env.example`), `data/`, and `credentials.json` with the `.corrupt-<n>` copies of it and of `settings.json` | Other file names (there are no patterns for key or certificate files, and a `settings.json` outside `data/` is not ignored) and `git add -f` |
| Trivy secret scan (`make trivy`, [Scanners](quality.md#scanners)) | The `security` check of a push of `main` or a tag, in the maintainer's hooks | Files of the working tree, with HIGH and CRITICAL findings failing the check | Git history, pushes of other branches, commits (`pre-commit` runs lint, types and caps only), and `.env`, which is skipped on purpose |
| Semgrep registry packs, among them `p/secrets` (`make semgrep`) | Same `security` check, on `src` and `scripts` | The patterns of those packs | Tests, docs and history; the packs need the network and are dropped by `SEMGREP_OFFLINE=1`, which the gate refuses |
| Semgrep `sankey-no-secret-in-logs` | Same `security` check, on `src` and `scripts` | A call of `debug`, `info`, `warning`, `warn`, `error`, `exception`, `critical` or `log` that is given `get_secret_value()` directly or inside an f-string | Other ways of reaching a log |
| Semgrep `sankey-no-secret-in-exceptions` | Same | A `raise` that is given `get_secret_value()` directly or inside an f-string | Other ways of reaching an error message |
| Unit tests (`cov`, every push): `tests/web/test_matrix_secrets.py`, `tests/web/test_schemas_secret_logs.py`, `tests/web/test_routes_graphs_secrets.py`, `tests/storage/test_settings_store.py` | Every push | A saved test password and a driver that echoes the whole URI in its error: no response body, header or log record may hold them | Secrets other than those test values |
| End-to-end test `tests/e2e/http/test_security_secrets_flow.py` | `e2e`, every push | Drives the settings, Mongo, graph, export and page routes with a stored password, then scans every response, log record and printed line for it | Secrets other than that test password |
| GitHub secret scanning | GitHub; enabled (checked on 2026-10-17) | The repository, including earlier commits, and every later push, for the secret types GitHub recognises | Types it has no pattern for; non-provider (generic) patterns and validity checks are off |
| GitHub push protection | GitHub; enabled (checked on 2026-10-17) | A push that contains a secret of a recognised type is blocked | Same |

Secret scanning has raised two alerts, first seen in two early commits. Both are resolved as "used
in tests": they are the fake connection strings in `tests/test_util.py` and
`tests/test_contract_mongo_safety.py` (a one-letter user, a two-character password, a made-up Atlas
host). Neither is a credential. An alert on anything else is treated as a leak
([If a secret is exposed](#if-a-secret-is-exposed)).

The git hooks are client-side only (`--no-verify`, a changed `core.hooksPath` and a fresh clone
skip them), the hosted CI runs only the unit tests and `main` has no required check or review (a ruleset blocks only deletion and force-push)
([ADR-37](decisions.md#adr-37-git-hooks-are-the-one-place-the-checks-run)). The checks are a
safety net for the maintainers, not a boundary.

## What must never be committed or logged

Never committed, pasted into an issue, a pull request or a vulnerability report, or put in a
commit message or a test fixture:

* the value of `QODANA_TOKEN` or `SANKEY_TEST_MONGO_RS_URI`, or any other token or password;
* a MongoDB connection string that carries credentials, whether it belongs to a maintainer, a user
  or a test database, and including one that only looks fake but is real;
* a `credentials.json`, a `credentials.json.corrupt-<n>` copy, a `settings.json` from an earlier
  version (it can still hold connection strings), or a copy of a data directory or of a backup of
  it (they hold connection strings in plain text);
* a private key, a certificate with its key, or an SSH key.

Never logged, never put in an error message, an API response, an export or a saved graph:

* the value of a `SecretStr`, or a connection string in any form other than `mask_uri(...)` output;
* the text of a driver exception (it can echo a connection string), or the input of a validation
  error. Log and report the connection name and the exception class.

## How the application handles MongoDB URIs

People give the application MongoDB connection strings, which usually carry a user name and a
password. The application treats them as secrets in every layer:

| Rule | Where it is enforced |
|---|---|
| A connection URI is a pydantic `SecretStr`. `repr`, `str` and `model_dump()` show a placeholder, never the value, and the validator refuses a masked placeholder, so a round trip through the UI cannot overwrite the real value. The same validator refuses URI options that read local files, load code or weaken TLS (for example `tlsCAFile`), naming the option key and never its value. `SANKEY_MONGO_URI` is a `SecretStr` too | `MongoConnection` in `src/sankey_studio/models/settings.py`; `check_mongo_uri` in `src/sankey_studio/mongo_safety.py`; `BootstrapConfig` in `src/sankey_studio/config.py` ([ADR-04](decisions.md#adr-04-secrets-never-leave-the-settings-store)) |
| `dump_settings` and `load_settings` are the only code that validates a settings document with its real values, and `SettingsStore` with `split_credentials` and `join_credentials` the only code that moves them between that document and the two files (the strings go to `credentials.json`, `settings.json` never holds one). Other code reads the real value only to use it: to open the Mongo client, to key the result cache and the write-back target, and to merge a settings save | `src/sankey_studio/storage/settings_store.py`, `src/sankey_studio/storage/credentials.py`, `src/sankey_studio/models/credentials.py` ([ADR-46](decisions.md#adr-46-connection-strings-live-in-credentialsjson)); the other call sites are `mongo.py`, `pipeline.py`, `services.py`, `edits/target.py` and `web/schemas/settings.py` |
| `settings.json` and `credentials.json` are always written atomically with mode 0600, `credentials.json` first. The data directory is created with mode 0700; an existing one owned by someone else is refused, and an existing one that group or others can write to loses those write bits (its read and search bits are left as they are). A settings file that is not valid JSON or not valid settings is moved aside as `settings.json.corrupt-<n>`, together with `credentials.json` as `credentials.json.corrupt-<n>` (still 0600; at most 20 copies, the last one is reused) instead of being overwritten; a file that cannot be opened (a symlink, not a regular file, over 1 MiB) is reported and left in place. A `credentials.json` that is broken is reported and never moved; one that group or others can read is tightened to 0600 on load | `settings_store.py`, `src/sankey_studio/storage/atomic.py` ([ADR-18](decisions.md#adr-18-hardening-of-files-settings-and-exports)) |
| `mask_uri` rebuilds the URI from an allow-list: scheme, `user:***`, hosts, database and the values of a short list of options (`SAFE_URI_OPTIONS`), and only when the value looks plain; every other option keeps its key and shows `***`, and an option whose key is unreadable is dropped. It never raises. No `mongodb` or `mongodb+srv` scheme gives `***`; any structural doubt gives `mongodb://***`. Its patterns end in `\Z`, so a newline cannot slip through | `mask_uri` and `looks_masked` in `src/sankey_studio/util.py` ([ADR-15](decisions.md#adr-15-uri-masking-fails-closed)); tests in `tests/test_util.py` |
| The API returns `uri_masked` and `has_secret` and has no field called `uri`. A save that sends no URI, an empty one, a masked one or the masked form of the stored one keeps the stored secret (a connection with no stored secret and no real URI is refused) | `ConnectionOut`, `SettingsOut` and `merge_settings` in `src/sankey_studio/web/schemas/settings.py` |
| While a remote server is read-only, the settings answer hides hosts and user names too (`mongodb://***`) | `connection_out` in the same file ([ADR-17](decisions.md#adr-17-remote-mode-is-read-only-by-default)) |
| Driver failures reach the caller as a message built from the connection name and, for some failures, the exception class, never the driver text. The CLI and `BootstrapConfig` print validation problems without their input (`hide_input_in_errors`), and the 422 answer of the API lists locations and messages, never the submitted value | `mongo_errors` in `src/sankey_studio/mongo.py`; `src/sankey_studio/cli.py`; `src/sankey_studio/web/errors.py` |
| A saved graph names its connection and never holds the URI. The result cache keys on the masked URI plus a SHA-256 digest of the secret one, so a rotated password invalidates old results; the digest is never logged or returned. The write-back target key carries a 12-character SHA-256 fingerprint of the masked URI and the default database, not the URI | `_mongo_stamp` in `src/sankey_studio/pipeline.py`; `src/sankey_studio/edits/target.py` |
| Two Semgrep rules reject `get_secret_value()` in a log call or a `raise`, and the tests scan the responses and logs of the routes they drive. Other routes to a log or an error are not covered | `.semgrep/rules/sankey.yml`; `tests/e2e/http/test_security_secrets_flow.py` and the unit tests in [Prevention and detection](#prevention-and-detection) |

What this does not do:

* `credentials.json` holds the URIs in plain text. It is not encrypted. Its protection is the file
  mode, the directory mode and the account of the person who runs the server, so anyone who can
  read the file as that user (or as root), and any backup or copy of the data directory, has the
  passwords. Keep the data directory out of shared folders and repositories.
* `SANKEY_MONGO_URI`, like any environment variable, is visible to other processes of the same
  user. There is no command line option for a URI, so it is never on a command line. It only seeds
  a connection named `default` while no `settings.json` exists; seeding writes nothing, and the
  first save of the settings that keeps this connection stores its URI in `credentials.json`.
* The only logging setting is the log level of uvicorn (`SANKEY_LOG_LEVEL`). The application does
  not configure the logging of the MongoDB driver or of other libraries; its own log lines carry
  the connection name only.
* There is no login. On a server that allows writes (loopback, or `--allow-remote-writes`), anyone
  who can reach it can add or change connections. The real limits are the privileges of the
  database user, so give the application a user that can do only what you want it to do
  ([README](../README.md#security-model)).

### The credentials file

`<data-dir>/credentials.json` holds the connection strings, apart from `settings.json` (which keeps the connection names and default databases and no password):

```json
{
  "version": 1,
  "mongo_connections": {
    "main": {"uri": "mongodb://user:password@host:27017/?replicaSet=rs0"}
  }
}
```

* The keys are the connection names of the Settings page. A connection with no entry is an error (`settings_error`, HTTP 422) that names the connection and the file; an entry whose name is not a connection is ignored and dropped by the next save.
* **Replace or rotate.** Edit the connection in Settings (a save rewrites the file), or replace the file while the server runs: write the new file next to it and `mv` it over `credentials.json`. The change applies on the next request, with no restart. Keep the mode 0600: a file that group or others can read is tightened to 0600 on load; a file owned by another user, a symlink or a file over 1 MiB is refused.
* **Back up** both files together. Deleting `settings.json` does not delete the strings, and the next save replaces `credentials.json`; to start over delete both, and copy `credentials.json` first if you want to keep the strings.
* **A broken file** is never moved or overwritten: the application answers 422 `credentials.json is not valid JSON` or `credentials.json is invalid` with the places that are wrong (never the values) until you fix it. If `settings.json` is the corrupt one, both files go aside together as `settings.json.corrupt-<n>` and `credentials.json.corrupt-<n>`.
* **Upgrading.** A `settings.json` written by an earlier version keeps the strings in its connection entries; they are read as they are and the next save of the settings (any change on the Settings page) moves them to `credentials.json`. Downgrading afterwards is not supported: the older version cannot read the new `settings.json` and moves it aside.
* The file is not encrypted (see above).

If you think a connection string of yours has leaked (a copied `credentials.json`, a shared backup),
change the password at the database first, then enter the new URI in Settings. Deleting your copy
of the file does not undo the leak.

## Rotation and revocation

There is no rotation schedule. A secret is replaced when it is exposed or you suspect it is (see
[If a secret is exposed](#if-a-secret-is-exposed)). A lost or stolen machine that holds `.env` is
a case of suspicion: treat both secrets, the maintainer's accounts and the signing key as exposed.

Removing a maintainer's access ([GOVERNANCE.md](../GOVERNANCE.md#access)) also means removing
their entry as a reviewer of the `pypi` environment and as a collaborator of the PyPI project
([release.md](release.md#one-time-setup)).

Where each one is revoked and where its replacement goes:

| Secret | Revoke at the issuer | Put the replacement |
|---|---|---|
| `QODANA_TOKEN` | Qodana Cloud, where the token was created (the project and its token; see `.env.example`) | In `.env`, replacing the old value |
| `SANKEY_TEST_MONGO_RS_URI` | The replica set: change the password of the test user, or remove the user | In `.env` or the environment, replacing the old value |
| Trusted publisher | The publishing settings of the PyPI and TestPyPI projects: delete the publisher entry | Register the publisher again once the cause is understood |
| A maintainer's GitHub or PyPI account | The service: end all sessions, change the password, replace the second factor, review the account's tokens and keys | The account owner |
| Signing key | The GitHub account: remove the public key from the signing keys | A new key, registered the same way |
| A user's connection string | The user, at their own database | The user, in Settings |

## If a secret is exposed

Exposed means pushed, pasted into an issue or a chat, printed in a log, shipped in a release or
found by secret scanning. Do not wait to confirm: from that moment treat it as public.

1. **Revoke it at the issuer** (table above). Do this before anything else; deleting the text does
   not undo an exposure.
2. **Issue a replacement** and store it as in [Storage rules](#storage-rules).
3. **Look at the issuer's activity** from the time of the exposure to the revocation, for whatever
   the issuer keeps: reports in Qodana Cloud that you did not upload; the authentication log of
   the replica set and any collection in the test database that the tests did not create; the
   audit log, security log and Actions runs of the GitHub account and organization; the history of
   the PyPI project and account.
4. **Remove it from where it sits.**
   * Only in a local commit: amend or rebase it away before pushing.
   * In a pushed branch or in `main`: the rotation is the fix. Rewriting history and force-pushing
     is the maintainers' decision, taken after the rotation. It does not reach forks, clones or
     caches, it changes the hash of every later commit and drops their signatures unless they are
     signed again, and a tag on a rewritten commit has to be created again.
   * In a published release: a file name on PyPI is used for good, even after a delete, so a
     release cannot be replaced. Yank it and publish a fixed patch version
     ([release.md](release.md#things-that-cannot-be-undone)); a yanked file can still be
     downloaded, so here too the rotation is the fix. The source distribution contains `src/`,
     `docs/*.md`, `README.md`, `LICENSE`, `CHANGELOG.md`, `SECURITY.md` and `CONTRIBUTING.md`, so a
     secret in those ships.
5. **Close the scanning alert** only after step 1. A real secret is closed as revoked. A fake
   fixture is closed as used in tests, as the two existing alerts were.
6. **Tell the people affected.** If users' credentials or data could be affected, or a release
   contained the secret, publish a GitHub security advisory and a line in
   [CHANGELOG.md](../CHANGELOG.md), as [SECURITY.md](../SECURITY.md#what-to-expect) describes for a
   fixed vulnerability.

**If you find a secret that is not yours**, in the repository, a release, a log or a response of
the application, report it privately through GitHub, as
[SECURITY.md](../SECURITY.md#reporting-a-vulnerability) describes, not in an issue. Say where it
is; do not paste the value. A connection string, password or other secret in an API response, log,
error message or export is in scope there, and the project treats it as a vulnerability of the
application.

## Limits

* The scanners are a safety net, not a boundary. The hooks are client-side, the hosted CI runs only the unit tests,
  and the gate runs Trivy's and Semgrep's secret detection only for a push of `main` or a tag (or
  when someone runs `make trivy` or `make semgrep`), over the working tree, not over the history
  and not over `.env`.
* The two Semgrep project rules match two code shapes. They do not prove that no secret reaches a
  log or an error by another route; the tests scan the routes they drive, and the maintainers' own
  changes get no second reviewer yet ([GOVERNANCE.md](../GOVERNANCE.md#changes-and-review)).
* Of the names that can hold a secret, `.gitignore` lists the dotenv files and `data/` only. A key
  or certificate saved under another name is not ignored.
* GitHub secret scanning and push protection find the secret types they have patterns for; its
  generic-pattern and validity checks are off.
* `credentials.json` is not encrypted ([above](#how-the-application-handles-mongodb-uris)).
* The repository and the GitHub settings hold no copy of the two project secrets, so a lost `.env`
  cannot be restored from there; new ones are issued at the issuer.
