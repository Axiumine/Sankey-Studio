/**
 * The collections of the open level, as cards above the graphs.
 *
 * `folderSection({folders, handlers})` returns the whole block (heading "Collections", the count and
 * a grid of cards), or `null` when the level has no collection. Each card: the folder icon, the name
 * as a real link into the collection (`/?folder=<id>`), "N graphs, M collections", and the actions
 * Rename, Move and Delete (they carry `data-writes`, so a read-only server disables them). Names
 * are text nodes with control and direction characters removed ("Untitled collection" when nothing
 * is left); the full name is the tooltip.
 *
 * With `draggable` (writes allowed) each card is `draggable="true"`: dnd.js moves it into another
 * collection when it is dropped on a card or a crumb. The Move button stays the way without a mouse.
 *
 * Test ids: folder-grid, folder-card (data-folder-id), folder-open, folder-rename, folder-move,
 * folder-delete.
 */

import { h } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { icon } from "../core/icons.js";
import { folderLabel } from "./names.js";

function action(label, name, testid, onClick, extra = null) {
  return h(
    "button",
    { type: "button", class: ["btn", "btn-sm", extra], "data-writes": true, "aria-label": `${label} “${name}”`, "data-testid": testid, on: { click: (event) => onClick(event.currentTarget) } },
    label,
  );
}

function folderCard(folder, handlers, draggable) {
  const name = folderLabel(folder.name);
  const counts = `${formatCount(folder.graph_count, "graph")}, ${formatCount(folder.child_count, "collection")}`;
  return h(
    "article",
    { class: "card folder-card", "data-testid": "folder-card", "data-folder-id": folder.id, draggable: draggable ? "true" : null },
    h(
      "h3",
      { class: "folder-card-title" },
      icon("folder", { size: 18 }),
      h("a", { class: "card-link", href: `/?folder=${folder.id}`, title: name, "data-testid": "folder-open" }, name),
    ),
    h("p", { class: "folder-card-meta" }, counts),
    h(
      "div",
      { class: "folder-card-actions" },
      action("Rename", name, "folder-rename", (button) => handlers.onRename(folder, button)),
      action("Move", name, "folder-move", (button) => handlers.onMove(folder, button)),
      action("Delete", name, "folder-delete", (button) => handlers.onDelete(folder, button), "btn-ghost folder-card-delete"),
    ),
  );
}

/**
 * @param {{folders: object[], handlers: {onRename: Function, onMove: Function, onDelete: Function}, draggable?: boolean}} options
 * @returns {HTMLElement | null}
 */
export function folderSection({ folders, handlers, draggable = false }) {
  if (folders.length === 0) {
    return null;
  }
  return h(
    "section",
    { class: "folder-section", "aria-label": "Collections", tabindex: "-1" },
    h("h2", { class: "folder-section-title" }, "Collections ", h("span", { class: "text-muted folder-section-count" }, `(${folders.length})`)),
    h("ul", { class: "folder-grid", role: "list", "data-testid": "folder-grid" }, folders.map((folder) => h("li", null, folderCard(folder, handlers, draggable)))),
  );
}
