# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Editor: pick the colour of "One colour" mode in the Colours section (`style.mono_color`), with a reset to the palette colour.
- Editor: tap a category's colour square in the chart's category table to open the colour picker; the pick is saved as the category colour (`style.category_colors`).
- Project scaffold managed with `uv`: `src/` layout, `sankey-studio` console script, dev dependency group.
- Shared domain contract: pydantic models for sources (text, MongoDB, manual), transforms, styles and saved graphs; columnar `SankeyGraph`; typed domain errors.
- Optional per-entry categories (from data, glob rules or explicit user choice) with a donut chart that shares the category colour map with the Sankey.
- Read-only MongoDB guard (`mongo_safety`), credential masking (`mask_uri`) and a cached `MongoClients` registry.
- SVG and PNG export for both charts (kaleido), plus HTML, JSON and CSV.
- Quality tooling: ruff, mypy (strict), pytest, pytest-memray memory budgets, 100% coverage gate, mutmut, Semgrep (custom rules + rule tests), Trivy, Qodana Ultimate Plus, GitNexus code-intelligence index.
- Local `docker-compose.yml` MongoDB bound to `127.0.0.1:27117`.
- Text sources: csv, tsv, SankeyMATIC and JSON parsers with encoding/delimiter sniffing, per-row problem reporting (strict and lenient), size and record caps, and a hardened sources directory (upload, list, preview, delete) with symlink, traversal, case-collision and directory-lock protection.
- MongoDB sources: `find` and `aggregate` extraction under the read-only guard with row caps and time limits, BSON value normalisation (including UUID binaries), database/collection listing and field suggestions.
- Storage: file and MongoDB graph repositories, a local `settings.json` store with 0600 permissions and masked secrets, graph copy between stores with an unreadable-graph report, and export/import bundles.
- Graph building: merge/hide, minimum link value and top-N, cycle breaking, layering and category splitting with stable colour slots.
- Rendering: Sankey and donut figures with in-figure legends and escaped labels, a compare-view colour map, category and entry tables, HTML/JSON/CSV exports and SVG/PNG export behind size, pixel and time caps; memory-budget tests and a whole-pipeline memory profile script.
- Web interface served by `sankey-studio serve`: a library of saved graphs (search, tags, sorting, paging, import and export), an editor with a live preview (pasted, uploaded or managed text files, manual rows and MongoDB sources; transform and style options; an entries table to categorise links), a viewer, side-by-side compare and a settings page. Light and dark themes, full keyboard use, no external assets (Plotly is served locally).
- Browsers get an HTML "Page not found" or "Graph not found" page (404, same app shell, link back to the library) for unknown URLs, deleted or malformed graph links and invalid compare links; API paths and non-browser clients still get the JSON error.
- Settings: an "On this page" list beside the sections from 1280 px wide; a failed copy to a new storage location says how to switch without copying.
- Export panel: a "File colours" choice (Light, Dark, same as preview; default Light) used by every download, including images drawn by the browser.
- Upload tab: a styled "Choose a file" button instead of the browser's own file input.
- Stable hooks for browser tests: `data-ready` on charts, `data-loading` on the main area, and the test ids listed in `static/testids-extra.txt`.
- End-to-end tests: a live-server harness (mongomock, ephemeral ports), HTTP suites for settings, sources, categories, exports, library, MongoDB, storage switching, security and limits, and real-Chrome suites for the editor, library, compare, settings, dark mode, responsive layout and hostile text; `make e2e` runs them in five shards (about 90 s), `make e2e-mongo` runs the MongoDB flows against a real server when `SANKEY_TEST_MONGO_URI` is set.
- Project documentation: `README.md`, `CLAUDE.md`/`AGENTS.md` working agreement and `docs/` (architecture, API, UI, quality, end-to-end tests, decisions).

### Changed

- `import_bundle` defaults to the `new_ids` mode; `Services.test_storage` is refused in read-only remote mode.
- Number formatting rounds exact ties up and re-picks the SI prefix after rounding, like d3-format.
- Donut downloads are named `<name>-donut.<ext>` (a draft without a title: `graph` and `graph-donut`), so they no longer overwrite the Sankey file of the same graph; names over 80 characters are cut to 74 before `-donut`.
- The entries table spans the full width below the chart, with a shorter search placeholder; the export card no longer makes the page jump when it appears.
- Toasts sit along the bottom on phones, above the save bar, and the page scrolls so they never cover the focused control.

### Fixed

- Static files (`/static/*`) and `/static/vendor/plotly.min.js` now answer `Cache-Control: no-store` (no `ETag`, no `Last-Modified`, never a 304), and every page links its style sheets, scripts and icon under a version prefix (`/static/v-<digest>/css/layout.css`) that nested modules and script-loaded style sheets share, so a browser never keeps showing an old UI after a change, not even with copies it stored before; the active header link (Library, New graph, Settings) is drawn in the accent blue, and "New graph" is no longer always blue.
- Saving settings above 1 MiB is refused instead of making the next load fail.
- Page `limit` and `offset` are capped at 2**31-1 (no 503 on the MongoDB backend); graphs above the 32 MiB file cap are refused when saved.
- A CSV record spanning many lines is capped at 64 KiB; the 4096-character line limit counts after a BOM; decode errors name the real line.
- Lenient JSON loads skip non-object array entries with a warning; `save_stream` accepts any `IO[bytes]`.
- The MongoDB row cap counts usable rows; database listing uses `nameOnly`; field suggestions never offer `_id`.
- Export maps every browser-protocol error to a clean 502; `valuesuffix`/`valueformat` are escaped.
- Host check ignores letter case (`CaseInsensitiveTrustedHost`); the bound loopback address always answers its own `Host`.
- `serve` with a bare IPv6 `--host` and `--allow-remote` starts; `[::]` and `::ffff:0.0.0.0` count as wildcards.
- A `SANKEY_MONGO_URI` the settings refuse exits 2 at startup (reason only, never the URI); the banner example no longer lists a host twice.
- `PUT /settings` with the same rename again (previous name gone, new name stored) answers 200 and keeps the secret instead of 422; saving settings is serialised (`Services.settings_transaction`), so a rotated secret is never lost.
- Mongo inspection and the Mongo probe no longer need the sources directory; `POST /settings/storage/test` runs at most 4 probes at once, then answers 503 `busy`.
- Every name `GET /sources/files` lists can be previewed and deleted (newline names included); names with a backslash, which those routes refuse, are no longer listed.
- Read-only remote mode answers 403 before decoding the body on `PUT /settings` and the probes (`GuardedRoute` is shared by the graphs, settings and sources routers).
- `GET /graphs/export` builds the bundle one graph at a time and refuses at the 16 MiB cap without loading the rest; it measures and writes UTF-8 (no `\u` escapes), so any graph `POST /graphs` accepts can be exported and imported.
- Every HTML page is sent with `Cache-Control: no-store`, so Back and Forward never show a page rendered before a change.
- `/compare` without ids opens the empty compare page, and deleted graphs in a compare link show a "This graph is gone" card without failed requests.
- A graph whose name has no visible characters is called "Untitled graph" in headings, titles, cards, menus, dialogs and toasts; such search text and tags no longer leave empty labels.
- Control characters (bell, escape, DEL, C1) in node, category and graph names no longer make SVG exports ill-formed or PNG exports fail; markup in names is drawn as literal text. The empty-basis donut hides its axes.
- A far-out `?page=` in the library address opens the last page instead of an error; export toasts use thousands separators; the chart toolbar can no longer offer "Share chart...".
- Settings: a theme change and Save settings no longer overwrite each other, in either order, even on a slow server; deleting or editing a connection cancels its running test (no stale toast, Save no longer waits behind dead tests); the "Holds your graphs" badge only shows while MongoDB is the storage; the System theme card names what the device does now; read-only servers no longer say connection strings can be replaced and show the copy box unticked; dismissing the copy report moves focus to Test storage.
- Editor: reverting an edit (clearing a field, putting a value back) no longer leaves "Unsaved changes" or the leave prompt; Paste rows keeps the first row of data with comma decimals and says when a header row was skipped; Save and Ctrl+S with an empty name mark the Name field even when it has focus; toggling "first row is a header" re-matches the columns; the paste counter counts an emoji as one character.
- A graph with no drawable links (empty data, every row skipped, or Transform filtering everything) shows a clear empty state instead of "The chart could not be drawn", with its exports disabled.
- The entries table refreshes after the server comes back (chart Try again), its notice has its own Try again, and a download the browser cannot draw says so instead of "Cannot reach the server".
- Library, viewer and compare reload after Back/Forward and cache restores without leaking chart observers; a failed import after Esc shows a toast; focus returns to Import and after compare removal.
- Page shell: the saved theme is rendered on first paint (no flash); header and banners reach the scrollbar; aborted requests, long text, focus under the sticky bar and the squashed toast close button are fixed; the editor's unsaved-changes flag compares with the last saved state; a refused save no longer marks the chart as out of date.
- Long chart titles in the editor preview wrap instead of being cut off at the edge.
- "Try again" on the entries notice also clears the chart's "server cannot be reached" message.
- The entries table no longer scrolls inside its own box; the page scrolls and the header row stays visible.
- A unit suffix such as `<b>$` is shown as typed in the viewer's totals instead of its escaped form.
- A MongoDB source no longer warns "Result truncated at limit N" when the collection holds exactly N documents: the server is asked for one document more than `limit`, and only that extra document (never turned into a row) makes the warning appear.
- A browser opening a page while the graph store is unreachable (503), or hitting any other server error, gets an HTML error page in the app shell instead of the raw JSON envelope; API clients are unchanged.
- The 422 for an unknown `source.type` no longer quotes the submitted value; it lists the allowed types.
- The editor's MongoDB tab pre-selects the only connection after "Check again", so its databases and collections load without picking it again.

### Security

- Category rules are bounded to 20 million (name x rule) matches per build, so a hostile settings file cannot stall a build.
- The MongoDB result-cache key includes a SHA-256 digest of the full connection string, so rotating only a password no longer serves a graph loaded with the old credentials for up to 30 s.
- Tests assert that log records (message, args, traceback), not only response bodies, never contain a MongoDB password.
- Names of nodes, categories and graphs are drawn as literal text in charts, hover text, legends and SVG, PNG and HTML exports: control characters and direction overrides are removed and markup such as `<a>` or `<b>` is escaped. Names with direction overrides can no longer reverse nearby text in the pages.
