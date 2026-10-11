# Architecture

Sankey Studio draws and manages Sankey graphs, plus an optional donut chart of the same data. This
document describes what the product does, how the code is organised and why. For the HTTP contract
see [api.md](api.md), for the browser UI see [ui.md](ui.md), for the quality gates see
[quality.md](quality.md) and for the reasoning behind the main choices see
[decisions.md](decisions.md).

Contents

* [Product](#product)
* [Process model](#process-model)
* [Module map](#module-map)
* [Data model](#data-model)
* [Pipeline](#pipeline)
* [Categories and the donut](#categories-and-the-donut)
* [Storage](#storage)
* [Rendering and export](#rendering-and-export)
* [Security design](#security-design)
* [Cross-cutting rules](#cross-cutting-rules)

## Product

* **Library.** Many saved graphs with create, read, update, delete, duplicate, search, tags and JSON
  bundle import and export. A compare page shows up to 12 graphs side by side.
* **Sources.** `text` (pasted or uploaded text, or a file in the managed sources directory; CSV, TSV,
  SankeyMATIC lines, JSON array or NDJSON), `mongo` (a named connection, `find` or `aggregate`,
  strictly read-only) and `manual` (an editable table of links stored inside the graph).
* **Pages.** Library `/`, editor `/graphs/new` and `/graphs/{id}/edit`, viewer `/graphs/{id}`, compare
  `/compare?ids=` and settings `/settings`.
* **Charts and exports.** A Sankey and an optional donut. Both export to SVG, PNG, HTML and JSON, and
  to CSV as a table. SVG and PNG are rendered on the server through kaleido and Chrome; the UI falls
  back to Plotly's client-side image download when the server answers 422 `export_too_large` or
  501, 502, 503 or 504. The legend is part of the figure, so exports contain it.
* **No login.** There is no authentication anywhere. The server therefore binds to loopback by
  default and defends itself (see [Security design](#security-design)).
* **Optional categories.** Categorising entries is optional everywhere. A graph with no categories is
  a plain Sankey, with no donut and no category legend.

All user-facing and code strings are English.

## Process model

One `uvicorn` worker, started in-process by `sankey-studio serve` (`cli.py`). File locks and the
export slot are per process, so more than one worker is not supported. `limit_concurrency` is 100,
`proxy_headers` and the `Server` header are off, and websockets are disabled. The OpenAPI, Swagger
and ReDoc routes are disabled (Swagger UI would load JavaScript from a CDN).

The application is built by `web/app.py::create_app(config, *, services=None)`. It refuses to build
unless `config.is_loopback or config.remote_mode`, which re-asserts what `BootstrapConfig` already
enforces.

## Module map

Package `src/sankey_studio/`. Imports only point downwards in this table; nothing imports a higher
layer.

| Layer | Modules | Role |
|---|---|---|
| 0 foundation | `errors`, `util`, `config`, `models/`, `mongo_safety`, `mongo` | Domain errors with stable codes, URI masking and category identity, bootstrap configuration, all pydantic specs and the built-graph dataclass, the read-only Mongo guard, the cached Mongo client registry |
| 1 domain | `sources/`, `graph/`, `render/`, `storage/` | Load links, build the graph, draw it, persist it |
| 2 wiring | `services`, `bundle` | `Services` wires settings, Mongo clients, storage and the source context; `RenderBundle` is the JSON shape of one drawn graph |
| 3 pipeline | `pipeline` | Draft to graph to bundle, with a small result cache |
| 4 web | `web/` | FastAPI app, middleware, routers, schemas, templates, static assets |
| 5 frontend | `web/static/`, `web/templates/` | Vanilla ES modules and Jinja page shells |

`cli.py` and `__main__.py` sit on top of everything. `render/`, `sources/` and `storage/` never
import `web/`.

| Module | One-line role |
|---|---|
| `errors.py` | `SankeyError` hierarchy; every error has a stable `code` and an HTTP `status_code` |
| `util.py` | `mask_uri` (fail-closed), `looks_masked`, category normalisation and identity |
| `config.py` | `BootstrapConfig` (`SANKEY_*` variables): host, port, data dir, sources dir, allowed hosts, seed Mongo URI, remote mode |
| `models/` | Spec models (`TextSource`, `MongoSource`, `ManualSource`, `TransformSpec`, `StyleSpec`, `GraphDraft`, `GraphDefinition`, `AppSettings`, ...) and the `SankeyGraph` dataclass |
| `mongo.py` | `MongoClients`: cached clients, per-connection concurrency slots, driver errors mapped to domain errors |
| `mongo_safety.py` | Filter, pipeline, name and URI validators for everything that reaches Mongo |
| `sources/base.py` | `Diagnostics`, `SourceContext`, `CategoryCleaner`, the `DataSource` protocol |
| `sources/text.py`, `sources/formats/` | Text source: decoding, format sniffing, one generator parser per format |
| `sources/files/` | Managed sources directory: safe paths, upload names, list, save, delete, preview |
| `sources/mongo_*.py` | Mongo source, extraction, inspection, sampling, field suggestions |
| `sources/manual.py` | The manual source (links live inside the graph definition) |
| `graph/` | `build_graph` in six steps: intern, categories, pairs, cycles, layers, assemble |
| `render/` | Plain-dict Plotly figures for the Sankey and the donut, legend, colours, palette, tables, number formatting |
| `render/export/` | The only code that imports plotly and kaleido: HTML, JSON, CSV, SVG and PNG exports |
| `storage/` | Graph repositories (files and Mongo), `settings.json` store, atomic file primitives, bundles, migration |
| `services.py` | `Services`: the only place that wires things; the web layer talks to it |
| `bundle.py` | `RenderBundle` and `BundleStats` |
| `pipeline.py` | `build_graph_from_draft`, `render_bundle`, `render_compare`, `preview_entries` and the result cache |
| `web/` | `app.py` (assembly only), `deps.py`, `middleware.py`, `security.py`, `errors.py`, `schemas/`, `routers/` |

Package sizes follow the code caps (see [quality.md](quality.md)): a module that nears 400 lines
becomes a package with a re-exporting `__init__.py`, so public import paths stay stable
(`sankey_studio.graph`, `sankey_studio.sources.files`, `sankey_studio.render.export`,
`sankey_studio.web.schemas`, `sankey_studio.models`).

## Data model

All specs derive from one `_Model` base: `extra="forbid"`, strings stripped, `validate_assignment`,
and validation input hidden from error messages. Specs are values: never mutate one, rebuild it with
`Model.model_validate({**m.model_dump(), "field": value})`. Request models forbid unknown fields; the
persisted `GraphDefinition` ignores unknown top-level fields and carries `schema_version`.

| Model | Purpose |
|---|---|
| `GraphDraft` | `source`, `transform`, `style`: an unsaved graph |
| `GraphCreate` / `GraphUpdate` | Draft plus `name`, `description`, `tags`; update adds the `revision` it was based on |
| `GraphDefinition` | The persisted shape: adds `id` (32 hex characters), `schema_version`, `revision`, `created_at`, `updated_at` |
| `GraphSummary` | Library row: id, name, description, tags, source type, revision, `updated_at` |
| `TextSource` | `origin` (`inline` or `file`), `content` or `path`, `format`, delimiter, header and column selection, `category_column`, `detect_category`, `encoding` |
| `MongoSource` | `connection`, `database`, `collection`, `mode` (`find` or `aggregate`), `filter` or `pipeline`, dotted field paths, `limit`, `max_time_ms` |
| `ManualSource` | A list of `Link(source, target, value, category)` |
| `TransformSpec` | `min_link_value`, `top_links`, `hide_nodes`, `merge_nodes`, `on_cycle`, `strict`, `entry_categories`, `category_rules`, `rules_override` |
| `StyleSpec` | Title, orientation, `color_mode` (`node`, `layer`, `mono`, `category`), colour overrides, node and link geometry, value format, font size, height, and the `DonutStyle` |
| `AppSettings` | Storage backend and target, Mongo connections, theme, default style, `max_links`, `max_drawn_links`, `max_upload_mb`, `mongo_timeout_ms` |
| `MongoConnection` | `name`, `uri` (a `SecretStr`), `default_database` |
| `SankeyGraph` | The built graph: a frozen, columnar dataclass (`array('i')` for node and category indexes, `array('d')` for values) that is never persisted |

`TransformSpec.top_links` keeps the N largest source-target pairs. It is different from
`AppSettings.max_links`, which caps the raw rows read from a source, and from `max_drawn_links`,
which caps how many links are drawn.

Secrets: `MongoConnection.uri` is a `SecretStr`. Default serialisers print `**********` and refuse to
load it back. Only `storage.settings_store.dump_settings` and `load_settings` handle real values.

`sources_dir` is not a setting. It is bootstrap-only (`--sources-dir` or `SANKEY_SOURCES_DIR`),
because a web-writable root would be arbitrary file read and write.

## Pipeline

```
SourceSpec -> open_source(spec, ctx).iter_links(diag) -> RawLink(source, target, value, category|None)
           -> graph.build_graph(links, transform, max_raw_links=..., diag=...) -> SankeyGraph
           -> render.sankey.build_figure / render.donut.build_donut_figure -> Plotly figure dict
           -> browser (plotly.js from the installed plotly package) or kaleido (SVG, PNG)
```

`pipeline.render_bundle(services, draft, options)` runs the whole chain and returns a `RenderBundle`.
`render_compare` builds every graph first and then one shared `ColorMap` so a category keeps one hue
in every card. A small LRU cache (`ResultCache`, 16 graphs, injectable clock) is keyed by a hash of
the canonical JSON of source and transform (style excluded; file origins also by mtime and size). Its
time-to-live is 120 s, and 30 s for Mongo sources, so paging the entries table does not reload a file
or re-query Mongo on every keystroke.

### `build_graph`

The order of the steps is part of the contract:

1. **Intern.** Stream the links once (never `list(links)`), count raw rows (more than `max_raw_links`
   raises `GraphTooLargeError`), resolve `merge_nodes` alias chains, intern node names in
   first-appearance order, and aggregate entries. That order is the stable colour slot of a node and
   does not change when filters change. A link that becomes a self-loop through merging is dropped
   with one aggregated warning.
2. **Categories.** Resolve one category per aggregated entry (never per raw row) with the precedence
   described below. Rule patterns are compiled once and matched per distinct node name.
3. **Pairs.** Apply `hide_nodes`, aggregate to category-agnostic (source, target) pair totals, then
   `min_link_value` and `top_links` on the pair totals, then drop nodes left without a pair.
4. **Cycles.** `on_cycle="error"` raises `GraphBuildError` naming one cycle; `"break"` removes
   back-edges found by an iterative depth-first search and adds a warning.
5. **Layers.** Longest-path depth by an iterative Kahn pass; node in and out sums come from the pair
   totals.
6. **Assemble.** Only now split surviving pairs into parallel per-category links and build the column
   arrays.

Topology never depends on categories: the nodes, layers and pair totals of a graph are identical with
and without its categories. Both searches are iterative so 100,000 nodes are fine. A guard raises
`GraphTooLargeError` when distinct names times category rules exceed 20,000,000.

## Categories and the donut

An entry is a (source, target) pair as the user sees it in the entries table.

* **Identity.** A category name is normalised (NFC, trimmed, inner whitespace collapsed) and compared
  case-insensitively. The display spelling is the first one seen. Control characters and lone
  surrogates are rejected. At most 200 distinct categories per graph; later ones become uncategorised
  with one warning.
* **Reserved names.** `Uncategorized` and `Other` (any case or spacing) belong to the renderer.
  User-authored specs reject them; data sources turn them into `None` with one aggregated warning.
* **Precedence**, highest first: the user's explicit `entry_categories` (exact, case-sensitive match
  on post-merge names; `category: null` forces uncategorised), then the data (CSV column, Mongo
  field, `| category` suffix, manual `Link.category`), then glob `category_rules` (first match wins).
  With `rules_override=True` the rules rank above the data but still below `entry_categories`. For a
  manual source the entries table edits `Link.category` on every link of the pair and never writes
  `entry_categories`.
* **Tolerance.** One implementation (`sources.base.CategoryCleaner`) for every source: a missing,
  empty, non-scalar, over-long or reserved category value becomes `None`, the row is kept, and at most
  one aggregated warning is emitted per load. Only a named `category_column` missing from the header
  is a hard error.
* **One representation of "no category".** `SankeyGraph.link_category == -1`. `SankeyGraph.categories`
  holds only real categories that appear on the final links. `Uncategorized` is a render-time label
  for the -1 bucket (shown only when some but not all links are categorised) and `Other` is the donut
  fold bucket; neither is ever in `categories`.
* **The donut exists iff `len(graph.categories) > 0`**, evaluated on the final links, so filters never
  leave a dead donut tab. Otherwise `RenderBundle.donut_available` is false and an export of the donut
  answers 422 `no_categories`.
* **Basis** (`DonutStyle.basis`): `all` counts every link as entered, `initial` only links leaving a
  source node, `terminal` only links entering a sink node (both after cycle breaking).
* **Colour follows the entity.** Node and category colour slots come from first-appearance order in
  the unfiltered data, so filters and top-N toggles never repaint survivors. Slots 0 to 7 map to the
  eight palette hues, higher slots are neutral. `ColorMap.has_hue(category)` is the one test for
  "drawn in its own hue" and both the donut fold and the legend `Other` use it. The compare view
  ranks the union of categories by summed value so "Food" has one hue in every card.

## Storage

Saved graphs live in a `GraphRepository` (`storage/base.py`): `list_graphs`, `count`, `all_tags`,
`get`, `create`, `update`, `put`, `iter_definitions`, `delete`, `unreadable_ids`, `ping`.

* Ids are 32 lowercase hex characters, validated before any path or query use; a malformed id is a
  404. Listings are ordered by `updated_at` descending then id ascending.
* **Optimistic concurrency.** `PUT /graphs/{id}` carries the `revision` it was based on. The revision
  compare and the write are one critical section. A stale revision raises `ConflictError` (409) with
  `revision=N` and `updated_at=<iso>` in `details`, and the UI offers reload or save as copy.
* **File backend** (`storage/files/`). One `<id>.json` per graph under `<data_dir>/graphs/`, written
  atomically (temporary file created exclusively with mode 0600, fsync, `os.replace`, directory
  fsync). A process-wide registry keyed by the resolved directory gives every repository instance on
  that directory one lock and one listing index, which `stat` validates on each use.
* **Mongo backend** (`storage/mongo_store.py`). Collection `sankey_studio_graphs` in the database
  named by `AppSettings.storage_database` (never `admin`, `local` or `config`). The connection needs
  write permission. Updates use `find_one_and_update` filtered on `{_id, revision}`. User text can be
  a document key (node and category names, Mongo operators in a filter), so every write goes through
  `encode_mongo_doc` (such dicts become `[[key, value], ...]` lists and filters or pipelines become
  JSON strings) and every read through `decode_mongo_doc`; `find_unsafe_key` runs before each write
  and fails closed. This is the only code allowed to write to MongoDB.
* **Settings** (`storage/settings_store.py`). `<data_dir>/settings.json` is written atomically with
  mode 0600 inside a data directory created with mode 0700; a corrupt file is moved aside as
  `.corrupt-<n>` (still 0600) and a `SettingsError` is raised. The load is cached by mtime. A missing
  file yields defaults plus a `default` connection seeded from `SANKEY_MONGO_URI`.
* **Services.** `Services.graphs()` returns one cached repository per (backend, connection, database,
  resolved graphs directory), so locks are shared by every request. `update_settings(new, migrate=)`
  validates, pings the destination, optionally copies graphs (`CopyReport`: copied, skipped,
  unreadable), then persists; the source store is never deleted and a failure leaves the old settings.
* **Bundles and migration** (`storage/bundle.py`, `storage/migrate.py`). A bundle is
  `{"format": "sankey-studio/graphs", "version": 1, "graphs": [...]}`, at most 1000 graphs, every
  graph validated, with a per-graph error list (capped at 50). Import modes are `new_ids` and
  `keep_ids`.

## Rendering and export

* **Figures are plain dicts**, built by hand, with explicit colours, fonts and hover styling so the
  browser and the kaleido export look identical. `render/sankey.py`, `render/donut.py`,
  `render/legend.py`, `render/colors.py` and `render/palette.py` do not import plotly. Only
  `render/export/` and the static route import it.
* **No endpoint accepts figure JSON.** A figure with `layout.images[].source` would make Chrome fetch
  arbitrary URLs, so export takes only a saved id or a `GraphDraft`.
* **Labels.** Plotly renders pseudo-HTML, so every user string that reaches a label, title, legend,
  annotation or `customdata` goes through `escape_label` (`&`, `<`, `>` are escaped, unseen
  control and bidi characters are stripped). User text never enters a `hovertemplate`.
* **Drawing cap.** `AppSettings.max_drawn_links` (default 3000) limits the links drawn; the figure
  carries a "Showing N of M links" note and the bundle repeats it in `warnings`.
* **Legend in the figure.** The Sankey legend (category and layer colour modes) is drawn as
  zero-point scatter traces inside the figure, so SVG, PNG and HTML exports contain it. The donut uses
  its native legend.
* **Donut folding.** One function (`donut_fold.fold_totals`) feeds both the figure and the category
  table. The top `max_slices` categories that have a hue are kept; everything else folds into one
  `Other` slice (pattern fill, always last); `Uncategorized` is a solid neutral slice right before it.
* **Palette.** Eight categorical hues, an ordinal blue ramp for the `layer` mode, and neutral tokens
  for `Uncategorized` and `Other`; values live in `render/palette.py`.
* **Images** (`render/export/images.py`). `resolve_image` is pure: width and height clamp to 200..4000,
  scale to 1..4, `width * height * scale**2 <= 36,000,000`, at most 5000 links and 2000 nodes
  (`ExportTooLargeError` otherwise). Exports run one at a time behind a bounded semaphore with a 2 s
  wait (`ExportBusyError`), and a 30 s kaleido timeout (`ExportTimeoutError`). MathJax is off, so an
  export never touches the network. `_render_image` is the only function that calls kaleido and is the
  seam tests replace.
* **Textual exports.** `export_html` builds its own page around `plotly.io.to_html(validate=False)`
  with an escaped title; the CSV export neutralises spreadsheet formula cells (OWASP guard) on every
  text cell.
* **File names.** Sankey `<name>.<ext>`, donut `<name>-donut.<ext>`, an untitled draft is `graph` and
  `graph-donut`; long names are cut to 74 characters before `-donut`. Downloads carry a sanitised
  ASCII `filename` plus RFC 5987 `filename*`.

## Security design

There is no login, so the app defends itself in every layer.

* **Binding.** The default bind is `127.0.0.1`. A non-loopback host needs `remote_mode`
  (`--allow-remote`); `BootstrapConfig` enforces it, not only the CLI. Remote mode prints a loud
  "NO AUTHENTICATION" banner with the bound address, auto-allows only the bound address as a `Host`
  value (never `*` unless the operator sets it) and is read-only for every persisting endpoint
  unless `--allow-remote-writes` is also given.
* **Host check.** Trusted-host middleware with `allowed_hosts` defeats DNS rebinding. It is registered
  last so it also covers `/static` and error responses.
* **CSRF.** One pure ASGI middleware on POST, PUT, PATCH and DELETE. A request is allowed iff
  `Sec-Fetch-Site` is `same-origin` or `none`, or `Origin` is present and equals the request's own
  scheme, host and port (the host must be in `allowed_hosts`). With neither header the request is
  treated as a non-browser client and is allowed only with `Content-Type: application/json`, so
  uploads need a same-origin signal. `Origin: null` and other ports or schemes are refused with 403
  `forbidden`. The middleware also enforces content types (415) and rejects cross-site GETs under
  `/api`. There are no CORS headers.
* **Headers.** `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'
  'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none';
  base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  same-origin`, `Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store` on API
  responses and on every HTML page. Downloads add `Content-Disposition: attachment` and
  `Content-Security-Policy: sandbox`.
* **Request bodies.** A pure ASGI limiter counts bytes while streaming and never trusts
  `Content-Length`: JSON routes 8 MiB, graph import 16 MiB, upload `max_upload_mb` plus 1 MiB. List
  parameters are bounded (`ids` at most 12 for compare and 200 for export).
* **Files.** Source files are confined to the managed sources directory, which must not equal or
  contain the data directory, `graphs/` or `settings.json`. Access is fd-based with `O_NOFOLLOW`, a
  regular-file check after open and a casefolded extension allow-list (`.csv .tsv .txt .json .ndjson
  .sankey`); uploads use `O_EXCL`, a streamed size cap and sanitised names (NFC, no control or bidi
  characters, no leading dots, basename only, at most 255 bytes).
* **Mongo.** Reads go through `mongo_safety`: a recursive pipeline-stage allow-list, name validators,
  `admin`, `local`, `config` and `system.*` never readable, and a URI check that refuses options which
  read local files, load code or weaken TLS (`tlsCAFile`, `tlsCertificateKeyFile`, `tlsInsecure`,
  proxy options, `authMechanismProperties`, control characters, and any `authMechanism` other than
  DEFAULT, SCRAM-SHA-1 and SCRAM-SHA-256). Requests are bounded per connection (four concurrent
  slots) and have timeouts. Source and inspect code is read-only, which a Semgrep rule enforces.
* **Secrets.** URIs never appear in logs, errors, API output or exports. The API returns
  `uri_masked` and `has_secret` and never a field named `uri`. A masked placeholder can never
  overwrite a stored secret. Driver exception text is never forwarded, only the connection name and
  the exception class. The CLI prints validation problems without their input.
* **Output encoding.** Jinja autoescape is on and page data reaches the browser only through a
  `<script type="application/json">` block. The frontend never uses `innerHTML` and friends.
* **Exports.** Pixel, link and node caps, one export at a time, MathJax off, sanitised file names and
  sandboxed downloads.

## Cross-cutting rules

* Python 3.14. PEP 758 syntax (`except A, B:` without parentheses) is in use and is what `ruff format`
  writes.
* Full type annotations (`mypy --strict`), pydantic v2 models and `from __future__ import annotations`.
  `web/**` keeps runtime-evaluated annotations because FastAPI resolves them at runtime.
* A function takes at most 4 parameters. Related options travel in a small frozen dataclass
  (domain code) or a pydantic model with `extra="forbid"` (web query and form models); FastAPI routes
  take path parameters, one query model, the body and a `Services` dependency.
* Domain errors live in `errors.py` with unique stable codes and are mapped to the JSON error envelope
  by `web/errors.py`. Messages never contain secrets or URIs.
* Seams keep Chrome, the clock, the real server and Mongo out of unit tests: `_render_image`,
  `cli._run_server`, the `ResultCache` clock and `MongoClients(factory=...)`.
