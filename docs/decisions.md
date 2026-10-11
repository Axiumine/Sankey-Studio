# Decisions

Architecture decision records: the choices that shape Sankey Studio, with the reason for each. They
are accepted and in force; to change one, add a new record that supersedes it. Related:
[architecture.md](architecture.md), [quality.md](quality.md), [api.md](api.md), [ui.md](ui.md).

Non-negotiable product requirements that no decision may trade away:

* No login gate.
* Categorising entries is optional everywhere: a graph with zero categories behaves exactly like a
  plain Sankey, every category field is nullable and the donut appears only when categories exist.
* A donut chart, and SVG and PNG export of both charts.
* Sources are text files and MongoDB (plus a manual table); a web UI for settings, saved graphs and
  drawing a new one.
* ruff, mypy, pytest and memray in the toolchain.

Contents

| ID | Title |
|---|---|
| [ADR-01](#adr-01-storage-protocol-and-graph-ids) | Storage protocol and graph ids |
| [ADR-02](#adr-02-text-source-fields-are-not-stripped) | Text source fields are not stripped |
| [ADR-03](#adr-03-category-tolerance-everywhere) | Category tolerance everywhere |
| [ADR-04](#adr-04-secrets-never-leave-the-settings-store) | Secrets never leave the settings store |
| [ADR-05](#adr-05-build-order-keeps-topology-category-agnostic) | Build order keeps topology category-agnostic |
| [ADR-06](#adr-06-one-representation-of-no-category) | One representation of no category |
| [ADR-07](#adr-07-category-identity-and-reserved-names) | Category identity and reserved names |
| [ADR-08](#adr-08-null-entry-category-means-force-uncategorised) | Null entry category means force uncategorised |
| [ADR-09](#adr-09-entries-are-a-preview-and-a-paged-endpoint) | Entries are a preview and a paged endpoint |
| [ADR-10](#adr-10-colour-follows-the-entity) | Colour follows the entity |
| [ADR-11](#adr-11-rule-matching-per-distinct-name) | Rule matching per distinct name |
| [ADR-12](#adr-12-persisted-shape-ignores-unknown-fields) | Persisted shape ignores unknown fields |
| [ADR-13](#adr-13-the-sources-directory-is-bootstrap-only) | The sources directory is bootstrap-only |
| [ADR-14](#adr-14-csrf-rule-without-tokens) | CSRF rule without tokens |
| [ADR-15](#adr-15-uri-masking-fails-closed) | URI masking fails closed |
| [ADR-16](#adr-16-mongo-access-is-read-only-and-allow-listed) | Mongo access is read-only and allow-listed |
| [ADR-17](#adr-17-remote-mode-is-read-only-by-default) | Remote mode is read-only by default |
| [ADR-18](#adr-18-hardening-of-files-settings-and-exports) | Hardening of files, settings and exports |
| [ADR-19](#adr-19-test-tooling-and-lint-configuration) | Test tooling and lint configuration |
| [ADR-20](#adr-20-figures-are-plain-dicts) | Figures are plain dicts |
| [ADR-21](#adr-21-aggregation-keys-and-memory-tests) | Aggregation keys and memory tests |
| [ADR-22](#adr-22-the-drawing-cap) | The drawing cap |
| [ADR-23](#adr-23-the-legend-lives-inside-the-figure) | The legend lives inside the figure |
| [ADR-24](#adr-24-palette-patterns-and-streaming-uploads) | Palette, patterns and streaming uploads |
| [ADR-25](#adr-25-test-fixtures-and-directories) | Test fixtures and directories |
| [ADR-26](#adr-26-html-error-pages-for-browser-navigations) | HTML error pages for browser navigations |
| [ADR-27](#adr-27-compare-is-tolerant-of-unknown-ids) | Compare is tolerant of unknown ids |
| [ADR-28](#adr-28-html-pages-are-not-cached) | HTML pages are not cached |
| [ADR-29](#adr-29-export-file-names) | Export file names |
| [ADR-30](#adr-30-label-hygiene) | Label hygiene |
| [ADR-31](#adr-31-untitled-graphs) | Untitled graphs |
| [ADR-32](#adr-32-settings-writes-are-serialised-on-the-client) | Settings writes are serialised on the client |
| [ADR-33](#adr-33-toast-placement) | Toast placement |

## ADR-01 Storage protocol and graph ids

**Decision.** `GraphRepository` has `put(graph, *, overwrite=False)` and `iter_definitions()` besides
the CRUD methods. Graph ids match `^[0-9a-f]{32}$` on `GraphDefinition.id` and `GraphSummary.id`. Lists
are ordered by `(updated_at desc, id)`. `Services.graphs()` returns one cached repository per
(backend, connection, database, graphs directory) so locks are shared.

**Why.** Migration between backends and bundle import need to store a graph verbatim. Ids are used as
file names and query keys, so they are validated before any use. A cached instance per target keeps
one lock per directory.

## ADR-02 Text source fields are not stripped

**Decision.** `TextSource.delimiter` and `content` are not whitespace-stripped (field-level
`StringConstraints(strip_whitespace=False)`). `encoding` must be a canonical Python text codec
(`codecs.lookup`); codecs such as zlib or base64 are refused.

**Why.** A tab or space delimiter and a leading tab in pasted content are meaningful. A non-text
codec would turn a decode step into a decompression bomb.

## ADR-03 Category tolerance everywhere

**Decision.** A missing, empty, non-scalar or over-long category value becomes `None` in every source,
the row is kept, and at most one aggregated warning is emitted per load. One implementation
(`CategoryCleaner`) serves all sources. `TextSource.detect_category` switches off the "category"
header auto-detection. A named `category_column` absent from the header is a `SourceError`.

**Why.** Categories are optional, so a data quirk in an optional field must never drop a row. A
column the user named explicitly is different: a typo should fail loudly.

## ADR-04 Secrets never leave the settings store

**Decision.** `AppSettings` never serialises real URIs by accident: `MongoConnection.uri` is a
`SecretStr` and the masked placeholder is rejected when loading. Only
`storage.settings_store.dump_settings` and `load_settings` round-trip real values. The API takes
`MongoConnectionIn(name, uri | None, previous_name, default_database)` and returns
`{name, uri_masked, has_secret, default_database}` with no field called `uri`; one merge function keeps
the stored secret when the incoming URI is absent, empty, masked or equal to the mask of the stored
one. The 422 handler strips `input` and `ctx`. `settings.json` and its `.corrupt-<n>` copies are
created with mode 0600.

**Why.** A Mongo URI carries credentials. The UI must be able to edit a connection without ever
seeing, storing or echoing its password.

## ADR-05 Build order keeps topology category-agnostic

**Decision.** `build_graph` merges and hides nodes, aggregates to (source, target) pair totals,
applies `min_link_value` and `top_links` on the pair totals, handles cycles on pairs, computes layers
and node sums from the pair totals, and only then splits surviving pairs into parallel links per
category.

**Why.** Toggling categories must never change which nodes or flows exist or how they are laid out.

## ADR-06 One representation of no category

**Decision.** A link without a category has `link_category == -1`, always. `SankeyGraph.categories`
holds only real categories, in first-appearance order. `Uncategorized` is a render-time label for the
-1 bucket and `Other` is the donut fold bucket; neither is ever in `categories`. The donut is offered
iff `len(categories) > 0`.

**Why.** A single sentinel avoids parallel representations that drift apart. Evaluating "has
categories" on the final links means a filter can never leave an empty donut tab.

## ADR-07 Category identity and reserved names

**Decision.** A category name is normalised to NFC, trimmed and whitespace-collapsed; identity is
case-insensitive and the display spelling is the first one seen. `uncategorized` and `other`
(casefolded) are reserved: user-authored specs reject them, data sources turn them into `None` with an
aggregated warning.

**Why.** Users type `Food`, `food` and `FOOD`; they mean one category. The renderer needs two names
for its own buckets without collisions.

## ADR-08 Null entry category means force uncategorised

**Decision.** `EntryCategory.category` is `str | None`, and `None` means "force uncategorised".

**Why.** It lets the user clear a category that came from the data or a rule without editing the source.

## ADR-09 Entries are a preview and a paged endpoint

**Decision.** `RenderBundle.entries` is a capped preview (default 2000, plus `entries_total`). The
categorising table pages through `POST /api/v1/entries?offset=&limit=&q=`, whose body is a draft. The
UI categorises "all entries matching a filter" by generating a glob `category_rules` entry instead of
thousands of per-entry rows, and tells the user to use rules when `entry_categories` would pass
20,000 pairs.

**Why.** A graph can have 100k pairs; shipping and editing them one by one does not scale.

## ADR-10 Colour follows the entity

**Decision.** Colour slots follow first appearance in the unfiltered data. Categories in slots 0 to 7
get a palette hue; the donut folds every category outside the top `max_slices` among those with a hue
into `Other`. Node colours in `node` mode come from a stable name-to-slot map built from the
unfiltered order (`SankeyGraph.node_color_slot`). The compare view builds one category map from the
union of categories.

**Why.** Filters, basis and top-N toggles must not repaint surviving entities, and one category must
have one hue across all compared cards.

## ADR-11 Rule matching per distinct name

**Decision.** Category rules are glob patterns matched with `fnmatch.fnmatchcase` on casefolded text,
once per distinct node name rather than per raw link. A work guard (`check_rule_work`) raises
`GraphTooLargeError` before matching when distinct names times rules exceed 20,000,000.

**Why.** It avoids both quadratic cost on large inputs and regex denial of service.

## ADR-12 Persisted shape ignores unknown fields

**Decision.** `GraphDefinition` (the persisted shape, never a request body) ignores unknown top-level
fields and carries `schema_version`. Request models forbid unknown fields.

**Why.** Stored documents can gain fields and be upgraded by `schema_version`, while a client cannot
smuggle fields through a request body.

## ADR-13 The sources directory is bootstrap-only

**Decision.** `sources_dir` is not an `AppSettings` field. It is `BootstrapConfig.sources_dir`
(`--sources-dir`, `SANKEY_SOURCES_DIR`), defaults to `<data_dir>/sources`, and the settings page shows
it read-only.

**Why.** A web-writable file root would be arbitrary file read and write.

## ADR-14 CSRF rule without tokens

**Decision.** Unsafe methods are allowed iff `Sec-Fetch-Site` is `same-origin` or `none`, or `Origin`
is present and equals the request's own scheme, host and port (host in `allowed_hosts`). With neither
header the request is a non-browser client and is allowed only with `Content-Type: application/json`.
`Origin: null` is refused. Uploads therefore need a same-origin signal. `Referrer-Policy: same-origin`
is set and the UI never submits HTML forms.

**Why.** There is no session to hang a token on. The rule blocks cross-site browsers (which always
send one of the headers) while keeping curl and scripts usable for JSON.

## ADR-15 URI masking fails closed

**Decision.** `util.mask_uri` masks every query value whose key looks secret, the whole
`authMechanismProperties` value, user info without a colon (a token in the user name) and any odd or
percent-encoded form; an unparseable URI is fully masked. Every regex ends in `\Z`.

**Why.** A mask that misses one shape leaks a password into logs or the UI.

## ADR-16 Mongo access is read-only and allow-listed

**Decision.** `mongo_safety` applies a recursive stage allow-list (including inside `$facet`,
`$lookup.pipeline` and `$unionWith.pipeline`). It refuses every stage outside the allow-list (so
`$graphLookup`, `$out` and `$merge`) and the code operators `$where`, `$function` and `$accumulator`.
It validates database, collection and namespace names everywhere (settings, inspect and source
routes) and refuses reads of `admin`, `local`, `config` and `system.*`. `MongoConnection` rejects URI
options that read local files, load code or weaken TLS. There is deliberately no opt-in for OIDC, AWS,
GSSAPI or X.509 authentication.

**Why.** The app executes user-supplied filters and pipelines against a database it does not own.

## ADR-17 Remote mode is read-only by default

**Decision.** `--allow-remote` accepts a non-loopback bind and prints a loud banner; it also makes
every persisting endpoint answer 403 `read_only_mode` unless `--allow-remote-writes` is given. The
flags live in `BootstrapConfig` (`remote_mode`, `remote_writes`). `GET /settings` hides connection
hosts and user names in this mode. Pure computations (preview, entries, export, detect) stay available.

**Why.** Without authentication, the safe default for a reachable server is read-only. The rule
covers graph writes as well as settings, because a saved graph can persist a Mongo pipeline.

## ADR-18 Hardening of files, settings and exports

**Decision.** Settings are written atomically with restrictive modes. File sources use fd-based
opens with `O_NOFOLLOW` and a regular-file check, uploads use `O_EXCL`. Every user string in a
Plotly label is escaped, including the HTML export. Image exports have pixel caps, a one-at-a-time
semaphore and a timeout. Request bodies have per-route caps. The Mongo client is constructed outside
the registry lock. `Content-Disposition` carries a sanitised ASCII name plus `filename*`.

**Why.** Each item closes a concrete attack or failure mode of a login-less local server: symlink
swaps, pseudo-HTML links in SVG, export denial of service and header injection.

## ADR-19 Test tooling and lint configuration

**Decision.** `httpx2` is a dev dependency next to `httpx` (Starlette 1.x `TestClient` prefers it and
warns at import otherwise), and the suite runs with `filterwarnings = error` and no ignores. Ruff
relaxes only the type-checking import rules and unused-argument checks under `web/**`, because
FastAPI resolves annotations at runtime.

**Why.** Warnings stay errors; the few justified relaxations are explicit.

## ADR-20 Figures are plain dicts

**Decision.** Figures are built as plain dicts with explicit layout (no default template), validated
with `go.Figure(d)` only in tests. Kaleido runs with MathJax disabled and never touches the network.
All user strings go through one `escape_label` helper.

**Why.** A default template adds kilobytes per figure and differs between browser and export;
MathJax would be fetched from a CDN on every export.

## ADR-21 Aggregation keys and memory tests

**Decision.** Aggregation keys are built from Python ints after interning (no fixed-width packing that
can overflow). Memory-budget tests build their input in fixtures, because pytest-memray measures only
the test body, and `scripts/profile_memory.py` measures the whole pipeline.

**Why.** Overflow would silently merge distinct pairs, and a budget test that includes setup measures
the wrong thing.

## ADR-22 The drawing cap

**Decision.** `AppSettings.max_drawn_links` (default 3000, 50 to 20000) limits the links the Sankey
draws: the top N by value, with a visible in-figure note and a bundle warning ("Showing N of M links").

**Why.** A Sankey with tens of thousands of links is unreadable and slow; the user must be told what
was left out.

## ADR-23 The legend lives inside the figure

**Decision.** The Sankey legend for the `category` and `layer` colour modes is drawn inside the
figure as annotations and legend traces. The donut uses the native legend.

**Why.** Exports (SVG, PNG, HTML) must contain the legend.

## ADR-24 Palette, patterns and streaming uploads

**Decision.** The ordinal ramp for the `layer` mode is validated. `Other` gets a pattern fill so it
differs from the solid neutral `Uncategorized`. The upload API takes a stream, never `bytes`, and
enforces its size cap while streaming. Wrappers around plotly's untyped returns are typed.

**Why.** Two neutral slices must stay distinguishable when adjacent; large uploads must not be read
into memory.

## ADR-25 Test fixtures and directories

**Decision.** Shared `SourceContext` builder fixtures live in `tests/conftest.py`. Each area owns a
test sub-directory (`tests/sources`, `tests/storage`, `tests/render`, `tests/web`) and may add a
`conftest.py` only there. `sources/__init__.py` (`open_source`) is a thin dispatcher.

**Why.** It keeps fixtures discoverable and test files within the code caps.

## ADR-26 HTML error pages for browser navigations

**Decision.** A browser navigation is a `GET` with `Accept` containing `text/html` on a path outside
`/api/` and `/static/`. For it, every error answers the app-shell page `error.html` with the status of
the error and `Cache-Control: no-store`, never the JSON envelope: an unknown URL, a gone or malformed
`/graphs/{id}[/edit]` and an invalid compare query are the 404 not-found pages; an unreachable graph
store (503 `storage_error`) is "Graph database unavailable" (MongoDB backend) or "Graphs folder
unavailable" (file backend); any other domain or HTTP error and every unexpected 500 is "Something
went wrong". The body never echoes request text or error text. "Reload" is a plain `href=""` link (same
path and query, no script). Every other client keeps the JSON error envelope. The page boot context
is `{page: "notfound", kind: "page" | "graph"}` for the 404 pages and
`{page: "error", kind: "database" | "folder" | "server"}` for the others. If the error page cannot be
rendered, the unexpected-error handler falls back to the envelope.

**Why.** People who paste a stale link, or open the app while MongoDB is down, get a real page and a
way out; API clients keep a machine-readable error.

## ADR-27 Compare is tolerant of unknown ids

**Decision.** `/compare` and `/compare?ids=` are 200 (empty state). Unknown ids are 200 with `ids`
(all, in order, deduplicated, at most 12), `graphs` (existing summaries) and `missing`. The client draws
"This graph is gone" cards from `missing` without probing.

**Why.** A shared compare link should degrade per card instead of failing as a whole.

## ADR-28 HTML pages are not cached

**Decision.** Every HTML page, including the not-found page, carries `Cache-Control: no-store`. Pages
are therefore not back/forward-cache eligible; Back and Forward re-request and re-render. The
`pageshow persisted` handlers stay as a safety net.

**Why.** Back and Forward must never show a page that was rendered before the graph changed or went away.

## ADR-29 Export file names

**Decision.** The Sankey is `<name>.<ext>`, the donut `<name>-donut.<ext>`, an untitled draft is
`graph` and `graph-donut`. Names over 80 characters are cut to 74 before `-donut`. Server and client
agree; the client never doubles the suffix and strips bidi characters.

**Why.** The same export must get the same name from the server and from the browser fallback.

## ADR-30 Label hygiene

**Decision.** `render/text.py::strip_unseen` (C0, DEL, C1 and bidi embeddings, overrides and isolates)
runs inside `escape_label`. `<`, `>` and `&` are escaped; quotes are not (Plotly does not decode
`&quot;`). `strip_unseen` returns the same string object when nothing is removed.

**Why.** No figure string may hold an unseen character. The identity guarantee matters for memory:
copying every label made `build_figure` for 20k links exceed its budget.

## ADR-31 Untitled graphs

**Decision.** A name with no visible character (control or bidi only) is "Untitled graph" on every
page, including the editor heading, server-rendered and client-rendered alike.

**Why.** An invisible name would produce an empty heading and an empty link.

## ADR-32 Settings writes are serialised on the client

**Decision.** All settings writes go through one queue on the client. The header theme switch, the
theme cards and "Save settings" are serialised, and each re-reads the stored settings before it
writes. Connection probes are abortable and abort when their row is edited or deleted.

**Why.** Concurrent read-modify-write cycles could restore an older value.

## ADR-33 Toast placement

**Decision.** Toasts sit bottom-left on wide screens and along the bottom on phones, lifted above a
docked save bar. Showing a toast scrolls the page so the focused control clears the stack. The padding
that reserves toast space must not transition: with reduced motion a 0.01 ms transition delays the
padding by a frame and the scroll falls short. A test pins this.

**Why.** Toasts must never cover the control a user is working on.
