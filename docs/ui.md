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

Contents

* [How the frontend is built](#how-the-frontend-is-built)
* [Pages](#pages)
* [The shell](#the-shell)
* [Library](#library)
* [Editor](#editor)
* [Viewer](#viewer)
* [Compare](#compare)
* [Settings](#settings)
* [Error pages](#error-pages)
* [data-testid reference](#data-testid-reference)
* [DOM wait signals](#dom-wait-signals)
* [Theming](#theming)
* [Accessibility](#accessibility)
* [Frontend rules](#frontend-rules)
* [Starting a server for browser tests](#starting-a-server-for-browser-tests)
* [Expected console and network noise](#expected-console-and-network-noise)
* [Known quirks](#known-quirks)

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
| Library | `/` (`?q=&tag=&sort=&page=&folder=`) | `library` | Graphs | `pages/library.js` |
| New graph | `/graphs/new` (`?folder=<id>`) | `new` | New graph | `pages/editor.js` |
| Editor | `/graphs/<id>/edit` | `edit` | Edit `<name>` | `pages/editor.js` |
| Viewer | `/graphs/<id>` | `viewer` | the graph name | `pages/viewer.js` |
| Compare | `/compare?ids=a,b,c` | `compare` | Compare graphs | `pages/compare.js` |
| Settings | `/settings` | `settings` | Settings | `pages/settings.js` |
| Not found | any unknown URL, a gone graph, an invalid compare link | `notfound` | Page not found or Graph not found | `core/shell.js` only |
| Error | any other error of a page: graph store unreachable (503), any other failure | `error` | Graph database unavailable, Graphs folder unavailable or Something went wrong | `core/shell.js` only |

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

`<html data-theme="system|light|dark">` is rendered from the stored setting. `data-theme-source` is
`server` when the server persists changes (the stored theme wins) and `device` on a read-only server
(this browser's cached choice wins).

## The shell

The shell is rendered by `page.html` and is present in every state of every page, the error pages
included.

* `a.skip-link` ("Skip to main content") targets `#main`.
* `#loading-bar` (`loading`, `role=progressbar`, label "Loading") is `hidden` unless a non-quiet API
  request has been running for 150 ms. It is not a page-ready signal.
* `header.app-header`: the brand link (`aria-label` "Sankey Studio, home"), `nav.main-nav`
  (`aria-label` "Main") with `nav-library`, `nav-new` and
  `nav-settings`, and the `theme-switch` group (`aria-label` "Colour theme") with three buttons
  `[data-theme-value=system|light|dark]`, accessible names "System theme", "Light theme" and "Dark
  theme", `aria-pressed` following the chosen theme. `aria-current=page` marks `nav-library` on the
  library, `nav-new` on the new-graph page and `nav-settings` on settings; the library link gets the
  class `is-section` on the editor, viewer and compare pages instead. The link with `aria-current=page`
  or `is-section` is the one drawn in the accent (blue) colour; the other links are plain text.
* `remote-banner` (only when the server was started with `--allow-remote`) and `read-only-banner`
  (only when `writes_allowed` is false, which is remote mode without `--allow-remote-writes`).
* `main#main.app-main` carries `data-page`, `data-testid="app-root"`, `data-loading` and
  `tabindex=-1`. Inside it: `.page-head` with the `h1` and `#page-actions` (the buttons next to the
  heading), then `#page-root`, where the page module draws. Without JavaScript `#page-root` shows a
  `noscript` notice and the links of the page.
* Outside `#app`: the toast region `#toast-region`, the screen-reader regions `#a11y-polite` and
  `#a11y-assertive`, the boot block and the scripts.

Behaviour shared by every page:

* **Theme switch.** A click applies the theme at once (`html[data-theme]` changes), caches it in
  `localStorage` (`sankey-studio.theme`) and, when writes are allowed, saves it: `GET /settings`, then
  `PUT /settings` with the new `theme` (skipped when the stored theme already matches). A failed save
  shows one info toast and the theme lasts until reload. On a read-only server nothing is sent.
  All settings writes (theme switch, theme cards, Save settings) share one queue, so they never
  overwrite one another.
* **Toasts** (`toast`, `data-kind` success, error, info or warning). They disappear after 5 s (error
  9 s, warning 7 s; the "Created ... copy" toast stays 12 s); hover or keyboard focus on a toast
  pauses its timer. Errors have `role=alert`. A message that is already visible is not stacked. At
  most 4 are visible (1 when the window is shorter than 520 px, 2 when it is shorter than
  640 px). They sit bottom-left (16 px from the edge, 24 rem wide) on wide screens, along the bottom on phones, lifted above a
  docked save bar, and the page scrolls so the focused control is never under the stack.
* **Dialogs** (`confirm-dialog` and the page-specific ones) are `role=dialog` with `aria-modal`. While
  one is open `#app` is `inert`, `html` has the class `is-modal`, Tab is trapped, Esc or a
  mousedown on the backdrop cancels, and focus returns to the opener. A dangerous confirmation
  (delete, replace file) starts on its Cancel button, so pressing Enter right away cancels. A dialog
  can show an X in its header (`dialog-close`) that closes like Esc. Dialogs may stack (the consent
  question opens above the Add dialog): Esc closes only the newest.
* **Popovers and menus** (`core/popover.js`, `core/menu.js`). A popover is NOT modal: the page stays
  usable behind it, only one is open at a time, Esc closes it and returns the focus to its trigger,
  a press outside it or the focus leaving it closes it without moving the focus, and print hides it.
  A menu is a popover with the ARIA menu-button keys: Enter, Space, a click or ArrowDown on the button
  open it on the first item (ArrowUp on the last), the arrows wrap, Home and End jump, Tab closes it, and
  choosing an item closes it with the focus back on the button before the item's action runs (so a
  dialog it opens returns the focus there).
* **Read-only servers.** Controls marked `data-writes` are disabled with the title "Not available:
  this server is read-only" (links lose their `href`). Previews and exports keep working.
* **Shared state blocks** (`core/states.js`): `state-empty` (title, message, optional actions),
  `state-error` (`role=alert`, with a `state-retry` "Try again" button when a retry makes sense) and
  `state-loading` (`role=status`, `aria-busy=true`, skeleton). Pages and panels reuse them for their
  empty, error and loading states.

## Library

`/` lists the saved graphs of the open collection, 12 cards per page. The top level lists the graphs that
sit in no collection. A collection is called "collection" in every visible text and `folder` in every
identifier, address and test id.

Layout: the page actions hold the buttons "New collection" and, inside a collection, "New graph here",
then a group "Bundle" with Import and Export; then, on a read-only server, a note; the breadcrumb (inside
a collection); the toolbar (search, sort, "Clear filters", tag chips); the "Collections (N)" block of
cards for the open level; the results (count line, optional note, card grid); the pager (`nav`, label
"Pages of graphs"); the selection bar.

States:

| State | What is on screen |
|---|---|
| Loading | `state-loading` "Loading graphs", only when the first paint cannot use the boot data (a filter in the address, or arrival by Back or Forward) |
| Ready | `graph-card` elements and `library-count` ("Showing 1-12 of 32 graphs" with an en dash; "5 graphs" when everything fits one page; filters are appended, for example `matching "rent"` or `tagged "demo"`) |
| Empty library | `library-empty` ("No graphs yet"; "Create your first graph" and "Import a bundle" actions when writes are allowed, a read-only sentence otherwise). Shown only when there is no graph and no collection at all |
| Empty collection | `library-folder-empty` (an open collection with no graph and no sub-collection: "New graph here" and "New collection", and the sentence "Create a graph here, or move graphs in with the Move button on their cards or by dragging them onto this collection one level up."; on a read-only server the sentence "This server is read-only, so graphs cannot be created or moved here." and no buttons). A level that has collections but no graphs shows a plain hint ("There are no graphs outside the collections." or "...directly in this collection."), never "No graphs yet" |
| Missing collection | `library-folder-missing` ("This collection no longer exists", a link "Back to the library"): a well-formed id in the address that names no collection. No list request is made and there is no "New collection" |
| No match | `library-no-results` ("No graphs match", with a "Clear filters" button) |
| Error | `state-error` "The library could not be loaded" with `state-retry` |
| Selection | `selection-bar` visible while at least one card is ticked |

Behaviour:

* A plain visit paints from the boot data and makes no list request. Back and Forward (and a page
  restored from the browser cache) ask the API again.
* The query lives in the address and is written with `replaceState`: `q` (at most 200 characters),
  `tag` (40), `sort` (`updated-desc` default, `updated-asc`, `name-asc`, `name-desc`) and `page`.
  Defaults are left out. A page number beyond the last page opens the last page; `0`, `abc` and `-3`
  open the first. A search or tag made only of control or bidirectional characters is no filter.
* `updated-desc` pages on the server. The other sorts load up to 1,000 matching graphs, sort them in
  the browser and show the note "This order covers the 1,000 most recently updated graphs that
  match." when more exist.
* Search is debounced by 250 ms and Enter searches at once. The URL, count and cards follow.
* Tag chips are `library-tag-filter` buttons (`data-tag`, `aria-pressed`); a second click clears the
  tag. More than 10 tags collapse behind "Show N more" ("Show fewer tags"); the active tag always
  shows. A card shows 4 tags and "+N more".
* A card holds the compare checkbox (`aria-label` `Select "<name>" to compare`), the name link, the
  description, tags, a source badge (Text data, Manual table or MongoDB), "Updated <relative time>",
  `Rev N` and the actions Edit, Duplicate and Delete (accessible names `Edit "<name>"` and so on).
  Duplicate and Delete carry `data-writes`.
* **Collections.** `/?folder=<id>` is a real link, so reload, Back, Forward and "open in a new tab" need
  no script. Anything that is not a 32-hex id reads as the top level (no error). The first paint uses the
  boot data (`graphs`, `folders`, `folder`) and makes no list request. While there is no search text and no
  tag, the list, count, pager and sort stay inside the open collection (`GET /graphs?folder=root|<id>`,
  the sorts other than `updated-desc` load that collection's graphs only); a search or a tag looks at
  EVERY collection (no `folder` is sent), hides the breadcrumb and the collection cards, shows
  `library-scope-note` ("Searching all collections.") and puts a chip `graph-folder` with the path
  ("Finance / Q3 reports", a link to that collection) on each result.
* `folder-breadcrumb` reads `Library / A / B`: `folder-crumb` is on every link, "Library" included, and the
  last one has `aria-current=page`. It is hidden at the top level, while searching and for a missing
  collection; long names are cut with an ellipsis.
* The collection cards sit in `folder-grid` under "Collections (N)": a `folder-card` (`data-folder-id`)
  with the name link `folder-open`, "N graphs, M collections", and the buttons Rename (`folder-rename`),
  Move (`folder-move`) and Delete (`folder-delete`). `folder-new` ("New collection") and `folder-new-graph`
  ("New graph here", a link to `/graphs/new?folder=<id>`) are in the page actions, not in the block; both
  are hidden while searching and "New collection" is hidden inside a collection that is already 8 levels
  deep. A graph card gets `graph-move` ("Move") once at least one collection exists, and the selection bar
  `selection-move` ("Move to collection"; the cap of 12 is shared with compare).
* `folder-dialog` creates and renames (`folder-name-input`, `folder-name-error`, `folder-name-confirm`):
  Enter submits (not while composing), an empty name keeps the dialog ("Give the collection a name."), so
  does a taken name ("A collection with this name already exists in that place. Choose another name."), a
  second Enter while the request runs sends nothing, and the field stops at 100 characters. `move-dialog`
  is a radio tree, "Library (top level)" first and the collections below it, children indented by their
  depth: `move-option` is the label of each radio (`data-folder-id`, `root` for the top level) and
  `move-confirm` ("Move here") stays disabled until a choice is made. Places that cannot be chosen stay
  visible, disabled, with their reason ("already here", "inside the collection being moved", "too deep (at
  most 8 levels)"); the arrow keys choose and Tab reaches "Move here". A refused move shows its sentence
  in `folder-name-error`, which is the error line of this dialog too. `folder-delete-dialog` starts on
  Cancel, says how many graphs and collections move up to the library and that no graph is deleted, and
  `folder-delete-confirm` deletes.
* **Drag and drop** does the same two moves as the Move dialog (graphs into a collection, a collection into
  another one) with the pointer and without a dialog. The Move buttons stay: they are the keyboard,
  screen reader and touch way to the same moves, and the empty-collection text points at both.
  * *Sources.* A `graph-card` and a `folder-card` carry `draggable="true"` only while writes are allowed
    and the list follows the open collection (no search, no tag); a `graph-card` also needs at least one
    collection to exist. On a read-only server and in search results no card has the attribute and nothing
    reacts. The attribute is set when the cards are drawn and flips to `"false"` while the pointer is over a
    button, the compare checkbox, the description, the meta line or the tags (`dnd-grip.js`), so the mouse
    still selects that text and a click that wobbles still counts; the card padding, the head and the name
    link are the handles. A picked graph (compare checkbox) carries every picked graph in selection order
    (at most 12) and the selection is cleared by the move; an unpicked graph carries only itself and leaves
    the picks alone.
  * *Targets.* The `folder-card`s and the `folder-crumb`s (`data-folder-id`; `root` is "Library", the top
    level). Graph cards are no targets: there is no reordering and no drop on the list. Anything that did
    not start on the page (a file, text, a link from another page or tab) is ignored completely: no mark,
    no `preventDefault`, no request.
  * *Refusals.* The sentences of the Move dialog, from one source (`folder-rules.js`): "already here" (a
    graph on the open collection, a collection on its own parent; both are the last crumb), "inside the
    collection being moved" (a collection on itself or on one of its own sub-collections) and "too deep (at
    most 8 levels)". Graphs picked in a search can sit anywhere, so no place is "already here" for them.
    "that collection no longer exists" is new: the dragged collection or the target is no longer in the
    list the page holds. A refusing target gets `data-drop="denied"` with the sentence in
    `data-drop-reason` (there is no tooltip), a dashed outline, and the polite live region says "Not
    possible: <reason>" once when the pointer enters it; the pointer shows the no-drop cursor and a drop
    there sends nothing. A target that accepts gets `data-drop="ok"` and a solid accent outline.
  * *Marks.* The carried cards have `data-dragging="true"` (half opacity), set one animation frame after
    the drag starts. All marks go away when the drag ends: a drop, Esc, a drop outside every target or the
    window losing focus. In forced-colors mode the outlines are Highlight (accept) and GrayText (refuse).
  * *A drop* runs at once, after the rules were checked again against the live list, and says so in the
    toast of the dialog: `Moved "<name>" to "<collection>".`, `Moved 2 graphs to "<collection>".` or
    `... to the library.` (the quotes in the toast are curly), with the dialog's note when some graphs no
    longer existed. A second drop (or drag) while the request and the reload run is ignored. The focus goes
    where the dialog leaves it: the results summary after graphs, the moved collection's card (else the
    block of cards) after a collection. A collection that is gone (404) or changed elsewhere (stale
    revision) is an info toast and a reload; any other failure (a taken name, a rule of the server, the
    network) is an error toast with the dialog's sentence, then a reload. Nothing is retried.
* When a collection was changed elsewhere, a 404 or a stale revision (409 `conflict`) from a collection
  write shows a toast ("That collection no longer exists..." or "...was changed elsewhere..."), reloads the
  list and closes the dialog; any other failure stays in the dialog under the field. After a create, rename
  or move the card's link takes the focus; after a graph move the summary line does (a drop leaves the
  focus in the same places).
* Duplicate creates `<name> (copy)` (in the collection of the original) and shows the toast `Created "<name> (copy)".` with an "Open
  copy" button; the list reloads and the copy comes first in "Recently updated".
* Delete opens `delete-dialog` (`Delete "<name>"?`, focus on Cancel, confirm button `delete-confirm`
  labelled "Delete graph"); Esc cancels and returns focus to that card's Delete button; confirming
  shows `Deleted "<name>".`.
* Up to 12 cards can be ticked. At 12 the unticked boxes are disabled (title "You can compare up to
  12 graphs at a time") and `compare-limit-message` appears. `compare-open` links to
  `/compare?ids=a,b,...`; with fewer than two ticked it stays visible with `aria-disabled=true` and
  no `href`.
* `library-export` reads "Export" and then "Export all (N)" (no collections), "Export top-level graphs (N)"
  (at the top level when collections exist), "Export this collection (N)" (inside one; disabled while it is
  empty), "Export results (n)" (filter active), "Export selected (k)" (cards ticked) or "Export newest 200
  of 1,010" (more than 200 graphs; a toast repeats the reason). It downloads `sankey-studio-graphs.json`,
  a version 2 bundle that also carries the collections of the exported graphs (parents first).
* Import: `library-import` is a `<label class="btn">` around a visually hidden file input (accepts
  `.json`); use `set_input_files` on it. A readable bundle opens `import-dialog` ("Import graphs",
  "This bundle holds N graphs and M collections.", a line saying that a collection which already exists in
  the same place is reused, Cancel and `import-confirm` "Import"), then `import-report`
  ("Import finished", "Imported N graphs and M collections.", and "N graphs could not be imported." with
  the first problems, among them lines `collection N: ...`; "Nothing was imported" when none went in). A file that is not a bundle gives an error
  toast instead of a dialog. On a read-only server the label has `aria-disabled=true` and the input
  is disabled.
* **Read-only servers.** Browsing collections, opening them and exporting work; every write control
  (`folder-new`, `folder-new-graph`, rename, move, delete, `graph-move`, `selection-move`) carries
  `data-writes`, is disabled with the usual title and "New graph here" loses its `href`. The note says
  duplicating, deleting, moving and importing are turned off. An empty collection says "This server is
  read-only, so graphs cannot be created or moved here." and has no buttons.

## Editor

`/graphs/new` and `/graphs/<id>/edit` share one page. The editor keeps the draft in a store and asks
`POST /api/v1/preview` for a bundle 300 ms after the last change.

Layout, top to bottom: the title row (the `h1` and, right after it, the gear `graph-settings-button`,
then the page actions `view-graph` ("View graph", hidden until the graph is saved)); the chart row
`div.ed-chart-row#editor-output`, full width, with the chart panel (`div[data-panel=chart]`: the tab
strip and, at the right of the header, the chart tools `div.out-chart-tools`: "Order nodes", "Reset
order" while an order is stored, and the gear `chart-settings-button`); the form row `div.ed-form-row`
with the panels `source` and `transform` side by side from 900 px (stacked below); then `entries` (with its
own bounded scroll) and `savebar` (a sticky bar). The chart is NOT sticky: while you edit Source or
Transform it scrolls out of view, and there is no "Go to the chart" link. Below 560 px the action row keeps
its own line so the form does not jump when it fills.

The sections Data source and Transform are native `<details>` elements whose `<summary>` is
`section-source` or `section-transform`. Data source is open by default; Transform is closed, and its
fields are in the DOM but hidden until the summary is clicked. The open or closed choice of each is
remembered in `localStorage` (`sankey-studio.editor.sections`). Style (`section-style`) and Export live
in the chart settings popover, below.

**The title row.** `graph-settings-button` ("Graph settings", a gear) is a sibling right after the `h1` and
opens the menu `graph-settings-menu` with "Edit details" (`graph-settings-details`) and "Change data
source" (`graph-settings-source`); it is an ARIA menu button (see the shell keys above). The gear carries
a red dot and the name "Graph settings, N problems" while the server rejected the name, description or
tags.

* **Graph details** (`details-dialog`, modal, with an X `dialog-close`): name, description and tags, bound to
  the draft as you type (the heading, the dirty flag and the preview follow). "Done" (`details-done`)
  validates the name only: an empty name keeps the dialog, shows "Give the graph a name so you can find
  it later." and focuses the field. Esc, the X and the backdrop close without validating; the focus returns
  to the gear. A second request for the dialog (the gear again, Save, Ctrl+S) reuses the open one.
* **Change data source** (`change-source-dialog`): one radio per kind, `change-source-kind-text|paste|
  upload|manual|mongo` (the current one is preselected and marked "(current)"; MongoDB is disabled with "No
  MongoDB connection is configured" unless it is the current kind). Choosing the kind that is already in use
  makes the primary button read "Edit source settings": it only closes the dialog and focuses the inline tab,
  because the source settings are edited inline. Choosing another kind reads "Change source"
  (`change-source-apply`) and swaps the source through the same cache as the inline tab strip, so going
  back restores what was typed. When the graph holds graph-only edits (category edits, added entries, a
  stored node order) a note says "Changing the source drops N category edits unless you keep them." and the
  checkbox `change-source-keep` ("Keep my graph-only edits", off = dropped) appears. After applying, the
  Data source section is open and the inline tab `source-tab-<kind>` is selected and focused. The inline tab
  strip asks the same question (a dialog "Keep your edits to this graph?" with Cancel, "Drop them", "Keep
  them"; Cancel leaves the tab and the draft alone).

**The new-graph wizard.** `/graphs/new` first shows an inline card `new-wizard` (`data-step` is `details` or
`source`; `#page-root[data-wizard]` mirrors it). It never POSTs, so it works on a read-only server.

* Step 1 (`wizard-step-details`): heading "Name your graph", then name, description and tags (the same
  `editor-name|description|tags` as the details dialog). The name is focused; Enter in it is Next
  (`wizard-next`); an empty name shows "Give the graph a name so you can find it later." and stays.
  `wizard-cancel` is a link to `/` (or `/?folder=<id>` when `?folder=` named a collection).
* Step 2 (`wizard-step-source`): "Where does the data come from?" with the five source tabs (the same
  implementation as the editor's), the checkbox `source-has-header` ("The first row is a header", for the
  text tabs; the F3 case is a headerless paste) and a hint per tab. `wizard-back` returns with the values
  kept. `wizard-later` ("Do it later") exists for Paste and Manual while they are empty and starts an
  empty graph of that kind; Text file, Upload and MongoDB need a choice first. `wizard-create` reads "Start
  editing" and is disabled until the source has input; under the buttons "Nothing is saved until you press
  Save." (read-only server: "This server is read-only: you can draw, not save.").
* Typed input is protected by the leave guard ("Leave without saving?"). Finishing removes the wizard,
  focuses `#main`, announces "Editing <name>" and mounts the editor, which starts as "Not saved yet" with a
  dirty draft; `#page-root[data-ready=true]` appears only then. Each step change announces "Step N of 2: ...".
* `/graphs/new?folder=<id>` carries the collection into the editor (`store.meta.folder_id`, never part of the
  saved body): the first Save creates the graph with `POST /graphs?folder=<id>`. If the collection is gone
  by then (404) the graph is saved at the top level and a warning toast says so ("That collection no
  longer exists, so the graph was saved at the top level of the library.").

**The chart settings popover.** `chart-settings-button` ("Chart settings", a gear in the chart header,
`aria-expanded`) opens `chart-settings-panel` (a non-modal `role=dialog` under the gear, `hidden` while
closed) with the tabs `chart-settings-tab-style` and `chart-settings-tab-export` (the Style section, open and
not remembered, and the Export card) and a close button `chart-settings-close`. The chart stays visible and
live behind it, so a typed title or a changed colour shows at once.

* Opening it from the gear shows the tab used last (Style the first time). Esc or the X closes it and
  returns the focus to the gear; a press or the focus outside closes it without moving the focus; Tab on the
  open gear enters the panel. Print hides it, and at 390 px it stays inside the window.
* While the server rejects a style value (a 422 on `style.*`) the gear shows a red dot and the name "Chart
  settings, N problems", and opening it selects Style with the field error. Clearing the value removes the
  dot.
* Every `export-*` control and `section-style` is inside this panel: open it before using them.

Page states:

| State | What is on screen |
|---|---|
| Wizard | `/graphs/new` only: `new-wizard` is on the page and `#page-root` has no `data-ready` yet |
| Loading | `state-loading` "Loading the editor"; `#page-root` has no `data-ready` yet |
| Load error | `state-error` "The graph could not be loaded" with `state-retry`; or, for a graph deleted after the page opened, `state-empty` "This graph no longer exists" with a link back to the library |
| Ready | `#page-root[data-ready=true]`: the graph and settings are loaded and every panel is mounted (the first chart may still be drawing) |
| Panel failure | the failing panel shows `state-error` "This part could not be loaded" and an error toast; the other panels still work |

Chart panel states (the chart area never jumps; its height is reserved):

* Skeleton while the first preview is in flight (`state-loading`).
* `state-empty` "Nothing to draw yet" when there is no data.
* `state-empty` "No links to draw yet", "No link is left to draw" (Transform filters removed every
  link) or "No row could be read" when the bundle has zero nodes. Plotly cannot draw such a bundle, so
  no chart is drawn.
* `state-error` with the server's explanation, and "Try again" for failures that pass by themselves,
  when a preview fails and there is no chart yet. When a chart exists, a failed refresh keeps it and
  adds a `role=alert` notice above it.
* While a refresh runs the old chart stays, dimmed, with an "Updating" label.

Entries panel states: skeleton "Loading entries"; `state-empty` "No entries yet" (no data) or "No
entries" (no flows); "No entries match" with a clear action; `state-error` "The entries could not be
loaded" (with "Try again" when transient); `aria-busy` on the table block while it refreshes.

What appears when (the DOM keeps hidden elements, so check visibility, not presence; elements marked
"absent" are removed from the DOM when they have nothing to say):

* Paste tab (default for a new graph): `source-content` is visible. `source-file-select` belongs to
  the Text file tab, `source-upload-input` to the Upload tab, `manual-*` to the Manual tab and
  `mongo-*` to the MongoDB tab. A saved file source opens on the Text file tab. The tabs are, in
  order, Text file, Paste, Upload, Manual and MongoDB; switching keeps what was entered on the others.
* `source-format` and the block "How to read the data" exist for the three text tabs. The column
  pickers (`source-column-*`), `source-has-header` and `source-no-category-switch` are visible only
  for a CSV or TSV source that has data. `source-column-category` reads "Auto (none found)" when the
  data has no category column (headerless data with fewer than four columns included) and "Auto (col 4)"
  for headerless data with a fourth column.
* `chart-tab-donut` is absent unless the graph has categories. `donut-hint` is absent when it has
  categories (or nothing to draw). `category-table`, `category-row` and the legend items appear with
  categories; legend items exist only in the `category` and `layer` colour modes.
* `categorise-category` and `categorise-all-matching` are absent unless the entries search box is not
  empty; the bulk row then says `N entries match "Food".` (`1 entry matches` for one).
* `category-error` is absent unless a category edit was refused. `entries-basis-hint` is absent unless
  the chosen donut basis ignores categorised entries.
* `conflict-banner` (and its buttons) is absent until a save is refused with 409 (or 404).
* A failing source shows `state-error` in the chart and entries areas and a notice inside the Data
  source section (a "1 problem" badge on its summary), not a toast.

Details by panel:

* **Name, description, tags.** They live in the details dialog (above) and in step 1 of the wizard. Name is
  required (at most 200 characters), description at most 2,000, tags up to 20 of 40 characters each (chip
  input: type and press Enter or a comma). Save with an empty name opens the details dialog with "Give
  the graph a name so you can find it later.", sets the status "Give the graph a name before saving."
  and sends no request.
* **Paste.** `source-content` has an icon button `source-clear` inside the box, at its top right
  (accessible name "Clear the pasted data", title "Clear"); it exists only while the box holds text and is
  one Tab stop right after the box. Click, Enter or Space empties the box, keeps the focus in it,
  announces "Cleared", draws the empty state "Nothing to draw yet" and shows the toast "Cleared" with
  Undo, which puts the text back (the focus stays in the box and the preview is asked again). The toast
  is retired as soon as the box holds anything else (typing, pasting, an example, Undo itself) or another
  source tab is chosen, so Undo never overwrites newer data; clearing twice dismisses the first toast.
  Without a header (`source-has-header` unticked) the fourth column is the category:
  `source-column-category` reads "Auto (col 4)", and `source-no-category-switch` turns that off.
* **Source.** Upload tab: a dashed drop zone ("Drop a file here, or", a styled `label.btn` "Choose a
  file", "No file chosen" or the chosen name, "csv, tsv, txt, json, ndjson or sankey, up to N MB.");
  `source-upload-input` is a visually hidden 1 x 1 px input fed by `set_input_files`; dropping works
  too. A name that already exists opens `confirm-dialog` "Replace the existing file?" (confirm button
  "Replace file"). Success reads "<name> was uploaded and is now the source." and the file list shows
  the row with "In use". Text file tab: `source-file-select` options read `<name> (<size>)`. Manual
  tab: a table of links (at most 5,000); inputs are labelled `Source, row 1`, `Target, row 1`, `Value,
  row 1`, `Category (optional), row 1`; a value that is not a number above 0 shows "Use a number
  above 0.", the categories Uncategorized and Other show "Uncategorized and Other are reserved
  names. Pick another category."; a row is drawn only when it has a source, a target and a value
  above 0. MongoDB tab: `mongo-connection` is preselected when there is one connection,
  `mongo-database` and `mongo-collection` are text inputs with suggestions, `mongo-filter` (find mode)
  and `mongo-pipeline` (aggregate mode) are JSON text areas, "Show sample documents" fills the region
  `mongo-sample` and then offers `mongo-suggest` ("Use the suggested fields"). Without any connection
  `mongo-no-connections` ("No MongoDB connections yet") offers "Open Settings" and "Check again".
* **Transform.** `transform-min-value`, `transform-top-links`, `transform-hide-nodes` (chip input),
  `transform-merge-nodes` and `transform-rules` (editable tables; a bulk rule from the entries panel
  shows up in `transform-rules`), `transform-on-cycle` (`error`: "Stop and show an error", `break`:
  "Drop the links that close the loop") and `transform-strict`.
* **Style** (in the chart settings popover). `style-title`, `style-color-mode` (`node`, `layer`, `mono`, `category`; `category` is
  offered only when categories exist or it is already chosen), `style-orientation` (`h` or `v`) and
  `style-height` (240 to 2400). Other fields (spacing, opacity, font size, number format, donut options) have no test id. "Preview
  colours" (Match page, Light, Dark) is not saved with the graph. The checkbox "Show values under the node names"
  (`style.show_values_in_labels`; it was "Show values in node labels") puts the value on a second line under the node
  name. The "Donut chart" group has "Show percentages", "Show values" (`donut.show_value`, off by default: the slice
  value, next to the percentage) and "Show the total in the middle"; all three are found by their label.
* **Chart and summary.** `sankey-chart` and `donut-chart` are the Plotly divs. `stats` is a `<dl>` with
  Nodes, Links ("x of y" when the chart draws only the largest links), Total in, Total out, Columns
  and, only when categories exist, Categories. Warnings (`warnings`, items `warning-item`) show
  three at a time with "Show N more warnings" (at most 100 are kept).
* **Dragging nodes.** In the Sankey a bar can be dragged with every `arrangement` except `fixed`, in both
  orientations. The new order of every drawn column is saved in the draft (`style.node_order`, so the graph
  becomes unsaved), the chart redraws in that order after about half a second and a toast says "Node order
  saved with this graph. Editing the data rows does not move the bars until you press Reset order." with
  Undo. A drag that ends in the order the bars were DRAWN in when the press began stores nothing (the
  drawn order is read from the chart, because without a stored order Plotly lays the columns out by itself and
  that can differ from the order of the rows). Undo takes back only its own edit: a newer Undo toast replaces
  the older one, and an Undo whose parts were changed again meanwhile says "Undo is no longer possible: the
  graph changed after this edit." and changes nothing. The rows of the data follow best effort (pasted text, the manual table, a file the graph may
  write; never MongoDB). When the new rows would change a colour, the colours are pinned in the style in
  the same step (Undo takes both back) and a second toast says "N colours were pinned so the chart keeps
  its colours."; if the pins would not fit in the style, a toast says "Rows were not reordered because
  that would change the colours. The order is kept in this graph." once per source (a file whose rows
  could not be written says "Order kept in this graph only."). A plain click, a
  press beside the bars and a right click do nothing. In snap mode a bar must be dragged clearly past its
  neighbour or it settles back. `chart-reset-order` ("Reset order", in the chart tools) is visible while an
  order is stored and returns to the automatic layout; manual row edits never move the bars while an order
  is stored. The viewer, compare and every export draw the stored order.
* **Order nodes** (`chart-order-open`, "Order nodes", in the chart tools; disabled with the title "The nodes
  cannot move while Dragging nodes is set to Fixed." for `fixed`, and when nothing can be ordered). It opens
  `order-dialog`: an intro, one section per drawn column ("Column n of N"), and a row per node with
  `order-up` and `order-down` (accessible names "Move <name> up|down", disabled at the ends). A press swaps
  the node in the list, keeps the focus on it (on the other button when the pressed one became disabled),
  announces "<name> moved to position i of n" and saves the whole order through the same path as a drag.
  "Done" (no test id) or Esc closes the dialog and returns the focus to the button. This is the keyboard and
  single-pointer way to do what a drag does.
* **Clicking a node.** A click on a BAR of the Sankey (never on a link, never after a drag) opens the "Add a
  flow" dialog for that node. A bar that nothing leaves (a sink) gets a flow that ENDS at it (the target is
  filled in, the source is focused); every other bar gets a flow that STARTS at it (the source is filled in,
  the target is focused). The dialog then shows the fieldset `add-entry-direction` with the radios
  `add-entry-from-node` ("The new flow starts at <node>") and `add-entry-to-node` ("The new flow ends at
  <node>"); choosing the other one swaps source and target (what was typed for the other end follows it),
  retitles the dialog ("Add a flow from <node>" or "Add a flow into <node>", the name cut at 60 characters),
  keeps the focus on the radio so the arrow keys work, and refreshes the hints. The click works with every
  arrangement. The bars are mouse-only: `entries-add` is the keyboard twin. Touch without hover can click a
  bar only when the arrangement is `fixed`. When the source names no file or collection yet, the click shows
  the toast of the disabled button instead of the dialog.
* **Entries.** One row per source and target pair, 100 rows per page (`entries-row` counts the
  current page, `entries-total` the whole: "9 entries", or "3 of 9 entries" while filtered).
  `category-cell` is an `<input list>`: Enter commits and moves to the next row (Shift+Enter to the
  previous), blur commits, a picked suggestion commits, Esc reverts a touched cell, and the `x`
  button (`category-clear`) forces "None, on purpose". Every commit is checked by the server
  (`POST /entries?limit=1`) and the save bar waits for pending checks. "Other" and "Uncategorized"
  are refused with `"Other" is reserved for the chart (it labels the leftovers). Pick another
  name.`; an empty bulk category gives "Type the category these entries should get.". The bulk
  button adds ONE glob rule (`*text*`, matching source or target names) and shows the toast `Rule
  added: names containing "Food" get "Living". You can edit it under Transform.` with Undo.
  `entries-sort` options: `value`, `source`, `target`, `category`. The search clears on Esc.
* **Typing a category is a data edit.** Pasted text gains or updates the category column (a `category`
  header is added when there is none; headerless rows get a fourth cell), the manual table fills the
  Category of every link of the pair (pairs of merged nodes are found), and a text file or a MongoDB
  collection first asks the consent question below. A screen reader hears "Category saved in your data" for
  text and manual links; a file or collection shows the toast "Updated N row(s)/document(s) in <target>.". When the data had no
  category at all, the other rows legitimately stay uncategorised, so after the first category a toast says
  "N other entries have no category." with "Show them", which ticks `entries-uncategorized-only` (once per
  page). When the edit cannot go into the data (an aggregate source, a refused value, a read-only
  server) it stays in the graph (`transform.entry_categories`) and one fixed info toast says why, once per
  reason and source.
* **Add entry.** The Entries card header holds `entries-add` ("Add entry"; always shown, and disabled with a
  title - "Choose a file first." or "Choose a collection first." - while a Text file or MongoDB source
  names nothing yet) and the chip `entries-overlays`. The button opens `add-entry-dialog` ("Add a flow",
  modal) with Source (`add-entry-source`), Target (`add-entry-target`), Value (`add-entry-value`) and an
  optional Category (`add-entry-category`); node names and categories are offered as suggestions. Enter
  submits (not while composing). The first problem, in reading order, goes to the one `role=alert` line
  `add-entry-error`, the field gets `aria-invalid` and the focus, and typing clears it: names of 1 to 200
  characters without control characters and different from each other, a finite value above 0 ("1 200" and
  "1e3" are read, "1,5" is refused) and a category that is not "Uncategorized" or "Other". Under Source
  and Target the hint "New node: <name> will be created." appears for a name the chart does not have.
  `add-entry-submit` ("Add") is busy while the edit runs; `add-entry-cancel` and Esc close the dialog and
  return the focus to `entries-add`. An answer with a sentence (a loop, the 5,000-link cap, a stale draft)
  stays in the dialog. For a file or collection source the consent dialog opens above this one and Esc
  closes only the newest. Success closes the dialog; the toast reads "Entry added." with Undo when the
  entry went into pasted text, manual links or the graph only, and "Added 1 row in <file>." or "Added 1
  document in <target>." when it was written to a file or collection.
* **Graph-only edits.** `entries-overlays` ("Graph-only edits (N)", hidden at 0) counts the category edits,
  added entries and the custom node order that live in the graph and not in the data. It opens
  `overlays-dialog`: "These edits are stored in this graph, not in your data." and a row per item ("Budget to
  Rent: category Housing", "Budget to Food: no category", "Budget to Gifts: 50, category Fun", "Custom node
  order (3 nodes)") with `overlay-remove`. Remove changes the draft at once (the table and the chart
  follow, the graph becomes unsaved) and moves the focus to the next Remove or to Done; at most 200 rows
  are listed; an empty list reads "No graph-only edits are left."; closing returns the focus to the chip, or
  to `entries-add` when the chip left. `entries-unmatched` is a notice above the toolbar: "N of your
  category edits no longer match an entry (the names changed). They are ignored and listed under
  Graph-only edits."
* **Consent dialog.** For a text file or a MongoDB `find` source the first data edit opens
  `write-back-dialog` ("Change your data too?"). It names the target, repeats the edit ("Entry Budget to
  Rent: category Housing."), says the change is immediate, not part of Save and cannot be undone here,
  that other graphs reading the file change too (a file) or that the database user needs write permission
  (a collection), and "The file will be re-formatted." for JSON. The answers: `write-back-accept` ("Update
  the source") writes now and saves the answer with the graph; `write-back-decline` ("Keep in this graph",
  initial focus) keeps this one edit in the graph and is remembered for the page session and the same
  target only, never saved; `write-back-never` ("Keep in this graph, don't ask again") saves that choice
  with the graph; `write-back-cancel` (Cancel, Esc, the backdrop) does nothing and the cell rolls back
  quietly. Edits of one target that arrive while the dialog is open (Enter, Enter, Enter) wait on the SAME
  dialog. The answer is bound to the file or collection: a different one asks again. On a read-only server
  there is no dialog and one toast says "This server is read-only here: your change stays in this graph and
  is not written to the source."
* **Write-back status.** With a file or collection chosen, the Source panel shows `source-write-back`: a
  line "Edits to the data: ask me each time | written to the source | kept in this graph" and the button
  "Ask me again" (disabled until a choice is stored) that resets the saved choice. It is a status, never a
  way to grant consent: only the dialog grants. It falls back to "ask me each time" when the file or
  collection changes. Its helper text repeats the facts of the dialog.
* **Export** (in the chart settings popover, tab Export). Width (200 to 4000, default 1200), height (200 to 4000, empty means the figure's),
  scale (0.5 to 4, default 2), transparent background, file colours (`export-theme`: Light, Dark,
  "Same as the preview"; default Light), and the buttons. The line "Images come out 2,400 x 1,120 px."
  follows the inputs. The options are remembered in `localStorage` (`sankey-studio.export`). The export card stays
  hidden until the first preview has finished. All buttons are disabled until a chart exists and
  while an export runs; donut buttons also need a donut. `export-data-chart` (`sankey` or `donut`) chooses what HTML, JSON and CSV describe. A saved,
  unmodified graph is exported by `GET /graphs/<id>/export`; an unsaved or edited one by
  `POST /export` with the draft, so the file matches the screen. Success shows "Downloaded <file>" in
  the panel's status line (no toast).
* **Save bar.** `save-status` (`data-state` new, dirty, saved, saving, error or readonly) reads "Not
  saved yet", "Unsaved changes", "All changes saved" plus "Revision N" and "Saved <relative time>",
  "Saving...", the reason a save failed, or "Read-only server: saving is turned off. You can still
  preview and export.". `save-button` (Ctrl or Cmd+S too) posts the first time and puts with the
  revision afterwards; the toasts are "Graph saved." and "Saved as revision N." and focus stays on
  Save. `save-as-copy` is enabled once the graph has an id. A 409 shows `conflict-banner`: "This graph
  was saved somewhere else after you opened it. It is now at revision N, just now. Your changes are
  not saved." with `conflict-reload` ("Reload (discard my changes)", then the toast "Reloaded the
  saved version (revision N). Your edits were discarded.") and `conflict-save-copy` ("Save my version
  as a copy", then the toast "Saved as a copy: <name>." and the address moves to the copy). When the
  graph was deleted meanwhile (404) the banner reads "This graph no longer exists: ..." and offers
  only "Save my version as a new graph".
* **Leaving.** Clicking an in-app link with unsaved changes opens `confirm-dialog` "Leave without
  saving?" (buttons "Stay and keep editing" and "Leave without saving"); reload or close fires the
  native `beforeunload` dialog.

## Viewer

`/graphs/<id>` shows one saved graph: header (description, tag links to `/?tag=...`, source badge,
"Updated ..." and "Revision N"), the stats strip, warnings and the chart card, which spans the full
width of the page and holds the export popover behind the download icon. The
page actions hold `graph-edit` (link to `/graphs/<id>/edit`) and `graph-duplicate`.

States:

| State | What is on screen |
|---|---|
| Loading | a chart frame with `state-loading` ("Loading the graph") and skeletons in the layout of the finished page |
| Ready | `stats`, optional `warnings`, tabs and charts, `links-table` (and `category-details` in the Donut tab), the download icon `export-menu-button` (its panel stays closed); the Sankey is drawn at once |
| Render failed | `state-error` "The graph could not be drawn" with the server's message, `state-retry` and a link "Open in the editor" |
| Deleted after the page opened | `state-empty` `viewer-missing` "This graph no longer exists" with "Back to the library" (reproduce by answering `GET /api/v1/graphs/<id>/render` with a 404 envelope; a URL of a graph that is already gone is the HTML not-found page) |
| Theme reload failed | an error toast; the chart on screen stays |

Behaviour:

* The bundle comes from `GET /graphs/<id>/render?theme=<shown theme>` (plus the display switches the person
  changed); a theme change asks again with
  the other theme and redraws in place. After Back or Forward the header is read again.
* The icon `display-menu-button` ("Chart display options", `aria-expanded`) at the right of the tab row opens
  `display-menu-panel`, a small panel of view-only switches: `display-node-values` ("Show values under the node
  names", Sankey), `display-donut-percent` ("Show percentages") and `display-donut-value` ("Show values"), both
  Donut; the Donut group is hidden when the graph has no donut. The switches start from the saved style
  (`show_values_in_labels`, `donut.show_percent`, `donut.show_value`). A change redraws at once: the switch
  a person touched is sent as `node_values`, `donut_percent` or `donut_value` with `GET /graphs/<id>/render` and with
  every `GET /graphs/<id>/export`, so a download looks like the screen. The saved graph is never changed (a reload
  starts from the saved style again). If the redraw fails the switch goes back and a toast says "The chart could not
  be redrawn." The panel closes on Escape (focus returns to the icon), on a press outside it and when focus
  leaves it; a press on a tab counts as outside, and opening the export menu closes it.
* The Sankey shows the value under the name of each node (two text lines) when its switch is on. A donut slice shows
  the percentage and/or the value on every slice: with four slices or fewer the name stays on the slice as well, with
  more the legend and the category table carry the names; with neither switch on the slices are bare. The tab strip
  has no vertical scrollbar.
* Tabs `chart-tab-sankey` and `chart-tab-donut` (`role=tab`, Arrow, Home and End keys move and
  activate). `chart-tab-donut` exists only when the graph has categories; otherwise `donut-hint`
  ("Want a donut? Give your links a category: ...") sits under the Sankey. The donut is drawn when its
  tab is first opened. A donut basis that selects nothing shows `donut-hint` inside the Donut tab.
* The Sankey tab also holds the legend (`legend`, only in the `category` and `layer` colour modes) and
  `links-table`, a `<details>` "Table view of the links" that builds a sortable table of 20 rows per
  page when first opened (rows carry `data-source` and `data-target`, no test id; a note says "The
  first N of M links. The editor lists them all." when the bundle holds fewer than the graph).
  The Donut tab holds a note naming the donut basis and `category-details`, a `<details>` "Table view of
  the categories" (closed, the same link-like summary as `links-table`) that holds `category-table`
  ("Totals by category", with a total row). The block keeps its open or closed state when the chart is
  redrawn (theme, display switches).
* The Sankey is drawn without its in-figure legend row (`withoutLegend` of `core/chart.js`: the legend traces go,
  the plot takes the band back and the top margin loses it) because the `legend` list under the chart names the
  same entries; the editor chart does the same. The server figure, the exports and the compare cards keep the
  legend row. The donut legend hides and shows slices, so it stays in the donut figure.
* `stats` is a `div[role=group]` of tiles: Total in, Total out, Categories. The graph size (nodes,
  links, layers) is not shown here; the editor chart summary and the compare cards still list it.
  Values carry the unit suffix of the style.
* The download icon `export-menu-button` ("Export settings", `aria-expanded`, `aria-controls` the panel) sits
  at the right of the tab row, after the sliders icon `display-menu-button`. It opens `export-menu-panel`, a
  non-modal `role=dialog` popover under the icon (`hidden` while closed, headed "Export"), so the chart uses
  the full width of the page and there is no export column or card beside it. Every other `export-*` control
  lives in that panel, so none is visible until the icon is clicked. Escape closes it and puts the focus back on the
  icon; a pointer press outside it closes it; so does focus moving outside it; opening another popover (the
  display menu) closes it. A download does not close it, so the status line, the size line and the fallback
  note stay in view. Switching between the Sankey and Donut tabs while it is open changes which image buttons
  it shows. It stays inside the window at 390 px and scrolls when the window is short.
* Export panel (inside that popover): width, height, scale, transparent, file colours (`export-theme`: Light
  or Dark, default Light), Sankey SVG and PNG (shown on the Sankey tab), Donut SVG and PNG (shown on the Donut
  tab), and HTML, JSON and CSV for the active tab. Each button asks `GET /graphs/<id>/export` (with the
  display switches the person changed) and shows `Saved <file>.` The line "Image size: 2,400 × 1,120 px." follows the inputs.
* Fallback: when the server cannot draw an image (422 `export_too_large`, or 501, 502, 503, 504) the
  browser draws the chart it already shows with Plotly and `export-fallback-note` explains why ("This
  server cannot draw images (Chrome was not found). Your browser drew the image instead, as it looks
  on screen."). A transparent background is not possible there. HTML, JSON and CSV never fall back.
* File names come from the server's `Content-Disposition`: `<name>.<ext>` for the Sankey and
  `<name>-donut.<ext>` for the donut (the suffix appears once; names over 80 characters are cut). A
  browser-drawn image follows the same rule. CSV of the donut has the header `category,value,share`; the
  Sankey CSV has `source,target,value,category`.
* Chart text is drawn literally: `<b>x</b>` appears as those characters, and control and bidirectional
  characters are removed from every label, hover, legend, donut and exported file. The modebar has no
  "Share chart" or camera entry.

## Compare

`/compare?ids=a,b,c` draws up to 12 graphs side by side with one shared category colour map. The page
actions hold a "Back to the library" link.

Layout: the toolbar (a status line "Comparing N graphs" or "No graphs in the comparison", the add
control, the limit message), the shared-colour note, then `compare-grid` (`data-count`), which holds
the cards, or the empty or error block.

States:

| State | What is on screen |
|---|---|
| Loading | one placeholder card with `state-loading` "Loading the graphs" |
| Empty | `state-empty` "Nothing to compare yet" inside `compare-grid[data-count=0]`, with a "Back to the library" button (the same link text also sits in the page actions); the add menu is shown; no request is made |
| Ready | one `compare-card` per id, in address order; charts draw lazily |
| Missing graph | `compare-missing` "This graph is gone" with a remove button; ids in `boot.missing` show it at once with no request and a warning toast "One graph could not be drawn. The others are shown." |
| Broken graph | a `compare-card` with `data-chart=none`, `state-error` "This graph cannot be drawn" (a cycle, an unreadable source) and a link "Fix it in the editor" |
| Error | `state-error` "The comparison could not be drawn" with `state-retry` |
| Limit | at 12 graphs `compare-limit-message` is visible and the add control is hidden |

Behaviour:

* A card holds the name link, the Sankey or Donut switch `compare-card-toggle` (`role=switch`,
  `aria-checked=true` while the donut shows; without categories it has `aria-disabled=true` and the
  title "No categories, so there is no donut chart"), the remove button `compare-remove`, the chart
  and a summary table (Nodes, Links, Total in, Total out, Layers, Categories) plus a warnings
  `<details>`. `compare-card[data-chart]` is `sankey`, `donut` or `none`.
* `GET /compare/render?ids=&theme=` returns the bundles; a graph that is missing or broken is set
  aside instead of failing the page. Adding or removing a graph reloads the whole set (the shared
  colour map can re-rank) and updates the address with `replaceState`; removing the last card leaves
  `/compare`, which reloads as the empty state. After a removal focus moves to the remove button that
  took its place. A theme switch reloads with the other theme. Each card remembers whether it showed
  the Sankey or the donut.
* The add control (`compare-add-select`, `compare-add`) is disabled with the option "Loading graphs"
  until the library list arrives and lists the graphs not yet compared by display name.
* `compare-shared-colours` (the note and legend listing each category once with the colour all cards
  use) is absent when no drawn graph has categories.
* Charts draw when a card comes within 300 px of the viewport; the donut of a card draws only when its
  switch is turned on.

## Settings

`/settings` has five sections, `section.settings-section` with the ids `settings-appearance`,
`settings-storage`, `settings-connections`, `settings-limits` and `settings-server`, then the sticky
save bar. From 900 px each section is a title and help text on the left and a card on the right; below
900 px they stack. From 1280 px a sticky rail `nav.settings-toc` ("On this page", `aria-label` "Settings
sections") lists the section anchors and follows the reading position with `aria-current=location`;
below 1280 px it is `display: none`. It is added a moment after the page is assembled.

States:

| State | What is on screen |
|---|---|
| Loading | `state-loading` "Loading settings" |
| Error | `state-error` "The settings could not be loaded" with `state-retry` |
| Ready | the sections and the save bar (wait for `settings-save`) |
| Validation error | `settings-error` ("Settings were not saved", with links to the fields) and inline field messages, an error toast; focus moves to the summary |
| Saving | `.settings[aria-busy=true]`, fields disabled, `settings-save` has `aria-busy` and `aria-disabled` but stays focusable |
| Read-only | every field of the form is disabled, including Test connection, Delete, Add connection, Test storage and `settings-save`; both banners; the theme cards still work and keep the choice on this device |

Behaviour:

* **Appearance.** Three cards `settings-theme-option` (radio inputs in the order System, Light, Dark).
  A pick applies at once and saves through the shared queue. The result is a hint line under the cards,
  not a toast: "Theme saved." (on a read-only server "Kept on this device only: this server is
  read-only."; when the save fails "Applied, but not saved." plus one info toast). The System card
  reads "Follows your device (now light)." or "(now dark)" for what the device does now.
* **Storage.** `settings-storage-backend` (`file` "Files on this computer" or `mongo`).
  While the backend is `file`, `settings-storage-folder` (a `code` element, read-only) names the folder
  that holds the graph files, after "Graphs folder:"; it is hidden for `mongo` and follows the select
  before saving.
  `settings-storage-connection` and `settings-storage-database` show only for `mongo`, with the hint "The
  graphs go into the MongoDB collection sankey_studio_graphs of this database, and the library's own
  collections (groups of graphs) into sankey_studio_collections."; the connection needs write permission on
  both and "Test storage" probes both. A switch can copy the existing graphs and their collections
  (`settings-migrate`, "Copy my N existing graphs to the new location"). On a
  read-only server it is unticked and disabled ("Not available: this server is read-only, so nothing
  can be copied."). `settings-test-storage` writes its result into `settings-storage-status`
  ("Storage is reachable and writable."). After a copy `settings-copy-report` (`role=status`,
  `tabindex=-1`, `data-copied`, `data-skipped`, `data-unreadable`, `data-folders`, `data-folders-skipped`)
  shows Copied, "Already there, skipped" and "Could not be read", and, only when either is not zero,
  "Collections copied" and "Collections skipped"; `settings-copy-unreadable` lists up to 50 ids followed by "And N
  more that are not listed."; its button "Dismiss the copy report" moves focus to
  `settings-test-storage`. Switching to files while the old MongoDB is unreachable fails with the
  summary, a toast and the hint to untick "Copy my existing graphs" and save again.
* **Connections.** Rows (`settings-connection`, `role=group`) exist only after `connection-add` or
  when connections are stored (at most 20); with none, `state-empty` "No connections yet" is shown. Name (`^[A-Za-z0-9_.-]{1,64}$`), connection string
  (`connection-uri`, `type=password`, placeholder "(unchanged)" once stored, never prefilled, the
  value is nowhere in the page or in `GET /settings`), default database. `connection-test` calls
  `POST /settings/mongo/<name>/test` for a saved, unchanged row and `POST /settings/storage/test` for
  a new or edited one; the result is `connection-status` (and `connection-latency` after a success).
  After 1.5 s it reads "Still testing the connection... A MongoDB server that cannot be reached can
  take up to 15 seconds to answer." (the stored `mongo_timeout_ms`). Editing or deleting the row
  aborts the request (`net::ERR_ABORTED`, no toast, no stale line). `connection-delete` removes the
  card at once, with no confirmation, and shows `Connection "<name>" removed. It is deleted when you
  save.` with Undo; it needs Save. The badge "Holds your graphs" shows only on the card chosen as the
  MongoDB storage connection while the backend is `mongo`. The visible names of the test and delete
  buttons are "Test connection" and "Delete", but their `aria-label` includes the connection name.
  On a read-only server the hint reads "Stored: mongodb://***. Connection strings cannot be changed
  because this server is read-only."
* **Limits.** `settings-max-links` (100 to 5,000,000, default 200,000), `settings-max-drawn-links` (50
  to 20,000, default 3,000), `settings-max-upload-mb` (1 to 100, default 25) and
  `settings-mongo-timeout` (500 to 300,000 ms, default 15,000). Values are validated in the browser
  first ("Enter a whole number from 100 to 5,000,000."), so an invalid value sends no request.
* **This server.** Read-only facts: `settings-sources-dir`, `settings-remote-mode` ("Local only: this
  computer" or "Remote: reachable from other machines") and `settings-writes-allowed` ("Allowed" or
  "Read-only").
* **Save bar.** `.savebar[data-state]` is `clean`, `dirty`, `saving` or `readonly`;
  `settings-save-status` reads "All changes saved.", "You have unsaved changes.", "Saving..." or
  "Read-only: settings cannot be changed on this server."; it says "All changes saved." only after
  the write queue is empty. `settings-discard` ("Discard changes") shows only while there are
  changes. Enter in a text, number or password field saves. `settings-save` ("Save settings") shows
  "Settings saved." on success.
* **Conflicts.** Saving re-reads the stored settings first. If they changed elsewhere, a dialog
  (`confirm-dialog`, "Settings were changed elsewhere") offers Cancel, `conflict-reload` ("Show their
  settings") and `settings-conflict-overwrite` ("Save mine anyway"); the last stores both the theme
  and the limits.
* **Leaving.** With unsaved changes an in-app link opens `confirm-dialog` "Discard unsaved changes?"
  and the native `beforeunload` prompt guards reload and close.

## Error pages

A browser navigation is a `GET` whose `Accept` header contains `text/html`, for a path outside
`/api/` and `/static/`. For it every error answers the HTML app shell with the status of the error,
`Content-Type: text/html; charset=utf-8` and `Cache-Control: no-store`, never the JSON envelope:

* **404, `notfound`.** An unknown URL, a graph page (`/graphs/<id>` or `/graphs/<id>/edit`) whose graph
  is gone or whose id is malformed, and an invalid compare link (`/compare?ids=bad`, more than 12 ids,
  any other query parameter).
* **503, `error`.** The graph store is unreachable or unusable (`/`, `/graphs/<id>`,
  `/graphs/<id>/edit`, `/compare?ids=<id>`). `/graphs/new` and `/settings` never read the store and
  open normally.
* **Any other status, `error`.** Every other domain or HTTP error of a page and every unexpected
  failure (500) is "Something went wrong" with the status of the error.

Every other client (curl, `fetch` with `*/*` or `application/json`, no `Accept`), every `/api/...` and
`/static/...` path and every non-`GET` method still receive the JSON error envelope (see
[api.md](api.md)). A CORS preflight (`OPTIONS`) is refused with 405 and no CORS headers are ever sent.

The page is the normal shell with `main[data-page=notfound]` or `main[data-page=error]`, boot data
`{page, kind, remote_mode, writes_allowed, theme}` and no page module: `core/shell.js` is the only
script, so `body[data-shell=ready]` is its ready signal. `#page-root` exists here too (it holds the
card) but never gets `data-ready`. Nothing of the request (path, id, query) and nothing of the error
(message, details, exception text) is ever in the body.

| `kind` | Status | `h1` and title | Card text |
|---|---|---|---|
| `page` | 404 | Page not found | There is nothing at this address, so the link may be wrong or out of date. |
| `graph` | 404 | Graph not found | This graph does not exist any more, or the link is wrong. |
| `database` | 503 | Graph database unavailable | The graph database is not reachable right now. Check that MongoDB is running, then reload. |
| `folder` | 503 | Graphs folder unavailable | The graphs folder cannot be read right now. Check that it exists and that you can read it, then reload. |
| `server` | the error's | Something went wrong | The server could not show this page. Reload it, or go back to the library. |

`database` and `folder` are the two wordings of a 503 `storage_error`, picked after the stored
storage backend (MongoDB or the graphs folder).

The `page` and `graph` card is `state-empty` and holds the link "Back to the library" (`a.btn.btn-primary`,
`href="/"`). The other three are a `state-error` card (`role=alert`) with three links in this order:
"Reload" (`state-retry`, `a.btn.btn-primary`, `href=""`: a plain link to the same path and query, no
script, and the address is not written into the page), "Back to the library" (`href="/"`) and "Open
Settings" (`href="/settings"`). The document itself is the only error of a visit: Chrome prints one
console line for it and Playwright reports the response status.

## data-testid reference

`data-testid` values are a contract: end-to-end tests select by them, so they are never renamed or
removed. The list has 257 distinct ids (count them with the two files below, not by hand). The base list
of 127 is kept in `tests/web/test_static_policy_support.py` (it mirrors the id table in [api.md](api.md));
the other 130, used by the shared frontend code, are in `src/sankey_studio/web/static/testids-extra.txt`
(append-only: add an id with a shell `>>` and a comment, never by editing the file). A few dynamic ids
(`change-source-kind-<tab>`, `source-column-<role>`) are built from a fixed set and are not listed one by one. `tests/web/test_static_policy.py` fails when a
template or script uses an id found in neither. To add an id, use a kebab-case literal in the
template or script and list it in `testids-extra.txt` with a comment saying where it is used.

Conventions: "repeated" means one element per row, card or item. "Hidden" means present in the DOM
with the `hidden` attribute; "absent" means removed from the DOM. Tests must check visibility, not
presence, for hidden elements. A dynamic id such as `source-column-<role>` is built from `source`,
`target`, `value` and `category`.

### Shell (every page)

| data-testid | element | notes |
|---|---|---|
| `app-root` | `main#main` | carries `data-page` and `data-loading` |
| `loading` | `div#loading-bar[role=progressbar]` | hidden unless a non-quiet request runs for more than 150 ms; not a ready signal |
| `nav-library` | `a` | link to `/` |
| `nav-new` | `a` | link to `/graphs/new`, styled as the primary button |
| `nav-settings` | `a` | link to `/settings` |
| `theme-switch` | `div[role=group]` | three `button[data-theme-value=system\|light\|dark]` with `aria-pressed` |
| `toast` | `div` (repeated) | `data-kind` success, error, info or warning; `role=alert` for errors; contains a dismiss button (`aria-label` "Dismiss notification") and an optional action button |
| `remote-banner` | `div` | only with `--allow-remote` |
| `read-only-banner` | `div` | only when `writes_allowed` is false |
| `confirm-dialog` | `div[role=dialog]` | generic dialog: unsaved-changes guards, "Replace the existing file?", the settings conflict dialog |
| `confirm-dialog-confirm` | `button` | confirm button of `confirm-dialog` (renamed by callers such as `delete-confirm`) |
| `confirm-dialog-cancel` | `button` | cancel button; initial focus of dangerous confirmations |
| `dialog-close` | `button` | the X in the header of a dialog that asks for one (the details dialog); closes like Esc |
| `state-empty` | `div` | empty block (title, message, actions); also the not-found card |
| `state-error` | `div[role=alert]` | error block; also the card of the 503 and 500 error pages |
| `state-retry` | `button` | "Try again" inside `state-error`; on the server-rendered error pages the "Reload" link (`a`, `href=""`) |
| `state-loading` | `div[role=status][aria-busy]` | skeleton |

Elements without a test id that tests often need: `a.skip-link`, the brand link, `#main h1`,
`#a11y-polite`, `#a11y-assertive`, `#toast-region`, `nav.settings-toc` (links `a[href=#settings-appearance]`
and so on), the upload button `label.btn` "Choose a file" inside `.ed-dropzone-pick`, and the link
"Back to the library".

### Library

| data-testid | element | notes |
|---|---|---|
| `library-search` | `input[type=search]` | debounced 250 ms; address `?q=` |
| `library-sort` | `select` | values `updated-desc`, `updated-asc`, `name-asc`, `name-desc`; address `?sort=` |
| `library-tag-filter` | `button` (repeated) | tag chip, `data-tag`, `aria-pressed`; address `?tag=` |
| `library-clear-filters` | `button` | hidden unless a search or tag is active |
| `library-count` | `p` | "Showing 1-12 of 32 graphs" (en dash) or "5 graphs" |
| `library-empty` | `div` | empty library |
| `library-no-results` | `div` | search or tag matched nothing |
| `graph-card` | `article` (repeated) | `data-graph-id`; 12 per page; `draggable="true"` ("false" while the pointer is over a control or text) when drag and drop is on; `data-dragging` while carried |
| `compare-select` | `input[type=checkbox]` (repeated) | in the card header; at most 12 ticked |
| `graph-open` | `a` (repeated) | name link to `/graphs/<id>` |
| `graph-edit` | `a` (repeated) | link to `/graphs/<id>/edit` |
| `graph-duplicate` | `button` (repeated) | `data-writes`; opens the "Created ..." toast with "Open copy" |
| `graph-delete` | `button` (repeated) | `data-writes`; opens `delete-dialog` |
| `delete-dialog` | `div[role=dialog]` | `Delete "<name>"?`; initial focus on cancel |
| `delete-confirm` | `button` | confirm button of `delete-dialog` ("Delete graph") |
| `library-pager-prev` | `button` | "Previous"; the pager is hidden when everything fits one page |
| `library-pager-next` | `button` | "Next" |
| `library-export` | `button` | label changes with what it exports; downloads `sankey-studio-graphs.json` |
| `library-import` | `label` | wraps the hidden file input; `set_input_files` on it; `aria-disabled=true` when read-only |
| `import-dialog` | `div[role=dialog]` | "This bundle holds N graphs." |
| `import-confirm` | `button` | "Import" |
| `import-report` | `div[role=dialog]` | "Imported N graphs." and the problems |
| `selection-bar` | `section` | hidden until a graph is ticked |
| `selection-clear` | `button` | "Clear selection" |
| `compare-open` | `a` | link to `/compare?ids=a,b,...`; `aria-disabled` with fewer than two ticked |
| `compare-limit-message` | `p[role=status]` | hidden until 12 are ticked |
| `folder-new` | `button` | "New collection", in the page actions; `data-writes`; hidden while searching and inside a collection 8 levels deep |
| `folder-new-graph` | `a` | "New graph here" (`/graphs/new?folder=<id>`), in the page actions; only inside a collection; `data-writes` |
| `folder-breadcrumb` | `nav` | `Library / A / B`; hidden at the top level, while searching and for a missing collection |
| `folder-crumb` | `a` (repeated) | every link of the breadcrumb, "Library" included; the last has `aria-current=page`; `data-folder-id` (`root` is the top level); a drop target |
| `folder-grid` | `ul` | the "Collections (N)" block of cards of the open level |
| `folder-card` | `article` (repeated) | `data-folder-id`; "N graphs, M collections"; `draggable` and `data-dragging` as on `graph-card`; a drop target (`data-drop`, `data-drop-reason`) |
| `folder-open` | `a` (repeated) | name link to `/?folder=<id>` |
| `folder-rename` | `button` (repeated) | opens `folder-dialog` with the name selected; `data-writes` |
| `folder-move` | `button` (repeated) | opens `move-dialog`; `data-writes` |
| `folder-delete` | `button` (repeated) | opens `folder-delete-dialog`; `data-writes` |
| `folder-dialog` | `div[role=dialog]` | create and rename |
| `folder-name-input` | `input[type=text]` | at most 100 characters |
| `folder-name-error` | `p[role=alert]` | "Give the collection a name.", a taken name, and the refusal line of `move-dialog` |
| `folder-name-confirm` | `button` | "Create" or "Rename" |
| `move-dialog` | `div[role=dialog]` | radio tree of places for a graph, the selection or a collection |
| `move-option` | `label` (repeated) | the label of one radio; `data-folder-id` (`root` is the top level); disabled with a reason when impossible |
| `move-confirm` | `button` | "Move here"; disabled until a place is chosen |
| `folder-delete-dialog` | `div[role=dialog]` | initial focus on Cancel; says how many graphs and collections move up |
| `folder-delete-confirm` | `button` | deletes the collection (never a graph) |
| `graph-move` | `button` (repeated) | "Move" on a graph card; only once a collection exists; `data-writes` |
| `selection-move` | `button` | "Move to collection" in the selection bar; `data-writes` |
| `graph-folder` | `a` (repeated) | chip with the collection path on a search result; links to that collection |
| `library-folder-empty` | `div` | an open collection with nothing in it |
| `library-folder-missing` | `div` | the address names a well-formed id that is no collection |
| `library-scope-note` | `p` | "Searching all collections." while a search or tag is active and collections exist |

### Editor

Name, description, tags and the page actions:

| data-testid | element | notes |
|---|---|---|
| `editor-name` | `input[type=text]` | required to save; at most 200 characters; inside `details-dialog` and in wizard step 1 |
| `editor-description` | `textarea` | at most 2,000 characters; same places |
| `editor-tags` | `input[type=text]` | the input inside the chip list; Enter or a comma adds a chip; same places |
| `view-graph` | `a` | "View graph"; hidden until the graph has an id |

Title row, dialogs and wizard:

| data-testid | element | notes |
|---|---|---|
| `graph-settings-button` | `button` | "Graph settings", the gear right after the `h1`; `aria-expanded`; `data-badge=error` while the server rejects name, description or tags |
| `graph-settings-menu` | `div[role=menu]` | `hidden` while closed |
| `graph-settings-details` | `button[role=menuitem]` | "Edit details" |
| `graph-settings-source` | `button[role=menuitem]` | "Change data source" |
| `details-dialog` | `div[role=dialog]` | "Graph details" (modal, with the X `dialog-close`) |
| `details-done` | `button` | "Done"; refuses an empty name |
| `change-source-dialog` | `div[role=dialog]` | one radio per kind: `change-source-kind-<text\|paste\|upload\|manual\|mongo>` (dynamic) |
| `change-source-apply` | `button` | "Change source", or "Edit source settings" for the current kind |
| `change-source-keep` | `input[type=checkbox]` | "Keep my graph-only edits"; shown only when the graph holds some |
| `new-wizard` | `section` | `data-step` `details` or `source`; present only on `/graphs/new` until finished |
| `wizard-step-details` | `div` | step 1: name, description, tags |
| `wizard-step-source` | `div` | step 2: the source tabs |
| `wizard-next` | `button` | "Next" |
| `wizard-back` | `button` | "Back"; keeps the values |
| `wizard-create` | `button` | "Start editing"; disabled until the source has input |
| `wizard-later` | `button` | "Do it later"; Paste and Manual while empty |
| `wizard-cancel` | `a` | "Cancel", a link to `/` or `/?folder=<id>` |

Chart settings popover and chart tools:

| data-testid | element | notes |
|---|---|---|
| `chart-settings-button` | `button` | "Chart settings", the gear in the chart header; `aria-expanded`; `data-badge=error` while a style value is rejected |
| `chart-settings-panel` | `div[role=dialog]` | non-modal; `hidden` while closed |
| `chart-settings-close` | `button` | X; closes and returns the focus to the gear |
| `chart-settings-tab-style` | `button[role=tab]` | holds `section-style` |
| `chart-settings-tab-export` | `button[role=tab]` | holds the `export-*` controls |
| `chart-order-open` | `button` | "Order nodes"; disabled for `fixed` arrangement |
| `chart-reset-order` | `button` | "Reset order"; visible while `style.node_order` is not empty |
| `order-dialog` | `div[role=dialog]` | the nodes per drawn column |
| `order-up` | `button` (repeated) | "Move <name> up" |
| `order-down` | `button` (repeated) | "Move <name> down" |

Data source:

| data-testid | element | notes |
|---|---|---|
| `section-source` | `summary` | expands or collapses the section; open by default |
| `source-tab-text` | `button[role=tab]` | Text file (managed sources folder) |
| `source-tab-paste` | `button[role=tab]` | Paste (default for a new graph) |
| `source-tab-upload` | `button[role=tab]` | Upload |
| `source-tab-manual` | `button[role=tab]` | Manual |
| `source-tab-mongo` | `button[role=tab]` | MongoDB |
| `source-content` | `textarea` | Paste tab |
| `source-clear` | `button` | Clear icon inside the Paste box (top right); exists only while the box holds text; the toast "Cleared" offers Undo |
| `source-file-select` | `select` | Text file tab; options `<name> (<size>)` |
| `source-upload-input` | `input[type=file]` | Upload tab; visually hidden but focusable; disabled when read-only |
| `source-format` | `select` | `auto`, `csv`, `tsv`, `sankeymatic`, `json`; text tabs only |
| `source-column-source` | `select` | options "Auto (<header>)" and the columns; CSV or TSV with data. When the header uses synonyms (`from`, `to`, `amount`) the editor matches them once: the select then holds that column (`from`), not "Auto (from)", and the block says "Matched by name: from as source, ..." |
| `source-column-target` | `select` | same |
| `source-column-value` | `select` | same |
| `source-column-category` | `select` | "Auto (none found)" when the data has no category column |
| `source-has-header` | `input[type=checkbox]` | "The first row is a header" |
| `source-no-category-switch` | `input[type=checkbox]` | switch "This data has no category column" |
| `manual-table` | `table` | Manual tab |
| `manual-row` | `tr` (repeated) | inputs labelled `Source, row N` and so on |
| `manual-add-row` | `button` | "Add a link" |
| `mongo-connection` | `select` | configured connections |
| `mongo-database` | `input[type=text]` | with suggestions |
| `mongo-collection` | `input[type=text]` | with suggestions |
| `mongo-filter` | `textarea` | find mode |
| `mongo-pipeline` | `textarea` | aggregate mode |
| `mongo-sample` | `div[role=region]` | sample documents; hidden until loaded |
| `mongo-suggest` | `button` | "Use the suggested fields"; hidden until a sample suggests fields |
| `mongo-no-connections` | `div` | empty state with "Open Settings" and "Check again" |
| `source-write-back` | `div` | status line "Edits to the data: ask me each time \| written to the source \| kept in this graph" with the button "Ask me again"; only with a chosen file or collection; never grants consent |
| `write-back-dialog` | `div[role=dialog]` | "Change your data too?" |
| `write-back-accept` | `button` | "Update the source" |
| `write-back-decline` | `button` | "Keep in this graph"; initial focus |
| `write-back-never` | `button` | "Keep in this graph, don't ask again" |
| `write-back-cancel` | `button` | "Cancel" |

Transform and Style:

| data-testid | element | notes |
|---|---|---|
| `section-transform` | `summary` | closed by default; the fields are in the DOM but hidden |
| `transform-min-value` | `input[type=number]` | "Smallest link to draw" |
| `transform-top-links` | `input[type=number]` | "Only the largest links" |
| `transform-hide-nodes` | `input[type=text]` | chip input |
| `transform-merge-nodes` | `table` | merge table |
| `transform-rules` | `table` | category rules; a bulk rule appears here |
| `transform-on-cycle` | `select` | `error` or `break` |
| `transform-strict` | `input[type=checkbox]` | strict reading |
| `section-style` | `summary` | inside the chart settings popover (tab Style); open and not remembered |
| `style-title` | `input[type=text]` | chart title; also names exported files |
| `style-color-mode` | `select` | `node`, `layer`, `mono`, `category` (`category` is offered only when categories exist or it is already chosen) |
| `style-orientation` | `select` | `h` or `v` |
| `style-height` | `input[type=number]` | 240 to 2400 |

Chart and summary:

| data-testid | element | notes |
|---|---|---|
| `chart-tab-sankey` | `button[role=tab]` | |
| `chart-tab-donut` | `button[role=tab]` | absent unless the graph has categories |
| `sankey-chart` | `div[role=img]` | the Plotly div: `data-ready`, `data-chart-theme`, `aria-label` "Sankey diagram with N nodes and M links"; hidden while the Donut tab is active |
| `donut-chart` | `div[role=img]` | `data-ready`; `aria-label` "Donut chart of N categories" |
| `donut-hint` | `div` | absent when the graph has categories; text "No donut yet. Give a few entries a category in the Entries table and a donut chart appears. ..." and a "Go to entries" button |
| `stats` | `dl` | Nodes, Links, Total in, Total out, Columns, and Categories when there are any; hidden until a bundle exists |
| `legend` | `ul` | its block is hidden when empty; items only in `category` and `layer` colour modes |
| `legend-item` | `li` (repeated) | `data-kind` category or layer |
| `category-table` | `table` | "Totals by category" |
| `category-row` | `tr` (repeated) | `data-category`, `data-kind` |
| `style-mono-color` | `input[type=color]` | the One colour picker; shown only when `style-color-mode` is `mono`, saves `draft.style.mono_color` |
| `style-mono-reset` | `button` | "Use palette colour"; removes `mono_color` |
| `category-colour` | `input[type=color]` (repeated) | one per real category, laid over its swatch: a tap opens the colour picker and saves `draft.style.category_colors` |
| `warnings` | `div` | hidden when empty |
| `warning-item` | `li` (repeated) | for example "Removed 1 link(s) that closed a cycle" |

Entries:

| data-testid | element | notes |
|---|---|---|
| `entries-table` | `table` | 100 rows per page |
| `entries-row` | `tr` (repeated) | `data-source`, `data-target`; `aria-busy` while a category commit is checked |
| `entries-total` | `span` | "9 entries" or "3 of 9 entries" |
| `entries-search` | `input[type=search]` | debounced 250 ms; Esc clears |
| `entries-sort` | `select` | `value`, `source`, `target`, `category` |
| `entries-uncategorized-only` | `input[type=checkbox]` | "Only uncategorised" |
| `entries-pager-prev` | `button` | previous page of entries |
| `entries-pager-next` | `button` | next page of entries |
| `category-cell` | `input[type=text]` (repeated) | `<input list>`; Enter commits and moves down, blur commits, Esc reverts |
| `category-clear` | `button` (repeated) | forces "None, on purpose" |
| `category-datalist` | `datalist` | existing categories; never visible |
| `category-error` | `p[role=alert]` | the one error line for a cell edit or the bulk rule; absent when empty |
| `categorise-category` | `input[type=text]` | bulk category; absent while the search box is empty |
| `categorise-all-matching` | `button` | adds one glob rule; absent while the search box is empty |
| `entries-basis-hint` | `div` | notice about categorised entries the donut basis leaves out; absent otherwise |
| `entries-add` | `button` | "Add entry"; disabled with a title while a Text file or MongoDB source names nothing |
| `entries-overlays` | `button` | chip "Graph-only edits (N)"; hidden at 0 |
| `entries-unmatched` | `div[role=status]` | notice that category edits no longer match an entry; absent otherwise |
| `overlays-dialog` | `div[role=dialog]` | "Graph-only edits" |
| `overlay-remove` | `button` (repeated) | one per listed item |
| `add-entry-dialog` | `div[role=dialog]` | "Add a flow" (from the button or a click on a node) |
| `add-entry-source` | `input[type=text]` | with suggestions |
| `add-entry-target` | `input[type=text]` | with suggestions |
| `add-entry-value` | `input[type=text]` | a number above 0 |
| `add-entry-category` | `input[type=text]` | optional |
| `add-entry-error` | `p[role=alert]` | the one problem line; `hidden` when empty |
| `add-entry-submit` | `button` | "Add" |
| `add-entry-cancel` | `button` | "Cancel" |
| `add-entry-direction` | `fieldset` | only when opened from a node: the two radios below |
| `add-entry-from-node` | `input[type=radio]` | "The new flow starts at <node>" |
| `add-entry-to-node` | `input[type=radio]` | "The new flow ends at <node>" |

Export (all inside the chart settings popover, tab Export; open it first):

| data-testid | element | notes |
|---|---|---|
| `export-sankey-svg` | `button` | |
| `export-sankey-png` | `button` | |
| `export-donut-svg` | `button` | disabled without a donut |
| `export-donut-png` | `button` | disabled without a donut |
| `export-html` | `button` | chart chosen in `export-data-chart` |
| `export-json` | `button` | |
| `export-csv` | `button` | |
| `export-data-chart` | `select` | `sankey` or `donut` (donut disabled without categories) |
| `export-width` | `input[type=number]` | 200 to 4000, default 1200 |
| `export-height` | `input[type=number]` | 200 to 4000, empty means the figure's |
| `export-scale` | `input[type=number]` | 0.5 to 4, default 2 |
| `export-transparent` | `input[type=checkbox]` | |
| `export-theme` | `select` | `light`, `dark`, `match` ("Same as the preview"); default light |
| `export-fallback-note` | `div[role=status]` | absent until a browser-drawn fallback happened; text "This server cannot draw images (Chrome is not available), so your browser drew it instead. ..." |

Save bar and conflict:

| data-testid | element | notes |
|---|---|---|
| `save-button` | `button` | "Save"; disabled when read-only |
| `save-as-copy` | `button` | "Save as copy"; disabled until the graph has an id |
| `save-status` | `div` | `data-state` new, dirty, saved, saving, error or readonly |
| `conflict-banner` | `div[role=alert]` | absent until a 409 (or 404) |
| `conflict-reload` | `button` | "Reload (discard my changes)"; hidden when the graph was deleted |
| `conflict-save-copy` | `button` | "Save my version as a copy" |

The editor also uses the shell ids `dialog-close`, `toast`, `confirm-dialog`, `confirm-dialog-confirm`,
`confirm-dialog-cancel`, `state-empty`, `state-error`, `state-retry` and `state-loading`.

### Viewer

| data-testid | element | notes |
|---|---|---|
| `graph-edit` | `a` | page action, link to `/graphs/<id>/edit` |
| `graph-duplicate` | `button` | page action, `data-writes`; toast "Created ... copy" with "Open copy"; stays on the page |
| `stats` | `div[role=group]` | tiles: Total in, Total out, Categories |
| `warnings` | `section` | absent when the render has no warnings |
| `warning-item` | `li` (repeated) | |
| `chart-tab-sankey` | `button[role=tab]` | |
| `chart-tab-donut` | `button[role=tab]` | absent unless the graph has categories |
| `sankey-chart` | `div[role=img]` | `data-ready`, `data-chart-theme`; `aria-label` "Sankey diagram of <name>: N nodes and M links. The links table below has the same data."; hidden while the Donut tab is active |
| `donut-chart` | `div[role=img]` | drawn when the tab is first opened; `aria-label` "Donut chart of the categories in <name>" |
| `donut-hint` | `p` | "Want a donut? ..." when there is no donut; inside the Donut tab when the basis selects nothing |
| `display-menu-button` | `button` | the icon at the right of the tab row; `aria-label` "Chart display options", `aria-expanded`, `aria-controls` the panel |
| `display-menu-panel` | `div[role=group]` | the panel of switches; `hidden` while closed; closes on Escape, a press outside and focus leaving |
| `export-menu-button` | `button` | the download icon at the right of the tab row, after `display-menu-button`; `aria-label` "Export settings", `aria-expanded`, `aria-controls` the panel |
| `export-menu-panel` | `div[role=dialog]` | the popover that holds every `export-*` control; `hidden` while closed; closes on Escape (focus returns to the icon), a press outside and focus leaving; stays open after a download |
| `display-node-values` | `input[type=checkbox]` | "Show values under the node names"; sends `node_values`; view-only |
| `display-donut-percent` | `input[type=checkbox]` | "Show percentages" (Donut group, hidden without a donut); sends `donut_percent` |
| `display-donut-value` | `input[type=checkbox]` | "Show values" (Donut group, hidden without a donut); sends `donut_value` |
| `legend` | `ul` | absent unless the colour mode is `category` or `layer` |
| `legend-item` | `li` (repeated) | `data-kind` |
| `category-table` | `table` | in the Donut tab inside `category-details` (hidden while that block is closed), with a total row |
| `category-row` | `tr` (repeated) | `data-category`, `data-kind` |
| `links-table` | `details` | "Table view of the links" |
| `category-details` | `details` | "Table view of the categories"; in the Donut tab, closed until opened |
| `export-sankey-svg` | `button` | visible on the Sankey tab only |
| `export-sankey-png` | `button` | visible on the Sankey tab only |
| `export-donut-svg` | `button` | visible on the Donut tab only |
| `export-donut-png` | `button` | visible on the Donut tab only |
| `export-html` | `button` | follows the active tab |
| `export-json` | `button` | follows the active tab |
| `export-csv` | `button` | follows the active tab |
| `export-width` | `input[type=number]` | 200 to 4000, default 1200 |
| `export-height` | `input[type=number]` | 200 to 4000, empty means the figure's |
| `export-scale` | `input[type=number]` | 0.5 to 4, default 2 |
| `export-transparent` | `input[type=checkbox]` | |
| `export-theme` | `select` | `light` or `dark`; default light; independent of the page theme |
| `export-fallback-note` | `p[role=status]` | hidden until a browser-drawn fallback happened |
| `viewer-missing` | `div` | the graph was deleted after the page opened |

The viewer also uses `state-loading`, `state-error`, `state-retry`, `state-empty` and `toast`.

In the viewer every `export-*` control except `export-menu-button` sits inside `export-menu-panel`: click `export-menu-button` before using one.

### Compare

| data-testid | element | notes |
|---|---|---|
| `compare-grid` | `div` | `data-count`; also holds the empty and error blocks |
| `compare-card` | `article` (repeated) | `data-graph-id`, `data-chart` sankey, donut or none |
| `compare-card-toggle` | `button[role=switch]` (repeated) | `aria-checked`; `aria-disabled=true` without categories |
| `compare-remove` | `button` (repeated) | on every card and on `compare-missing` |
| `compare-missing` | `article` (repeated) | "This graph is gone" |
| `sankey-chart` | `div[role=img]` (repeated) | one per card; `data-ready`; drawn lazily |
| `donut-chart` | `div[role=img]` (repeated) | only on cards with categories; drawn when the switch is first turned on |
| `compare-add-select` | `select` | graphs not yet compared |
| `compare-add` | `button` | "Add" |
| `compare-limit-message` | `p[role=status]` | hidden until 12 graphs are compared |
| `compare-shared-colours` | `div` | the shared colour note and legend; absent without categories |

The compare page also uses `state-loading`, `state-empty`, `state-error`, `state-retry` and `toast`.

### Settings

| data-testid | element | notes |
|---|---|---|
| `settings-theme-option` | `input[type=radio]` (repeated) | three cards in the order system, light, dark |
| `settings-storage-backend` | `select` | `file` or `mongo` |
| `settings-storage-folder` | `code` | read-only path of the graphs folder; only for the `file` backend |
| `settings-storage-connection` | `select` | only for the `mongo` backend |
| `settings-storage-database` | `input[type=text]` | only for the `mongo` backend |
| `settings-migrate` | `input[type=checkbox]` | "Copy my N existing graphs to the new location" |
| `settings-test-storage` | `button` | "Test storage" |
| `settings-storage-status` | `p` | result line of the storage test |
| `settings-copy-report` | `div[role=status]` | after a copy; `data-copied`, `data-skipped`, `data-unreadable`, `data-folders`, `data-folders-skipped` |
| `settings-copy-unreadable` | `ul` | unreadable graph ids, at most 50 |
| `connection-add` | `button` | "Add connection" |
| `settings-connection` | `div[role=group]` (repeated) | one card per connection |
| `connection-name` | `input[type=text]` | `^[A-Za-z0-9_.-]{1,64}$` |
| `connection-uri` | `input[type=password]` | placeholder "(unchanged)" once stored; never prefilled |
| `connection-default-db` | `input[type=text]` | optional |
| `connection-test` | `button` | "Test connection" |
| `connection-status` | `p` | result line |
| `connection-latency` | `strong` | after a successful test |
| `connection-delete` | `button` | removes the card at once; needs Save |
| `settings-max-links` | `input[type=number]` | 100 to 5,000,000 |
| `settings-max-drawn-links` | `input[type=number]` | 50 to 20,000 |
| `settings-max-upload-mb` | `input[type=number]` | 1 to 100 |
| `settings-mongo-timeout` | `input[type=number]` | 500 to 300,000 ms |
| `settings-sources-dir` | `code` | read-only path |
| `settings-remote-mode` | `span` | badge |
| `settings-writes-allowed` | `span` | badge |
| `settings-error` | `div[role=group]` | error summary "Settings were not saved" |
| `settings-save-status` | `p[role=status]` | "All changes saved." and the other states |
| `settings-discard` | `button` | "Discard changes"; hidden unless there are changes |
| `settings-save` | `button` | "Save settings" |
| `settings-conflict-overwrite` | `button` | "Save mine anyway" in the conflict dialog |
| `conflict-reload` | `button` | "Show their settings" in the conflict dialog (the editor's banner uses the same id) |

The settings page also uses `confirm-dialog`, `state-loading`, `state-error`, `state-retry`,
`state-empty` (the "No connections yet" block), `toast`, `remote-banner` and `read-only-banner`. The header
`theme-switch` and the `settings-theme-option` cards stay in step.

### Error pages

The shell ids, `state-empty` (404) and `state-error` with `state-retry` (every other error). There is no other test id.

## DOM wait signals

`wait_for_load_state("networkidle")` is not reliable (plotly.js, lazy chart drawing, the debounced
preview). Wait for these signals instead.

| Signal | Where | Meaning |
|---|---|---|
| `body[data-shell=ready]` | every page | `core/shell.js` finished wiring the theme switch and loading state; the only ready signal of the error pages |
| `main#main[data-page=<name>]` | every page | which page rendered |
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

## Theming

* Tokens live in `css/tokens.css` as custom properties on `:root`. The dark set is defined twice:
  under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])` (so
  `system` follows the device) and under `:root[data-theme="dark"]` (explicit choice). An explicit
  `data-theme` always wins over the media query. A print block resets to the light tokens.
* Main values (light and dark): surface `#fcfcfb` and `#1a1a19`, page plane `#f9f9f7` and `#0d0d0d`,
  ink `#0b0b0b` and `#f0efec`, accent `#256abf`, borders of inputs `--border-strong` (`#898781`). The
  `<meta name="theme-color">` tags match the surface tokens. The ink and surface tokens equal
  `render/palette.py`, the palette the charts use; a test compares them.
* No colour literal exists outside `tokens.css`. Text never wears a data colour; chart colours come
  from the server figure only.
* The theme is chosen in the header switch or on the settings page and stored in the server settings
  (`theme`). `<html data-theme>` is rendered by the server, so a first visit paints the saved theme
  with no flash. On a read-only server the browser's own choice (`localStorage`
  `sankey-studio.theme`, read by the classic script `core/theme-init.js` before first paint) wins.
* Charts carry their own colours: the client asks for `?theme=light|dark` and redraws on a theme
  change (`sankey-chart[data-chart-theme]` shows which). The editor preview can be pinned with
  "Preview colours" (Match page, Light, Dark); exported files use their own `export-theme` choice
  (default Light), independent of both.
* Breakpoints: 480, 640 (header goes to one row), 900 (Source and Transform side by side) and 1280 px (settings rail);
  the viewer chart card is always full width (the export popover opens under its icon at every width). `prefers-reduced-motion: reduce`
  cuts animations and transitions to 0.01 ms; the `html` toast clearance padding never transitions.
  `forced-colors: active` is handled for buttons and inputs and for the drop marks of the library
  (a solid `Highlight` outline accepts, a dashed `GrayText` outline refuses).

## Accessibility

* Landmarks and skip: skip link first, `header`, `nav` "Main", `main#main` (focusable programmatically),
  a `region` for each save bar and the toast region. Tab order of every page starts with the skip
  link, the brand, `nav-library`, `nav-new`, `nav-settings` and the three theme buttons.
* Keyboard in the editor: the first Tab stop in the main area is `graph-settings-button`, then the chart
  tabs and the chart tools ("Order nodes", "Reset order", the chart settings gear). Enter, Space or
  ArrowDown on a gear opens its menu or popover and Escape returns to it. The wizard starts on the name
  and Enter in it is Next. The bars of the Sankey are mouse-only; `entries-add` (add a flow) and
  `chart-order-open` (reorder, with `order-up` and `order-down`) are the keyboard and single-pointer ways
  to the same edits (WCAG 2.1.1 and 2.5.7). Every dialog traps the focus, returns it to the opener and
  closes on Esc, the newest first.
* Library drag and drop is a pointer shortcut only: "Move" on a card, "Move to collection" in the selection
  bar and the Move dialog do every move from the keyboard or with a single pointer (WCAG 2.1.1 and 2.5.7).
  A target that refuses is dashed (shape, not only colour) and the live region says why.
* Live regions: `#a11y-polite` and `#a11y-assertive` announce results without a focus change (graph
  counts, chart tab switches, save results, import and upload outcomes); toasts live in a polite
  region and errors are `role=alert`.
* Charts have `role=img` with a descriptive `aria-label` and an HTML twin: the legend list, the
  category table (the donut as numbers) and the links table.
* Tabs follow the WAI-ARIA pattern: roving `tabindex`, Arrow, Home and End move and activate, panels
  stay in the DOM so form state survives switching (the editor's Donut tab leaves the DOM while there is
  no donut).
* Dialogs trap focus, restore it to the opener and cancel on Esc. The compare switch is
  `role=switch` with `aria-checked`. Chip inputs, steppers and row tables name every control (for
  example `Source, row 3`, `Remove row 3`).
* Focus rings are a 2 px outline with a 2 px offset in the theme's focus colour on buttons, links,
  tabs, cards and switches; inputs also change their border. Contrast of text is at least 4.5:1 (3:1 for
  large text) in both themes, and borders of inputs use `--border-strong`.
* No horizontal page scroll at 360, 390, 768 and 1440 px; the editor's form row stacks below 900 px; the
  chart settings popover, the menus and every dialog stay inside the window at 390 px and the wizard has no
  horizontal scroll on either step; the library grid is `auto-fill` with cards at least 19 rem wide.
* Visible names and accessible names can differ: card buttons are `Edit "<name>"`, `Duplicate "<name>"`
  and `Delete "<name>"`; connection buttons are `Test connection <name>` and `Delete connection
  <name>`; the export buttons in the editor are `Download the sankey chart as SVG` and so on. Prefer
  test ids to role names for these.

## Frontend rules

These are enforced by tests (`tests/web/test_templates_policy.py`, `tests/web/test_static_policy.py`,
`tests/web/test_pages_xss.py`) and Semgrep rules (`.semgrep/rules/sankey-js.yml`,
`sankey-html.yml`); see [quality.md](quality.md).

* Vanilla ES modules, no build step, no bundler, no framework, no transpiling. Every script passes
  `node --check`.
* No CDN and no external URL of any kind: scripts, styles, fonts, images and `fetch` targets are local
  (`/static/...`). plotly.js is `/static/vendor/plotly.min.js`. The CSP is `default-src 'self';
  script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none';
  frame-ancestors 'none'; base-uri 'none'; form-action 'self'`.
* Banned sinks in `templates/` and `static/`: `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write` and `document.writeln`, `eval`, `new Function`, `Function(...)`, Jinja `|safe` and
  `autoescape off`. Also banned: `javascript:` URLs, string arguments to `setTimeout` and
  `setInterval`, `document.cookie`, `srcdoc`, `window.open`, iframes, `debugger`, `console.log`,
  `console.debug` and `console.info`, inline `style` attributes in HTML, HTML imports and CSS
  `expression()`.
* No inline scripts and no inline event handlers. The only `<script>` without `src` is the JSON boot
  block. `core/theme-init.js` is a classic external script in `<head>`; everything else is
  `<script type="module">`.
* Page data reaches the page only through the `application/json` boot block, written with
  `{{ boot|tojson }}`. All other data is fetched through `core/api.js`, which uses only
  root-relative `/api/v1` paths, sends `Content-Type: application/json` for bodies (a `FormData` for
  the upload), and turns every failure into an `ApiError`.
* User text is always a text node (`h()`), never markup. Control and bidirectional characters are
  removed from text and attributes by `core/text.js` and from chart labels by `core/chart.js`.
* Every JavaScript file has at most 300 lines. Split a module instead of growing it.
* No colour literal outside `css/tokens.css` (the two `theme-color` metas are the exception).
* Every `data-testid` is in the contract lists (see [data-testid reference](#data-testid-reference)).
* Editor panels register through `editor/panels.js` (`registerPanel`; names are unique) and a panel
  that throws is replaced by an error block without stopping the others.

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
  (mode 0600). Files uploaded to `--sources-dir` persist between tests that share it, and an upload
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
  envelope are in [api.md](api.md).
* There is no real MongoDB in a plain run. A connection to an unreachable host (for example
  `mongodb://u:p@127.0.0.1:1/`) fails only after `mongo_timeout_ms` (15 s by default); set the setting
  to 500 in tests that exercise the failure path.
* The Playwright fixtures, the live-server helper, mongomock-backed apps, failure artefacts and the
  list of flows are described in [e2e.md](e2e.md); the harness code is in `tests/e2e`.

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
