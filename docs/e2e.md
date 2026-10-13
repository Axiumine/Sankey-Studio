# End-to-end tests

The end-to-end (e2e) suite starts the real application and drives it the way a client does: over HTTP
with `httpx`, and through real Chrome with Playwright's synchronous API. The server is uvicorn running
in a thread of the pytest process, on an ephemeral loopback port, with mongomock standing in for
MongoDB. This page is for a developer who has to run the suite, add a test to it or find out why one
fails. Related: [ui.md](ui.md) (the `data-testid` contract, the DOM wait signals and the browser
quirks every UI test relies on), [api.md](api.md) (the routes the HTTP tests call),
[quality.md](quality.md) (the gates and the suppression policy), [decisions.md](decisions.md).

Contents

* [Purpose and coverage](#purpose-and-coverage)
* [How to run](#how-to-run)
* [Real MongoDB (opt-in)](#real-mongodb-opt-in)
* [Harness reference](#harness-reference)
* [Writing a new test](#writing-a-new-test)
* [Runtime budget and flakiness](#runtime-budget-and-flakiness)
* [Troubleshooting](#troubleshooting)

## Purpose and coverage

The unit suite (`make test`) calls the app in process and replaces every external seam. It cannot see
what only a running server and a real browser decide: the headers on the wire, the Host, Origin and
CSRF guards, downloads, images drawn by Chrome, lazy chart drawing, the Content-Security-Policy, theme
paint, keyboard use and layout. The e2e suite covers those. It is not measured for coverage and not
mutated (`make cov` and `make mutate` leave it out), and it is part of `make ci` and `make full`
through `make e2e`. `make e2e-mongo` is not: `make check`, `make ci` and `make full` must pass without
any database.

The suite has roughly 770 tests (`uv run pytest tests/e2e --collect-only -q | tail -1`); about 740 run
in `make e2e` and about 40 need a real MongoDB.

| Directory | Driven by | Covers |
|---|---|---|
| `tests/e2e/http/` | `httpx` clients against the live server, no browser | The API as a client sees it, see the table below |
| `tests/e2e/ui/` | Chrome through the `page` fixture | The pages as a person uses them, see the table below |
| `tests/e2e/mongo/` | The HTTP flows again, against a real MongoDB | The Mongo and storage flows of `http/`, plus a safety net that refuses other projects' MongoDBs |
| `tests/e2e/test_harness_*.py` | The harness itself | Self-tests of the fixtures, the watcher, the shards and the failure artefacts, so a broken harness is never mistaken for a broken app |
| `tests/e2e/support/` | none (no tests) | The harness code: servers, clients, builders, waits, watcher, page objects |

HTTP flows (`tests/e2e/http/`, one file group per area):

| Files | Area |
|---|---|
| `test_settings_*` | Defaults, ranges, MongoDB connections, the "keep the secret" semantics, probes, no password in any response, log or console |
| `test_file_source_*` | Upload, list, preview and render of a file source; traversal, symlinks and special files never leave the sources folder |
| `test_categories_*` | Chosen entries, glob rules, precedence, clearing, reserved names, the donut sums, categories being optional |
| `test_exports_*` | File names, headers and formats without Chrome; SVG and PNG drawn by Chrome (marked `slow`); hostile text; one image export at a time; no Chrome process left behind |
| `test_library_*` | 25 saved graphs listed, searched, tagged and paged; create, duplicate, edit with the revision check, delete; JSON bundle export and import |
| `test_mongo_*`, `test_storage_switch_flow` | MongoDB sources and the file or MongoDB graph store, written once and shared with `tests/e2e/mongo/` |
| `test_limits_*` | `max_links`, `max_drawn_links`, cycles and the validation of the limits themselves |
| `test_security_*` | Host, Origin and Fetch-Metadata rules, response headers, error bodies without internals or echoes, read-only remote mode, secrets |

Browser flows (`tests/e2e/ui/`):

| Files | Area |
|---|---|
| `test_smoke_nav` | Shell, navigation, keyboard-only paths, focus ring, dialogs |
| `test_draw_graph` | Drawing from pasted CSV, live preview, saving, reload, viewer and library |
| `test_categorise_*` | Entries table and category tools, the pager, the donut, colour by category |
| `test_export_*` | Every download of the viewer and the editor, and the browser-drawn fallback when the server answers 501 |
| `test_viewer_display_*` | The viewer's display menu: icon, panel and its three ways to close, the tab strip, the Sankey and donut switches, the downloads that carry them, the saved style, a failed redraw |
| `test_sources_*` | Text file and upload tabs, column mapping, the manual table, the MongoDB tab with and without a connection |
| `test_library_*`, `test_compare_*` | Browsing, actions, bundles, the 409 conflict; the compare cards and the 12-graph limit |
| `test_settings_*`, `test_readonly_ui` | Limits, MongoDB connections, storage backend, theme; the read-only remote server |
| `test_theme_dark_ui`, `test_responsive_ui` | Tokens and chart surfaces in both themes, phone-width layout |
| `test_resilience_*` | Error sentences instead of JSON, not-found pages, a slow server |
| `test_security_*_ui` | Hostile text on every page, in the editor and in downloads, and a detector that proves the inertness check can fail |

The docstrings of the test modules cite sections of the original test plan (`A.1` to `A.9` for the HTTP
flows, `B1` to `B.12` for the browser flows, `C` for real MongoDB). The tables above are the map: the
docstring of each file says what it covers.

## How to run

Install the dependencies once with `make sync`. The browser tests need Chrome: the harness tries the
system Chrome first (Playwright channel `chrome`) and then the Chromium that Playwright downloads
(`uv run playwright install chromium`). Without either, every test that needs a browser is skipped with
the reason, and the HTTP tests still run. The tests that draw SVG or PNG on the server also need Chrome
for kaleido (`uv run plotly_get_chrome`, see the README) and skip when the server answers 501.

```bash
make e2e                        # everything, in 5 parallel shards (about the time of one shard)
make e2e E2E_SHARDS=3           # another number of shards
make e2e-serial                 # one process, one stream of output (the same as E2E_SHARDS=1)
uv run pytest tests/e2e/ui/test_smoke_nav.py                       # one file
uv run pytest "tests/e2e/ui/test_smoke_nav.py::test_escape_closes_the_delete_dialog_and_the_chart_tabs_follow_the_arrow_keys"
uv run pytest tests/e2e -k "theme and dark" -x                     # by keyword, stop at the first failure
uv run pytest tests/e2e/http -m "not slow"                         # HTTP flows without the Chrome exports
E2E_SHARD=2/5 uv run pytest tests/e2e -m "e2e and not mongo" -p no:cacheprovider   # one shard by hand
```

* **Marks.** Every test below `tests/e2e` gets the `e2e` mark from `tests/e2e/conftest.py`, which is why
  `make test` (`-m "not memory and not e2e"`) leaves them out. `mongo` marks the tests that need a real
  MongoDB and `slow` the ones that start Chrome on the server; `make e2e` runs `-m "e2e and not
  mongo"`. Markers are strict, and `filterwarnings = error` applies here as everywhere.
* **Shards.** `make e2e` runs `E2E_SHARDS` pytest processes at once, each with
  `E2E_SHARD=<n>/<count>`, and prints their output one shard at a time. A shard owns whole modules, so
  a module-scoped server starts once. The assignment is computed by every shard from the same
  collection (`tests/e2e/support/shard.py`): modules are weighed (a test that uses `page` or `open_page`,
  or is marked `slow`, weighs 8, any other test 1, a `mongo` test 0), sorted by weight, and dealt out
  biggest first, each to the lightest shard so far. Every test runs in exactly one shard
  (`test_harness_shard.py` proves it). A failing shard fails the target after the others finish. A bad
  `E2E_SHARD` (`0/5`, `6/5`, `x`) is a usage error, never an empty run. Running a file by hand without
  `E2E_SHARD` runs all of its tests.
* **Browser.** Chrome is always headless (`--no-sandbox --disable-dev-shm-usage`, English locale), and
  a self-test pins that. There is no headed or slow-motion switch: to see what a test saw, open its
  trace.
* **Parameters.** `-p no:cacheprovider` is what the make targets pass; do the same when you run shards
  by hand. `-ra` (the project default) prints the reason of every skip.

**Artefacts.** A test that fails, or that passes but leaves browser problems, writes
`.e2e-artifacts/<test-id>/` (git-ignored, replaced on the next failure of the same test;
`E2E_ARTIFACTS_DIR` moves the root, and `rm -rf .e2e-artifacts` cleans it up):

| File | Content |
|---|---|
| `page-<context>-<page>.png` | A screenshot of every page that was open at the end |
| `trace-<context>.zip` | The Playwright trace (screenshots and DOM snapshots of every step) |
| `problems-<context>.txt` | Every console, page error, network and CSP line, each marked `ALLOWED` or `PROBLEM` |

Open a trace with `uv run playwright show-trace .e2e-artifacts/<test-id>/trace-0.zip` (`<context>` is
0 for the first browser context of the test, 1 for the second, and so on). The directory name is the
pytest node id with every run of characters outside `A-Za-z0-9_.-` replaced by `_`, cut to its last
150 characters. Passing tests leave nothing behind. The tests that save screenshots for a human (theme
review) write to `.e2e-artifacts/ui-b-review/`.

## Real MongoDB (opt-in)

The mongomock suite proves the API against a faithful stand-in. The same flows can run against a real
server, to catch what mongomock hides (operators, aggregation stages, time limits, the real driver):

```bash
make mongo-up                                              # the project-local MongoDB (Docker)
SANKEY_TEST_MONGO_URI=mongodb://127.0.0.1:27117 make e2e-mongo
make mongo-down
```

* **Only the project-local Mongo.** `docker-compose.yml` starts `mongo:8` as `sankey-studio-mongo`,
  bound to `127.0.0.1:27117` so it never collides with another MongoDB. Never point the suite at other
  projects' instances. `real_world` (`tests/e2e/support/http_b_world.py`) fails the test when the URI is a
  loopback address (`127.0.0.1`, `localhost`, `::1`) on port 27017, 27018 or 27019, and a URI without a
  port means 27017. `tests/e2e/mongo/test_real_guards.py` proves the refusal; it needs no MongoDB, so
  it runs in plain `make e2e`. A host that is not loopback is not judged: that is your deliberate
  choice.
* **One unique database per test.** `sankey_e2e_<8 hex>` holds the seeded documents, the source
  collections and, when a scenario switches the storage backend, the graph store. It is dropped at
  teardown, after the server has stopped, even when the test failed. `MongoWorld.drop()` refuses a
  database without that prefix, and nothing else is read, written or dropped.
* **Same scenarios.** The Mongo and storage flows are written once (`http_b_mongo_flows`,
  `http_b_mongo_guards`, `http_b_storage_flows`) against a `FlowEnv`. `tests/e2e/http` runs them on
  `mongomock_world()`, `tests/e2e/mongo` on `real_world(uri)` with the production client factory
  `sankey_studio.mongo.default_factory`.
* **Unset or down.** Without `SANKEY_TEST_MONGO_URI` the tests skip, and the reason says so. With the
  variable set and nothing answering they fail (they do not skip): `SANKEY_TEST_MONGO_URI is set but
  the server did not answer: <error type>`. `make e2e-mongo` runs in one process, without shards.
* **A new real-Mongo test** carries `@pytest.mark.mongo` and takes `real_env` (from
  `tests/e2e/mongo/conftest.py`) or `real_mongo_uri`. Without the mark `tests/conftest.py` removes the
  variable and a tripwire refuses to construct a real `pymongo.MongoClient`.

## Harness reference

`tests/e2e/conftest.py` holds the fixtures and its module docstring is the short form of this section.
`tests/e2e/support/` holds the code behind them; each module has a docstring with the details.

### Servers

`make_server(**options)` starts a `LiveServer` per call and stops all of them at teardown. Each one
gets a fresh `data_dir` and `sources_dir` under `tmp_path`, and the bootstrap config sets every field
explicitly, so no `SANKEY_*` variable of your shell can leak in. The options:

| Option | Effect |
|---|---|
| `remote_mode: bool` | `--allow-remote`: a read-only remote server (banners, 403 `read_only_mode` on every write) |
| `allow_remote_writes: bool` | `--allow-remote-writes`; only valid together with `remote_mode` |
| `settings: Mapping` | `AppSettings` fields written to `settings.json` before start, bypassing the read-only guard (`{"max_links": 100, "max_drawn_links": 50}`) |
| `export_unavailable: bool` | Image exports (`svg`, `png`) answer the production 501 `export_unavailable`, because Chrome is installed on the test machine but the browser fallback has to be tested. HTML, JSON and CSV exports and every other route are real (`support/unavailable.py`) |
| `seed_mongo: Callable` | Called with the mongomock client before the server starts (`builders.seed_flows`) |
| `mongo_factory: ClientFactory` | Replaces the mongomock client factory; only the `mongo` suites use it, with `sankey_studio.mongo.default_factory` |

A `LiveServer` offers `url` (`http://127.0.0.1:<port>`, no trailing slash), `url_for(path)`, `port`,
`config`, `services`, `mongo` (the `E2EMongoClient` behind every Mongo connection), `data_dir`,
`sources_dir`, `graphs_dir`, `settings_file`, `read_only` and `stop()`. Start-up waits up to 20 s for
uvicorn. `stop()` asks uvicorn to exit, joins the thread (20 s), closes the services, re-raises an
error the server thread died with, and asserts that the port is closed. A configured MongoDB URI is
never dialled.

| Fixture | Scope | Gives |
|---|---|---|
| `make_server` | function | The factory above; use it for the read-only variant, a second server or special options |
| `live_server` | function | `make_server()`: the default local server, fresh for every test |
| `module_make_server`, `module_server` | module | The same, shared by every test of the module (cheaper) |
| `real_mongo_uri` | function | The value of `SANKEY_TEST_MONGO_URI`; skips with the reason when it is unset |

Use a module server only for tests that need no clean state: unique names per test and no counting of
other tests' data. Settings are server-wide, so settings, theme and storage tests keep one server per
test. To make `api`, `foreign`, `bare` and `page` use the shared server, override `live_server` in the
module:

```python
@pytest.fixture
def live_server(module_server: LiveServer) -> LiveServer:
    return module_server
```

### HTTP clients

All three are `httpx.Client` instances bound to `live_server`, with no redirects followed and no proxy
from the environment (`support/clients.py`).

| Fixture | Sends | Use |
|---|---|---|
| `api` | `Origin: <server url>` | What a browser sends from the app's own pages; writes pass the CSRF guard |
| `foreign` | `Origin: http://evil.example` | Must get 403 on every write |
| `bare` | no `Origin` | curl: only `application/json` bodies pass; multipart and a bodiless DELETE are 403 |

`make_client(server, origin=...)` builds more. Helpers in the same module: `seed_graph(client, name,
draft=None, tags=())` (asserts the 201), `upload_source`, `post_multipart`, `json_of(response, status)`
(asserts the status and parses the body), and `fetch_json(page, method, path, body)`, which does the
request from inside the browser with its own same-origin headers. API timestamps are compared as
instants with `support/stamps.py`, never as strings.

### Browser and the `page` fixture

| Fixture | Scope | Gives |
|---|---|---|
| `browser` | session | System Chrome, else the bundled Chromium, else the test is skipped with the reason; sets the `expect` timeout to 10 s |
| `color_scheme` | function | `"light"` by default (`"dark"`, `"no-preference"`) |
| `viewport` | function | 1280 by 900 by default |
| `open_page(server, *, color_scheme, viewport)` | function | A `WatchedPage` in a fresh context for any server (the read-only variant, a second server) |
| `page` | function | `open_page(live_server, ...)` |

Override `color_scheme` and `viewport` per test: `@pytest.mark.parametrize("color_scheme", ["dark"])`
or `@pytest.mark.parametrize("viewport", [{"width": 390, "height": 844}])` (`PHONE` and `DESKTOP` are
in `support/ui_b_common.py`). Every context has the locale `en-US`, the time zone UTC, reduced motion,
downloads accepted, `base_url` set to the server and a default action timeout of 15 s. The CSP is never
bypassed: it is part of what is under test. Tracing is on for every context.

**The watcher.** A `WatchedPage` is a real Playwright `Page` plus `watch`, `allow_errors`, `allow_http`
and `new_tab()` (another page of the same context). `PageWatch` collects:

| Line | Source |
|---|---|
| `console.error` and `console.warning` | Console messages with their URL |
| `pageerror` and `crash` | Uncaught exceptions and a crashed page |
| `requestfailed` | Failed requests, except `net::ERR_ABORTED` (a cancelled preview or a download) |
| `http <status>` | Responses with status 400 or more |
| `csp` | `securitypolicyviolation` events, through a binding that survives navigations |

At teardown of a test that otherwise passed, any line that no allow pattern covers fails the test with
the list; CSP violations can never be allowed. Chrome prints every 4xx or 5xx as a console error and
Playwright reports the response too, so an expected status needs both lines allowed:

* `page.allow_http(409, "/api/v1/graphs/")` allows both lines of the status on URLs containing the
  path.
* `page.allow_errors(r"regex", ...)` allows any lines (`re.search` on the whole line).
* `page.watch.matching(regex)` returns the lines seen, allowed or not: assert that the expected noise
  happened, so an allow-list entry cannot go stale unnoticed.

Allow per test, never globally, and put a comment next to every entry saying why the noise is expected.
[ui.md](ui.md#expected-console-and-network-noise) lists the legitimate ones.

### Waits and DOM signals

Never sleep, never `networkidle`, never `page.wait_for_function` (the CSP blocks its string predicate,
[ui quirk 1](ui.md#known-quirks)). Browser state is waited for with Playwright's `expect` and the
helpers of `support/uiwait.py`, which wait on the signals described in
[ui.md](ui.md#dom-wait-signals):

| Helper | Waits for |
|---|---|
| `wait_shell(page)` | `body[data-shell=ready]`: `core/shell.js` has wired the page |
| `wait_page(page, name)` | `main[data-page=<name>]`: `library`, `new`, `edit`, `viewer`, `compare`, `settings`, `notfound` |
| `wait_idle(page)` | `main#main[data-loading=false]`: no API request and no pending or running preview; it turns `true` at once on a change, so it is safe right after an input |
| `wait_chart(page, testid)` | `data-ready=true` on `sankey-chart` (default) or `donut-chart`; still true for the old chart while a new request runs |
| `wait_editor(page)` | `#page-root[data-ready=true]`: the editor mounted every panel |
| `wait_preview(page)` | `wait_idle` then `wait_chart`: the safe wait after an edit |
| `wait_charts(page, count)` | `count` charts ready, none drawing or failed (compare page) |
| `chart_state(page, testid)` | The current `data-ready` (`true`, `false`, `error`) or `None`, without waiting |

Two more bounded waits cover what is not in a browser. `wait_until(probe, timeout=10, what=...)`
(`support/waits.py`) polls a probe every 50 ms and fails with `timed out after Ns waiting for <what>;
last: ...`. `poll_js(page, expression, ...)` in `support/ui_b_common.py` polls a JavaScript
expression with `page.evaluate`. `Hold` (`support/ui_b_hold.py`) makes chosen requests slow
deterministically from inside the page: it wraps `window.fetch`, holds matching requests until the test
releases them and reports whether the app aborted one.

### Page objects

`AppPage` (`support/pages.py`) is the base: a subclass sets `path` and `name` (the value of
`main[data-page]`) and adds locators and actions. It gives `goto(suffix)` (opens the page, waits for
`expect_ready`, returns Playwright's response), `expect_ready()`, `tid(testid)`, `heading`, `nav(which)`,
`theme_button(value)`, `expect_html_theme(value)`, `toasts()`, `expect_toast(text, kind)`,
`remote_banner` and `read_only_banner`. The page objects live in `tests/e2e/support/`:

| Modules | Provide |
|---|---|
| `ui_a_editor`, `ui_a_entries`, `ui_a_sources`, `ui_a_manual`, `ui_a_mongo` | The editor, the entries table and the source tabs |
| `ui_a_viewer`, `ui_a_charts`, `ui_a_downloads`, `ui_a_display` | The viewer, `ChartDom` (Sankey, donut and legend read from the Plotly DOM), real downloads and PNG info, the viewer's display menu and a log of its `/render` and `/export` requests |
| `ui_a_keyboard`, `ui_a_seed` | `tab_until` and `focus_ring`; seeding a graph through the API |
| `ui_b_library`, `ui_b_compare`, `ui_b_settings`, `ui_b_editor`, `ui_b_viewer` | The library, compare, settings, a slim editor and the viewer with the figure readers |
| `ui_b_common`, `ui_b_hold`, `ui_b_hostile` | Viewports, CSS and download helpers, `Hold`, `HostileGraph` and `Inert` |
| `http_a_*` | Helpers of the first HTTP suites: settings, categories, exports, library, exact request targets, PNG and SVG readers (no imaging library), HTML export parsing, a response recorder, Chrome process counting |
| `http_b_*` | Limits, security expectations (routes, headers, internals scan), `Tape`, and the Mongo and storage scenarios with `MongoWorld` and `FlowEnv` |

The letters in `a` and `b` only record which of the two original authoring groups wrote a module; they
are ordinary modules, import what you need.

### Builders and samples

`support/builders.py` builds the data of the tests. `Sample` pairs a CSV text with what the app reports
for it:

| Sample | Content |
|---|---|
| `BUDGET` | The UI flow F1 graph, no categories: 10 nodes, 9 links, 4 columns, 3,800 in and out |
| `BUDGET_CATEGORISED` | The same links with a `category` column (Income, Housing, Food, Transport, Savings) and the flow per category |
| `LAYERED` | Three levels: 6 nodes, 6 links, 3 columns, 16 in and out |
| `CYCLE` | Start, A, B, C and back to A: `on_cycle="error"` is a 422 `graph_build_error`, `"break"` draws |
| `MANY_LINKS`, `many_links(n)` | 300 distinct links `S000..` to `T000..T014`, values 1 to 9 |

Payload factories: `csv_text(rows, header=None)`, `graph_draft(content, source=, transform=, style=)`
(the body of `/preview`, `/entries` and `POST /export`), `graph_create(name, draft, tags=,
description=)` (the body of `POST /graphs`) and `unique_name(prefix)` (`"<prefix> <8 hex>"`). Mongo:
`seed_flows` (a `seed_mongo` option: database `flows`, collection `transfers`) and
`mongo_settings(name, database)` (a `settings` option with one connection whose URI holds the password
`MONGO_PASSWORD`, which no response, page or log may contain).

## Writing a new test

Rules:

* **No sleeps.** Not `time.sleep`, not `wait_for_timeout`, not `networkidle`. Wait on the signals above
  or on `expect`. `filterwarnings = error` and the policy tests apply to the suite like any other.
* **Unique names per test.** Create graphs with `unique_name("...")` and look at them through
  `?q=<name>`, so no test depends on what another left on a shared server. Settings, uploads and the
  Mongo preview cache are server-wide: take a fresh `live_server` for a test that changes them.
* **Select by `data-testid`** (`page.get_by_test_id`), as listed in
  [ui.md](ui.md#data-testid-reference). The exceptions are the documented structural hooks
  (`#page-root`, `main#main`, `html[data-theme]`), Plotly's own DOM read through `ChartDom`, and
  the few elements the app gives no test id, found by role or label. A CSS class or id of the app is a
  last resort and belongs inside a page object, so a rename is fixed in one place.
* **Page objects in `tests/e2e/support/`.** A test module holds scenarios, not locators. Add or extend
  a page object and keep it under the caps.
* **Seed through the API, not the UI**, unless the UI path is the point (`seed_graph(api, ...)`). Assert
  the outcome with `expect`, not the click that should have caused it.
* **Code caps apply.** At most 4 parameters or fixtures per test (bundle options in a small dataclass or
  a `Case`), 50 lines per function, 500 per file, nesting 4. Split a file by topic.
* **No `skip` or `xfail` marks.** `tests/test_policy.py` forbids `pytest.mark.skip` and
  `pytest.mark.xfail`; `skipif` needs a `reason`. `pytest.skip(reason)` is for an absent external
  prerequisite only (Chrome, `/proc`, `SANKEY_TEST_MONGO_URI`).
* **A known product bug** is reported, never hidden: the test keeps asserting the right behaviour and
  calls `pytest.xfail(reason)` at runtime, only while the bug is still there, with a constant (and a
  comment starting `PRODUCT BUG`) that documents the reason. When the bug is fixed the same test is a
  plain regression test and the `xfail` branch never runs; remove it then. No test calls it at the
  moment.
* **Name the behaviour,** as the existing tests do: `test_an_empty_library_invites_a_first_graph...`.
  The docstring of the module says what the file covers.

A browser test, as a skeleton (`library` is the page object of the library):

```python
def test_a_saved_graph_is_listed(
    page: WatchedPage, live_server: LiveServer, api: httpx.Client
) -> None:
    name = unique_name("Listed")
    seed_graph(api, name)
    library = LibraryPage(page, live_server)
    library.goto(f"?q={name}")
    expect(library.card(name)).to_be_visible()
```

`page` fails the test at teardown if the browser logged an error, a failed request or a CSP violation
that the test did not allow. An HTTP test takes `live_server` and `api` (or `foreign`, `bare`) and
needs no browser. A test of a different server flavour takes `make_server` and, for the browser,
`open_page`:

```python
def test_a_remote_server_is_read_only(make_server: ServerFactory, open_page: PageOpener) -> None:
    server = make_server(remote_mode=True)
    page = open_page(server, color_scheme="light", viewport=DESKTOP)
```

## Runtime budget and flakiness

`make e2e` should finish in under 3 minutes on a development machine. The suite is waiting-bound (Chrome,
HTTP round trips), so five shards share the machine without getting in each other's way; one process
needs about 5 minutes (see the Makefile). What costs time:

* The shard planner counts a browser test as eight HTTP tests. An image export on the server starts
  Chrome (about a second each, and the first one is slower), so keep image exports to the tests whose
  point they are.
* A module is the unit of a shard, so one huge module limits the speed-up. The 500-line cap keeps
  modules small; split by topic rather than growing a file.
* Prefer an HTTP test for a contract, and a browser test only for what the browser decides. Use a module
  server when the tests only read, and seed through the API.

Checklist for a test that fails now and then (run it five times in a row, alone and with its shard):

* Waits only on signals: `wait_preview` (never `data-ready` alone, the old chart keeps `true` while the
  new request runs), `wait_idle`, `expect`. After `go_back()` wait for the same signals as after `goto`.
* Absent means absent: elements such as `donut-hint` or `conflict-banner` are removed, not hidden, so
  assert `to_have_count(0)`.
* Compare cards draw when they near the viewport: use a tall viewport and `wait_charts`.
* A theme change needs a frame: `wait_background(page, colour)`. Toasts can cover controls: dismiss one
  before clicking under it.
* No shared state: unique names, a fresh server for settings, uploads, storage and Mongo results.
* A slow server is simulated with `Hold`, not with a sleeping `page.route` handler (that blocks the
  synchronous dispatcher).
* Every allow-list entry has a matching `page.watch.matching(...)` assertion, so the noise really
  happened.
* Downloads use `expect_download`; the first image export of a process takes longer.
* Machine load: try `make e2e E2E_SHARDS=3`, or run the module alone.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every browser test is skipped: `no browser could be started (system Chrome: ...; bundled Chromium: ...)` | Neither browser starts. Install Chrome, or run `uv run playwright install chromium`; `-ra` (the project default) prints the reasons |
| Export tests skip with `Chrome is not available: the server answers 501 export_unavailable` | kaleido finds no Chrome. Run `uv run plotly_get_chrome` or install Chrome |
| A passing test ends in an error: `the browser reported problems:` | The browser logged a console error, page error, failed request, 4xx or 5xx, or a CSP violation. Read the lines and `problems-<n>.txt`; fix the app, or allow the expected noise per test with `allow_http` and a comment |
| `port N still accepts connections after stop()` or `the server thread did not stop within 20s` | A request or connection of the test is still open, or the server thread is stuck. Close clients and pages before the server (the fixtures already order this), and check for a hung request |
| `timed out after 20s waiting for the server on port N to start` | The app failed to start, or the machine is overloaded. Run `make e2e-serial` and look at the first error |
| `E2E_SHARD must look like '2/5'` | A malformed `E2E_SHARD`; `make e2e` sets it for you |
| Leaked processes after an interrupted run | The tests count the Chrome processes started by their own process (`http_a_procs.chrome_descendants`) and assert none is left after the exports. After a killed run, look for orphaned headless Chrome processes (`pgrep -af headless`) and stop them with `kill`; leave your own browser alone |
| `Address already in use` | The e2e servers bind port 0 and never use a fixed port, so this is not the suite. For `make mongo-up` it means another process holds `127.0.0.1:27117`; stop that process, and never retarget the suite at 27017 to 27019 |
| `SANKEY_TEST_MONGO_URI points at 127.0.0.1:27017-27019` | The refusal described above. Use `make mongo-up` and `mongodb://127.0.0.1:27117` |
| `SANKEY_TEST_MONGO_URI is set but the server did not answer` | The container is not up yet. Run `make mongo-up`, wait a few seconds, run again |
| `needs /proc` skips | The process-counting tests need Linux's `/proc`; they skip elsewhere by design |
| A mongomock call is missing or has another signature | mongomock lacks `list_databases(nameOnly=True, maxTimeMS=...)` and `database.list_collection_names(maxTimeMS=...)`, which the inspect routes call. `E2EMongoClient` (`support/mongo.py`) adds both; the `unreachable` switch (`server.mongo.unreachable = True`) simulates an outage without waiting for `mongo_timeout_ms`. For a gap beyond these, test the pure code in the unit suite or use the `mongo` mark ([quality.md](quality.md#test-conventions)) |
| Old screenshots or traces confuse you | `rm -rf .e2e-artifacts`; `make clean` does not remove it |
