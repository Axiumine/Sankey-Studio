# UI reference

The browser interface of Sankey Studio: the pages and the states they pass through, the
`data-testid` contract that end-to-end tests rely on, the DOM signals tests wait on instead of
sleeping, theming, accessibility, the rules every frontend change follows and how to start a
server for browser tests. It is written for developers who change the frontend and for anyone who
writes browser tests. The statements were checked against the templates in
`src/sankey_studio/web/templates`, the scripts and style sheets in `src/sankey_studio/web/static`
and the page routes; where an older description and the code differed, the code won. Statements
about timings, console output and download sizes come from runs in real Chrome.

Related: [api.md](api.md) (routes, error envelope, request rules), [architecture.md](architecture.md)
(where the frontend sits), [quality.md](quality.md) (the gates that police the frontend),
[decisions.md](decisions.md) (why it is built this way), [e2e.md](e2e.md) (the end-to-end harness).

This page is the index and holds the overview: how the frontend is built and the pages. The rest
is split by page and topic into the files under `docs/ui/`.

Contents

* [How the frontend is built](#how-the-frontend-is-built)
* [Pages](#pages), with [Boot data](#boot-data)
* [The shell and the error pages](ui/shell.md): [The shell](ui/shell.md#the-shell), [Error pages](ui/shell.md#error-pages)
* [Library](ui/library.md)
* [Editor](ui/editor.md)
* [Viewer and compare](ui/viewer.md): [Viewer](ui/viewer.md#viewer), [Compare](ui/viewer.md#compare)
* [Settings](ui/settings.md)
* [data-testid reference](ui/testids.md#data-testid-reference)
* [Browser testing](ui/testing.md): [DOM wait signals](ui/testing.md#dom-wait-signals),
  [Starting a server for browser tests](ui/testing.md#starting-a-server-for-browser-tests),
  [Expected console and network noise](ui/testing.md#expected-console-and-network-noise),
  [Known quirks](ui/testing.md#known-quirks)
* [Theming, accessibility and frontend rules](ui/frontend.md): [Theming](ui/frontend.md#theming),
  [Accessibility](ui/frontend.md#accessibility), [Frontend rules](ui/frontend.md#frontend-rules)

## How the frontend is built

The server renders one HTML shell per page and a page module draws everything else in the browser.
There is no build step, no bundler and no framework.

* `templates/base.html` is the document skeleton, `templates/page.html` extends it with the header,
  banners, `main` element, toast region and scripts, and `templates/error.html` extends `page.html`
  for the error pages (not found, store unreachable, server error). `templates/partials/icons.html` holds the
  inline icons of the shell.
* Each page loads `static/js/core/shell.js` and one page module, `static/js/pages/<module>.js`
  (`new` and `edit` both use `editor.js`). The module imports plain ES modules from `core/`,
  `library/`, `editor/`, `viewer/`, `compare/` and `settings/`.
* Templates link every `/static` file through `static_url("css/layout.css")`, which gives
  `/static/v-<digest>/css/layout.css` (the first 12 hex characters of the SHA-256 of the whole static
  directory, `web/assets.py`). Modules import each other by relative path and a script loads a style
  sheet with `new URL("../../css/x.css", import.meta.url)`, never an absolute `/static/...` path (a
  policy test enforces it), so every file of a page shares the prefix and a new version is a new URL
  for all of them: no browser keeps an old style sheet or script. Static answers are `no-store`
  (no `ETag`, never a 304), plotly.js included: the browser keeps nothing between reloads.
* Markup is built only with `h()` from `core/dom.js` (`createElement`, `setAttribute`,
  `createTextNode`). Every string child is a text node, so a graph name, a category or a server
  message can never become markup.
* Page data enters through the JSON block `<script type="application/json" id="page-data">`, read by
  `core/boot.js`. Everything else is fetched from `/api/v1` by the one fetch wrapper `core/api.js`.
* Style sheets: `css/tokens.css` (design tokens), `base.css`, `components.css`, `layout.css`, then
  one sheet per page. The template links `css/pages/<module>.css`; the real page sheets are
  `css/pages-library.css`, `pages-viewer.css`, `pages-compare.css`, `pages-editor.css` and
  `pages-editor-output.css`, which the page scripts load before they draw, so nothing paints
  unstyled. The settings sheet is `css/pages/settings.css`.
* plotly.js is served from the installed plotly package at `/static/vendor/plotly.min.js` (never from
  a CDN) and is injected only by pages that draw a chart.

## Pages

| Page | URL | `main[data-page]` | `h1` and title | Script |
|---|---|---|---|---|
| [Library](ui/library.md) | `/` (`?q=&tag=&sort=&page=&folder=`) | `library` | Graphs | `pages/library.js` |
| [New graph](ui/editor.md) | `/graphs/new` (`?folder=<id>`) | `new` | New graph | `pages/editor.js` |
| [Editor](ui/editor.md) | `/graphs/<id>/edit` | `edit` | Edit `<name>` | `pages/editor.js` |
| [Viewer](ui/viewer.md#viewer) | `/graphs/<id>` | `viewer` | the graph name | `pages/viewer.js` |
| [Compare](ui/viewer.md#compare) | `/compare?ids=a,b,c` | `compare` | Compare graphs | `pages/compare.js` |
| [Settings](ui/settings.md) | `/settings` | `settings` | Settings | `pages/settings.js` |
| [Not found](ui/shell.md#error-pages) | any unknown URL, a gone graph, an invalid compare link | `notfound` | Page not found or Graph not found | `core/shell.js` only |
| [Error](ui/shell.md#error-pages) | any other error of a page: graph store unreachable (503), any other failure | `error` | Graph database unavailable, Graphs folder unavailable or Something went wrong | `core/shell.js` only |

* The document title is `<h1 text> - Sankey Studio`. Graph ids are 32 lowercase hex characters.
* A graph whose name is empty once control and bidirectional characters are removed is called
  `Untitled graph` in every heading, title, card, menu, dialog and toast (the editor heading is
  `Edit Untitled graph`). The stored name is never rewritten; only the display falls back.
* The editor heading is `New graph` while the graph has no name, `New graph: <name>` while an unsaved
  graph has one, and `Edit <name>` once it is saved; it follows the name.
* Every HTML page answers `Cache-Control: no-store`, so Back and Forward ask the server again.
* After the first save of a new graph the address becomes `/graphs/<id>/edit` through
  `history.replaceState`: there is no navigation or load event.
* `/compare` and `/compare?ids=` are valid (HTTP 200, empty state). `/compare` takes 1 to 12
  distinct ids; blank and repeated ids are dropped (`?ids=a,,b,a` is two graphs).

### Boot data

Every page embeds `page`, `remote_mode`, `writes_allowed` and `theme`. Extra keys:

| Page | Extra keys |
|---|---|
| Library | `graphs` (up to 200 newest `GraphSummary` objects directly in the open collection), `total`, `folders` (every collection with its graph and child counts), `folder` (the open collection's id, `null` at the top level) |
| New graph | `graph: null`, `folder_id` (the existing collection `?folder=` names, else `null`) |
| Editor and viewer | `graph` (a `GraphSummary`: `id`, `name`, `description`, `tags`, `source_type`, `revision`, `updated_at`) |
| Compare | `ids` (every id of the address, deduplicated, at most 12), `graphs` (summaries of the ones that exist), `missing` (ids with no graph) |
| Settings | none |
| Not found | `kind`: `page` or `graph` |
| Error | `kind`: `database`, `folder` or `server` (see [Error pages](ui/shell.md#error-pages)) |

`<html data-theme="system|light|dark">` is rendered from the stored setting. `data-theme-source` is
`server` when the server persists changes (the stored theme wins) and `device` on a read-only server
(this browser's cached choice wins).
