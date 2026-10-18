# The shell and the error pages

Part of the [UI reference](../ui.md).

Contents

* [The shell](#the-shell)
* [Error pages](#error-pages)

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
  question opens above the Add dialog, both described in [Editor](editor.md)): Esc closes only the newest.
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
[api.md](../api.md)). A CORS preflight (`OPTIONS`) is refused with 405 and no CORS headers are ever sent.

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
