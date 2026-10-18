# Library

Part of the [UI reference](../ui.md).

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
| Loading | `state-loading` "Loading graphs", only when the first paint cannot use the [boot data](../ui.md#boot-data) (a filter in the address, or arrival by Back or Forward) |
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
  `data-writes`, is disabled with the [usual title](shell.md#the-shell) and "New graph here" loses its `href`. The note says
  duplicating, deleting, moving and importing are turned off. An empty collection says "This server is
  read-only, so graphs cannot be created or moved here." and has no buttons.
