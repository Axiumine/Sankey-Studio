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
| [ADR-34](#adr-34-edits-are-written-back-to-the-data-when-the-person-agrees) | Edits are written back to the data when the person agrees |
| [ADR-35](#adr-35-collections-are-a-tree-stored-beside-the-graphs) | Collections are a tree stored beside the graphs |
| [ADR-36](#adr-36-editor-chrome) | Editor chrome |
| [ADR-37](#adr-37-git-hooks-are-the-one-place-the-checks-run) | Git hooks are the one place the checks run |
| [ADR-38](#adr-38-mongodb-runs-on-one-server-and-on-a-cluster) | MongoDB runs on one server and on a cluster |
| [ADR-39](#adr-39-releases-are-published-to-pypi-from-a-tag) | Releases are published to PyPI from a tag |
| [ADR-40](#adr-40-a-weekly-trivy-scan-and-the-openssf-scorecard-run-in-github-actions) | A weekly Trivy scan and the OpenSSF Scorecard run in GitHub Actions |
| [ADR-41](#adr-41-requirementstxt-is-a-generated-copy-of-uvlock-for-githubs-dependency-graph) | requirements.txt is a generated copy of uv.lock for GitHub's dependency graph (superseded) |
| [ADR-42](#adr-42-uvlock-is-the-one-source-of-the-dependency-list) | uv.lock is the one source of the dependency list |
| [ADR-43](#adr-43-codeql-a-ruleset-on-main-and-signed-release-assets) | CodeQL, a ruleset on main and signed release assets |
| [ADR-44](#adr-44-a-hosted-ci-job-runs-the-unit-tests) | A hosted CI job runs the unit tests |
| [ADR-45](#adr-45-mask_uri-shows-option-values-from-an-allow-list) | mask_uri shows option values from an allow-list |
| [ADR-46](#adr-46-connection-strings-live-in-credentialsjson) | Connection strings live in credentials.json |
| [ADR-47](#adr-47-fuzzing-runs-in-clusterfuzzlite-from-testsfuzz) | Fuzzing runs in ClusterFuzzLite from tests/fuzz |

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

**Addendum (headerless data).** Without a header the category column defaults to the fourth column
(index 3), as source, target and value default to columns 1 to 3. The default applies only when
`detect_category` is true, no `category_column` is given, and column 4 is not already read by an
explicit source, target or value pick. A row with fewer than four cells stays uncategorised and is
kept. An unusable cell (over 100 characters, reserved name, control characters) is dropped with the
existing aggregated warning. The rule covers csv and tsv; SankeyMATIC and JSON carry their category
explicitly (`| category`, a `category` key). The browser mirrors it in `editor/source/columns.js`
(the select reads "Auto (col 4)"), and a test compares that table with the Python one.

*Why.* `Salary,Budget,3000,Income` is the same data with or without a header row; the old rule tied
category detection to a header the person did not have, so a pasted headerless table lost every
category except the one typed afterwards. *Cost.* Headerless data whose fourth column is not a
category (a note, a date) now yields categories; "This data has no category column"
(`detect_category=false`) turns that off.

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

**Clarified by [ADR-46](#adr-46-connection-strings-live-in-credentialsjson).** The real values are in
`credentials.json`, and `settings.json` holds none.

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

**Addendum (write-back, [ADR-34](#adr-34-edits-are-written-back-to-the-data-when-the-person-agrees)).**
An existing allowed file can be replaced atomically when the graph owner agreed to write an edit
back (`sources/files/store.py edit_file`): the same fd-based checks as `located` and `open_leaf`
(extension allow-list, `O_NOFOLLOW` per component, a regular file that must already exist), a stat
stamp compared before the replace, the size cap of `max_upload_mb`, and a part file created with
`O_EXCL`. Uploads are not the only writer of that directory any more; the directory is still
bootstrap-only and nothing new can be created outside an upload.

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

**Clarified by [ADR-45](#adr-45-mask_uri-shows-option-values-from-an-allow-list).** The sentence about keys that
"look secret" is read as the allow-list described there.

## ADR-16 Mongo access is read-only and allow-listed

**Decision.** `mongo_safety` applies a recursive stage allow-list (including inside `$facet`,
`$lookup.pipeline` and `$unionWith.pipeline`). It refuses every stage outside the allow-list (so
`$graphLookup`, `$out` and `$merge`) and the code operators `$where`, `$function` and `$accumulator`.
It validates database, collection and namespace names everywhere (settings, inspect and source
routes) and refuses reads of `admin`, `local`, `config` and `system.*`. `MongoConnection` rejects URI
options that read local files, load code or weaken TLS. There is deliberately no opt-in for OIDC, AWS,
GSSAPI or X.509 authentication.

**Why.** The app executes user-supplied filters and pipelines against a database it does not own.

**Addendum (two library collections and opt-in source write-back).** The title says how a source is
read, and that is unchanged: every filter, pipeline, name and URI still goes through `mongo_safety`
and `admin`, `local`, `config` and `system.*` are never readable. Writes now exist in exactly two
places, both under `storage/` and both listed in the Semgrep waivers: the library store (graphs in
`sankey_studio_graphs`, collections in `sankey_studio_collections`, [ADR-35](#adr-35-collections-are-a-tree-stored-beside-the-graphs))
and the opt-in source write-back of [ADR-34](#adr-34-edits-are-written-back-to-the-data-when-the-person-agrees)
(`storage/mongo_source_writes.py`), which never touches `admin`, `local`, `config`, `system.*` or a
collection whose name starts with `sankey_studio_`.

## ADR-17 Remote mode is read-only by default

**Decision.** `--allow-remote` accepts a non-loopback bind and prints a loud banner; it also makes
every persisting endpoint answer 403 `read_only_mode` unless `--allow-remote-writes` is given. The
flags live in `BootstrapConfig` (`remote_mode`, `remote_writes`). `GET /settings` hides connection
hosts and user names in this mode. Pure computations (preview, entries, export, detect) stay available.

**Why.** Without authentication, the safe default for a reachable server is read-only. The rule
covers graph writes as well as settings, because a saved graph can persist a Mongo pipeline.

**Addendum (source write-back).** `--allow-source-writes` (`SANKEY_SOURCE_WRITES`, `BootstrapConfig.source_writes`)
is a second bootstrap-only flag and needs `--allow-remote-writes`. In remote mode a read-only server
refuses file write-back (it follows `privileged_writes_allowed`, because a remote writer can already
replace a file through the upload route), and writing an edit back to a MongoDB source needs this
flag besides `--allow-remote-writes`: `--allow-remote-writes` alone does NOT unlock it. On loopback
both are always allowed. `POST /edits/plan` stays available in read-only mode (it writes nothing);
`POST /edits/write` and the collection writes (`POST`, `PUT` and `DELETE /folders*`,
`POST /graphs/move`) answer 403 `read_only_mode` before the body is decoded
([ADR-34](#adr-34-edits-are-written-back-to-the-data-when-the-person-agrees),
[ADR-35](#adr-35-collections-are-a-tree-stored-beside-the-graphs)).

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

**Amendment.** The viewer and the editor list the same entries as HTML under the chart, so they draw the
figure without the legend row (`withoutLegend` in `core/chart.js`); the figure, the exports and the
compare cards keep it.

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

## ADR-34 Edits are written back to the data when the person agrees

**Decision.** An edit of the entries (a category, an added entry, a node order) is routed by
`POST /edits/plan` and written by `POST /edits/write` (package `edits/`, above `pipeline` and below
`web`). One table decides where it goes:

| Source | Where | Consent |
|---|---|---|
| manual links, pasted text (`origin=inline`) | the draft (`source.links`, `source.content`) | never |
| a managed text file (`origin=file`) | the file, replaced atomically | per graph and target |
| MongoDB `find` (an added entry needs a plain equality filter) | the documents of the collection | per graph and target |
| anything else, or an edit that is refused | the graph: `transform.entry_categories`, `transform.extra_links`, `style.node_order` | never |

*Consent and its key.* A file or a collection is written only after the graph owner said yes in the
dialog "Change your data too?". The answer is saved with the graph as `source.write_back =
{mode: "source" | "graph", target}`. `target` is an opaque key that the SERVER builds from resolved
values (`edits/target.py`): `file:<path>`, or `mongo:<connection>/<resolved database>/<collection>#<fp>`
where `fp` is the first 12 hex digits of the SHA-256 of the masked URI, a separator and the default
database (non-secret; the URI never enters the key). The browser never computes a key: it calls
`plan` first, reads `consent` (`ask` or `granted`) and `target_key` from the answer and stores the
key verbatim when the person accepts. A preference counts only while its `target` equals the key of
the current source, so a different file, collection, database or connection, or a connection whose
URI was edited in Settings, asks again with no extra code. `write` re-checks everything: the
effective preference must be `source` (else 422 `source_edit_refused`, reason `no_consent`).
"Keep in this graph" keeps that one edit in the graph and is remembered for the page session and
that key only; "Keep in this graph, don't ask again" saves `mode: "graph"`; Cancel or Esc does
nothing. A bundle import drops `write_back` from every graph (a consent names a file or connection
of the exporting machine).

*Operator gates*, evaluated in `plan` and again in `write` before a source is touched, first match
wins: (1) a file or MongoDB edit on a server that may not write (remote mode without
`--allow-remote-writes`); (2) a MongoDB edit in remote mode without `--allow-source-writes`;
(3) the namespace rules (`check_target`: system databases and `system.*`, and any collection whose
casefolded name starts with `sankey_studio_`, in any database); (4) new text that a spreadsheet could
read as a formula (`util.starts_like_formula`, the predicate of the CSV export guard; numbers are
exempt, pasted and manual text is the person's own data and is not gated; a `set_category` stores only
its category, so only that is checked). `plan` answers `graph`
with the reason; `write` answers 403 `read_only_mode` for 1 and 2 and `graph` for 3 and 4.

*Writers.* The text rewriter (`sources/rewrite/`) keeps every untouched line byte for byte, may
normalise the quoting of a touched csv record, and accepts its output only after the real parser
reads the new text as the old data plus the intended change (a multiset of source, target, value and
category compared; one retry with the format and delimiter pinned; else `cannot_verify` and the edit
stays in the graph). It refuses text over 8 MiB or a rewritten line over 4096 characters, and it
never emits what the encoding of the file cannot hold. JSON arrays are re-formatted (`indent=2`); the consent text says so for
files and a notice says so for pasted JSON. For a file, `write` repeats the dry run under the
directory lock and replaces the file only when the rewrite equals the dry-run text, else 409
`conflict`. For MongoDB, `storage/mongo_source_writes.py` is the only code that calls `update_many`
or `insert_one` on a source collection: one `$set` or `$unset` of one string field, on at most
1,000 documents chosen by `_id` and re-filtered (`{"$and": [{"_id": {"$in": ids}}, filter]}`, so a
document edited meanwhile is not touched), or one `insert_one` of a scalar document; field paths,
values and filters are validated by `mongo_safety.check_write_document`, `check_write_update` and
`check_filter`; the graph cache is cleared after every write; an INFO line names the connection,
database, collection, operation and count, never a value. A driver or OS failure whose result is
unknown is an error (502 `source_write_failed`, 503, 409) and never becomes a graph-only edit, so an
added entry cannot be duplicated by a retry.

*Order.* A node order is always stored in `style.node_order` and drawn by the server with Plotly's
`sort: "input"` (never with node coordinates: Plotly ignores a coordinate of exactly 0 and
re-snaps). Rows of the data follow best effort and only where a write is allowed anyway: pasted text
and manual links, and a file whose preference is `source`; MongoDB never. The guard
`edits/recolour.py` compares the colour slots of the graph before and after: when a reorder would
repaint a node or category that the chart colours by (slots 0 to 7 are hues; pinned colours are
ignored; `layer` and `mono` never repaint), the answer carries `pins` (the light-theme hex of the
colour each moved name had) next to the rewritten rows, and the browser merges them into
`style.node_colors` or `style.category_colors` in the same history step (Undo takes both back). So a
drag updates the data in the default colour mode too. The trade-off: a pinned colour is one fixed hex
in both themes, like any colour the person sets. Only when the pins would not fit in the style (1,000
overrides) are the rows kept and the answer `graph` with reason `would_recolour`. The stored order is
unaffected.

*Visible overlays.* Edits that stay in the graph are listed in the Entries card ("Graph-only edits
(N)", a Remove button on each); a toast alone would hide state that Save persists.

**Why.** Editing a category in the chart while the data says something else leaves the data and the
chart disagreeing, and the person wants the data to be the source of truth. Writing into someone's
file or database is the one place where the app changes data it does not own, so it is opt-in per
target, announced before it happens, bounded (one field, one document or one file, 1,000 documents at
most), checked by the real parser or the database filter, and refused wherever the app cannot be
sure. The key is built by the server because the browser cannot know the default database of a
connection.

**Accepted risk.** There is no login, and the saved preference travels in the request body, so it is
UX consent and not an authorisation boundary. Any caller who can reach the API can `$set` one string
field on documents selected by `field in [names]`, and insert one scalar document, in any non-system,
non-`sankey_studio_` collection that the connection's database user may write (the storage
connection must be writable, so a source that reuses it is writable by construction), and can have
an existing managed text file rewritten. The real controls are the database user's privileges (a
read-only user answers `permission_denied` and the edit stays in the graph), loopback by default, the
Host and CSRF checks, `--allow-remote-writes` for files and also `--allow-source-writes` for MongoDB
in remote mode, the namespace refusals, equality filters for inserted documents (a category update accepts any filter the
read checks allow) and the 1,000-document cap. A
per-connection flag in `settings.json` was rejected: the same unauthenticated caller can edit
settings, so it would not be a boundary, and a flag that defaults to false would make MongoDB
write-back unreachable out of the box.

**Limits (documented, not hidden).**

* `add_entry` on MongoDB counts the documents the source reads and then inserts, which is not atomic:
  in the worst case the new document falls outside the read window and the next plan answers
  `limit_reached`.
* The write is immediate and not part of Save; other graphs that read the same file or collection
  change too; the consent is saved only when the graph is saved (an unsaved graph asks again next time).
* A manual change of the rows does not move the bars while a stored order exists; "Reset order"
  returns to the layout of the data. In the default `node` colour mode a drag pins the colours it
  would have moved. A node renamed in the data jumps to the end of its layer.
* A file write replaces the file: ownership and ACLs are not preserved and a hard link to the file is
  broken. Rewritten files keep short rows short. A rewrite that changes nothing answers `graph` with
  the silent reason `order_in_graph` and the browser keeps its graph-level patch.
* A third Style choice "Same as the data rows" for the order was rejected: the saved explicit order is
  what makes the chart reproducible.

## ADR-35 Collections are a tree stored beside the graphs

**Decision.** Saved graphs can be grouped in a tree of "collections". The identifier noun is `folder`
everywhere in code, URLs, JSON, query parameters, test ids and CSS (the Mongo word `collection`
already means a driver object); the word "collection" appears only in user-visible text and in the
fixed name of the Mongo collection `sankey_studio_collections`.

* *Model.* An adjacency list: one record per collection `{id, name, parent_id, revision, created_at,
  updated_at}`; a graph points at at most one collection with `GraphDefinition.folder_id` (`null` =
  the top level). There is no member list in the collection (unbounded arrays, two-document
  updates). `GraphCreate` and `GraphUpdate` do not carry the field: a graph is placed at creation
  (`POST /graphs?folder=`) and moved only by `POST /graphs/move`, so a stale editor tab can never move
  it back. A move changes neither `revision` nor `updated_at`.
* *Rules*, in one pure module shared by both backends (`storage/folder_tree.py`): sibling names are
  unique after NFC and casefold, names are 1 to 100 characters, at most 8 levels, at most 1,000
  collections, no cycles. Every walk carries a visited set. Deleting a collection re-parents: its
  graphs and sub-collections move up to its parent and nothing is deleted; a name clash at the
  parent refuses the delete (409 `folder_name_taken`).
* *Dangling references are tolerated, not prevented* (there are no cross-document transactions on
  MongoDB and a crash can fall between two files on disk): a graph whose `folder_id` names no
  collection, or a collection whose parent is gone, reads as top level everywhere.
* *Second protocol.* `FolderRepository` (CRUD, `put_folder`, `list_in`, `count_in`, `move_graphs`,
  `ping`) sits beside `GraphRepository`, whose surface only gained `create(data, *, folder_id=None)`.
  `Services.folders()` is cached under the same key as `graphs()`; a frozen `Stores(graphs, folders)`
  pair is what the storage switch handles.
* *File backend.* One `folders.json` per graphs directory (`[0-9a-f]{32}.json` it is not, so the graph
  index ignores it), written atomically with mode 0600 under the lock the graphs already use and cached
  by `(mtime_ns, size, inode)`. A damaged file fails soft on reads (no collections, graphs at the top
  level, one warning in the log) and closed on writes (503 `storage_error`).
* *MongoDB backend.* The collection `sankey_studio_collections` in the storage database, a unique
  `(parent_id, name_key)` index for atomic sibling-name uniqueness (the pure rules run first for a
  friendly error), compare-and-set on `revision` for rename and move, and `$set` of `folder_id` only
  for moving graphs. Deleting moves the graphs up first, then removes the record, then re-parents the
  sub-collections (the record goes before its children because a child may carry the deleted
  collection's name). The storage connection needs write access to both collections.
  `MongoStoreTarget` refuses equal names for the two. All writes live in
  `storage/mongo_folder_store.py` with the Semgrep waiver allowed under `storage/`.
* *Bundles are version 2* (a `folders` list after `graphs`; version 1 is refused on purpose, old saves
  need not work). `new_ids` import gives every collection a new id and reuses a same-named sibling
  (case-insensitive) under the same new parent, so importing the same bundle twice does not double the
  tree; `keep_ids` keeps the ids (a refused collection's graphs and sub-collections move to the nearest stored ancestor too). A collection whose parent is missing counts as top level: renaming it heals the parent, and sibling names are compared by that effective parent. A collection that cannot be stored is a report line
  `collection N: <reason>` (position, never the content) and its graphs land in the nearest stored
  ancestor. The storage switch copies the collections first, parents first, then the graphs.
* *Listing.* `GET /graphs` without `folder` is exactly today's search. `folder=root|<id>` lists one
  level, newest first, and cannot be combined with `q` or `tag` (422): the library search is global by
  design and each result names its collection. The pages `/` and `/graphs/new` take `?folder=`
  leniently (an invalid or unknown value is the top level).
* *Library UI.* Real links (`/?folder=<id>`), so Back, Forward and reload need no routing code; the
  server renders the boot data of the scope; a breadcrumb, the cards of the open level above the
  graphs, dialogs to create, rename, move and delete, "Move" on a graph card and "Move to collection"
  on the selection (cap 12, shared with compare). Moving uses a dialog with a radio tree whose
  impossible places stay visible and say why; the dialog is the accessible baseline. Drag and drop
  (graph cards and collection cards onto collection cards and breadcrumb links) was added on top of
  it as a pointer shortcut, frontend only: `js/library/folder-rules.js` is the one place that decides
  which places are refused, for the dialog and for a drop, and a drop uses the same requests and
  toasts as the dialog.

**Why.** Libraries with dozens of graphs need structure, and a tree with membership on the graph is
the smallest model that both backends can enforce (a unique index on Mongo, one lock on disk) without
transactions. Keeping the rules in one pure module means the two backends cannot drift.

**Accepted risks.** Two racing moves on MongoDB can end in a cycle (readers cut it); a graph moved
into a collection while that collection is being deleted ends up at the top level; a bulk
`put_folder` of a 1,000-collection tree does O(n^2) reads on MongoDB (the cap bounds it).

## ADR-36 Editor chrome

**Decision.** The editor shows a full-width chart row, then Source and Transform side by side from
900 px (stacked below), then Entries and the save bar. What used to share the page moved out of it:

* *Chart settings* (Style and Export) live in a non-modal popover under a gear in the chart header
  (`core/popover.js`; only one popover is open; Escape closes it and returns focus to the gear, a
  press outside or focus leaving closes it without moving focus). A modal would make `#app` inert and
  dim the chart, which kills the live feedback while styling. The chart row is a full-width,
  non-sticky card: while editing Source or Transform it scrolls out of view (the accepted cost of
  the layout request). `ctx.chartTools` is the extension slot of the chart header; "Order nodes" and
  "Reset order" are added before the gear so the gear's popover stays inside a phone window.
* *Name, description and tags* live in a modal "Graph details" dialog opened from a gear that is a
  SIBLING of the page `<h1>` (the heading's text is rewritten by the page). A menu item is a
  decision, not live styling, so the title menu opens modal dialogs. The fields are bound to the
  real store (live, dirty) and "Done" only validates the name, so the leave guard and the dirty flag
  behave as before; there is no Apply or Cancel pair.
* *Change data source* is a guided path beside the inline tab strip, which stays the quick path and
  the contract of the test ids. Choosing the kind that is already in use only goes to the inline tab
  (the source settings are edited inline). Graph-only edits (`entry_categories`, `extra_links`,
  `node_order`) belong to the data, so changing the kind asks whether to keep them; the question is
  one module (`source/overlays.js`) shared by the dialog and the tab strip.
* *The new-graph wizard* is client side: two steps (name, then data source) drawn before the editor
  exists. It never POSTs (so it works on a read-only server), keeps its own store, seeds the editor
  after the dirty tracking started (so typed data is protected by the leave prompt), and its finish
  button reads "Start editing" with "Nothing is saved until you press Save". `source-has-header`
  appears in step 2 because a headerless paste is the case of the ADR-03 addendum. The source tabs are
  one implementation (`source/tab-set.js`) shared with the editor.
* *Paste Clear* is an icon inside the box. It wipes the only copy of the data, so it shows a "Cleared"
  toast with Undo, retired as soon as the box holds anything else or another tab is chosen.
* *Chart events.* A drag is read from Plotly's public `plotly_restyle` (the end-of-drag positions of
  every node; a plain click fires the same event, so a pointer gate is needed). Plotly does not emit
  `plotly_click` while bars are draggable, so a node click is built from pointer events plus the node
  of the last `plotly_hover` and de-duplicated with Plotly's own click. The drawn columns, not the
  server layer, group the order (Plotly's `justify` alignment puts every node without an outgoing link
  in the last column). "Order nodes" is the keyboard and single-pointer twin of the drag (WCAG 2.1.1
  and 2.5.7) and calls the same engine function. A click on a bar opens the same "Add a flow" dialog
  as the Entries card, prefilled; the role of the node comes from the drawn `bundle.nodes`.
* *Tests.* The e2e page objects for the wizard, the menu, the dialogs and the popover probe the DOM
  once and also drive the older editor, so one test ran on both while the chrome landed in waves.

**Why.** The chart is the point of the page: the form fields that are touched once per graph
(details, style) should not compete with it, and the dialogs, popover and wizard are accessible
patterns the app already had (focus trap, Esc, return of focus).

## ADR-37 Git hooks are the one place the checks run

**Decision.** Every quality check runs from a git hook and nowhere else automatically. The hooks
`pre-commit`, `pre-merge-commit` and `pre-push` are three-line shims over `scripts/githook_gate.py`
(standard library only); `commit-msg` is unchanged.

* *Tiers.* A commit and a clean `--no-ff` merge run `fast` (lint, typecheck, caps) on the index
  tree. A push runs the messages of the new commits through `commit-msg`, then `fast`, `cov`,
  `memray` and `e2e`. A push whose REMOTE ref is `refs/heads/main` or `refs/tags/*` also runs
  `security` (semgrep-test, semgrep, trivy), `e2e-mongo`, `e2e-mongo-rs`, `qodana` and `mutation` (`mutate` then
  `mutate-gate` as one check). The `main` tier (push plus security) exists only for
  `make gate-main`. The release tier is bound to every push of `main`, not to a tag convention:
  no tag exists, so a tag-only tier would never fire.
* *Stamps.* A check that passed leaves a stamp keyed on the check and a digest of the tree without
  the files no check reads (Markdown outside `src/`, images under `docs/`, `LICENSE`) in
  `<git-common-dir>/hook-stamps/`, and the next commit or push of that tree skips it, a docs-only
  change included. It is written
  only after every step exited 0, no test was skipped and neither the tree nor
  `git status --porcelain --untracked-files=all` changed during the run. `security` also carries
  the UTC date. Each stamp stores the duration of its steps.
* *Preflight.* A check can name quick probes of the machine (`Check.needs`: Docker answers,
  `QODANA_TOKEN` is set, the replica set answers). They are `make preflight-*` targets, run unstamped
  before the first long check of a run, so a push that cannot pass is refused in seconds and not after
  `cov` and `e2e`.
* *Inline.* `pre-push` runs the missing checks itself, sequentially, in the foreground, and stops at
  the first failure. It does so only on a clean working tree whose HEAD is the pushed commit;
  otherwise it refuses before running anything and says what to do. A retry resumes, because the
  stamps of the finished checks stay.
* *Fail closed.* A skipped test fails a check (only the 8 mongo unit tests may skip in `cov`), so
  the machine is part of the gate: Chrome, `node`, `bash` and Linux `/proc` are prerequisites of
  `cov`; a push that has to run `security` is refused while any `*_OFFLINE` variable is set
  (matched by suffix, so a new switch is caught too); a missing `QODANA_TOKEN` fails `qodana`; a busy
  lock, a malformed ref line and any error refuse. A dry run exits 0 only when nothing would run and
  every new commit message passes `commit-msg`. A check starts only on the state that was verified
  for its tree, and a push job that passed must have left its stamp. The child environment
  loses git's local variables, `PYTEST_ADDOPTS` and `SANKEY_TEST_MONGO_URI`, and `UV_LOCKED=1`.
* *One at a time.* A `flock` on `<git-common-dir>/hook-gate.lock` allows one gate run, and checks run
  sequentially (two e2e runs at once would mean ten Chromes, which break the 15 s and 20 s timeouts).
* *Logic in Python.* The gate is Python with an injectable runner, clock and output, under the code
  caps like every script, so it is unit-tested without running a hook. Signals are handled with
  process groups: a bash `trap` is deferred while a foreground child runs, and `setsid` without
  `-w` returns at once, which would let a hook pass without running anything.
* *Agents.* Agents never run the gates by hand (`CLAUDE.md`); they run only the tests of their own
  change, and push with `run_in_background`.

**Why.** Before this, only the code caps ran in a hook, and `CLAUDE.md` claimed the hooks ran the
full suite. Lint, typecheck, coverage, memory, e2e, the scanners and mutation ran when someone
remembered. Worse, some checks passed without running: the 8 mongo-marked unit tests never ran
(`make cov` skips them without `SANKEY_TEST_MONGO_URI`, and `make e2e-mongo` selected only
`e2e and mongo`); e2e and the image exports skip and exit 0 without Chrome; `mutate-gate` judged
whatever `mutants/` held; `SEMGREP_OFFLINE` and `TRIVY_OFFLINE` silently weakened the scans. The
rule is now one sentence: tests run in the hooks, and a check that did not run is a failure.

* A stamp is keyed on the tree because that is what a check vouches for: a commit-time pass is
  reused at push, amend, rebase and cherry-pick keep their stamps, a `--no-ff` merge of an unmoved
  `main` reuses the branch's, and a failed or dropped push loses nothing that finished.
* `pre-push` runs the checks inline instead of refusing and printing a command: it keeps one rule
  for people and agents, and the stamp lookup is the same code path. The cost is a long hook.
* The scanners' rules and databases change without the tree changing, so the `security` stamp
  expires with the UTC day. `mutation` (about 19 minutes in the last local run, a figure no earlier
  document states) and the `qodana` scan are tree-keyed because they judge the code.
* `qodana` is required for `main` and tags and runs a fresh `make cov` first, because it imports
  `coverage.xml` and only warns when it is missing or stale. It runs before `mutation` so a missing
  token fails before the long mutation run.
* The hooks are client-side only. The hosted CI (ADR-44) runs only lint, types, caps and the unit tests and nothing
  requires it, and `main` requires no check or review (a ruleset blocks only deletion and force-push,
  ADR-43); the hooks stay the one full gate and are a convenience gate that stops mistakes, not a security boundary.

**Accepted risks.** `--no-verify`, `core.hooksPath` overrides and a clone without `make hooks` skip
every hook (the rules for agents forbid them; nothing enforces it). A push gate of 30+ minutes holds
the connection to the remote open, and whether SSH survives that is untested; if it drops, the stamps
are kept and the next push is instant, and `make gate-release` first avoids it. A commit is refused
while a push gate holds the lock. Stamps do not record the environment (Docker images, Chrome,
anything outside `uv.lock`). A gate killed with SIGKILL can leave the project Mongo or child
processes running, free the lock while they run, and leave stale holder text in it (the lock
stays with the gate on purpose: a descendant that outlived a normal run would otherwise keep every
later commit and push waiting); killing only
`git` leaves the gate running to the end, and it still writes its stamps. A partial staging
(`git add -p`) is validated as the working tree, not the index; the commit is unstamped and
`pre-push` checks the committed tree. `git push --dry-run` is recognised from the command lines of
the hook's ancestors (`/proc`); without `/proc` it runs `pre-push` for real. Several runtimes are
unknown until the first real runs, which print and store them.

## ADR-38 MongoDB runs on one server and on a cluster

**Decision.** A connection string may name a standalone server, a replica set, the `mongos` routers
of a sharded cluster or `mongodb+srv://`; the application does not branch on the topology.

* URI options (`replicaSet`, `readPreference`, `w`, `retryWrites`, `authSource`, `tls`...) reach the
  driver unchanged. `default_factory` fixes a few options and ignores the same ones in the string:
  server selection and connect timeouts (`mongo_timeout_ms`, which the Settings page owns), the
  socket timeout (at least 60 s), the pool (8 per host, idle and wait timeouts), `tz_aware` and
  `appName`. `tlsCAFile`, client certificates and non-SCRAM logins stay refused (ADR-16).
* The library stores (`sankey_studio_graphs`, `sankey_studio_collections`) open their database
  through `mongo.primary_database`: they read what they have just written (a save then a load, a
  delete then an import). Source collections keep the URI's read preference: reading from secondaries
  is the point of setting it, and the data may lag by the replication delay.
* Nothing uses sessions or transactions, so a standalone server (no retryable writes, no
  transactions) behaves like a cluster. The multi-document writes are `update_many` calls: the
  write-back and "move graphs" scope them by an `_id` list, the folder re-parent and delete by
  `parent_id` or `folder_id`. The driver does not retry them and they are not atomic across
  documents: after a failover the person is told to try again, and repeating one is safe (a document
  already changed no longer matches the filter). A refused update can leave the documents before it
  changed.
* `mongo_errors` words a failover instead of a bare class name: `NotPrimaryError` ("no primary right
  now"), `AutoReconnect` and `NetworkTimeout` ("interrupted ...; a write in flight may have been
  applied"), `WriteConcernError` and
  `WTimeoutError` ("not confirmed by enough members; it may have been applied"). Messages still carry
  the connection name and the class name only. `ServerSelectionTimeoutError` stays "unreachable".
* "Test connection" of a saved connection pings with `primaryPreferred`, so a replica set electing a
  primary is not reported as down while a secondary answers. Testing a new or edited storage
  connection also creates the indexes on the primary, so it still needs one.
* A refused `update_many` (a validator, a shard key that may not change) is `write_rejected`, like a
  refused insert, instead of a 502.

**Why.** The code already worked on a cluster by the driver's defaults, but nothing proved it and
one defect hid behind it: with `readPreference=secondary*` in the saved URI a bundle import after a
delete read stale folders. The suite `make e2e-mongo-rs` (marker `mongo_rs`, `docs/e2e.md`) now
runs every real-Mongo flow, and the same flows with `readPreference=secondaryPreferred`, against a
replica set you run yourself. The release gate runs it as the `e2e-mongo-rs` check (no Docker: the
cluster is the user's), so a push of `main` or a tag needs that cluster reachable; without its URI
the tests skip and a skip fails the check, like every other skip.

**Accepted risks.** The application never shards its own collections; sharding
`sankey_studio_collections` would break the unique `(parent_id, name_key)` index. `list_databases`
and `list_collection_names` (the pickers) need a primary whatever the preference. A private CA works
only through the system trust store (`SSL_CERT_FILE`, `SSL_CERT_DIR`). No failover is exercised
against a real cluster: the suite never steps a member down.

## ADR-39 Releases are published to PyPI from a tag

**Decision.** A tag `vX.Y.Z` on `main` starts `.github/workflows/release.yml`, which builds the sdist
and the wheel, checks them (`twine check --strict`, the wheel starts), uploads them to TestPyPI and,
after the approval of the `pypi` environment, to PyPI. The upload uses PyPI trusted publishing
(OIDC); the workflow has `id-token: write` only in the two upload jobs and `contents: read` in the
build job, and its actions are pinned to commit SHAs.

* No PyPI token exists anywhere, so there is nothing to leak from the repository, the GitHub
  secrets or this machine. Trusted publishing also attaches Sigstore attestations to the files.
* The workflow runs no tests. The checks stay in the git hooks (ADR-37), which run the full release
  tier before `main` or a tag is pushed; adding CI would duplicate them and was not wanted.
* TestPyPI first, then a manual approval, because a PyPI version can never be uploaded twice.
* `pyproject.toml` limits the sdist to `src/`, the Markdown docs and the policy files, so the tests,
  the agent skills and the scanner config are not published.

**Accepted risks.** The tag is the trigger, so whoever can push a `v*` tag can start a release; the
`pypi` environment's required reviewer is the second lock. The hooks that vouch for the tree are
client-side (ADR-37), so the workflow trusts the tag's commit as the maintainer pushed it. How to
make a release is in [release.md](release.md).

## ADR-40 A weekly Trivy scan and the OpenSSF Scorecard run in GitHub Actions

**Decision.** `.github/workflows/trivy-weekly.yml` runs `scripts/trivy.sh` (the same `trivy.yaml` and
pinned image as `make trivy`) every Monday and on demand. `.github/workflows/scorecard.yml` runs the
OpenSSF Scorecard on a push to `main`, weekly and when branch protection changes, publishes the result
to scorecard.dev (the README badge) and uploads the SARIF report to code scanning.

* The hooks run Trivy only when `main` or a tag is pushed, and when the weekly job was added GitHub's
  dependency graph listed no Python package, so Dependabot saw nothing (it lists them since a Dependabot
  graph job ran on 2026-10-17, see [dependencies.md](dependencies.md)). The weekly job checks the
  dependencies between pushes. A fixed HIGH or CRITICAL finding fails the run, and GitHub e-mails the
  person who last changed the schedule.
* The Scorecard gives an outside, repeatable score of supply-chain practices. It scores what the
  repository does, not whether the software is secure.
* Both jobs are read-only: `permissions: {}` at the top and `contents: read` in the job. The Scorecard
  job adds `actions: read`, `security-events: write` (the SARIF upload) and `id-token: write`
  (publishing the result). Every action is pinned to a commit SHA. Neither job runs the tests or looks at
  commits or pull requests.

**Accepted risks.** GitHub disables scheduled workflows after 60 days without activity in the
repository, so a finished project loses the weekly scan until someone re-enables it or pushes. The
Trivy job has the gate's limits: it leaves out the packages only the `dev` group needs and cannot check
the licences of uv packages. It cannot be run from the maintainer's agents (Docker is used only through
make), so its first run happens on GitHub. The Scorecard will show the gaps as they are: no branch
protection, no pull-request review, tools in `release.yml` that are not pinned.

## ADR-41 requirements.txt is a generated copy of uv.lock for GitHub's dependency graph

**Superseded by [ADR-42](#adr-42-uvlock-is-the-one-source-of-the-dependency-list).**

**Decision.** The repository commits `requirements.txt`, written by `make requirements` from the lock
(`uv export --locked --no-dev --no-emit-project --format requirements-txt`). `make lint` runs
`scripts/check_requirements.py` and fails when the file differs from a fresh export, so the `fast`
check of the pre-commit hook refuses a commit with a stale copy.

* GitHub's dependency graph listed nothing from `uv.lock` (checked 2026-10-17: "No dependencies found"),
  so Dependabot alerts and security updates saw no Python package. A pip requirements file is one it
  reads for certain. After the push GitHub's own `update-uv-graph` job read the lock as well and the
  graph listed 76 packages; `requirements.txt` and `dependabot.yml` were pushed together, so it was not
  tested which of them was needed. The file is kept as a second, pip-format source that Trivy also
  scans.
* It holds the runtime packages only, like the wheel. Dependency tools that need the `dev` group read
  `uv.lock`; GitHub's view of the development tools is out of scope.
* Comment lines are left out of the comparison, so a different uv version cannot fail the check by
  rewording its header. A real difference in a package, a version or a hash does fail it.
* Qodana skips the file (as it skips `uv.lock`) so a second copy of the same packages cannot add
  findings to its gate.

**Accepted risks.** The file is a second copy that can be out of step between a lock change and the
next `make lint` (the check closes that at the next commit, not on GitHub). The file may be redundant
now that the graph lists the lock ([dependencies.md](dependencies.md)); if one source is preferred, the
file, the Makefile targets and the script are removed together. The check runs in the maintainer's hooks, which are client-side. A
Dependabot pull request merged on GitHub updates one of the two files only; the next local `make lint`
fails until `make requirements` is run.

## ADR-42 uv.lock is the one source of the dependency list

**Decision.** The generated `requirements.txt` of [ADR-41](#adr-41-requirementstxt-is-a-generated-copy-of-uvlock-for-githubs-dependency-graph),
its `make requirements` and `make requirements-check` targets, the `make lint` dependency on the check
and `scripts/check_requirements.py` with its tests are removed. `uv.lock` is the only record of the
locked packages.

* After `.github/dependabot.yml` (with a `uv` entry) and `requirements.txt` were pushed together,
  GitHub's own Dependabot job `update-uv-graph` read the lock and the dependency graph listed 76
  packages, runtime and development. A second copy covered the runtime group only, needed a
  check in the commit gate to stay in step, and went stale whenever a Dependabot pull request was
  merged on GitHub.
* The trigger was not isolated when the copy was added, so the removal is the test: the graph is
  checked again after the push (`gh api repos/Axiumine/Sankey-Studio/dependency-graph/sbom`, the
  Insights page). If it falls back to nothing, the copy comes back through a new decision record.

**Result of the check after the removal.** On 2026-10-17, after the removal and a new Dependabot graph
job, the SBOM API still listed the same 76 packages and the manifests were `uv.lock`, `pyproject.toml`
and the workflow files. So the `uv` entry of `dependabot.yml` is what makes GitHub read the lock, and the
copy was never needed (see [dependencies.md](dependencies.md#github-dependabot)).

**Accepted risks.** Dependabot's coverage of `uv.lock` rests on a GitHub job that the project does not
control and that the repository cannot test.

## ADR-43 CodeQL, a ruleset on main and signed release assets

**Decision.**

* `.github/workflows/codeql.yml` runs CodeQL on Python, JavaScript and the workflow files on pushes to
  `main` and weekly. It is an explicit workflow because the OpenSSF Scorecard SAST check detects a
  workflow that uses `github/codeql-action` and did not detect GitHub's default setup (tried first on
  2026-10-17). Findings appear in code scanning and are not a gate. The first analysis raised eight
  alerts, all dismissed with a reason: five test files that log fake secrets on purpose and one Semgrep
  rule fixture ("used in tests"), the path sanitiser `sources/files/paths.py` (the containment code, T4
  of the assurance case) and a regex on a field the model validator caps at 24 characters ("false
  positive"; measured linear, 21 ms for 128000 characters).
* A repository ruleset, "main: no deletion, no force-push", applies to the default branch. It has
  two rules, `deletion` and `non_fast_forward`. It does not require pull requests, reviews or status
  checks: those would stop the maintainer's direct pushes, which is how the git-hook gate works
  ([ADR-37](#adr-37-git-hooks-are-the-one-place-the-checks-run)).
* A second ruleset, "v* tags: no deletion, no update, no force-push", protects every tag that matches `v*`.
  An existing release tag cannot be deleted or moved without a repository administrator switching the
  ruleset off. It does not restrict who may create a `v*` tag (a `creation` rule would also stop the
  maintainer, who has no bypass entry); creating one starts the release workflow, whose `pypi`
  environment waits for the reviewer.
* After a release the GitHub release page carries the wheel and the sdist exactly as on PyPI (the
  sha256 is compared with PyPI's) and, next to each, a Sigstore bundle `<file>.sigstore.json` made from
  the PyPI provenance of that file and verified against the identity of `release.yml`. The procedure is in
  [release.md](release.md#release-assets).

**Accepted risks.** The ruleset can be switched off by a repository administrator, and it protects
history, not the content of the next commit. CodeQL results depend on the languages GitHub detects and
are read by whoever looks at the Security tab. The release assets are copies; PyPI stays the place to
install from, and the bundle proves the file was built by this repository's workflow, not that the
code is safe.

## ADR-44 A hosted CI job runs the unit tests

**Decision.** `.github/workflows/ci.yml`, job `test`, runs on every push to `main`, every pull request
to `main` and on demand: `uv sync --all-extras --locked`, `make lint typecheck caps`, then `make cov`
(the unit suite with the 100% line and branch gate) after installing Node 22 for the tests of the
frontend modules. It uploads a JUnit and a coverage report. It starts
from `permissions: {}`, has `contents: read` in the job, uses pinned actions and no secret.

* Why: a test run tied to each check-in on the shared repository, with a report (the silver criterion
  `automated_integration_testing`, the passing criterion `test_continuous_integration`), and a check
  named `test` on pull requests, which is what the OpenSSF Scorecard CI-Tests check looks for.
* What stays local: the browser end-to-end suites, the memory budgets, mutation testing, Semgrep, Trivy,
  Qodana and the real-MongoDB suites. The pre-push gate stays the one full gate
  ([ADR-37](#adr-37-git-hooks-are-the-one-place-the-checks-run)).

**Accepted risks.** Nothing requires the job to pass: a required status check would stop the
maintainer's direct pushes ([ADR-43](#adr-43-codeql-a-ruleset-on-main-and-signed-release-assets)), so the
job reports and does not block. A pull request runs its own code on the runner with a read-only token
and no secret (none exists to reach). The runner differs from the maintainer's machine (image, Chrome,
kernel), so the job can fail for a reason the local gate never shows, and the other way round.

## ADR-45 mask_uri shows option values from an allow-list

**Status.** Clarifies [ADR-15](#adr-15-uri-masking-fails-closed), which stays in force.

**Decision.** ADR-15 says `util.mask_uri` "masks every query value whose key looks secret". The code
does the safer opposite and rebuilds the URI from an allow-list:

* The scheme must be `mongodb` or `mongodb+srv`; a text without it becomes `***`. Any structural doubt,
  and any exception, gives `mongodb://***`. The function never raises.
* User info is masked: `user:pw` becomes `user:***`, and a user info without a colon (a token in the
  user name) becomes `***`.
* Hosts and the database name are shown when they match plain-character patterns.
* A query option keeps its key, and its value is shown only when the key (compared in lower case) is one of
  the twelve in `SAFE_URI_OPTIONS` (`replicaSet`, `authSource`, `authMechanism`, `tls`, `ssl`,
  `retryWrites`, `retryReads`, `w`, `readPreference`, `appName`, `directConnection`, `loadBalanced`) and
  the value matches a plain pattern. Every other option, `authMechanismProperties` and
  `tlsCertificateKeyFilePassword` included, shows `key=***`. An item whose key is unreadable is
  dropped. Items are split on `&` and on `;`.
* The patterns that validate a host, a user, a database, an option key and an option value are
  anchored with `\Z` (a `$` would also match before a trailing newline). The scheme pattern is the one
  prefix match, by design.

**Why.** A deny-list of secret-looking keys fails open for the next secret-bearing option. An
allow-list fails closed: a new option stays hidden until someone adds it.

**Accepted risks.** A harmless new option is shown as `key=***` until it is added to
`SAFE_URI_OPTIONS`, so a masked URI can be less informative than the real one. The list is code, kept
in step by the table tests in `tests/test_util.py`.

## ADR-46 Connection strings live in credentials.json

**Decision.** The connection strings of the MongoDB connections are kept in `<data_dir>/credentials.json`, a file of their own. `settings.json` keeps the rest of each connection (name, default database) and never a `uri`.

* Format, version 1: `{"version": 1, "mongo_connections": {"<connection name>": {"uri": "<string>"}}}`. The key is the connection name (the identity a connection already has); one object per name, so a later secret (a key passphrase, a token) is a new field, not a new format. `models/credentials.py` validates it with the same function as `MongoConnection.uri` (`checked_uri`).
* `SettingsStore.save` writes `credentials.json` first and `settings.json` second, each atomically with mode 0600 in the 0700 data directory, and always both. `dump_settings` and `load_settings` keep their shape and stay the code that validates a settings document; `storage/credentials.py` splits and joins the plain dicts between them and the two files. The API, the exports and the bundles do not change (`uri_masked`, `has_secret`; a bundle never held a string).
* Loading reads both files and caches on both signatures, so a `credentials.json` replaced by hand applies on the next request, with no restart. A `uri` still inside `settings.json` (a file of an earlier version, or a hand edit) is used and wins; a load writes nothing; the next save moves the string out. A connection with no entry, an unreadable file, a file that is not JSON or not valid, a symlink and a file of another user are reported as `settings_error` (422) naming the file and the connection and never a value; nothing is moved or overwritten. An entry with no connection is ignored and dropped by the next save. A file that group or others can reach is tightened to its owner bits. When `settings.json` itself is corrupt it is moved aside together with `credentials.json` under one `.corrupt-<n>` number, so a repair finds both halves.
* `SANKEY_MONGO_URI` still seeds `default` while no `settings.json` exists; the first save stores it in `credentials.json`.

**Why.** The OpenSSF silver criterion `crypto_credential_agility` asks for credentials in files apart from other information and replaceable without a rebuild. A copy, a backup, a bug report or a diff of the settings no longer carries a password, and an operator can rotate one with `mv` while the server runs.

**Accepted risks.** The two files are not replaced together: a crash between the writes leaves new strings with old settings, which is harmless except for a connection that the save removed or renamed; the next load names it and the file has to be fixed by hand. The file is plain text: its protection is the file mode, the directory mode and the account of the person who runs the server (as in [ADR-04](#adr-04-secrets-never-leave-the-settings-store)). A version from before this record reads the new `settings.json` as invalid and moves it aside, so the change is one-way. An existing install keeps its strings in `settings.json` until its next save. There is no operator-chosen path: a mounted secret is usually a symlink (refused by `O_NOFOLLOW`) on a read-only volume, which would also need a read-only Settings page; left for a later record.

## ADR-47 Fuzzing runs in ClusterFuzzLite from tests/fuzz

**Context.** The code that reads text from outside (four source formats, the rewriter behind the write-back, the MongoDB filter, pipeline and URI guards, the name validators, the number formatter) is where a malformed input does the most harm, and the unit, mutation and end-to-end tests only try the inputs someone thought of. The OpenSSF criterion `dynamic_analysis` and the Scorecard check `Fuzzing` ask for fuzzing too. The project needs CPython 3.14 (PEP 758 syntax), and the OSS-Fuzz Python image ships 3.11.

**Decision.**

* The targets live in `tests/fuzz` (not a top-level directory), so lint, types, caps, the licence-header test and the policy tests apply to them unchanged. Seven Atheris entry points (`<name>_fuzzer.py`) call plain functions in `text_targets.py` and `guard_targets.py`; `targets.py` is the registry. A target accepts the errors the code is documented to raise and checks an oracle on what it accepts (for example: an accepted MongoDB document holds no `$where`, and the JSON reader gives the same result for every chunk size).
* `tests/fuzz/test_targets.py` runs every seed, 400 mutated seeds and 400 random inputs per target in the normal unit suite, so the targets cannot rot between fuzzing runs.
* ClusterFuzzLite runs them in GitHub Actions: 7 minutes on a pull request that touches the code they read, one hour every night on `main`, then a corpus prune. The corpus is kept as a workflow artifact. Neither workflow is in the git hooks or required.
* `.clusterfuzzlite/Dockerfile` starts from the OSS-Fuzz Python builder (by digest), installs CPython 3.14.7 and the project's runtime packages from `uv.lock` with uv, and the two fuzzing tools (`atheris` 3.1.0, the first release with a 3.14 wheel, and `pyinstaller`) by hash from `.clusterfuzzlite/requirements.txt`. `build.sh` turns each entry point into a PyInstaller one-file binary, so the runner needs no Python 3.14. The targets are pure Python, so no sanitizer runtime is preloaded and `address` is only the name of the run; `coverage` is refused.
* Nothing is added to `pyproject.toml` or `uv.lock` except a mypy override for `atheris`; only the entry points import it, and a test checks that.

**Why.** Fuzzing runs on GitHub's machines, not in the maintainer's hooks, and does not slow a commit or a push. Keeping the code in `tests/fuzz` means no new rule or exception for it.

**Accepted risks.** A second dependency list (the fuzz tools and two image digests) sits next to ADR-42; it is hash-pinned and Dependabot reads it (security updates only), but a bump is by hand. `atheris` lags new CPython releases, so a Python upgrade can break the image until it catches up. The image runs as root, as the OSS-Fuzz builders do (`AVD-DS-0002` in `.trivyignore`, expiry 2027-10-18). The ClusterFuzzLite actions fix their own `:v1` images by tag, not by the action's commit. The image is not built in the git hooks, so the first run on GitHub is its first real build and the first pull request fixes whatever the runner shows. A fuzzer finds nothing it cannot reach: the targets prove only that these inputs are handled, not that the code has no bug.
