# Security assurance case

This page argues, with evidence, that Sankey Studio meets its security requirements. It is the
maintainers' own assessment of their own work, not an external audit, and it says where the argument
is weak ([Residual risks and known gaps](#residual-risks-and-known-gaps)). It covers release 0.1.0
and `main`. The design is described in [architecture.md](architecture.md#security-design) and in the
decision records in [decisions.md](decisions.md); this page does not repeat them. It connects each
threat to a control, to the code that implements it and to the tests that exercise it. Code
paths are relative to `src/sankey_studio/`; test paths start with `tests/`; the workflow, scripts,
scanner configuration and lock file are named from the repository root. To report a vulnerability,
follow [SECURITY.md](../SECURITY.md).

Contents

* [Scope and security requirements](#scope-and-security-requirements)
* [Claims](#claims)
* [Threat model](#threat-model)
* [Threats, controls and evidence](#threats-controls-and-evidence)
* [Secure design principles](#secure-design-principles)
* [Common weaknesses](#common-weaknesses)
* [Supply chain and release integrity](#supply-chain-and-release-integrity)
* [Residual risks and known gaps](#residual-risks-and-known-gaps)
* [Evidence index](#evidence-index)

## Scope and security requirements

In scope: the Python server (`src/sankey_studio`), the vanilla JavaScript frontend it serves
(`web/static`, `web/templates`) and the way the package is built and released. Relied on but not
covered: the operating system, the browser, Chrome and kaleido, MongoDB itself, the third-party
libraries (FastAPI, pymongo, Plotly and the rest) and the GitHub and PyPI platforms.

Deployment model:

* A local application. `sankey-studio serve` binds `127.0.0.1` and has no login (a product
  requirement, see [decisions.md](decisions.md)), so the network boundary is the access control.
* One uvicorn process with one worker, no TLS of its own, WebSockets switched off, and forwarded
  headers not trusted (`workers=1`, `ws="none"` and `proxy_headers=False` in `cli.py`
  `_run_server`).
* An optional remote mode (`--allow-remote`) for a trusted network. Every endpoint that persists
  something is then read-only. `--allow-remote-writes` lifts that, and writing edits back to a
  MongoDB source needs `--allow-source-writes` as well. Without `--allow-remote`, both kinds of
  write are always allowed.
* The data: text files in a managed sources folder, saved graphs on disk or in MongoDB, and the
  MongoDB collections the user points it at (read-only unless the user opts in to write-back).

What the software is built to guarantee:

| ID | Requirement |
|---|---|
| R1 | The server is reachable only from the local machine unless the operator opts in, and an opened server is read-only unless the operator opts in again. |
| R2 | A web page in the user's browser cannot make the app change state or read its API (cross-site requests, DNS rebinding). |
| R3 | Reading, uploading, deleting and writing back source files stays inside the managed sources folder (hard links are the known exception, see T4). |
| R4 | A user-supplied MongoDB filter or pipeline cannot write, run code or read a system database. The application itself writes to MongoDB in two places only: the library store, when the operator chooses the MongoDB storage backend, and the source write-back, when the person agrees. Both are bounded (see T7). |
| R5 | Passwords and other secrets in connection strings never appear in API answers, logs, errors, exports or bundles; the API shows only a masked form. |
| R6 | User text (names, categories, titles, cell values) cannot become script, markup or a spreadsheet formula in a page, an export or a stored source. |
| R7 | A small request cannot exhaust memory, disk, connections or Chrome. |
| R8 | The package a user installs is the one the project built from the tagged source. |

Not guaranteed: authentication, separation between users, confidentiality on a network, protection
against the local user or against malware already on the machine, and anything the privileges of the
MongoDB user decide.

## Claims

Top-level claim (C0): in the deployment model above, and apart from the residual risks listed below,
Sankey Studio is built to keep the user's files, saved graphs, MongoDB data and credentials, and the
host machine, safe from the actors of the threat model.

| ID | Sub-claim | Rests on |
|---|---|---|
| C1 | The server is closed to the network by default and read-only when opened (R1) | T3 |
| C2 | A hostile web page cannot drive the app (R2) | T1, T2 |
| C3 | File access stays inside the sources folder (R3) | T4 |
| C4 | User queries are read-only, and the two MongoDB writers are opt-in and confined to their own collections or to one field of at most 1000 documents (R4) | T5, T6, T7 |
| C5 | Connection secrets never leave the settings store; only a masked form does (R5) | T8 |
| C6 | User text cannot become code, markup or a formula (R6) | T9, T10 |
| C7 | A small request cannot exhaust the machine (R7) | T11, T12, T13 |
| C8 | The released package is the tagged source, built by the project's workflow (R8) | T14, T15 |

C1 to C7 each rest on a control in the code and on tests that exercise it. Some also rest on a
Semgrep rule or a policy test, and the threat table names them. The mutation-score gate (at least
90) measures how many deliberate changes to the code the tests notice; it is evidence about the
tests, not proof of them. C8 rests on the release workflow, the GitHub settings and a check anyone
can run by hand (T15), not on tests. The argument is only as strong as those tests and gates, and
they have blind spots: mutation testing skips `cli.py` and `__main__.py` and does not mutate
decorated functions or module constants (those are pinned by hand-written exact-value tests, see
[quality.md](quality.md#mutation-testing)), and the gates run in the maintainer's git hooks, which
are client-side, see [Residual risks](#residual-risks-and-known-gaps).

## Threat model

Assets:

| Asset | Where it lives | Requirements |
|---|---|---|
| Source files (CSV, JSON, text) | the managed sources folder (`--sources-dir`, default `<data dir>/sources`) | R3, R6 |
| Saved graphs and collections | `graphs/` in the data dir (one JSON file per graph, and `folders.json`), or the MongoDB collections `sankey_studio_graphs` and `sankey_studio_collections` | R1, R2 |
| Data in the user's MongoDB collections | the user's MongoDB server | R4 |
| MongoDB credentials | `settings.json` (mode 0600, in a data directory the app creates as 0700) and `SANKEY_MONGO_URI` | R5 |
| The host machine: files, processes, network reach | the user's computer | R3, R6, R7 |
| The installable package | PyPI and the GitHub release | R8 |

Actors:

| Actor | What they can do | Treatment |
|---|---|---|
| Local user (operator) | Starts the server, chooses flags, owns every file | Trusted. The app only stops them from opening the server by accident |
| Malicious web page in the user's browser | Sends cross-site requests to the loopback port, tries DNS rebinding, tries to frame the app | Adversary (T1, T2, T9) |
| Network attacker in remote mode | Reaches the port, sends any request, reads or alters plain HTTP on the path | Adversary for requests (T3); not defended on the wire |
| Malicious data file, CSV or JSON, bundle or document | Hostile names, formula text, huge or deeply nested input, symlinks and special files in the sources folder | Adversary (T4, T9, T10, T11, T13) |
| Malicious or compromised MongoDB server | Hostile documents, slow or huge answers; a crafted connection string if it can edit settings | Adversary for data and size (T6, T11, T13) |
| Supply-chain attacker | Poisoned dependency, action or upload; stolen maintainer session | Adversary (T14, T15) |
| Person with a stolen token | A copy of `settings.json`, a maintainer's GitHub session; there is no PyPI token to steal | Partly defended (T8, T15) |

Trust boundaries:

* **TB1 browser to server.** Every request is untrusted. Checked: `Host`, `Sec-Fetch-Site` or
  `Origin`, content type, body size. The browser is told how to treat the answer (CSP and friends).
* **TB2 server to the sources folder.** File names and contents are untrusted. Access is by file
  descriptor, with no symlinks, an extension allow-list and a regular-file check.
* **TB3 server to MongoDB.** Filters, pipelines and names come from the request and are checked
  before the driver sees them. Documents that come back are data, never code.
* **TB4 server to Chrome and kaleido.** The server builds the figure itself and never accepts one.
  Chrome gets one export at a time, with caps and a time limit.
* **TB5 repository to PyPI and GitHub.** Source, build and publish are separated by job permissions
  and an approval step; the result carries a signed attestation.

## Threats, controls and evidence

| ID | Threat | Control | Where in the code | How it is tested | Residual risk |
|---|---|---|---|---|---|
| T1 | A malicious page makes the browser send a state-changing request or read the API (CWE-352) | An unsafe method passes only with `Sec-Fetch-Site` same-origin or none, or an `Origin` equal to the request's own (host in `allowed_hosts`); with neither header only `application/json`; `Origin: null` refused; a GET under `/api` marked `Sec-Fetch-Site: cross-site` refused; content type enforced; no CORS headers (ADR-14) | `web/middleware.py` `CsrfGuard.verdict`, `origin_of`; `web/app.py` `_add_middleware` | `tests/web/test_csrf.py`, `test_csrf_edges.py`, `test_csrf_units.py`, `test_matrix_csrf.py`; `tests/e2e/http/test_security_origin_flow.py`; Semgrep `sankey-no-cors` | A client that sends JSON and no browser headers is allowed on purpose (curl, scripts); the rule relies on the browser sending its headers. A `same-site` GET (a page on another port of the same host) is not refused, but no CORS header is sent, so that page cannot read the answer |
| T2 | DNS rebinding: a hostile name resolves to the loopback address (CWE-346) | `Host` must be in `allowed_hosts`, in any letter case; the bound address is added by itself; `*` only in remote mode; unusable entries refused at start-up | `web/middleware.py` `CaseInsensitiveTrustedHost`; `config.py` `BootstrapConfig._guards`, `_allow_bound_host`; `web/security.py` `host_pattern_problem`; `web/app.py` `check_allowed_hosts` | `tests/web/test_app_hosts.py`, `test_matrix_requests.py`; `tests/contracts/test_bootstrap_config.py`; `tests/e2e/http/test_security_origin_flow.py` | An operator who lists `*` in remote mode removes the check |
| T3 | A network attacker reaches the port, or the operator opens the server by mistake (CWE-306) | Loopback bind by default; a non-loopback host needs `--allow-remote` (enforced in `BootstrapConfig`, so `uvicorn --factory` cannot skip it); remote writes need `--allow-remote-writes`, and `--allow-source-writes` is refused without it; persisting routes answer 403 `read_only_mode` before the body is decoded, the upload route before a byte is read; "NO AUTHENTICATION" banner (ADR-17) | `config.py` `BootstrapConfig._guards`, `privileged_writes_allowed`, `source_writes_allowed`; `web/app.py` `create_app`; `web/deps.py` `GuardedRoute`, `require_writes`; `web/middleware.py` `BodySizeLimit`; `edits/gates.py` `check_gates`; `cli.py` `_announce` | `tests/contracts/test_bootstrap_config.py`; `tests/web/test_matrix_readonly.py`, `test_deps_guarded.py`, `test_routes_edits_readonly.py`, `test_app_full_routes.py`; `tests/test_edits_gates.py`; `tests/test_cli_main.py`; `tests/e2e/http/test_security_readonly_flow.py` | No authentication and no TLS. In read-only remote mode anyone who can reach the port can read every saved graph, list and preview the sources folder and run reads through the saved MongoDB connections. With `--allow-remote-writes` the same caller can also change settings and connections, upload and delete source files, and save or delete graphs |
| T4 | A path or name escapes the sources folder: `..`, an absolute path, a symlink, a FIFO or device, an odd upload name (CWE-22, CWE-59, CWE-367) | Relative POSIX path with no `.`, `..`, empty, backslash or NUL part; extension allow-list; each directory opened with `O_NOFOLLOW` against its parent descriptor; `fstat` regular-file check after the open; counted reads; uploads go to an `O_EXCL` part file under a sanitised name; graph ids are 32 hex digits; the folder may not equal or contain the data dir, `graphs/` or `settings.json`, nor sit inside `graphs/` (ADR-13, ADR-18) | `sources/files/paths.py` `split_relative`, `check_extension`, `open_parent`, `located`, `open_leaf`, `BoundedReader`; `sources/files/names.py` `clean_filename`; `sources/files/store.py` `save_stream`, `edit_file`; `config.py` `_check_sources_dir`; `storage/base.py` `check_graph_id` | `tests/sources/test_files_paths.py`, `test_files_names.py`, `test_files_upload.py`, `test_files_edit.py`, `test_files_syscalls.py`; `tests/e2e/http/test_file_source_traversal.py` | The folder itself may be a symlink (the operator's choice). Hard links are not detected: a hard link placed in the folder is read like any regular file (creating one needs write access to the folder). Relies on POSIX calls (`dir_fd`, `O_NOFOLLOW`, `fcntl`) |
| T5 | A filter or pipeline writes, runs server-side code, reads `admin`, `local`, `config` or `system.*`, or reads another database from inside a pipeline (CWE-943, CWE-94) | Recursive stage allow-list (also inside `$facet`, `$lookup`, `$unionWith`; an unknown stage is refused); `$where`, `$function`, `$accumulator`, `$out`, `$merge` refused anywhere in the tree; privileged `$$` system variables refused; system namespaces never readable; same-database `$lookup`; caps on depth, size and the number of `$lookup`, `$unwind` and `$facet` stages; every Mongo call inside a connection slot with a timeout (ADR-16) | `mongo_safety.py` `check_filter`, `check_pipeline`, `validate_namespace`, `FORBIDDEN_OPERATORS`, `ALLOWED_STAGES`, `SYSTEM_DATABASES`; `mongo.py` `MongoClients.slot`, `mongo_errors`; Semgrep `sankey-no-mongo-writes`, `sankey-no-js-in-mongo` | `tests/test_mongo_safety.py`, `test_contract_mongo_safety.py` (and `_stages`, `_limits`, `_tables`); `tests/e2e/http/test_mongo_guards_flow.py`; `tests/e2e/mongo/test_real_mongo_flow.py` (`test_mongo_guard_on_a_real_server`, marker `mongo`) | The guard walks the query tree; it is not a MongoDB parser. Stages are allow-listed, so a new stage is refused until it is added, but operators inside filters and expressions are deny-listed, so a new dangerous operator would pass until someone adds it to the list. The database user's privileges are the real limit. A legal but costly read is bounded by caps and time limits, not prevented |
| T6 | A crafted connection string reads local files, weakens TLS, uses a proxy or a non-SCRAM login (CWE-73, CWE-295) | Such options are refused when a connection is saved (and for the `SANKEY_MONGO_URI` seed at start-up), scanned before the driver parses the URI; messages name the option, never its value; `+srv` hosts checked without DNS (ADR-16) | `mongo_safety.py` `check_mongo_uri`, `FORBIDDEN_URI_OPTIONS`, `ALLOWED_AUTH_MECHANISMS`; `models/settings.py` `MongoConnection` | `tests/test_contract_mongo_safety_uris.py`, `tests/test_mongo_safety_boundaries.py`; `tests/web/test_matrix_secrets.py` | The server connects to any host a saved connection names (see CWE-918 below) |
| T7 | The app changes data nobody agreed to: edits written back to a file or collection, library writes (CWE-862) | Write-back is opt-in per target (a key the server builds); operator gates in `plan` and `write`; `find` sources only; one `$set` or `$unset` of one field on at most 1000 documents chosen by `_id` and re-filtered, or one `insert_one`; system and `sankey_studio_*` collections refused; plain field names, scalar values, no formula-like text; a file is replaced atomically and only if it exists; one INFO log line per write; the library store writes only its two own collections, in the storage database, and only with the MongoDB backend chosen (ADR-34, ADR-35) | `edits/gates.py` `check_gates`; `edits/target.py` `effective_write_back`, `write_target`; `storage/mongo_source_writes.py` `check_target`, `update_by_ids`, `insert_document`; `mongo_safety.py` `check_write_update`, `check_write_document`; `sources/files/store.py` `edit_file`; `storage/bundle.py` `import_bundle` | `tests/storage/test_mongo_source_writes.py`, `test_mongo_source_writes_failover.py`; `tests/test_mongo_safety_writes.py`; `tests/test_edits_gates.py`, `test_edits_write.py`, `test_edits_write_mongo.py`; `tests/e2e/mongo/test_source_write_back.py` (marker `mongo`); Semgrep `sankey-no-mongo-writes` (a waiver outside `storage/` is refused by `tests/test_policy.py`) | Consent is a convenience, not authorisation: it travels in the request, so a caller who can reach the API can trigger any write-back the database user may do (ADR-34 accepted risk). The limits are the loopback bind, `--allow-source-writes` and the database user's privileges. A multi-document write is not atomic: after a failover the person is told to try again, and repeating it is safe (ADR-38) |
| T8 | A secret leaks: a connection string or password in an answer, log, error, page, export or bundle (CWE-532, CWE-209, CWE-200) | `SecretStr`; only `dump_settings` and `load_settings` touch real values; the API returns `uri_masked` and `has_secret`, and read-only remote mode hides connection hosts and user names too; `mask_uri` rebuilds the URI from an allow-list and fails closed; `looks_masked` stops a placeholder from overwriting a secret; driver errors become the connection name and the exception class; bundles carry names only; `settings.json` is written atomically as 0600, and the data directory is created 0700 (an existing one loses group and other write bits, and one owned by another user is refused) (ADR-04, ADR-15) | `util.py` `mask_uri`, `looks_masked`; `storage/settings_store.py` `dump_settings`, `load_settings`; `mongo.py` `mongo_errors`; `storage/atomic.py` `write_atomic`, `ensure_private_dir`; `config.py` `BootstrapConfig`; Semgrep `sankey-no-secret-in-logs`, `sankey-no-secret-in-exceptions` | `tests/test_util.py`; `tests/contracts/test_settings_secrets.py`; `tests/web/test_matrix_secrets.py`, `test_schemas_secret_logs.py`; `tests/storage/test_atomic.py`, `test_settings_store.py`; `tests/e2e/http/test_security_secrets_flow.py` | `settings.json` holds the URIs in clear text: whoever reads the data directory as that user, or a backup of it, has them. `SANKEY_MONGO_URI` sits in the process environment. Outside read-only remote mode the masked form still shows the host and the user name |
| T9 | User text becomes script or markup in a page, an SVG or HTML export or a Plotly label (CWE-79, CWE-113, CWE-1021) | Jinja autoescape on; page data only through a `tojson` JSON block; no `innerHTML` and friends; CSP `script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`; `escape_label` on every figure string and none in a `hovertemplate`; unseen and bidi characters stripped; downloads are attachments with `nosniff` and `CSP: sandbox` under a sanitised name (ADR-18, ADR-30) | `render/text.py` `escape_label`, `strip_unseen`; `web/routers/pages.py` `TEMPLATES`; `web/security.py` `CSP`, `DEFAULT_POLICY`, `download_response`, `content_disposition`; `web/middleware.py` `SecurityHeaders`; Semgrep `sankey-js-no-dom-xss-sinks`, `sankey-no-unsafe-html` | `tests/render/test_text.py`, `test_unseen_text.py`, `test_export_textual.py`; `tests/web/test_pages_xss.py`, `test_templates_policy.py`, `test_static_policy.py`, `test_headers.py`, `test_downloads.py`; `tests/e2e/http/test_exports_hostile.py`, `test_security_headers_flow.py`; `tests/e2e/ui/test_security_pages_ui.py` | `style-src` allows `'unsafe-inline'`. An HTML export opened from disk has no CSP, so only the escaping of the figure strings and of the page title protects it. plotly.js is third-party code, served locally |
| T10 | A cell that starts with `=`, `+`, `-` or `@` runs as a formula in a spreadsheet (CWE-1236) | CSV cells get a `'` prefix on the way out; write-back refuses formula-like new text on the way in, because stored data cannot be guarded later; one shared predicate | `util.py` `starts_like_formula`; `render/export/tabular.py` `csv_cell`, `export_csv`; `edits/gates.py` `check_gates` | `tests/render/test_export_csv.py`; `tests/test_mongo_safety_writes.py`, `test_edits_gates.py`; `tests/e2e/http/test_exports_hostile.py` | Pasted and manual text is the person's own data and is not gated. The prefix changes what a spreadsheet shows |
| T11 | A request exhausts memory, disk, connections or time (CWE-400, CWE-770) | Streaming body caps counted while the body arrives (a declared `Content-Length` over the cap is refused early, a small one is never trusted): JSON 8 MiB, import 16 MiB, upload `max_upload_mb` plus 1 MiB; caps on rows, drawn links, bundle size, record and line length, filter size and depth; four Mongo slots per connection with timeouts; one worker with `limit_concurrency` 100; a drawing cap (ADR-22) | `web/middleware.py` `BodySizeLimit`; `web/security.py` `BodyLimits`; `models/settings.py` `AppSettings`; `storage/bundle.py` `MAX_BUNDLE_GRAPHS`; `mongo.py` `MAX_CONCURRENT_PER_CONNECTION`; `cli.py` `LIMIT_CONCURRENCY` | `tests/web/test_bodies.py`, `test_bodies_stream.py`, `test_bodies_upload.py`, `test_matrix_limits.py`; `tests/test_contract_mongo_safety_limits.py`; `tests/test_cli_main.py`; `tests/test_memory.py` (marker `memory`); `tests/e2e/http/test_limits_*_flow.py` | No rate limit and no per-client quota, and no total size limit on the sources folder. A caller can keep the CPU busy with legal work inside the caps |
| T12 | Image export is abused: huge images, parallel Chrome processes, a figure that makes Chrome fetch URLs (CWE-400, CWE-918) | No endpoint accepts figure JSON, the server builds it from a saved id or a draft; pixel, link and node caps; one export at a time with a 2 s wait; 30 s kaleido timeout; MathJax off; driver errors become fixed messages (ADR-18) | `web/routers/exports.py`; `render/export/images.py` `resolve_image`, `export_image`, `_render_image`, `map_render_error` | `tests/render/test_export_images.py`; `tests/web/test_routes_exports_images.py`; `tests/e2e/http/test_exports_images.py`, `test_exports_slot.py` | Chrome runs with kaleido's defaults; the project passes only the format, size, scale, MathJax and the timeout. A flaw in Chrome, kaleido or Plotly is outside its control |
| T13 | A hostile data file or document (CSV, TSV, JSON, SankeyMATIC, a bundle, a BSON value) crashes or tricks the parser (CWE-502, CWE-20) | Own parsers with record, line, object and number caps, strict or lenient mode and a warning cap; no `pickle`, `marshal`, `yaml`, `eval` or `exec` in `src`; a bundle is JSON validated per graph by pydantic; Mongo values are normalised to plain types | `sources/text.py`; `sources/formats/` (`RECORD_MAX_CHARS`, `MAX_OBJECT_CHARS`, `LINE_MAX`); `sources/mongo_extract.py`; `storage/bundle.py` `import_bundle`; Semgrep `sankey-no-dynamic-code` | `tests/sources/test_text_*.py`, `test_mongo_extract*.py`; `tests/test_bundle.py`, `test_bundle_shape.py` | No fuzzing and no property-based tests: parametrised tables only |
| T14 | A vulnerable or malicious dependency (CWE-1395, CWE-829) | `uv.lock` with hashes; Trivy (HIGH and CRITICAL findings that have a fix) and Semgrep in the push gate for `main` and tags; a weekly Trivy job in GitHub Actions; Dependabot alerts and security updates are switched on and GitHub's dependency graph lists the locked packages (checked 2026-10-17, no open alert). See [Supply chain](#supply-chain-and-release-integrity) | `uv.lock`, `trivy.yaml`, `scripts/trivy.sh`, `scripts/semgrep.sh`, `.trivyignore` | The gate itself: `tests/test_githooks.py`, `tests/test_githook_gate_*.py` | The wheel declares version ranges, so an install resolves at install time, and the release build resolves its own build tools at build time. The scans run on the maintainer's machine |
| T15 | A counterfeit or tampered release; a stolen publishing credential (CWE-494) | Trusted publishing (no token), SHA-pinned actions, job permissions of `id-token: write` only where needed, an approval step on the `pypi` environment, Sigstore attestations, a signed tag (the workflow does not check the signature) | `.github/workflows/release.yml`, `docs/release.md` | By hand: `pypi-attestations verify` ([release.md](release.md#verifying-a-release)); the workflow runs no tests | A maintainer account takeover: the only reviewer of the `pypi` environment is the lead maintainer and self-review is not blocked; no tag protection; build tools not pinned |

## Secure design principles

Saltzer and Schroeder's principles, with the place the project applies each and the maintainers'
verdict. Yes means a control and tests exist and no significant gap is known; Partly means a gap,
named in the row.

| Principle | Applied | Where, and the limit |
|---|---|---|
| Economy of mechanism | Partly | Security rules are small pure functions (`mongo_safety.py`, `util.mask_uri`); `download_response` is the one way a route serves a file; `storage/mongo_source_writes.py` is the one writer to a source collection; code caps keep functions to 50 lines. The application as a whole is large |
| Fail-safe defaults | Yes | Loopback bind; remote mode read-only; write-back off until agreed and, remotely, until two flags are set; allow-lists for extensions, stages and URI options; `mask_uri` and `Origin: null` fail closed; a skipped test fails a hook check |
| Complete mediation | Partly | Host, size, header and CSRF checks are middleware on every HTTP request, whatever the route. Read-only mode is enforced per router (`GuardedRoute`, `require_writes`), so a new router must opt in; `tests/web/test_app_full_routes.py` asserts the exact route table and `test_matrix_readonly.py` classifies every unsafe route. There is no per-user authorisation to mediate |
| Open design | Yes | GPL-3.0-only source; design in the README, `architecture.md` and the ADRs; the rules are tested in public (`.semgrep/rules`). The only secrets are the database credentials |
| Separation of privilege | Partly | In remote mode write-back needs two operator flags (bootstrap-only) and the per-target consent and the database user's rights; without `--allow-remote` the flags are not needed. A release needs a tag and an approval of the `pypi` environment, which one person can give to their own tag. Consent is not a second authenticated person |
| Least privilege | Partly | No PyPI token; workflow permissions `{}` at the top and the minimum per job; Mongo writes confined to three modules under `storage/` (the graph store, the folder store and the source write-back), the last limited to one field and 1000 documents; system namespaces unreadable; files 0600 and directories the app creates 0700. The process runs with the user's full rights and the database user's privileges are the operator's choice |
| Least common mechanism | Partly | Graphs, sources and settings live in separate places and the sources folder may not contain the data dir; write-back refuses the app's own collections. All callers share one cache, one export slot and one settings file: it is a single-user design |
| Psychological acceptability | Partly | Safe without configuration; the remote banner says what is enabled; in remote mode the start-up text lists the accepted hosts and how to add more; the write-back dialog ("Change your data too?") asks in plain words. No usability study of the security prompts has been done |

## Common weaknesses

OWASP Top 10 (2021), with the same meaning of Yes and Partly:

| Category | Status | Controls and notes |
|---|---|---|
| A01 Broken access control | Partly | No users or roles. The network boundary, read-only remote mode, CSRF and Host checks, path containment and the write gates (T1 to T4, T7) |
| A02 Cryptographic failures | Partly | No homemade crypto. Secrets are masked and kept in a 0600 file, not encrypted at rest (T8). The app has no TLS, so remote mode is plain HTTP |
| A03 Injection | Yes | NoSQL (T5), XSS (T9), spreadsheet formula (T10), header injection (`content_disposition`). No `subprocess` or `os.system` in `src`; Semgrep forbids `shell=True`, `os.system` and `os.popen` |
| A04 Insecure design | Partly | Threat model above, ADR-13 to ADR-18, ADR-34, ADR-38; fail-safe defaults. The threat model is the project's own and has had no external review |
| A05 Security misconfiguration | Yes | OpenAPI, Swagger and ReDoc disabled in `create_app`; `server_header=False`; no CORS; security headers on every answer except the plain-text 400 for a refused `Host`, which comes from the outermost host check; `*` hosts only in remote mode |
| A06 Vulnerable components | Partly | Trivy on `uv.lock` (T14), HIGH and CRITICAL findings that have a fix only; Dependabot alerts and security updates are switched on and the graph lists the locked packages (checked 2026-10-17); between pushes the weekly Trivy job also watches them (GitHub stops it after 60 days without repository activity) |
| A07 Identification and authentication failures | Not applicable by design | There is no login (product requirement). The risk is documented, not removed (T3) |
| A08 Software and data integrity failures | Partly | No unsafe deserialisation (T13); SHA-pinned actions, attestations, trusted publishing (T15); an import drops saved consent. No branch or tag protection, and build tools are not pinned |
| A09 Logging and monitoring failures | Partly | One INFO line per source write (connection, database, collection, operation, count); API errors carry the connection name and the exception class only. No audit trail of reads, no alerting |
| A10 Server-side request forgery | Partly | The server dials only MongoDB hosts of saved connections, and Chrome with MathJax off and no foreign figure (T12). A caller who can edit settings can point a connection at any host the server reaches, and a connection test tells reachable from unreachable. Read-only remote mode refuses the test routes |

Other weaknesses:

| CWE | Status | Where |
|---|---|---|
| CWE-22, CWE-59, CWE-367 path traversal, link following, check-then-use | Controlled for symlinks and traversal; hard links are not detected | T4 |
| CWE-79 XSS; CWE-113 header injection; CWE-1021 framing | Controlled | T9 |
| CWE-352 CSRF; CWE-346 origin validation | Controlled | T1, T2 |
| CWE-1236 formula injection | Controlled; pasted text is not gated | T10 |
| CWE-943 NoSQL injection; CWE-94 code injection | Controlled; operators inside filters are a deny-list | T5 |
| CWE-918 SSRF | Partly, see A10 | T6, T12 |
| CWE-532 and CWE-209 secrets in logs and errors | Controlled; clear text at rest | T8 |
| CWE-400, CWE-770 resource exhaustion | Capped; no rate limit | T11, T12 |
| CWE-502 unsafe deserialisation | Not applicable: no `pickle`, `marshal` or unsafe YAML in `src`, enforced by Semgrep `sankey-no-dynamic-code` | T13 |
| CWE-78 OS command injection | Not applicable: `src` has no `subprocess` or `os.system`; kaleido starts Chrome | T12 |
| CWE-306 missing authentication | Accepted by design | T3 |
| CWE-798 hard-coded credentials | Trivy secret scan and GitHub secret scanning; the two alerts so far were fake test values and are closed as used in tests | T14 |

## Supply chain and release integrity

* **Dependencies.** `uv.lock` pins every third-party package with hashes, and the hooks run with
  `UV_LOCKED=1`. The wheel itself declares ranges (for example `pymongo>=4.10`), so an install
  resolves at install time; the lock protects the maintainer's test and scan runs, not a user's
  environment and not the release build (see "Build tools" below).
* **Scanners.** `make security` (Semgrep with the project rules and registry packs, Trivy on the
  lock, secrets, misconfiguration and licences) runs in the pre-push gate for `main` and tags, with
  the scanner images pinned by version tag (not by digest). Trivy reports HIGH and CRITICAL
  vulnerabilities that have a fix. `.trivyignore` has no entries. See
  [quality.md](quality.md#scanners).
* **GitHub settings.** Secret scanning with push protection and Dependabot alerts and security
  updates are enabled. They are repository settings, not files, so they are stated here as they were
  when this page was written and nothing in the repository keeps them so.
  `.github/dependabot.yml` limits Dependabot to security updates. GitHub's dependency graph listed no
  dependencies until a Dependabot graph job ran on 2026-10-17; it now lists the 76 locked packages and
  no alert is open. The two secret-scanning alerts so
  far were fake credentials in test fixtures and are closed as used in tests. The default token
  permission of Actions is read-only. Branch protection, rulesets and tag protection are not used,
  and GitHub's option to require pinned action SHAs is off, so the pinning below is the
  maintainer's practice, not an enforced rule.
* **The release workflow.** `.github/workflows/release.yml` starts on a `v*` tag,
  sets `permissions: {}` at the top, `contents: read` in the build job and `id-token: write` in
  the two upload jobs, checks out without persisting credentials, pins every action to a full
  commit SHA and passes the tag name through an environment variable. Jobs run build, TestPyPI,
  then PyPI behind an approval of the `pypi` environment. Both environments deploy only from `v*`
  tags; `pypi` has one required reviewer, the lead maintainer, and does not block self-review.
* **Scheduled workflows.** `trivy-weekly.yml` runs the project's Trivy script every Monday and
  `scorecard.yml` runs the OpenSSF Scorecard on a push to `main` and weekly, publishing the score to
  scorecard.dev and the report to code scanning ([ADR-40](decisions.md#adr-40-a-weekly-trivy-scan-and-the-openssf-scorecard-run-in-github-actions)).
  Both use `permissions: {}` at the top, pinned actions and no secret. GitHub stops scheduled workflows
  after 60 days without activity in the repository. Neither runs the tests.
* **Build tools.** The build job does not use `uv.lock`: `hatchling` is a range in
  `pyproject.toml` (`>=1.27`), `twine` runs through `uvx`, and no `uv` version is pinned in the
  workflow or the project. The build job holds no publishing credential, and the upload jobs only
  upload the files it built.
* **Trusted publishing and attestations.** There is no PyPI token anywhere. The upload uses OIDC and
  attaches PEP 740 (Sigstore) attestations that tie each file to this repository, `release.yml` and
  the `pypi` environment; anyone can check one ([release.md](release.md#verifying-a-release)). The
  sdist holds `src/`, `docs/*.md`, `README.md`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  `LICENSE` and `pyproject.toml`; tests, hooks and scanner configuration stay out. The build is not
  claimed to be byte-reproducible.
* **Signatures.** The `v0.1.0` tag is signed, and every commit on `main` so far is SSH-signed and
  shows as Verified on GitHub. This is the maintainer's practice; no rule enforces it.
* **Accounts.** The organisation requires two-factor authentication
  ([GOVERNANCE.md](../GOVERNANCE.md)) and has two owners ([MAINTAINERS.md](../MAINTAINERS.md)).
  Neither adds a second check on the lead maintainer's pushes or releases (see Residual risks).
* **What the workflow does not do.** It runs no tests and no scanners. It checks that the tag equals
  the version in `pyproject.toml`, runs `twine check --strict` and starts the built wheel. The
  checks run in the git hooks before the tag is pushed, so the workflow trusts the commit as the
  maintainer pushed it (ADR-39).

## Residual risks and known gaps

* **No authentication, no TLS.** The network boundary is the only access control. Remote mode is for
  a trusted network, and on a computer with several accounts every account can reach the loopback
  port.
* **Consent is not authorisation** (ADR-34). The limit on write-back is the database user's rights.
* **Credentials sit in clear text** in `settings.json`, protected by file modes only.
* **The gates are client-side** (ADR-37). `--no-verify`, a changed `core.hooksPath` or a fresh clone
  skip every hook. There is no hosted CI that runs the tests or checks commits, no branch protection (the maintainer pushes to `main`
  directly) and no tag protection; none of the workflows runs the tests. The hook stamps do not record
  the environment (scanner images, Chrome).
* **One maintainer in practice.** Every commit so far is by one person. A second owner has agreed to
  take over within a week of the lead maintainer becoming unavailable
  ([GOVERNANCE.md](../GOVERNANCE.md)), but a second review of the maintainer's own changes is not
  required, and access to the PyPI project and the release approval is held by the lead maintainer
  alone ([MAINTAINERS.md](../MAINTAINERS.md)). A compromised lead-maintainer account
  could push to `main`, tag and approve its own release; the controls are the organisation's
  two-factor requirement and the `pypi` environment approval, which stops mistakes rather than a
  takeover of that account (ADR-39 accepted risk).
* **No external audit is claimed**, and there is **no fuzzing**. The human review of the design and
  trust boundary is recorded only through its written result (see the Evidence index).
* **Third-party code** is trusted: Chrome and kaleido (default flags), Plotly, FastAPI, pymongo.
  The scanners see known vulnerabilities only (Trivy: HIGH and CRITICAL with a fix), nothing else.
* **Build tools** are not pinned (see Supply chain), so the release build depends on what
  `hatchling`, `twine` and `uv` are at the time of the run.
* **Real MongoDB coverage** is thinner than the unit suite (mongomock): the marker-gated suites run
  in the hooks of `main` and tags, and no failover is exercised against a real cluster (ADR-38).
* **Content security and limits.** `style-src` allows inline styles and an exported HTML file has
  no CSP. Resource limits are caps, not quotas or rate limits.
* **Platform.** The file-safety code relies on POSIX calls; hard links are not detected.

## Evidence index

| Evidence | What it shows |
|---|---|
| [README Security model](../README.md#security-model) | The user-facing list of protections |
| [architecture.md Security design](architecture.md#security-design) | How each layer defends itself |
| [ADR-13](decisions.md#adr-13-the-sources-directory-is-bootstrap-only), [ADR-14](decisions.md#adr-14-csrf-rule-without-tokens), [ADR-15](decisions.md#adr-15-uri-masking-fails-closed), [ADR-16](decisions.md#adr-16-mongo-access-is-read-only-and-allow-listed), [ADR-17](decisions.md#adr-17-remote-mode-is-read-only-by-default), [ADR-18](decisions.md#adr-18-hardening-of-files-settings-and-exports) | The decisions, reasons and accepted risks behind T1 to T5, T8, T9 and T12 |
| [ADR-34](decisions.md#adr-34-edits-are-written-back-to-the-data-when-the-person-agrees), [ADR-38](decisions.md#adr-38-mongodb-runs-on-one-server-and-on-a-cluster) | Write-back and its accepted risk; MongoDB topologies |
| [ADR-37](decisions.md#adr-37-git-hooks-are-the-one-place-the-checks-run), [ADR-39](decisions.md#adr-39-releases-are-published-to-pypi-from-a-tag) | What the hooks do and do not guarantee; the release path |
| Human review | The maintainers state that a person reviewed the security design and the trust boundary by hand, not only with tools; the written result is the README Security model, ADR-14 to ADR-18 and ADR-38. The repository does not record who reviewed or when, and the review is not presented as an independent audit |
| [quality.md](quality.md) | The gates the maintainer's git hooks run: 100% line and branch coverage, mutation score of at least 90, strict typing, [scanners](quality.md#scanners), [fail-closed hooks](quality.md#fail-closed-rules) |
| `tests/` | Unit tests (mongomock), `tests/e2e` (real server, real Chrome), `mongo` and `mongo_rs` suites against real MongoDB ([e2e.md](e2e.md#replica-set)); policy tests `tests/test_policy.py`, `tests/web/test_templates_policy.py`, `tests/web/test_static_policy.py` |
| `.semgrep/rules/` | Project Semgrep rules with their own rule tests (`sankey.py`, `sankey-js.js`, `sankey-html.html`) |
| [release.md](release.md), `.github/workflows/release.yml` | How a release is made and how to verify one |
| [SECURITY.md](../SECURITY.md), [GOVERNANCE.md](../GOVERNANCE.md), [MAINTAINERS.md](../MAINTAINERS.md) | Reporting, roles, access rules and succession |
