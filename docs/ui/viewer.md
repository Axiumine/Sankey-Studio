# Viewer and compare

Part of the [UI reference](../ui.md).

Contents

* [Viewer](#viewer)
* [Compare](#compare)

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
