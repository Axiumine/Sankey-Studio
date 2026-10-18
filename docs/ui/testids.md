# data-testid reference

Part of the [UI reference](../ui.md).

`data-testid` values are a contract: end-to-end tests select by them, so they are never renamed or
removed. The list has 257 distinct ids (count them with the two files below, not by hand). The base list
of 127 is kept in `tests/web/test_static_policy_support.py` as `API_TESTIDS`;
the other 130, used by the shared frontend code, are in `src/sankey_studio/web/static/testids-extra.txt`
(append-only: add an id with a shell `>>` and a comment, never by editing the file). A few dynamic ids
(`change-source-kind-<tab>`, `source-column-<role>`) are built from a fixed set and are not listed one by one. `tests/web/test_static_policy.py` fails when a
template or script uses an id found in neither. To add an id, use a kebab-case literal in the
template or script and list it in `testids-extra.txt` with a comment saying where it is used.

Conventions: "repeated" means one element per row, card or item. "Hidden" means present in the DOM
with the `hidden` attribute; "absent" means removed from the DOM. Tests must check visibility, not
presence, for hidden elements. A dynamic id such as `source-column-<role>` is built from `source`,
`target`, `value` and `category`.

## Shell (every page)

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

## Library

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

## Editor

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

## Viewer

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

## Compare

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

## Settings

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

## Error pages

The shell ids, `state-empty` (404) and `state-error` with `state-retry` (every other error). There is no other test id.
