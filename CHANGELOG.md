# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Library collections: saved graphs can be grouped in a tree of collections (at most 8 levels and 1,000 collections; sibling names are unique ignoring case). `/?folder=<id>` opens one with a breadcrumb, the collections of that level and its graphs; a collection can be created, renamed, moved and deleted (deleting one moves its graphs and sub-collections up, nothing is deleted); a graph or a selection moves with "Move"; a search looks in every collection and names the collection of each result; "New graph here" and `/graphs/new?folder=<id>` save a new graph inside one. In code the noun is `folder`.
- Collections API: `GET` and `POST /api/v1/folders`, `GET`, `PUT` and `DELETE /api/v1/folders/{id}`, `POST /api/v1/graphs/move`, `?folder=root|<id>` on `GET /api/v1/graphs` (not together with `q` or `tag`) and `?folder=<id>` on `POST /api/v1/graphs`; `folder_id` on graph definitions and summaries; the error codes `folder_rule` (422) and `folder_name_taken` (409); `folders` and `folder` in the library boot data, `folder_id` in the new-graph boot data.
- Collections are stored in `folders.json` next to the graph files, or in the MongoDB collection `sankey_studio_collections` beside `sankey_studio_graphs` (unique `(parent_id, name_key)` index); "Test storage" probes both, and a storage switch that copies the graphs copies the collections first (`folders` and `folders_skipped` in the copy report).
- Write-back: when the person agrees, an edit is written into the data and not only into the graph. A category typed on an entry or an added entry goes into pasted text, manual links, a managed text file (the existing file is replaced atomically) or a MongoDB collection (`find` with a plain equality filter: one `$set` or `$unset` on at most 1,000 documents chosen by `_id` and re-filtered, or one inserted document); a row reorder can go into text and files. Files and collections ask first ("Change your data too?"); the answer is saved with the graph in `source.write_back`, bound to a key the server builds from the resolved file, connection, database and collection, so another target asks again. "Keep in this graph" keeps one edit in the graph, "Keep in this graph, don't ask again" saves that choice.
- A node drag also rewrites the data in the default colour mode: the edit answers `pins` (hex colours) that keep every node or category colour, and the editor merges them into `style.node_colors` / `style.category_colors` with the new rows. `would_recolour` is now only the answer when the pins would not fit in the style.
- A `set_category` is no longer refused as `unsafe_value` because a node name starts like a formula; an added entry for a file or collection is not blocked by a full list of graph-only entries; a MongoDB category update of up to 1,000 long string `_id`s is no longer refused; a category field that equals or nests with the value field is `field_conflict`.
- `POST /api/v1/edits/plan` (pure, also open on a read-only server) and `POST /api/v1/edits/write` decide where an edit goes (`draft`, `file`, `mongo` or `graph`), say what the person must agree to and write it; 25 stable reasons explain why an edit stayed in the graph, with one fixed sentence each (formula-like text, system or `sankey_studio_*` collections, aggregate sources, no category field, more than 1,000 documents, a database user without write rights, ...).
- `--allow-source-writes` / `SANKEY_SOURCE_WRITES`: with `--allow-remote-writes`, a remote server may also write edits back to MongoDB sources (`--allow-remote-writes` alone does not); on loopback MongoDB write-back is always available. The remote banner prints `source writes: ENABLED|DISABLED`.
- A text rewriter (csv, tsv, SankeyMATIC, json and manual links) adds an entry, sets a category or reorders rows, keeps untouched lines byte for byte and writes only what the real parser reads back as the old data plus the intended change; JSON arrays are re-formatted (the dialog and a notice say so).
- Entries: "Add entry" opens a dialog (source, target, value, optional category) that adds a flow to the data (pasted text, manual links, a text file or a MongoDB collection) or, when it cannot or may not, to the graph only; it hints at new nodes and stays open with a plain sentence when the entry is refused.
- Entries: a "Graph-only edits (N)" chip lists the category edits, added entries and the custom node order that live in the graph and not in the data, with a Remove button on each; a notice says when category edits no longer match any entry.
- Entries: after the first category typed into data that had none, a toast "N other entries have no category." offers "Show them".
- Chart: click a bar of the Sankey to add a flow that starts at it (or ends at it when nothing leaves it) in the same "Add a flow" dialog, with a choice of direction.
- Chart: drag a bar to reorder the nodes of its column. The order is saved with the graph (`style.node_order`) and drawn by the viewer, compare and the SVG, PNG and HTML exports (Plotly `sort: "input"`); "Order nodes" is a dialog with Up and Down buttons for keyboard and single-pointer use, "Reset order" returns to the layout of the data. Rows of the data follow a drag only when that does not change any colour and the saved choice allows it.
- Editor: a gear next to the title opens a menu with "Edit details" (name, description and tags in a dialog) and "Change data source" (a guided switch between Text file, Paste, Upload, Manual and MongoDB that asks what to do with graph-only edits). Changing the source tab asks the same question.
- Editor: a two-step new-graph wizard (name, then data source) replaces the blank editor; "Do it later" starts an empty Paste or Manual graph; nothing is saved until Save.
- Editor: Style and Export open from a gear in the chart header, in a popover that keeps the chart live (Escape, a click outside or the close button closes it); the gear is marked when the server rejects a style value.
- Paste tab: clearing the data shows a "Cleared" toast with Undo.
- `POST /api/v1/preview` lists the drawn nodes (`nodes`, aligned with the figure labels); graph-only entries (`transform.extra_links`) and a stored node order are part of every graph build.
- End-to-end tests: page objects for the wizard, the graph menu, the details and change-source dialogs, the chart settings popover, the consent dialog and the collection library; shared HTTP scenarios for write-back and collections that also run against a real MongoDB; the `allow_source_writes` server option.
- Editor: pick the colour of "One colour" mode in the Colours section (`style.mono_color`), with a reset to the palette colour.
- Editor: tap a category's colour square in the chart's category table to open the colour picker; the pick is saved as the category colour (`style.category_colors`).
- Viewer: a display menu (an icon at the right of the chart tabs) with view-only switches for the value under the node names (Sankey) and the percentage and value on each donut slice; they start from the saved style, redraw at once, are sent as `node_values`, `donut_percent` and `donut_value` with `GET /graphs/{id}/render` and every export, and never change the saved graph.
- Editor: "Show values" for the donut (`style.donut.show_value`, off by default) prints the slice value under the percentage, in the order of the switches.
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

- Editor layout: the chart is a full-width row above Source and Transform (side by side from 900 px); the sticky chart pane and the "Go to the chart" link are gone; name, description and tags moved into the details dialog; Style and Export moved into the chart settings popover. An unsaved graph with a name shows `New graph: <name>` in the heading, and Save with an empty name opens the details dialog.
- `/graphs/new` starts with the wizard instead of a blank editor; a graph made from it is not saved yet (the leave prompt and "Not saved yet" apply) and a new graph no longer inherits a node order from the default style.
- The Clear button of the Paste tab is an icon inside the data box (top right) instead of a button under it.
- Graph bundles are version 2 and end with the collections of the exported graphs (version 1 files are no longer read); importing the same bundle again reuses a collection with the same name in the same place, and an import drops any saved write-back consent from its graphs (a consent names a file or connection of the exporting machine).
- The library lists the graphs of the open collection (the top level lists the graphs that are in no collection); "Export" exports what the list shows ("Export this collection (N)", "Export top-level graphs (N)"); a duplicate is saved in the collection of its original, and saving a graph never changes its collection.
- MongoDB is no longer strictly read-only: the library store holds graphs and collections, and the opt-in source write-back above is the only other writer. The Semgrep message of `sankey-no-mongo-writes` and the docs say so; the rule itself is unchanged and its waivers stay under `src/sankey_studio/storage/`.
- Remote mode: edits to a file follow `--allow-remote-writes` (the upload route can already replace files); edits to a MongoDB source additionally need `--allow-source-writes`.
- The graph cache key ignores `source.write_back` (a consent toggle costs no source read; `style`, and so `style.node_order`, was never part of it), and `ResultCache.clear()` empties the cache after every MongoDB write.
- "Test storage" also probes the collections collection; a graph store needs write access to both `sankey_studio_graphs` and `sankey_studio_collections`.
- `plotly>=7.1`; the formula test of the CSV export is shared as `util.starts_like_formula` (behaviour unchanged).
- Changing the source tab of a graph that holds graph-only edits asks whether to keep them.
- The value of a node label (`style.show_values_in_labels`, now "Show values under the node names" in the editor) goes on a second line under the name instead of after it.
- Donut slices show the percentage and/or value on every slice, also with more than four slices (the name stays out and the legend carries it); before, such slices showed nothing.
- `import_bundle` defaults to the `new_ids` mode; `Services.test_storage` is refused in read-only remote mode.
- Number formatting rounds exact ties up and re-picks the SI prefix after rounding, like d3-format.
- Donut downloads are named `<name>-donut.<ext>` (a draft without a title: `graph` and `graph-donut`), so they no longer overwrite the Sankey file of the same graph; names over 80 characters are cut to 74 before `-donut`.
- The entries table spans the full width below the chart, with a shorter search placeholder; the export card no longer makes the page jump when it appears.
- Toasts sit along the bottom on phones, above the save bar, and the page scrolls so they never cover the focused control.

### Fixed

- Editor: a bar dropped back into the order of the rows is stored when the automatic layout had drawn another order (the drag is compared with the order drawn when the press began, not with the row order); the Undo of an added entry or a node drag undoes only its own edit, and a new Undo toast replaces the older one instead of keeping its Undo.
- A collection whose parent record is missing can be renamed again (the parent is healed to the top level) and takes part in the top-level name check; a `keep_ids` import moves the graphs and sub-collections of a refused collection to the nearest stored ancestor.
- A headerless csv or tsv text now reads its category from the fourth column (donut chart and "Auto (col 4)"), like source, target and value use columns 1 to 3; "This data has no category column" (`detect_category=false`) turns it off. A fourth column that is not a category (a note, a date) now yields categories, with the usual single warning for unusable cells.
- A category typed on one entry is written into the data (the Paste box, the Manual table, a text file or a MongoDB collection, after the question above) and not only into the chart, so the other entries keep their data categories instead of all showing "Uncategorized"; manual pairs of merged nodes are found.
- The chart tabs of the viewer no longer show a vertical scrollbar beside the Donut tab.
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
