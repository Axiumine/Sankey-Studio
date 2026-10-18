# Browser testing

Part of the [UI reference](../ui.md).

Contents

* [DOM wait signals](#dom-wait-signals)
* [Starting a server for browser tests](#starting-a-server-for-browser-tests)
* [Expected console and network noise](#expected-console-and-network-noise)
* [Known quirks](#known-quirks)

## DOM wait signals

`wait_for_load_state("networkidle")` is not reliable (plotly.js, lazy chart drawing, the debounced
preview). Wait for these signals instead.

| Signal | Where | Meaning |
|---|---|---|
| `body[data-shell=ready]` | every page | `core/shell.js` finished wiring the theme switch and loading state; the only ready signal of the error pages |
| `main#main[data-page=<name>]` | every page | which page rendered (values in the [Pages table](../ui.md#pages)) |
| `main#main[data-loading=true\|false]` | every page, always present | `true` while a non-quiet API request is in flight or the editor's preview is scheduled or running; updated at once (the bar `loading` shows only after 150 ms) |
| `#page-root[data-ready=true]` | editor only | the graph and settings are loaded and every panel is mounted. On `/graphs/new` it appears only after the wizard finished |
| `new-wizard[data-step=details\|source]`, `#page-root[data-wizard]` | `/graphs/new` | which wizard step shows; `new-wizard` is removed from the DOM (count 0) when "Start editing" or "Do it later" mounted the editor |
| `chart-settings-panel[hidden]`, `chart-settings-button[aria-expanded]` | editor | the chart settings popover is closed or open |
| `graph-settings-menu[hidden]`, `graph-settings-button[aria-expanded]` | editor | the title menu is closed or open |
| `sankey-chart[data-node-order]` | editor | the node names in figure order joined by `\|`, set after every successful Sankey draw and removed when nothing is drawn; it changes after a drag or an `order-up`/`order-down` press (the chart then animates for about half a second: poll the bar positions, never a clock) |
| `graph-card[data-dragging]`, `folder-card[data-dragging]` | library | `true` on the carried cards from one animation frame after `dragstart` (use an `expect` that retries) until the drag ends |
| `folder-card[data-drop]`, `folder-crumb[data-drop]`, `[data-drop-reason]` | library | on the target under the pointer during a drag: `ok` (it accepts) or `denied` (with the reason sentence in `data-drop-reason`, for example "already here"); removed when the pointer leaves or the drag ends |
| `details-dialog`, `change-source-dialog`, `add-entry-dialog`, `overlays-dialog`, `order-dialog`, `write-back-dialog`, `folder-dialog`, `move-dialog` | editor and library | attached while open, detached when closed |
| `[data-testid=sankey-chart][data-ready]`, `donut-chart` | wherever a chart is drawn | `false` from the moment drawing starts, `true` after `Plotly.react` resolved, `error` when plotly.js could not load or drawing threw; set on the same div that carries the id |
| `[data-chart-theme=light\|dark]` | the same chart divs | the theme the figure was drawn in |
| `compare-card[data-chart]`, `compare-grid[data-count]` | compare | which chart a card shows (`sankey`, `donut`, `none`) and how many ids are on screen |
| `save-status[data-state]` | editor | `new`, `dirty`, `saved`, `saving`, `error` or `readonly` |
| `.savebar[data-state]` | settings | `clean`, `dirty`, `saving` or `readonly` |
| `[aria-busy]` and `.is-busy` | buttons, rows, panels | present while that control's request runs (the button is also `disabled`); `tr[aria-busy]` in the entries table while a category is checked; `.table-block[aria-busy]` while the entries refresh; `.settings[aria-busy=true]` while settings save |
| `state-loading` | any page or panel | a skeleton that is visible while that area loads |
| `html[data-theme]`, `html[data-theme-source]` | every page | the chosen theme and who decides it |
| `[aria-pressed]`, `[aria-selected]`, `[aria-checked]`, `details[open]` | theme buttons and tag chips, tabs, compare switches, sections | current choice |

Recipes (these are the waits the e2e helpers in `tests/e2e/support/uiwait.py` implement):

* **Library.** `graph-card` (or `library-empty`, `library-no-results`, `library-folder-empty`,
  `library-folder-missing` or, at a level that has only collections, `folder-card`) is visible and
  `library-count` has its text. After a filter, search, sort or pager click wait for `library-count` to change or for
  `main[data-loading=false]`.
* **Editor load.** `#page-root[data-ready=true]`, then, when the graph has data,
  `sankey-chart[data-ready=true]`. On `/graphs/new` wait for `new-wizard` OR `#page-root[data-ready=true]`
  first (the page decides which it shows), finish the wizard, then wait as above. The e2e helper
  `finish_wizard` does this with a unique name and "Do it later".
* **Editor after a change.** The preview is debounced by 300 ms. `main[data-loading]` turns `true` on
  the change and `false` when the bundle is in, and the chart then redraws (`data-ready` goes `false`
  and `true` in the same task). The old chart keeps `data-ready=true` while the request runs, so never
  wait for `data-ready` alone: wait for `data-loading=false`, `data-ready=true` and the expected
  content (`stats`, `entries-total`).
* **Style and Export controls.** Open the popover first (`chart-settings-button`, then the tab), and open it
  again right before using a control after touching the page: it closes on any press or focus outside it.
* **Viewer.** `sankey-chart[data-ready=true]`. For the donut click `chart-tab-donut`, then wait for
  `donut-chart[data-ready=true]` (the Sankey div is hidden then). Export controls: click `export-menu-button`
  first; a press on a tab closes the popover, so open it again afterwards.
* **Compare.** The number of `compare-card` elements equals the ids, then every
  `[data-testid=compare-card] [data-ready=true]`. Cards draw when they near the viewport, so use a tall
  viewport or scroll.
* **Settings.** `settings-save` is visible. Wait for `nav.settings-toc` when the test needs the rail
  (only displayed from 1280 px).
* **Not-found.** `goto` returns the response with status 404; wait for `state-empty` and
  `body[data-shell=ready]`.
* **Back and Forward.** HTML is `no-store`, so `go_back()` requests the page again; wait for the same
  signals as after `goto`.
* **Downloads.** `with page.expect_download() as d: click(...)`, then `d.value.save_as(path)`. PNG and
  SVG exports run the server renderer (kaleido and Chrome): allow up to 60 s for the first one, about
  2 s afterwards.

## Starting a server for browser tests

Pick a free port per run instead of a fixed one, and give every run its own data and sources
directories (both are created on demand and must not contain one another):

```bash
PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
TMP=$(mktemp -d)
uv run sankey-studio serve --port "$PORT" --data-dir "$TMP/data" --sources-dir "$TMP/sources" &
PID=$!
until curl -fs "http://127.0.0.1:$PORT/api/v1/health" > /dev/null; do sleep 0.2; done   # {"status":"ok"}
# ... run the browser against http://127.0.0.1:$PORT ...
kill -TERM "$PID"; wait "$PID"
ss -ltn | grep ":$PORT "     # empty output means the port is free again
```

* The default is `--host 127.0.0.1 --port 8765`; always pass `--port`. Accepted `Host` values are
  `localhost`, `127.0.0.1` and `[::1]` (and the bound loopback address). Use the same spelling in the
  page URL and in an `Origin` header.
* Graphs are files in `<data-dir>/graphs/<id>.json` and the settings are `<data-dir>/settings.json`
  with the connection strings in `<data-dir>/credentials.json` (both mode 0600). Files uploaded to `--sources-dir` persist between tests that share it, and an upload
  of an existing name asks "Replace the existing file?".
* **Settings are server-wide.** The header theme switch and the settings page write
  `PUT /api/v1/settings`, so use a fresh data directory per module, or set `theme` back to `system`.
* **Read-only remote variant:** `serve --host 0.0.0.0 --allow-remote --port "$PORT" --data-dir ...
  --sources-dir ...` and open it as `http://127.0.0.1:$PORT`. It shows both banners and
  `writes_allowed` is false. Add `--allow-remote-writes` for remote mode with writes (only
  `remote-banner`); add `--allow-source-writes` as well to let edits be written back to a MongoDB
  source (without it a MongoDB edit stays in the graph with a read-only notice).
* **Seeding goes through the HTTP API, not the UI.** Every `POST`, `PUT`, `PATCH` and `DELETE` needs
  `Content-Type: application/json` for a body and, from a script, an `Origin` header equal to the
  server's own origin (for example `Origin: http://127.0.0.1:$PORT`). A bodiless `DELETE` or
  `POST .../duplicate` from curl without `Origin` is refused with 403. From a page, `fetch` with a
  JSON content type needs nothing more (the browser sends `Sec-Fetch-Site: same-origin`).
  Never send an absolute URL to another host or port from the page.

  ```bash
  curl -s -X POST "http://127.0.0.1:$PORT/api/v1/graphs" \
    -H 'Content-Type: application/json' -H "Origin: http://127.0.0.1:$PORT" \
    -d '{"name":"Budget","description":"","tags":["demo"],
         "source":{"type":"text","origin":"inline","format":"csv",
                   "content":"source,target,value\nSalary,Budget,3000\nBudget,Rent,1200\n"},
         "transform":{},"style":{}}'
  ```

  Unknown query parameters and unknown body fields are a 422. The request models, limits and error
  envelope are in [api.md](../api.md).
* There is no real MongoDB in a plain run. A connection to an unreachable host (for example
  `mongodb://u:p@127.0.0.1:1/`) fails only after `mongo_timeout_ms` (15 s by default); set the setting
  to 500 in tests that exercise the failure path.
* The Playwright fixtures, the live-server helper, mongomock-backed apps, failure artefacts and the
  list of flows are described in [e2e.md](../e2e.md); the harness code is in `tests/e2e`.

Browser launch notes that matter for the UI:

* The e2e harness launches Chrome with `--no-sandbox --disable-dev-shm-usage`. Native widgets (the file input
  text, date formats) follow the operating system locale, not Playwright's `locale`: launch with
  `LANGUAGE=en_US:en LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8` in the browser environment for English
  native text, and use `locale="en-US"` for `Intl` formatting (`3,800`).
* Never pass `bypass_csp=True`: the CSP is part of what is under test. Install a
  `securitypolicyviolation` listener in an init script to collect violations.
* `reduced_motion="reduce"` makes focus rings readable at once and removes transition waits.
* The "nothing may go wrong" watcher of a step collects console errors and warnings, page errors,
  failed requests (ignoring `ERR_ABORTED`, which is a cancelled preview or probe), and responses with
  status 400 or more that the step did not expect; see the next section.

## Expected console and network noise

Chrome prints every 4xx or 5xx response as a console error ("Failed to load resource: the server
responded with a status of N"). Allow the following per test, never globally:

| Where | Request | Status |
|---|---|---|
| Editor with an invalid source | `POST /api/v1/preview`, `POST /api/v1/entries` | 422 |
| Editor conflict | `PUT /api/v1/graphs/<id>` | 409 |
| Editor, an entry that closes a loop (Add entry, a click on a node), or a draft the server cannot build | `POST /api/v1/edits/plan`, `POST /api/v1/edits/write`, `POST /api/v1/entries` | 422 `graph_build_error` |
| Editor, a name or style value the server rejects | `POST /api/v1/preview`, `POST /api/v1/graphs` | 422 |
| Library, a collection name that is taken, or a rule that is broken | `POST /api/v1/folders`, `PUT /api/v1/folders/<id>`, `POST /api/v1/graphs/move` | 409 `folder_name_taken`, 422 `folder_rule` |
| Library, a collection deleted or changed elsewhere | `PUT`, `DELETE /api/v1/folders/<id>`, `POST /api/v1/graphs/move` | 404, 409 |
| Editor, saving into a collection that vanished | `POST /api/v1/graphs?folder=<id>` | 404 (the page retries at the top level) |
| Export fallback | `POST /api/v1/export` or `GET /api/v1/graphs/<id>/export` | 501 (or the status the test forces) |
| MongoDB with nothing listening | `GET /api/v1/mongo/<name>/databases`; `POST /api/v1/settings/mongo/<name>/test` | 422; 503 |
| Compare with a graph deleted after load | `GET /api/v1/compare/render`, `GET /api/v1/graphs/<id>/render` | 404 (ids in `boot.missing` make no request at all) |
| Not-found pages | the document itself (`/nope`, `/graphs/<gone>`, `/compare?ids=bad`) | 404 |
| Graph store down | the document itself (`/`, `/graphs/<id>`, `/graphs/<id>/edit`, `/compare?ids=<id>`) | 503 |
| Settings probe aborted by editing or deleting the row | `POST /api/v1/settings/storage/test`, `POST /api/v1/settings/mongo/<name>/test` | none (`net::ERR_ABORTED`) |
| Settings with invalid limits | none: validated in the browser first | none |

`net::ERR_ABORTED` on `/api/v1/preview` is a cancelled stale preview and is not an error.

## Known quirks

1. **`page.wait_for_function("...")` fails on every page.** Playwright evaluates the string predicate
   with `eval`, which the CSP (`script-src 'self'`) blocks. Use `expect(locator)`, `locator.wait_for()`,
   `wait_for_selector`, `wait_for_url`, `expect_download`, or poll with `page.evaluate`.
2. **`source-content.fill(text)` is one draft change** (one preview after the 300 ms debounce). Typing
   character by character restarts the debounce on every key; type only when typing is the test.
3. **The save bar and toasts are `sticky` or `fixed`.** A `full_page=True` screenshot puts the bar in the
   middle of the page; use a viewport as tall as the document instead. Clicks are fine: scroll padding
   (`scroll-padding-top` for the 52 px sticky header, `scroll-padding-bottom` for the bars) keeps targets
   clear, so `scroll_into_view_if_needed` is enough.
4. **The first save changes the address without an event.** Use `wait_for_url("**/graphs/*/edit")`; `view-graph`
   gets its `href` at the same moment. Saving needs a name; an empty name never reaches the server.
5. **The delete dialog starts on Cancel**, so pressing Enter right away cancels. While any dialog is open
   `#app` is `inert`: clicks on the page behind it fail.
6. **Toasts can cover controls that were not focused.** The page scrolls so the focused control clears
   them, but dismiss a toast (its `x`) or wait before clicking things under it.
7. **File inputs are hidden.** Call `set_input_files` on `library-import` (a label; Playwright targets the
   input inside) or on `source-upload-input`; do not click them. An existing upload name opens the
   replace `confirm-dialog`.
8. **Download names come from the server** (`<graph name>.<ext>` for the Sankey, `<graph name>-donut.<ext>`
   for the donut, hostile characters removed). The client keeps the `Content-Disposition` name as it is
   and never doubles `-donut`. Browser-drawn fallback images follow the same rule. A draft that was
   never saved is `graph` and `graph-donut` until the Name field has text (then the name, or the chart
   title of an edited graph).
9. **`data-loading` says nothing about lazy chart drawing**; combine it with the chart's `data-ready`.
10. **Browser storage carries state between tests of one browser context:** `sankey-studio.theme` (written on
    every theme change, read at start only on read-only servers), `sankey-studio.export` (the export
    options of the editor) and `sankey-studio.editor.sections` (which editor sections are open). Use a
    fresh context per test.
11. **The Mongo tab starts loading databases as soon as it is shown with a connection.** Against an
    unreachable host that takes `mongo_timeout_ms` to fail.
12. **Long chart titles are wrapped** with line breaks to the width of the chart (and wrapped again on
    resize) by `core/title-wrap.js`; the page itself wraps and never scrolls sideways.
13. **A 12-card compare page draws only the cards near the viewport**; scroll or use a tall viewport before
    asserting every card's chart.
14. **Unknown routes, a deleted graph's URL and bad compare links are HTML 404 pages in a browser**
    (`page.goto` returns status 404 with the shell). Non-browser requests (`request.get` without
    `Accept: text/html`, `fetch` with `*/*`) get the JSON envelope. `/compare` without ids is a 200 empty
    page.
15. **Back and Forward cannot use the browser cache** because pages are `no-store`; assertions after
    `go_back()` must wait for the page's ready signals again.
16. **Editor notices are absent, not hidden,** when they have nothing to say (`donut-hint`,
    `category-error`, `conflict-banner`, `entries-basis-hint`, `export-fallback-note`). Assert
    `to_have_count(0)`, not `not_to_be_visible()`, when the absence is the point.
17. **Slow-server tests of the settings page** need a delay in front of `PUT /api/v1/settings`: a small
    reverse proxy that forwards `Host` and `Origin` as the proxy's own origin. A `page.route` handler
    that sleeps blocks Playwright's synchronous dispatcher. A hanging MongoDB is a TCP socket that
    accepts and never answers; the probe then waits `mongo_timeout_ms`.
18. **Settings and Save never wait behind dead probes:** editing or deleting a connection row aborts its
    test, so twelve hung probes followed by Save still save at once.
19. **The chart settings popover closes on any press or focus outside it.** After touching another part of
    the page, open it again (`chart-settings-button`, then the tab) right before using a `style-*` or
    `export-*` control. Its panel is `hidden`, not removed, while closed.
20. **`/graphs/new` shows the wizard first.** `#page-root[data-ready=true]` appears only after "Start editing"
    or "Do it later", and the editor then starts dirty ("Not saved yet", a leave prompt). A test that needs
    an unnamed graph empties the name through the details dialog.
21. **Plotly emits no `plotly_click` for a plain click while the bars are draggable, and a plain click fires
    the same `plotly_restyle` as a drag.** The app reads a click from pointer events plus the last hovered
    node and a drag from the restyle behind a pointer gate; tests use `ChartDom.click_bar`, `drag_bar` and
    `expect_stack`, never a clock, because the chart animates for about half a second after a reorder.
22. **A graph on a text file or a MongoDB `find` source asks "Change your data too?" on its first data
    edit.** The answer lives in `source.write_back` and counts only for that exact file or collection; the
    "Keep in this graph" answer is remembered for the page session only. Edits that go into a file or a
    collection are immediate and not part of Save.
23. **Manual row edits do not move the bars while a node order is stored.** Press "Reset order" to hand the
    order back to the data.
