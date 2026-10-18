# Editor

Part of the [UI reference](../ui.md).

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
source" (`graph-settings-source`); it is an ARIA menu button (see the menu keys in [The shell](shell.md#the-shell)). The gear carries
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
