/**
 * The path above the list while a collection is open: Library > Finance > Q3 reports.
 *
 * Every crumb is a real link (`/` and `/?folder=<id>`), so the browser's own history, reload and
 * "open in a new tab" work and the page needs no routing code. The last crumb is the open
 * collection and carries `aria-current="page"`. Long names are cut by the style sheet with the full
 * name in the tooltip. Names are text nodes with control and direction characters removed.
 *
 * `createBreadcrumb()` returns `{el, update(path)}`; `path` is the list of folders from the top down
 * to the open one (`[]` at the top level hides the whole bar).
 *
 * Every crumb carries `data-folder-id` (the collection's id, "root" for Library, the same convention
 * as the Move dialog's options): the crumbs are drop targets for drag and drop (dnd.js), and the
 * last one is the open collection, where nothing can be dropped ("already here").
 *
 * Test ids: folder-breadcrumb (the nav), folder-crumb (each link, the Library link included).
 */

import { h } from "../core/dom.js";
import { folderLabel } from "./names.js";

function crumb(label, href, { id, current }) {
  return h(
    "li",
    null,
    h("a", { class: "breadcrumb-link", href, title: label, "aria-current": current ? "page" : null, "data-testid": "folder-crumb", "data-folder-id": id }, label),
  );
}

/**
 * @returns {{el: HTMLElement, update: (path: {id: string, name: string}[]) => void}}
 */
export function createBreadcrumb() {
  const list = h("ol", { class: "breadcrumb-list" });
  const el = h("nav", { class: "breadcrumbs", "aria-label": "Collection path", hidden: true, "data-testid": "folder-breadcrumb" }, list);
  return {
    el,
    update(path) {
      el.hidden = path.length === 0;
      const last = path.length - 1;
      list.replaceChildren(
        crumb("Library", "/", { id: "root", current: false }),
        ...path.map((folder, index) => crumb(folderLabel(folder.name), `/?folder=${folder.id}`, { id: folder.id, current: index === last })),
      );
    },
  };
}
