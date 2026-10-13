# Sankey Studio HTTP API

Sankey Studio is a single-process FastAPI application. It serves a handful of HTML pages and a JSON API under
`/api/v1`. This document is the contract of that HTTP surface: conventions, the security rules a client must
follow, the error envelope, every route, the `RenderBundle` the chart endpoints return, and the boot data embedded
in each HTML page. It is written for a developer who integrates with the API or extends it.

The application has no login, no CORS and no interactive API documentation (`/docs`, `/redoc` and `/openapi.json`
are 404). Everything below is enforced by the code in `src/sankey_studio/web/` and by its tests; when this text and
the code differ, the code wins and this text is a bug.

Related documents: [UI reference](ui.md) (page behaviour and the `data-testid` reference),
[Architecture](architecture.md) (how the layers fit together), [Quality](quality.md) (test and quality gates),
[Decisions](decisions.md) (why the contract looks like this), [End-to-end tests](e2e.md) (browser scenarios).

## Table of contents

1. [Conventions](#1-conventions)
2. [Client rules](#2-client-rules)
3. [Errors](#3-errors)
4. [Remote read-only mode](#4-remote-read-only-mode)
5. [Routes](#5-routes)
   - [5.1 Route index](#51-route-index)
   - [5.2 Library](#52-library)
   - [5.3 Render, preview, entries, compare](#53-render-preview-entries-compare)
   - [5.4 Exports](#54-exports)
   - [5.5 Settings](#55-settings)
   - [5.6 Sources](#56-sources)
   - [5.7 MongoDB inspection](#57-mongodb-inspection)
   - [5.8 Health and static files](#58-health-and-static-files)
6. [Request models](#6-request-models)
7. [RenderBundle](#7-renderbundle)
8. [Pages and boot data](#8-pages-and-boot-data)
9. [Pagination, caps and caching](#9-pagination-caps-and-caching)
10. [Client recipes](#10-client-recipes)

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Base URL | Wherever the server listens; the default is `http://127.0.0.1:8765`. Every path in this document is absolute. Browser code uses root-relative URLs (`/api/v1/...`). |
| Authentication | None. The server is meant for a loopback bind; see [section 4](#4-remote-read-only-mode) for remote use. |
| CORS | None. `HEAD` and `OPTIONS` are answered 405 on the API and the pages, so there is no preflight. |
| API documentation UI | None. `/docs`, `/redoc` and `/openapi.json` are 404. |
| Encoding | All JSON is UTF-8. Non-ASCII text is never escaped as `\uXXXX` in bundle exports. |
| HTML under `/api/v1` | Never. Every handler under `/api/v1` answers JSON or a file download. |
| Graph id | 32 lowercase hexadecimal characters (`^[0-9a-f]{32}$`). A malformed id in a path is a 404 `not_found`; inside an `ids` query parameter it is a 422 `validation_error`. |
| Timestamps | ISO-8601 in UTC with a trailing `Z` (`2026-10-10T19:47:54.692000Z`). The only exception is the `updated_at=` detail of a 409, which uses `+00:00`. |
| Strings | Trimmed on input. The exceptions are inline text `content` and `delimiter`, which are kept verbatim. |
| Unknown body fields | Rejected with 422 in every request model (`extra="forbid"`). |
| Unknown query parameters | Rejected with 422 (`query.<name>: Extra inputs are not permitted`) on every route that declares a query model: `GET /graphs`, `GET /graphs/export`, `GET /graphs/{id}/render`, `GET /compare/render`, `POST /preview`, `POST /entries`, both export routes, `GET /mongo/{name}/collections`, `GET /mongo/{name}/sample` and `GET /compare`. Routes without a query model ignore extra parameters. Do not append cache-busting parameters. |
| Input echo | A 422 never contains the submitted value, only the location and the reason. The location can hold a field name or a key the caller sent (`body.<key>: Extra inputs are not permitted`), and a few reasons name the offending MongoDB operator or pipeline stage, or the node or category names whose colour is not `#rrggbb`, never an argument or a value. An unknown `source.type` lists the allowed types, not the one sent ([section 3.1](#31-envelope)). |
| Caching | `Cache-Control: no-store` on every `/api/*` response and on every HTML page. Other `/static/*` files are `no-store` too (no `ETag`, no `Last-Modified`, never a 304), and every page links them under a version prefix, `/static/v-<12 hex of the SHA-256 of the whole static directory>/<file>` (`web/assets.py`, computed once per server start). Scripts import each other by relative path and load their style sheets with `new URL(..., import.meta.url)`, so nested modules share the prefix: after a change every file is a new URL, and a copy a browser stored before (even one it would reuse without asking) is never used. The mount drops the prefix (any digest), so `/static/<file>` still works. `/static/vendor/plotly.min.js` is `no-store` as well: the browser keeps nothing, so a server restart always serves the current files. |
| Order of results | Library lists are newest first (`updated_at` descending). |

### Request pipeline

A request passes these stages in order; the first stage that refuses it decides the response.

| Stage | Refusal |
|---|---|
| 1. Host check | 400 with the plain text body `Invalid host header` (not the JSON envelope) |
| 2. Body size | 413 `payload_too_large`. On the upload route in read-only mode: 403 `read_only_mode` before any byte is read |
| 3. CSRF and content type | 403 `forbidden`, 415 `unsupported_media_type` |
| 4. Routing | 404 `not_found`, 405 `method_not_allowed` |
| 5. Read-only guard | 403 `read_only_mode` on persisting routes, before the body is decoded (see [section 4](#4-remote-read-only-mode)) |
| 6. Validation | 422 `validation_error` |
| 7. Handler | the domain errors of [section 3](#3-errors) |

Security headers (section 2.4) are added by the middleware around stages 2 to 7, so every JSON answer carries them.
The stage 1 answer is produced outside that middleware.

---

## 2. Client rules

### 2.1 Content types

1. Every `POST`, `PUT`, `PATCH` or `DELETE` that carries a body sends `Content-Type: application/json` and a JSON
   body. Any other media type (`text/plain`, `application/x-www-form-urlencoded`, ...) is 415
   `unsupported_media_type`. Parameters such as `; charset=utf-8` are ignored and the comparison is case-insensitive.
2. The one exception is the file upload, `POST /api/v1/sources/files`. Send `multipart/form-data` from a `FormData`
   object and do not set `Content-Type` yourself; the browser adds the boundary.
3. Requests without a body (`DELETE /graphs/{id}`, `POST /graphs/{id}/duplicate`, `DELETE /sources/files/{name}`,
   `POST /settings/mongo/{name}/test`) need no `Content-Type`. A body is detected from a non-zero `Content-Length`
   or a `Transfer-Encoding` header; a bodiless request that nevertheless names a wrong `Content-Type` is 415.

### 2.2 CSRF verdict

The guard applies to `POST`, `PUT`, `PATCH` and `DELETE` on every path.

| Request | Verdict |
|---|---|
| `Sec-Fetch-Site: same-origin` or `none` | accepted, then the content type is checked |
| `Origin` equals the request's own origin (scheme, host, port) and its host is in `allowed_hosts` | accepted, then the content type is checked |
| Neither header, `Content-Type: application/json` | accepted (a script or curl) |
| Neither header, any other or no `Content-Type` | 403 `forbidden`. This includes a bodiless `DELETE` and a multipart upload sent by curl |
| `Origin` of another host, `Origin: null`, an unparsable `Origin` | 403 `forbidden` ("Cross-origin request refused") |
| `Sec-Fetch-Site: cross-site` or `same-site` with no matching `Origin` | 403 `forbidden` |

The rows are evaluated from top to bottom. A `GET` under `/api/` with `Sec-Fetch-Site: cross-site` is 403 as well: the export routes launch Chrome and the
Mongo routes open database connections, so they must not be reachable cross-site. `GET` requests elsewhere are not
checked.

For scripts without browser headers, add one of them to unsafe requests that have no JSON body, for example
`-H "Origin: http://127.0.0.1:8765"` or `-H "Sec-Fetch-Site: same-origin"`.

Browser rules that follow from this:

- Use root-relative URLs. A page opened on `http://localhost:8765` must not call `http://127.0.0.1:8765`; that is
  cross-origin and is refused.
- Never try to set `Origin` or `Sec-Fetch-*`; browsers forbid it and add them correctly.
- Do not send `body: ''` with a wrong content type on bodiless requests.

### 2.3 Host header

`Host` must match an entry of `allowed_hosts`, otherwise the answer is 400 with the plain text `Invalid host header`.

- Default entries: `localhost`, `127.0.0.1`, `[::1]`. The operator replaces the list with `SANKEY_ALLOWED_HOSTS`, a
  JSON list of all accepted hosts.
- The comparison ignores letter case (`Host: LOCALHOST:8765` is accepted) and the application sees the lower-case
  host.
- The address the server is bound to is always accepted, in every mode and also when `allowed_hosts` is set
  explicitly (`--host 127.0.0.2` answers `Host: 127.0.0.2`). Other loopback addresses are not accepted unless they
  are listed. A wildcard bind (`0.0.0.0`, `::`, `[::]`, `0::0`, `::ffff:0.0.0.0`) adds nothing.
- An entry is a host name or IPv4 address, `*.example.com`, or an IPv6 address in brackets (`[::1]`). No scheme,
  port or path. The entry `*` is allowed in remote mode only. An entry that cannot work stops the server at start-up.

### 2.4 Response headers and CSP

Every response carries these headers (a route that sets one itself keeps its value):

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `same-origin` |
| `Cross-Origin-Resource-Policy` | `same-origin` |
| `Cache-Control` | `no-store` on `/api/*` and on every HTML page |

File downloads replace the CSP with `Content-Security-Policy: sandbox`, so an exported HTML or SVG file opened from a
download list does not run in the origin of the app.

Consequences for front-end code:

- No inline `<script>` and no event-handler attributes. Code is loaded as `<script type="module" src="/static/...">`.
- The page data block `<script type="application/json" id="page-data">` is allowed because it is not executed.
- No CDN scripts and no network fonts. `data:` and `blob:` images are allowed. `fetch` is limited to the same origin.
- Pages declare their icon with `<link rel="icon" href="/static/img/favicon.svg">`, so browsers do not need
  `/favicon.ico`. A request for `/favicon.ico` itself is a JSON 404 and would show up as a console error.

### 2.5 Body size caps

Caps are counted while the body streams in, never trusted from `Content-Length`. An oversized body is 413
`payload_too_large` with `details: ["limit_bytes=N"]`.

| Route | Cap |
|---|---|
| Every JSON route | 8 MiB (8388608 bytes) |
| `POST /api/v1/graphs/import` | 16 MiB (16777216 bytes) |
| `POST /api/v1/sources/files` | `max_upload_mb` as stored now, plus 1 MiB of multipart framing (default 25 MiB gives 27262976 bytes) |

---

## 3. Errors

### 3.1 Envelope

Every failure other than the Host rejection uses one envelope:

```json
{"error": {"code": "not_found", "message": "Graph not found", "details": []}}
```

- `code` is stable and meant for programs. `message` is for people. `details` is a list of strings, possibly empty.
- For a 422 `validation_error`, `details` holds `"<location>: <message>"`. The location is `body.<field path>`,
  `query.<name>` or `body.<form field>` (multipart). A discriminated source shows its tag in the path, for example
  `body.source.text: Value error, content is required when origin is 'inline'`. A malformed JSON body is
  `body.1: JSON decode error`; an empty body is `body: Field required`.
- A `source` whose `type` matches no variant is `body.source: type must be one of: manual, text, mongo` (the
  allowed tags, built from the schema); a `source` without `type` is `body.source: type is required`. The
  value that was sent is never quoted, whatever its type or length: pydantic's own wording
  (`Input tag 'x' found using 'type' ...`) is replaced.
- At most 50 details are returned and each is cut to 300 characters.
- Messages never contain a connection URI, a stack trace, or a file-system path beyond names inside the sources
  directory.
- A 409 `conflict` from a stale `PUT` carries `details: ["revision=N", "updated_at=<iso>"]` with the stored values.

Routing errors keep their status: 404 `not_found`, 405 `method_not_allowed` (with the `Allow` header), and
`http_error` for any other HTTP error raised by the framework or the static files. An unexpected failure is a
generic 500 `internal_error` with the message `Internal server error` and no detail.

A browser navigation to a page URL gets none of these envelopes: every error status (404, 503 `storage_error`,
500, 502, ...) is an HTML page in the app shell with the same status ([section 8.3](#83-error-pages)). API
paths and every client that does not ask for HTML keep the envelope exactly as described here.

### 3.2 Error codes

| Status | Code | Meaning |
|---|---|---|
| 400 | `unsafe_source` | Path escape, symbolic link, forbidden Mongo database, collection or stage, upload filename with a path separator or a disallowed extension |
| 403 | `forbidden` | The CSRF guard refused the request ([section 2.2](#22-csrf-verdict)) |
| 403 | `read_only_mode` | A persisting route in remote read-only mode ([section 4](#4-remote-read-only-mode)) |
| 404 | `not_found` | Unknown or malformed graph id, or unknown URL. JSON for every client except a browser navigation to a page URL, which gets the HTML not-found page ([section 8.3](#83-error-pages)) |
| 404 | `source_not_found` | Unknown source file or unknown Mongo connection name |
| 405 | `method_not_allowed` | The path exists but not for this verb |
| 409 | `conflict` | Stale `revision` on `PUT /graphs/{id}`, or an upload name that is already taken |
| 413 | `payload_too_large` | Request body over its cap ([section 2.5](#25-body-size-caps)), or an upload over `max_upload_mb` |
| 413 | `graph_too_large` | More raw links than `max_links`, or category rules that would need more than 20 million name and rule matches |
| 415 | `unsupported_media_type` | Wrong `Content-Type` ([section 2.1](#21-content-types)) |
| 422 | `validation_error` | A request model or query model is invalid, including unsafe Mongo filters and pipelines |
| 422 | `source_error` | The data could not be read or parsed (bad rows, bad column mapping), or an upload filename is empty, too long (over 255 bytes) or holds control or formatting characters |
| 422 | `graph_build_error` | The links cannot form a drawable graph: a cycle with `on_cycle: "error"`, flow sums beyond the float range |
| 422 | `no_categories` | A donut was asked for and no entry has a category |
| 422 | `settings_error` | The settings are invalid or cannot be read or saved; `details` list `location: reason` |
| 422 | `bundle_error` | Unusable import bundle, or an export larger than an import accepts |
| 422 | `export_too_large` | Image over the pixel cap (36,000,000 pixels after scale), or a graph with more than 5000 links or 2000 nodes asked as SVG or PNG |
| 500 | `internal_error` | Unexpected failure, no detail |
| 501 | `export_unavailable` | No Chrome or Chromium for SVG and PNG export; fall back to `Plotly.downloadImage` in the browser |
| 502 | `export_failed` | The renderer crashed; fall back to the browser |
| 503 | `export_busy` | Another image export is running (one at a time) |
| 503 | `busy` | A bounded resource is in use (a storage probe slot or a MongoDB connection slot) |
| 503 | `storage_error` | Disk or MongoDB unreachable, or the sources directory is not usable. A browser navigation to a page URL gets the HTML "Graph database unavailable" page instead ([section 8.3](#83-error-pages)) |
| 504 | `export_timeout` | The renderer did not finish in 30 seconds; fall back to the browser |

On `export_too_large` (422) and on 501, 502, 503 `export_busy` and 504 a browser client falls back to
`Plotly.downloadImage`. HTML, JSON and CSV exports never need Chrome.

---

## 4. Remote read-only mode

By default the server binds to a loopback address. A non-loopback bind needs `--allow-remote`; because there is no
authentication, the server then refuses everything that persists unless `--allow-remote-writes` is given too.

| Flags | `remote_mode` | `writes_allowed` |
|---|---|---|
| none (loopback) | false | true |
| `--allow-remote` | true | false |
| `--allow-remote --allow-remote-writes` | true | true |

`--allow-remote-writes` without `--allow-remote` is refused at start-up. Both values appear in the boot data of every
page and in `GET /settings` (`bootstrap.remote_mode`, `bootstrap.writes_allowed`).

When `writes_allowed` is false, these ten routes answer 403 `read_only_mode`:

| Route |
|---|
| `POST /api/v1/graphs` |
| `PUT /api/v1/graphs/{id}` |
| `DELETE /api/v1/graphs/{id}` |
| `POST /api/v1/graphs/{id}/duplicate` |
| `POST /api/v1/graphs/import` |
| `PUT /api/v1/settings` |
| `POST /api/v1/settings/storage/test` |
| `POST /api/v1/settings/mongo/{name}/test` |
| `POST /api/v1/sources/files` |
| `DELETE /api/v1/sources/files/{name}` |

The settings probes count as persisting because they connect to URIs a caller supplies.

- For the routes of the graph library and the settings, the refusal comes after the CSRF check (a cross-site request
  is still 403 `forbidden`, a wrong content type still 415) but before the body is decoded and before validation.
  An invalid or undecodable body on these routes is therefore 403, never 422. `DELETE /sources/files/{name}` has no
  body and is refused the same way. The upload route is refused even earlier, in the body-size stage, before any
  byte of the multipart body is read and before the CSRF check. A refused request writes nothing.
- The message is `This action is disabled in read-only remote mode (start with --allow-remote-writes)`.
- Still available: every `GET`, `POST /preview`, `POST /entries`, `POST /sources/detect`, `POST /export`,
  `GET /compare/render` and all exports. These are pure computations or reads.
- `GET /settings` hides the Mongo connections: `uri_masked` is the bare placeholder `mongodb://***` instead of the
  masked host and user name.
- UI clients should disable write controls when `writes_allowed` is false; see the [UI reference](ui.md).

---

## 5. Routes

All API routes live under `/api/v1`. In the tables, `{id}` is a graph id.

### 5.1 Route index

The application serves 35 routes: 28 API routes, the vendored Plotly script and 6 HTML pages. Static files under
`/static/` are served by a mount that comes after every route.

| Route | Section | Persists |
|---|---|---|
| `GET /api/v1/graphs` | [5.2](#52-library) | no |
| `POST /api/v1/graphs` | [5.2](#52-library) | yes |
| `GET /api/v1/graphs/export` | [5.2](#52-library) | no |
| `POST /api/v1/graphs/import` | [5.2](#52-library) | yes |
| `GET /api/v1/graphs/{id}` | [5.2](#52-library) | no |
| `PUT /api/v1/graphs/{id}` | [5.2](#52-library) | yes |
| `DELETE /api/v1/graphs/{id}` | [5.2](#52-library) | yes |
| `POST /api/v1/graphs/{id}/duplicate` | [5.2](#52-library) | yes |
| `GET /api/v1/tags` | [5.2](#52-library) | no |
| `POST /api/v1/preview` | [5.3](#53-render-preview-entries-compare) | no |
| `GET /api/v1/graphs/{id}/render` | [5.3](#53-render-preview-entries-compare) | no |
| `GET /api/v1/compare/render` | [5.3](#53-render-preview-entries-compare) | no |
| `POST /api/v1/entries` | [5.3](#53-render-preview-entries-compare) | no |
| `GET /api/v1/graphs/{id}/export` | [5.4](#54-exports) | no |
| `POST /api/v1/export` | [5.4](#54-exports) | no |
| `GET /api/v1/settings` | [5.5](#55-settings) | no |
| `PUT /api/v1/settings` | [5.5](#55-settings) | yes |
| `POST /api/v1/settings/storage/test` | [5.5](#55-settings) | yes (probe) |
| `POST /api/v1/settings/mongo/{name}/test` | [5.5](#55-settings) | yes (probe) |
| `GET /api/v1/sources/files` | [5.6](#56-sources) | no |
| `POST /api/v1/sources/files` | [5.6](#56-sources) | yes |
| `DELETE /api/v1/sources/files/{name}` | [5.6](#56-sources) | yes |
| `GET /api/v1/sources/files/{name}/preview` | [5.6](#56-sources) | no |
| `POST /api/v1/sources/detect` | [5.6](#56-sources) | no |
| `GET /api/v1/mongo/{name}/databases` | [5.7](#57-mongodb-inspection) | no |
| `GET /api/v1/mongo/{name}/collections` | [5.7](#57-mongodb-inspection) | no |
| `GET /api/v1/mongo/{name}/sample` | [5.7](#57-mongodb-inspection) | no |
| `GET /api/v1/health` | [5.8](#58-health-and-static-files) | no |
| `GET /static/vendor/plotly.min.js` | [5.8](#58-health-and-static-files) | no |
| `GET /`, `/graphs/new`, `/graphs/{id}`, `/graphs/{id}/edit`, `/compare`, `/settings` | [8](#8-pages-and-boot-data) | no |

The last row stands for the 6 HTML pages. "Persists: yes" means the route answers 403 `read_only_mode` in remote
read-only mode ([section 4](#4-remote-read-only-mode)).

### 5.2 Library

| Route | Query | Body | Success | Errors |
|---|---|---|---|---|
| `GET /graphs` | `q` (at most 200 characters, blank means none), `tag` (at most 40, exact match, blank means none), `limit` 1 to 200 (default 200), `offset` 0 or more (default 0) | none | 200 `GraphPage` | 422 |
| `GET /tags` | none | none | 200 sorted list of strings, for example `["demo","smoke"]` | none |
| `POST /graphs` | none | `GraphCreate` | 201 `GraphDefinition` with `revision` 1 | 422 |
| `GET /graphs/{id}` | none | none | 200 `GraphDefinition` | 404 |
| `PUT /graphs/{id}` | none | `GraphUpdate` (`GraphCreate` plus `revision`) | 200 `GraphDefinition`, `revision` plus 1 | 404, 409, 422 |
| `DELETE /graphs/{id}` | none | none | 204, no body | 404 |
| `POST /graphs/{id}/duplicate` | none | none | 201 `GraphDefinition`: name `"<name> (copy)"` (the name is shortened so the result stays within 200 characters), new id, `revision` 1 | 404 |
| `GET /graphs/export` | `ids`: 1 to 200 distinct graph ids, comma separated or repeated | none | 200 JSON bundle download | 404, 422 |
| `POST /graphs/import` | none | the bundle exactly as exported (a JSON object) | 200 `ImportReport` | 413, 422 `bundle_error` |

**Search.** `q` is a case-insensitive substring match over the name, the description and the tags. `tag` must equal
one of the graph's tags exactly. `total` in the answer counts every match, not only the returned page.

`GraphPage`:

```json
{"items": [{"id": "cdfaad9764a8456aac96bb56cf398a92", "name": "Energy", "description": "", "tags": ["demo"],
            "source_type": "text", "revision": 1, "updated_at": "2026-10-10T19:47:54.692000Z"}],
 "total": 2, "limit": 5, "offset": 0}
```

Each item is a `GraphSummary`: `id`, `name`, `description`, `tags`, `source_type` (one of `manual`, `text`, `mongo`),
`revision`, `updated_at`. It carries no source content and no style.

**`GraphCreate`** is the body the editor saves. Only `name` and `source` are required:

```json
{"name": "Household budget", "description": "Smoke graph", "tags": ["smoke", "demo"],
 "source": {"type": "text", "origin": "inline", "format": "csv",
            "content": "source,target,value,category\nSalary,Budget,3000,Income\n..."},
 "transform": {}, "style": {"title": "Household budget"}}
```

**`GraphDefinition`** is the stored graph and the answer of `POST`, `GET` and `PUT` on a graph. Defaults are filled
in:

```json
{"source": {"type": "text", "origin": "inline", "content": "source,target,value,category\nSalary,Budget,3000,Income\n...",
            "path": null, "format": "csv", "delimiter": null, "has_header": true, "source_column": null,
            "target_column": null, "value_column": null, "category_column": null, "detect_category": true,
            "encoding": "utf-8"},
 "transform": {"min_link_value": 0.0, "top_links": null, "hide_nodes": [], "merge_nodes": {}, "on_cycle": "error",
               "strict": false, "entry_categories": [], "category_rules": [], "rules_override": false},
 "style": {"title": "Household budget", "orientation": "h", "color_mode": "node", "node_colors": {},
           "category_colors": {}, "node_pad": 16, "node_thickness": 18, "link_opacity": 0.4, "arrangement": "snap",
           "value_format": ",.2~f", "value_suffix": "", "show_values_in_labels": false, "font_size": 13,
           "height": 560, "donut": {"basis": "all", "max_slices": 6, "hole": 0.58, "show_percent": true,
                                    "show_total": true, "sort": "value"}},
 "name": "Household budget", "description": "Smoke graph", "tags": ["smoke", "demo"],
 "id": "74828c79fb6f4e03913f605ea8b9a79c", "schema_version": 1, "revision": 1,
 "created_at": "2026-10-10T19:47:34.778000Z", "updated_at": "2026-10-10T19:47:34.778000Z"}
```

**Optimistic concurrency.** `PUT` must send the `revision` the client last saw. If the stored revision has moved on,
the answer is 409:

```json
{"error": {"code": "conflict", "message": "Graph was modified since you loaded it; reload it or save a copy",
           "details": ["revision=1", "updated_at=2026-10-10T19:47:34.778000+00:00"]}}
```

A client then offers "reload" (`GET` the graph) or "save as copy" (`POST /graphs` with the editor's content, or
`POST /graphs/{id}/duplicate` of the stored graph).

**Bundles.** The bundle file is
`{"format": "sankey-studio/graphs", "version": 1, "graphs": [<GraphDefinition>, ...]}`.

- Export is a download: `Content-Type: application/json` (no charset), attachment name `sankey-studio-graphs.json`.
  The graphs come in the order of `ids`; repeated ids are dropped.
- The document is built one graph at a time and counted in UTF-8 bytes. At the first graph that takes it over 16 MiB
  the answer is 422 `bundle_error` and the rest is never loaded, so an unknown id listed after that graph answers
  422, not 404. Non-ASCII text is written as UTF-8, so every graph `POST /graphs` accepts can be exported and
  imported back.
- Import always assigns fresh ids, creation times and `revision` 1; there is no way to keep ids over HTTP. One bad
  graph never blocks the others. A bundle holds at most 1000 graphs; a wrong format, a wrong version or a missing
  `graphs` list is 422 `bundle_error` and nothing is stored.

`ImportReport`:

```json
{"imported": 2, "failed": 0, "ids": ["0a95...", "2396..."], "errors": []}
```

`errors` holds at most 50 entries of the form `graph <position>: <reason>` (position counts from 1).

### 5.3 Render, preview, entries, compare

| Route | Query | Body | Success |
|---|---|---|---|
| `POST /preview` | `theme`: `light` (default) or `dark` | `GraphDraft` | 200 `RenderBundle` |
| `GET /graphs/{id}/render` | `theme` | none | 200 `RenderBundle` of the saved graph |
| `GET /compare/render` | `ids`: 1 to 12 distinct graph ids, comma separated or repeated; `theme` | none | 200 list of `RenderBundle`, in the order of `ids` |
| `POST /entries` | `offset` 0 or more (default 0), `limit` 1 to 500 (default 100), `q` (at most 200 characters), `only_uncategorized` (boolean, default false), `sort`: `value` (default), `source`, `target` or `category` | `GraphDraft` | 200 `EntriesPage` |

`theme` is `light` or `dark` here. The stored setting `system` exists only in the settings; a client resolves it
itself and asks for a concrete theme. Switching theme is a new request: the colours are chosen by the server and are
inside the figure.

Errors: 404 for an unknown graph, 404 `source_not_found` for an unknown Mongo connection, 413 `graph_too_large`,
422 `validation_error`, `source_error` or `graph_build_error`. A cycle with `on_cycle: "error"` is 422 with a message
such as `The links form a cycle: A -> B -> A. Set on_cycle to 'break' to drop the links that close it`; with
`on_cycle: "break"` the call is 200 and `warnings` says how many links were removed.

**Compare.** All cards share one category colour map, so a category has the same colour on every card. Category
colour overrides come from the style of the first graph in `ids`. More than 12 ids is 422
(`query.ids: Value should have at most 12 items after validation, not 13`). One unknown id makes the whole call
404; a page that wants to survive a deleted graph asks again without that id (the compare page does this by
listing missing ids in its boot data, see [section 8](#8-pages-and-boot-data)).

**Entries.** `POST /entries` pages the entries table of a draft. Rows are the (source, target) pairs of the built
graph. `q` is a case-insensitive substring match on source, target and category. `sort` is `value` descending, or
the chosen text column ascending (case-insensitive, uncategorised rows last for `category`); ties keep the order of
first appearance. The `style` of the draft is accepted but not used.

`EntriesPage`:

```json
{"rows": [{"source": "Salary", "target": "Budget", "value": 3000.0, "category": "Income",
           "mixed": false, "overridden": false}],
 "total": 8}
```

`category` is the dominant category of the pair; `mixed` is true when the pair has several categories; `null` means
uncategorised; `overridden` is true when the pair is set in `transform.entry_categories`. `total` counts all rows
that match the filters, not the page.

### 5.4 Exports

| Route | Query | Body |
|---|---|---|
| `GET /graphs/{id}/export` | see below | none |
| `POST /export` | the same | `GraphDraft` (an unsaved draft) |

| Query parameter | Values | Default |
|---|---|---|
| `chart` | `sankey`, `donut` | `sankey` |
| `format` | `svg`, `png`, `html`, `json`, `csv` | `svg` |
| `theme` | `light`, `dark` | `light` |
| `width` | integer 1 to 100000 | 1200 |
| `height` | integer 1 to 100000 | the figure's own height |
| `scale` | number above 0 and up to 100 | 2.0 |
| `transparent` | boolean | false |

Every answer is an attachment with `Content-Disposition: attachment; filename="Household_budget.csv";
filename*=UTF-8''Household%20budget.csv`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`.

| Format | `Content-Type` |
|---|---|
| `svg` | `image/svg+xml` |
| `png` | `image/png` |
| `html` | `text/html; charset=utf-8` (a standalone page with Plotly inlined; works offline) |
| `json` | `application/json` (the Plotly figure) |
| `csv` | `text/csv; charset=utf-8` |

**File names.** The Sankey files are named after the graph (`<name>.svg`, `.png`, `.html`, `.json`, `.csv`); a draft
uses `style.title`, or `graph` when there is none. The donut files add `-donut` before the extension
(`<name>-donut.csv`), so the two charts of one graph never share a file name. A name longer than 80 characters is cut
before the suffix is added (74 characters of the name plus `-donut`), so the suffix is never lost. The `filename`
form keeps only `A-Z a-z 0-9 . _ -` (runs of anything else become `_`, `graph` if nothing is left); `filename*`
carries the full name percent-encoded as UTF-8. The `<title>` of the HTML export is the graph name. A client that
builds a file name itself (the `Plotly.downloadImage` fallback) should use the same scheme.

**Content.**

- CSV is the full list of links, not capped: `source,target,value,category`. The donut CSV is
  `category,value,share`, for example `Income,3800.0,0.4222222222222222`. Cells that a spreadsheet could read as a
  formula (starting with `=`, `+`, `-`, `@`, a tab or a carriage return) are prefixed with a quote character.
- The Sankey SVG and PNG are drawn like on screen, with at most `max_drawn_links` links (a note in the figure says
  "Showing N of M links").
- Image size is `width` by (`height`, or the figure's height), multiplied by `scale`, for SVG and PNG alike: with a
  560 pixel high figure, `format=png&width=400&scale=2` gives 800x1120 pixels.
- `width` and `height` are clamped to 200..4000 and `scale` to 1..4 on the server before the cap is applied; the
  query accepts the wider ranges above. `width=100` gives 200 pixels and `width=9000` gives 4000.
- `export_too_large` (422) is returned when `width x height x scale^2` exceeds 36,000,000 pixels, or when the
  figure has more than 5000 links or 2000 nodes.
- Image export runs Chrome through kaleido: one export at a time (a second one waits up to 2 seconds, then 503
  `export_busy`), and a render that takes longer than 30 seconds is 504 `export_timeout`.
- `no_categories` (422) is returned for the donut of a graph without categories, in every format including CSV.

Use `fetch`, then `blob()`, an object URL and an `<a download>` link. Take the file name from `filename*` (UTF-8) and
fall back to `filename`.

### 5.5 Settings

| Route | Query | Body | Success |
|---|---|---|---|
| `GET /settings` | none | none | 200 `SettingsOut` |
| `PUT /settings` | `migrate`: boolean, default false | `SettingsIn` | 200 `SettingsSaved` |
| `POST /settings/storage/test` | none | `SettingsIn` (the candidate; nothing is saved) | 200 `{"ok": true}` |
| `POST /settings/mongo/{name}/test` | none | none | 200 `{"ok": true, "latency_ms": 12.3}` |

**`SettingsOut`.** There is no field called `uri` anywhere in it, so the answer is safe to log:

```json
{"storage_backend": "file", "storage_connection": null, "storage_database": "sankey_studio",
 "mongo_connections": [{"name": "main", "uri_masked": "mongodb://alice:***@db.example:27017/?authSource=admin",
                        "has_secret": true, "default_database": "flows"}],
 "theme": "dark",
 "default_style": { "...": "a full style, same keys as GraphDefinition.style" },
 "max_links": 200000, "max_drawn_links": 3000, "max_upload_mb": 25, "mongo_timeout_ms": 15000,
 "bootstrap": {"sources_dir": "/home/me/.local/share/sankey-studio/sources", "remote_mode": false,
               "writes_allowed": true}}
```

`bootstrap` holds operator-level values that come from the environment or the command line and cannot be changed
through the API.

**`SettingsIn`** (the `PUT` body) has the same keys, except that the items of `mongo_connections` are:

```json
{"name": "main", "uri": "mongodb://user:pw@host:27017", "previous_name": null, "default_database": "flows"}
```

- `uri` is optional. Omit it, or send `null`, an empty string or the masked string, to keep the stored secret. A
  connection with no stored secret and no URI is a 422 `settings_error`. A URI is validated on save: options that
  read local files or ambient credentials are refused, and a masked placeholder is refused.
- `previous_name` is the name the connection had when the client loaded it. A rename keeps the secret
  (`{"name": "renamed", "previous_name": "main"}` keeps the URI of `main`). A retried rename, where `previous_name`
  is gone and `name` is already stored, is 200 and keeps the secret; a request whose `previous_name` and `name` are
  both unknown is 422.
- The keys `uri_masked` and `has_secret` of a `GET` answer, and the whole `bootstrap` block, are accepted and
  ignored, so a `GET` answer can be edited and sent back as it is.
- A client uses an `<input type="password">` with the placeholder "(unchanged)" for the URI and sends `uri` only
  when the user typed something. It never stores or displays a URI.

Ranges and values: `theme` is `system`, `light` or `dark`; `storage_backend` is `file` or `mongo` (`mongo` needs
`storage_connection` to name a configured connection); `storage_database` at most 64 characters; `max_links`
100 to 5,000,000 (default 200,000); `max_drawn_links` 50 to 20,000 (default 3,000); `max_upload_mb` 1 to 100
(default 25, applies to the next upload at once); `mongo_timeout_ms` 500 to 300,000 (default 15,000); at most 20
connections with unique names matching `^[A-Za-z0-9_.-]{1,64}$`.

**`SettingsSaved`** (the `PUT` answer):

```json
{"settings": {"...": "a SettingsOut"},
 "copy_report": null}
```

`copy_report` is non-null only when `migrate=true` and the storage target changed. Existing graphs are then copied
with the same ids: `{"copied": 3, "skipped": 0, "unreadable": 0, "unreadable_ids": []}`, where `unreadable_ids` names
at most the first 50.

**Errors.** 422 `validation_error` for body shape and ranges (`body.max_links: Input should be greater than or equal
to 100`, `body.bogus: Extra inputs are not permitted`); 422 `settings_error` for semantic problems
(`Connection 'new1' needs a connection string`, `mongo_connections.0.uri: Value error, uri must start with mongodb://
or mongodb+srv://`, `storage_backend 'mongo' needs storage_connection naming a connection`); 404 `source_not_found`
for an unknown connection name on the Mongo probe; 503 `storage_error` when a probe cannot reach the server; 403
`read_only_mode` in remote read-only mode. Any route that reads the settings answers 422 `settings_error` when the
stored settings file is unreadable.

**Concurrency.** Settings writes are serialised: two simultaneous `PUT /settings` never lose a rotated secret, and
the stored document is always one request whole. `POST /settings/storage/test` runs at most 4 probes at the same
time in the whole process; a fifth waits up to `mongo_timeout_ms` and then answers 503 `busy`. The Mongo routes and
the Mongo probe do not need the sources directory.

### 5.6 Sources

Managed source files live under the sources directory of the server (`--sources-dir`, default
`<data dir>/sources`). `name` is a POSIX path relative to that directory.

| Route | Body | Success |
|---|---|---|
| `GET /sources/files` | none | 200 list of `{"name": "flows.csv", "size": 32, "modified": "2026-10-10T19:48:10.881624Z"}` |
| `POST /sources/files` | multipart: part `file` (required), form field `overwrite` (`true` or `false`) | 201 the stored file's info (same shape) |
| `DELETE /sources/files/{name}` | none | 204 |
| `GET /sources/files/{name}/preview` | none | 200 `{"name": "flows.csv", "lines": ["source,target,value", "A,B,5", "B,C,3"]}` |
| `POST /sources/detect` | `{"sample": "<text>"}` (JSON cap 8 MiB; only the first 4096 characters are read) | 200 `{"format": "csv"}`, one of `csv`, `tsv`, `sankeymatic`, `json` |

**Listing.** Regular files with an allowed extension, sorted by name (case-insensitive), scanned up to three
directory levels below the sources directory. Symbolic links are skipped. A file whose name or folder contains a
backslash is not listed, because preview and delete refuse such a name. Every listed name can be previewed and
deleted, a name with a newline included.

**Allowed extensions:** `.csv`, `.tsv`, `.txt`, `.json`, `.ndjson`, `.sankey`.

**Upload.**

- The file part is `file`; the only other accepted part is `overwrite`. Any other part (a misspelt `overwite`) is
  422 `body.overwite: Extra inputs are not permitted`.
- A name that already exists, compared case-insensitively, is 409 `conflict` (`a file named 'flows.csv' already
  exists`) unless `overwrite=true`. With `overwrite=true` a file whose name differs only in case is replaced under
  its stored name.
- A file over `max_upload_mb` is 413 `payload_too_large`. The request is refused while it streams in once it passes
  `max_upload_mb` plus 1 MiB (`details: ["limit_bytes=N"]`); a file between `max_upload_mb` and that margin is
  refused by the handler with the same status and code, without the detail.
- The filename is NFC-normalised and the leading dots are stripped. A path separator (`/` or `\`) is 400
  `unsafe_source` (`filename must be a plain name without path separators`), so browser uploads always land at the
  top level of the sources directory. A disallowed extension is 400 `unsafe_source`. Control or formatting
  characters, an empty name after stripping, or more than 255 UTF-8 bytes are 422 `source_error`.
- The upload is streamed to disk, never held in memory.

**Delete and preview** accept names with `/` for files in sub-directories, used URL-encoded as the listing returns
them. A traversal (`../`), an absolute path, a backslash or a symbolic link is 400 `unsafe_source`; a missing file
is 404 `source_not_found`. The preview returns at most 50 lines, each at most 500 characters, 64 KiB in all, decoded
as UTF-8 with replacement characters.

A graph reads such a file through a `text` source with `origin: "file"` and `path` set to the `name` of the listing.

### 5.7 MongoDB inspection

These routes feed the editor's Mongo form. They are plain `GET` requests, open in read-only mode, and `name` is a
connection configured in the settings.

| Route | Query | Success |
|---|---|---|
| `GET /mongo/{name}/databases` | none | 200 list of database names; `admin`, `local` and `config` are never listed |
| `GET /mongo/{name}/collections` | `database` (1 to 64 characters, required) | 200 list of collection names; `system.*` are never listed |
| `GET /mongo/{name}/sample` | `database` (required), `collection` (1 to 120 characters, required), `n` 1 to 20 (default 5) | 200 `{"documents": [...], "suggested": {...}}` |

`suggested` is the field mapping the editor pre-selects:
`{"source": "from", "target": "to", "value": "amount", "category": null}`; `category` is `null` when no field looks
like one. `documents` are JSON-safe, size-bounded copies of up to `n` documents (nesting, items per container, string
length and total number of values are capped).

An unknown connection name is 404 `source_not_found` (`Unknown MongoDB connection 'nope'`). The databases `admin`,
`local`, `config` and collections named `system.*` are 400 `unsafe_source`. Driver failures are reported with the
connection name and the exception class only, never the URI. At most 4 Mongo operations run at once per connection;
more wait and then answer 503 `busy`.

### 5.8 Health and static files

| Route | Answer |
|---|---|
| `GET /api/v1/health` | 200 `{"status": "ok"}`. A liveness check only; it touches no storage |
| `GET /static/vendor/plotly.min.js` | 200, `Content-Type: text/javascript; charset=utf-8`, `Cache-Control: no-store`. The `plotly.min.js` of the installed `plotly` package (Plotly.js 4.1.1 at the time of writing, about 4.8 MB). Never a CDN |
| `GET /static/<path>` | The files of `src/sankey_studio/web/static/` (`css/`, `js/`, `img/`); a missing file is the JSON 404 |

The vendored script is an ordinary route registered before the static mount, so the mount never shadows it.

---

## 6. Request models

All request models reject unknown fields, trim strings and never echo input in a 422.

**`GraphCreate`**: `name` 1 to 200 characters; `description` at most 2000; `tags` at most 20 items, each at most 40
characters (trimmed, de-duplicated, blanks dropped); `source`; `transform`; `style`. **`GraphUpdate`** adds
`revision` (1 or more). **`GraphDraft`**, the body of `/preview`, `/entries` and `/export`, is `source` (required),
`transform` and `style` only.

### 6.1 `source`

Discriminated by `type`.

**`manual`**: `links`, at most 5000 items `{source, target, value, category}`. Names are 1 to 200 characters without
NUL; `value` is a finite number above 0; `category` is optional (empty or `null` means none), at most 100
characters, and `Uncategorized` and `Other` are reserved names (422).

**`text`**:

| Field | Rule |
|---|---|
| `origin` | `inline` (default) or `file` |
| `content` | Required for `inline`, at most 2,000,000 characters, not trimmed |
| `path` | Required for `file`: relative POSIX path, no `.`, `..` or empty segment, no backslash, at most 255 characters; the `name` from `GET /sources/files` |
| `format` | `auto` (default), `csv`, `tsv`, `sankeymatic`, `json` |
| `delimiter` | One character; not a quote, CR, LF or NUL; `null` sniffs |
| `has_header` | Default true |
| `source_column`, `target_column`, `value_column`, `category_column` | A header name (1 to 200 characters) or a 0-based integer up to 10000 |
| `detect_category` | Default true: a column headed `category` is used when no `category_column` is given |
| `encoding` | Default `utf-8`; any Python text codec, stored in canonical form; byte-to-byte codecs are refused |

**`mongo`**:

| Field | Rule |
|---|---|
| `connection` | Name of a configured connection, `^[A-Za-z0-9_.-]{1,64}$` |
| `database` | Optional, at most 64 characters; defaults to the connection's default database; `admin`, `local`, `config` refused |
| `collection` | 1 to 120 characters |
| `mode` | `find` (default) or `aggregate` |
| `filter` | Object for `find` mode. Operators that run server-side code or write data (`$where`, `$function`, `$accumulator`, `$out`, `$merge`) are refused anywhere in the tree |
| `pipeline` | At most 50 stages; required and non-empty for `aggregate`. Stages must come from a read-only allow-list, and the same forbidden operators are refused |
| `source_field`, `target_field` | Dotted paths, default `source` and `target` |
| `value_field` | Dotted path, default `value`; `null` counts each document as 1 |
| `category_field` | Optional dotted path |
| `limit` | 1 to 1,000,000 (default 10,000): the most documents read (skipped ones count). The server is asked for one more; only that extra document, which is never used, adds the warning `Result truncated at limit N`, so a collection of exactly `limit` documents is complete and silent. A last `$limit` stage of an `aggregate` pipeline up to `limit + 1` is kept as written (a `$limit` of `limit` or less is the pipeline's own cut and never warns) |
| `max_time_ms` | Optional, 100 to 300,000 |

Unsafe filters and pipelines are rejected when the draft is validated (422 `validation_error`).

### 6.2 `transform`

| Field | Rule |
|---|---|
| `min_link_value` | 0 or more (default 0) |
| `top_links` | 1 or more, or `null` (keep the N largest pairs) |
| `hide_nodes` | At most 1000 names |
| `merge_nodes` | Object `{alias: canonical}`, at most 5000 entries |
| `on_cycle` | `error` (default) or `break` |
| `strict` | Boolean. A bad row fails the load when true; it is skipped with a warning when false |
| `entry_categories` | At most 20,000 items `{source, target, category}`; `category: null` forces uncategorised; a pair may not repeat. Meant for `text` and `mongo` sources; a `manual` source keeps its categories on the links themselves |
| `category_rules` | At most 200 items `{match, pattern, category}`; `match` is `source`, `target` or `either`; `pattern` is a case-insensitive glob over the node name |
| `rules_override` | Boolean. By default the precedence is `entry_categories`, then the data category, then `category_rules`; with `true` the rules rank above the data category |

Categories are normalised (control characters are refused) and limited to 100 characters after normalisation. A
graph keeps at most 200 distinct categories; later ones become uncategorised and a warning says so.

### 6.3 `style`

| Field | Rule |
|---|---|
| `title` | Optional, at most 200 characters |
| `orientation` | `h` (default) or `v` |
| `color_mode` | `node` (default), `layer`, `mono`, `category` |
| `node_colors` | `{node name: "#rrggbb"}`, at most 1000 entries |
| `category_colors` | `{category: "#rrggbb"}`, at most 1000 entries; `Uncategorized` and `Other` cannot be overridden |
| `mono_color` | `"#rrggbb"` or absent (default: the palette colour); the colour of every node and link in `mono` mode |
| `node_pad` | 0 to 100 (default 16) |
| `node_thickness` | 1 to 100 (default 18) |
| `link_opacity` | 0.05 to 1 (default 0.4) |
| `arrangement` | `snap` (default), `perpendicular`, `freeform`, `fixed` |
| `value_format` | A d3-format string of at most 24 characters from `- + space , . ~ $ %` and letters and digits (default `,.2~f`) |
| `value_suffix` | At most 20 characters |
| `show_values_in_labels` | Boolean (default false) |
| `font_size` | 8 to 32 (default 13) |
| `height` | 240 to 2400 (default 560) |
| `donut.basis` | `all` (default), `initial` (first-hop entries), `terminal` (last-hop entries) |
| `donut.max_slices` | 2 to 8 (default 6) |
| `donut.hole` | 0.3 to 0.85 (default 0.58) |
| `donut.show_percent`, `donut.show_total` | Booleans, default true |
| `donut.sort` | `value` (default) or `name` |

With no categorised link, `color_mode: "category"` behaves like `node`.

---

## 7. RenderBundle

`RenderBundle` (`sankey_studio.bundle.RenderBundle`, no extra fields) is the answer of `POST /preview` and
`GET /graphs/{id}/render`, and each element of the `GET /compare/render` list. It holds JSON primitives only.

| Key | Type | Meaning |
|---|---|---|
| `figure` | object | Plotly figure `{data: [{type: "sankey", ...}], layout: {...}}`. Pass `data` and `layout` straight to `Plotly.newPlot`. Theme colours, fonts, title and height are inside; `layout.autosize` is true, so use `{responsive: true}` |
| `legend` | list of `{label, color, kind, value}` | The in-figure Sankey legend, repeated for the page. Empty in `node` and `mono` colour modes. Filled in `category` mode (`kind: "category"`, `value` is the drawn flow; the `Other` and `Uncategorized` buckets are category items) and in `layer` mode (`kind: "layer"`, `value` is `null`). The type also allows `node`, which the current renderer does not emit |
| `donut_available` | boolean | True if and only if at least one drawn link is categorised |
| `donut` | figure or `null` | `{data: [{type: "pie", ...}], layout}`. `null` exactly when `donut_available` is false |
| `donut_empty_reason` | `"no_categories"`, `"basis_empty"` or `null` | `"no_categories"` exactly when there is no donut. `"basis_empty"` when a donut exists but the chosen `basis` selects nothing; its figure then only shows an empty-state note |
| `categories` | list of `{name, color, value, share, kind}` | The donut as a table (needed for light-mode contrast). `kind` is `category`, `uncategorized` or `other`. Empty when there is no donut |
| `category_names` | list of strings | Every real category in slot order (display spelling), including those folded into `Other`: the data list for a category input |
| `stats` | object | `nodes`, `links`, `drawn_links`, `total_in`, `total_out`, `layers`, `category_count` |
| `entries` | list of entry rows | A preview of the entries table, at most 2000 rows. Page it with `POST /entries` |
| `entries_total` | integer | All pairs |
| `warnings` | list of strings | Human-readable notes: skipped rows with line numbers, `Showing N of M links`, `Removed N link(s) that closed a cycle`, the category cap, a truncated Mongo result, and so on |

`stats.links` and `stats.nodes` describe the built graph; `drawn_links` is `links` capped by `max_drawn_links`.
`total_in` is the flow leaving the source nodes and `total_out` the flow arriving at the sink nodes.
`drawn_links` below `links` means the figure was cut to the largest links; the figure carries its own note and
`warnings` repeats it.

A small example (manual graph, `theme=light`; node and link arrays are real, repeated `font` objects are shortened to
`{...}`):

```json
{
 "figure": {
  "data": [{"type": "sankey", "orientation": "h", "arrangement": "snap", "valueformat": ",.2~f", "valuesuffix": "",
            "textfont": {"family": "system-ui, -apple-system, \"Segoe UI\", sans-serif", "size": 13, "color": "#0b0b0b"},
            "hoverlabel": {"bgcolor": "#fcfcfb", "bordercolor": "#898781", "font": {"...": "..."}},
            "domain": {"x": [0, 1], "y": [0, 1]},
            "node": {"label": ["Salary", "Rent", "Food"], "color": ["#2a78d6", "#eb6834", "#1baf7a"], "pad": 16,
                     "thickness": 18, "line": {"color": "#fcfcfb", "width": 2},
                     "customdata": [["Salary", "0", "1,600"], ["Rent", "1,200", "0"], ["Food", "400", "0"]],
                     "hovertemplate": "%{customdata[0]}<br>In: %{customdata[1]}<br>Out: %{customdata[2]}<extra></extra>"},
            "link": {"source": [0, 0], "target": [1, 2], "value": [1200.0, 400.0],
                     "color": ["rgba(42, 120, 214, 0.4)", "rgba(42, 120, 214, 0.4)"],
                     "customdata": [["Salary", "Rent", "1,200", "75.0%", "100.0%", "Fixed"],
                                    ["Salary", "Food", "400", "25.0%", "100.0%", "Uncategorized"]],
                     "hovertemplate": "%{customdata[0]} → %{customdata[1]}<br><b>%{customdata[2]}</b><br>..."}}],
  "layout": {"autosize": true, "font": {"...": "..."}, "paper_bgcolor": "#fcfcfb", "plot_bgcolor": "#fcfcfb",
             "hoverlabel": {"...": "..."}, "modebar": {"bgcolor": "rgba(0, 0, 0, 0)", "color": "#898781",
                                                      "activecolor": "#0b0b0b"},
             "legend": {"font": {"...": "..."}, "bgcolor": "rgba(0, 0, 0, 0)"},
             "title": {"text": "Tiny", "font": {"...": "..."}, "x": 0, "xref": "container", "xanchor": "left",
                       "y": 1, "yref": "container", "yanchor": "top", "pad": {"l": 16, "t": 16}},
             "height": 240, "margin": {"l": 16, "r": 16, "t": 52, "b": 16}, "annotations": [], "showlegend": false}},
 "legend": [],
 "donut_available": true,
 "donut": {"data": [{"type": "pie", "...": "..."}], "layout": {"...": "..."}},
 "donut_empty_reason": null,
 "categories": [{"name": "Fixed", "color": "#2a78d6", "value": 1200.0, "share": 0.75, "kind": "category"},
                {"name": "Uncategorized", "color": "#898781", "value": 400.0, "share": 0.25, "kind": "uncategorized"}],
 "category_names": ["Fixed"],
 "stats": {"nodes": 3, "links": 2, "drawn_links": 2, "total_in": 1600.0, "total_out": 1600.0, "layers": 2,
           "category_count": 1},
 "entries": [{"source": "Salary", "target": "Rent", "value": 1200.0, "category": "Fixed", "mixed": false,
              "overridden": false},
             {"source": "Salary", "target": "Food", "value": 400.0, "category": null, "mixed": false,
              "overridden": false}],
 "entries_total": 2,
 "warnings": []
}
```

The donut figure has the same shape; its `data[0]` is `{"type": "pie", "labels": ["Fixed", "Uncategorized"],
"values": [1200.0, 400.0], "hole": 0.58, "sort": false, "marker": {"colors": [...]}, "textinfo": "label+percent",
"showlegend": true, ...}` plus a centre annotation with the total.

A graph without categories gives `"donut_available": false`, `"donut": null`, `"donut_empty_reason":
"no_categories"` and `"categories": []`. The donut tab, the category legend and the `category` colour mode are shown
only when `donut_available` is true; a client must never treat the missing donut as an error.

**Text in figures.** Every user string that enters a figure (node labels, link and node hover text, legend entries,
donut slice labels, category names, the title, the note, `valuesuffix`) goes through `escape_label`. It first removes
the characters that have no glyph or that change the text around them (all C0 controls including tab, line feed and
carriage return, DEL, the C1 block U+0080 to U+009F, the bidirectional embeddings and overrides U+202A to U+202E and
the isolates U+2066 to U+2069), then escapes `&`, `<` and `>` as entities, which Plotly decodes back to the typed
characters. Quotes are not escaped, because Plotly does not decode `&quot;`. The result: a node named
`<a href=javascript:1>x</a><b>y</b><br>` is drawn as exactly that text, never as a link, bold text or a line break,
and SVG and PNG exports stay valid. Node labels longer than 32 characters are cut in the figure and the full name is
in the hover text.

The fields of the bundle that are not figures (`legend[].label`, `categories[].name`, `category_names`, `entries`)
keep the names as stored; put them in the DOM with `textContent`. A figure text such as `valuesuffix` is
Plotly-escaped (`&lt;b&gt;$`); never show it as plain DOM text, take `style.value_suffix` from the graph instead.

The donut figure with `donut_empty_reason: "basis_empty"` carries `layout.xaxis.visible` and `layout.yaxis.visible`
set to false, like the Sankey legend layout, so no axes are drawn.

Rendering in the browser, under the CSP above:

```js
Plotly.newPlot(div, bundle.figure.data, bundle.figure.layout, { responsive: true });
// the donut works the same way with bundle.donut
```

---

## 8. Pages and boot data

The pages are plain `GET` routes in `web/routers/pages.py`. Each renders one template, `page.html`, which extends
`base.html`. The root element is `<main data-page="..." data-testid="app-root">`. The behaviour of each page and its
`data-testid` names are documented in the [UI reference](ui.md).

### 8.1 Template context

| Name | Type | Content |
|---|---|---|
| `page` | string | `library`, `new`, `edit`, `viewer`, `compare`, `settings`, `notfound` for the not-found page, or `error` for the other error pages |
| `heading` | string | Text for `<h1>` and the title (`<heading> - Sankey Studio`) |
| `links` | list of `{href, label}` | Navigation (`/`, `/graphs/new`, `/settings`) plus page-specific links |
| `boot` | object | The boot data below |
| `theme` | string | The stored theme (`system`, `light` or `dark`); rendered as `<html data-theme>` so a first visit paints in the saved theme |
| `theme_source` | string | `server` when this server persists the theme (writes allowed; the stored value wins) or `device` in read-only remote mode (the browser's own cached choice wins); rendered as `<html data-theme-source>` |

`boot` is rendered only as `{{ boot|tojson }}` inside `<script type="application/json" id="page-data">`. JavaScript
reads it with `JSON.parse(document.getElementById("page-data").textContent)`. Autoescape is on for every template,
and there is no `|safe` and no `Markup` anywhere; tests also forbid `innerHTML`, `outerHTML`,
`insertAdjacentHTML`, `document.write`, `eval` and `new Function` in `templates/` and `static/`. Each page then loads
`/static/js/core/shell.js` and `/static/js/pages/<module>.js` (`editor.js` serves both `new` and `edit`; the
error pages load only the shell).

Headings and link labels have control characters and bidirectional overrides removed, so a graph name cannot reverse
the text around it; a name that is empty after that shows as `Untitled graph` (`Edit Untitled graph` in the editor).
The boot data keeps the name exactly as stored, so a client falls back the same way.

### 8.2 Boot data per page

Every page gets `{"page": "<name>", "remote_mode": bool, "writes_allowed": bool, "theme": "<stored theme>"}`.
`theme` is `system` if the settings file cannot be read, so a page always loads. Keys are sorted by `tojson`.

| Route | `page` | Heading | Extra boot keys |
|---|---|---|---|
| `GET /` | `library` | `Graphs` | `graphs`: up to 200 newest `GraphSummary`; `total`: number of graphs. The page then calls `GET /api/v1/graphs` for search, tags and paging |
| `GET /graphs/new` | `new` | `New graph` | `graph: null` |
| `GET /graphs/{id}` | `viewer` | the graph name | `graph`: a `GraphSummary` |
| `GET /graphs/{id}/edit` | `edit` | `Edit <name>` | `graph`: a `GraphSummary` |
| `GET /compare?ids=a,b` | `compare` | `Compare graphs` | `ids`, `graphs`, `missing` (below) |
| `GET /settings` | `settings` | `Settings` | none |
| not-found page | `notfound` | `Page not found` or `Graph not found` | `kind`: `page` or `graph` |
| error page | `error` | `Graph database unavailable`, `Graphs folder unavailable` or `Something went wrong` | `kind`: `database`, `folder` or `server` |

`GraphSummary` is `{id, name, description, tags, source_type, revision, updated_at}`. The editor and the viewer fetch
the full `GraphDefinition` with `GET /api/v1/graphs/{id}`, then the bundle with `GET /api/v1/graphs/{id}/render`.

Library boot data:

```json
{"graphs": [{"description": "Smoke graph", "id": "0a95...", "name": "Household budget", "revision": 1,
             "source_type": "text", "tags": ["smoke", "demo"], "updated_at": "2026-10-10T19:48:26.466000Z"}],
 "page": "library", "remote_mode": false, "theme": "system", "total": 2, "writes_allowed": true}
```

**Compare.** `?ids=` takes 0 to 12 distinct graph ids, comma separated or repeated; blanks and repeats are dropped.

- `ids` is every id the address named, in order, so the client keeps asking for them. `graphs` holds the summaries
  of the ones that exist (the names for the cards). `missing` lists the ids that do not exist: the client draws a
  "This graph is gone" card for each at once and does not request them, so a deleted graph causes no 404 on load.
- `/compare` and `/compare?ids=` are the empty compare page: HTTP 200 with `ids`, `graphs` and `missing` all `[]`.
  It is also the address the client leaves to after the last card is removed.
- A malformed id, more than 12 ids, or any other query parameter is 422 JSON `validation_error` for non-browser
  clients. A browser navigation gets the HTML not-found page with status 404.

A graph deleted after the page loaded is still a 404 from `GET /api/v1/graphs/{id}`; the page script handles it
(a toast and a link back to `/`).

### 8.3 Error pages

A browser navigation is a `GET` whose `Accept` header contains `text/html`, for a path that is not under `/api/` and
not under `/static/`. For it, every error answers with an HTML page in the app shell (`templates/error.html`, same
header, navigation, theme switch and banners, only the shell script loaded) and the status of the error, never with
the JSON envelope:

| Case | Status | `kind` | Heading |
|---|---|---|---|
| An unknown URL | 404 | `page` | `Page not found` |
| A graph page (`/graphs/{id}`, `/graphs/{id}/edit`) whose graph is gone or whose id is malformed | 404 | `graph` | `Graph not found` |
| A page query that is not valid (`/compare?ids=bad`) | 404 | `page` | `Page not found` |
| The graph store is unreachable (503 `storage_error`) and graphs live in MongoDB | 503 | `database` | `Graph database unavailable` |
| The graph store is unusable and graphs live in the graphs folder | 503 | `folder` | `Graphs folder unavailable` |
| Any other domain or HTTP error of a page (503 `busy`, 502, 409, 405, ...), and every unexpected failure | the error's | `server` | `Something went wrong` |

`Content-Type: text/html; charset=utf-8`, `Cache-Control: no-store`, the security headers of [section 2.4](#24-response-headers-and-csp).
The body is the heading (also the `<h1>` and `<title>`) and one fixed sentence in a card:

| `kind` | Card | Sentence | Links |
|---|---|---|---|
| `page`, `graph` | `data-testid="state-empty"` | There is nothing at this address, so the link may be wrong or out of date. / This graph does not exist any more, or the link is wrong. | `Back to the library` (`/`) |
| `database` | `data-testid="state-error"`, `role="alert"` | The graph database is not reachable right now. Check that MongoDB is running, then reload. | `Reload`, `Back to the library`, `Open Settings` |
| `folder` | same | The graphs folder cannot be read right now. Check that it exists and that you can read it, then reload. | same |
| `server` | same | The server could not show this page. Reload it, or go back to the library. | same |

`Reload` (`data-testid="state-retry"`) is a plain link with `href=""`: the browser resolves it to the same path and
query, so the address is not written into the page and no script is needed. The page never contains the requested
URL, id, query, the message or the details of the error, or any other request text. `/graphs/new` and `/settings`
do not read the graph store and open normally while it is down.

Every other client keeps the JSON envelope: curl, `fetch` with `Accept: */*` or `application/json`, requests with no
`Accept`, every `/api/...` and `/static/...` path, and every method other than `GET`. Chrome logs one "Failed to
load resource" console line for the document itself; that is the real status, not a failed asset.

`Cache-Control: no-store` on every HTML answer means Back and Forward re-request the page instead of showing one
rendered before the change; it also makes the page ineligible for the browser's back/forward cache.

---

## 9. Pagination, caps and caching

| Limit | Value |
|---|---|
| `GET /graphs` page size | `limit` 1 to 200, default 200; `offset` from 0; `total` counts all matches |
| Entries page (`POST /entries`) | `limit` 1 to 500, default 100 |
| Entries preview inside a `RenderBundle` | 2000 rows; `entries_total` has the full count |
| Library boot data | the 200 newest graphs |
| Bundle export | 1 to 200 ids, 16 MiB in UTF-8 |
| Bundle import | 16 MiB body, 1000 graphs, 50 reported errors |
| Compare | 1 to 12 ids |
| Error `details` | 50 entries of at most 300 characters |
| JSON body | 8 MiB |
| Upload body | `max_upload_mb` (1 to 100) plus 1 MiB |
| Inline text `content` | 2,000,000 characters |
| Manual links | 5000 |
| Raw rows per source (`max_links`) | 100 to 5,000,000, default 200,000; beyond it 413 `graph_too_large` |
| Links drawn per figure (`max_drawn_links`) | 50 to 20,000, default 3,000; the largest links are drawn and a note says `Showing N of M links` |
| Distinct categories per graph | 200 |
| Image export | 200..4000 pixels per side, scale 1..4, 36,000,000 pixels, 5000 links, 2000 nodes, one at a time, 30 seconds |
| Source file preview | 50 lines, 500 characters per line, 64 KiB |
| Mongo sample | `n` 1 to 20 |
| Concurrent storage probes | 4 |
| Concurrent Mongo operations per connection | 4 |

**Graph cache.** Built graphs are kept in a small in-memory cache so that paging or filtering the entries table does
not parse the same file or query the same collection on every request. The key is a hash of the source, the
transform, `max_links` and, for files, the file's stamp. At most 16 graphs are kept, for 120 seconds (inline text,
manual links and files) or 30 seconds (MongoDB sources, which can change underneath). A file modified within the
last two seconds is not cached. Errors are never cached. A Mongo-backed preview can therefore show data up to 30
seconds old.

---

## 10. Client recipes

**A JSON request from a browser.**

```js
async function api(path, { method = "GET", body } = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init); // root-relative: /api/v1/...
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error.message), data.error);
  return data;
}
```

**A script (curl).**

```sh
curl -sS -X POST http://127.0.0.1:8765/api/v1/preview \
  -H 'Content-Type: application/json' \
  -d '{"source": {"type": "text", "content": "A,B,5\nB,C,3", "has_header": false}}'

curl -sS -X DELETE http://127.0.0.1:8765/api/v1/graphs/<id> \
  -H 'Origin: http://127.0.0.1:8765'
```

**Saving with a conflict.** Send the `revision` you loaded. On 409 offer "reload" (`GET /graphs/{id}`) or "save as
copy" (`POST /graphs` with the current content). On 200 keep the returned `revision` for the next save.

**Uploading a file.** `const form = new FormData(); form.append("file", file); form.append("overwrite", "false");`
then `fetch("/api/v1/sources/files", { method: "POST", body: form })`. Do not set `Content-Type`.

**Round-tripping settings.** `GET /settings`, change what the user edited, `PUT` it back. Connections the user did
not touch keep their secrets because `uri` is absent or masked. Send `previous_name` when a connection is renamed.

**Drawing a chart.** `GET /graphs/{id}/render?theme=dark` (or `POST /preview` for a draft), then
`Plotly.newPlot(div, bundle.figure.data, bundle.figure.layout, { responsive: true })`. Show the donut tab only when
`bundle.donut_available` is true. On a theme switch, request the bundle again with the other theme.

**Downloading an export.** `fetch` the export URL, check `response.ok`, read `blob()`, take the name from
`Content-Disposition` (`filename*` first), then click a temporary `<a download>`. On 422 `export_too_large` or 501,
502, 503, 504, fall back to `Plotly.downloadImage` and use the file-name scheme of [section 5.4](#54-exports).
