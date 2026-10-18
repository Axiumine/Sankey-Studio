# Theming, accessibility and frontend rules

Part of the [UI reference](../ui.md).

Contents

* [Theming](#theming)
* [Accessibility](#accessibility)
* [Frontend rules](#frontend-rules)

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
`sankey-html.yml`); see [quality.md](../quality.md).

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
* Every `data-testid` is in the contract lists (see [data-testid reference](testids.md#data-testid-reference)).
* Editor panels register through `editor/panels.js` (`registerPanel`; names are unique) and a panel
  that throws is replaced by an error block without stopping the others.
