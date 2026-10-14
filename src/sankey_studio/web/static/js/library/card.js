/**
 * One graph card of the library.
 *
 * Every user string (name, description, tags) is a text node. The card holds: a checkbox to pick
 * the graph for a comparison, the name as the link that opens the viewer, the description,
 * tags (each filters the list), a source badge, the update time and revision, and the row
 * actions (edit, duplicate, move, delete). Duplicate, move and delete carry `data-writes`, so a
 * read-only server disables them (core/boot.js `lockWriteControls`). "Move" (asks for a collection)
 * is only there once a collection exists. In search results, where graphs of every collection are
 * mixed, a chip names the collection a graph sits in and links to it.
 *
 * Test ids: graph-card (data-graph-id), compare-select, graph-open, graph-edit, graph-duplicate,
 * graph-move, graph-delete, graph-folder.
 */

import { h } from "../core/dom.js";
import { formatDate, formatRelative } from "../core/format.js";
import { icon } from "../core/icons.js";
import { stripBidi } from "../core/text.js";
import { graphHref } from "./data.js";
import { isFolderId } from "./state.js";

const SOURCES = {
  text: { label: "Text data", icon: "file" },
  manual: { label: "Manual table", icon: "table" },
  mongo: { label: "MongoDB", icon: "database" },
};
const TAGS_SHOWN = 4;

function sourceBadge(type) {
  const source = SOURCES[type] ?? { label: String(type), icon: "file" };
  return h("span", { class: "badge", "data-source-type": type }, icon(source.icon, { size: 12 }), source.label);
}

function tagList(tags, onTag) {
  if (tags.length === 0) {
    return null;
  }
  const shown = tags.slice(0, TAGS_SHOWN).map((tag) =>
    h("li", null, h("button", { type: "button", class: "chip", title: `Show graphs tagged “${stripBidi(tag)}”`, on: { click: () => onTag(tag) } }, tag)),
  );
  const rest = tags.slice(TAGS_SHOWN);
  if (rest.length > 0) {
    shown.push(h("li", null, h("span", { class: "chip", title: rest.map(stripBidi).join(", ") }, `+${rest.length} more`)));
  }
  return h("ul", { class: "tag-list", role: "list", "aria-label": "Tags" }, shown);
}

function selectBox(graph, ctx) {
  const picked = ctx.selection.has(graph.id);
  const blocked = !picked && ctx.selection.full();
  const input = h("input", {
    type: "checkbox",
    checked: picked,
    disabled: blocked,
    title: blocked ? "You can compare up to 12 graphs at a time" : null,
    "aria-label": `Select “${graph.name}” to compare`,
    "data-testid": "compare-select",
    on: { change: () => ctx.onSelect(graph, input) },
  });
  return h("label", { class: "graph-card-select" }, input);
}

function folderChip(graph, ctx) {
  const path = ctx.pathOf && isFolderId(graph.folder_id) ? ctx.pathOf(graph.folder_id) : null;
  if (path === null) {
    return null;
  }
  return h("a", { class: "graph-card-path", href: `/?folder=${graph.folder_id}`, title: `Open the collection ${path}`, "data-testid": "graph-folder" }, icon("folder", { size: 12 }), path);
}

function actions(graph, ctx) {
  const label = (verb) => `${verb} “${graph.name}”`;
  const move = ctx.canMove
    ? h("button", { type: "button", class: "btn btn-sm", "data-writes": true, "aria-label": label("Move"), "data-testid": "graph-move", on: { click: (event) => ctx.onMove(graph, event.currentTarget) } }, icon("folder", { size: 14 }), "Move")
    : null;
  return h(
    "div",
    { class: "graph-card-actions" },
    h("a", { class: "btn btn-sm", href: graphHref(graph.id, "/edit"), "aria-label": label("Edit"), "data-testid": "graph-edit" }, icon("edit", { size: 14 }), "Edit"),
    h("button", { type: "button", class: "btn btn-sm", "data-writes": true, "aria-label": label("Duplicate"), "data-testid": "graph-duplicate", on: { click: (event) => ctx.onDuplicate(graph, event.currentTarget) } }, icon("copy", { size: 14 }), "Duplicate"),
    move,
    h("button", { type: "button", class: "btn btn-sm btn-ghost graph-card-delete", "data-writes": true, "aria-label": label("Delete"), "data-testid": "graph-delete", on: { click: (event) => ctx.onDelete(graph, event.currentTarget) } }, icon("trash", { size: 14 }), "Delete"),
  );
}

function meta(graph) {
  const time = h(
    "time",
    { datetime: graph.updated_at, title: formatDate(graph.updated_at, { time: true }) },
    `Updated ${formatRelative(graph.updated_at)}`,
  );
  return h(
    "div",
    { class: "graph-card-meta" },
    sourceBadge(graph.source_type),
    time,
    h("span", { title: `Revision ${graph.revision}` }, `Rev ${graph.revision}`),
  );
}

/**
 * Builds a graph card.
 * @param {{id: string, name: string, description: string, tags: string[], source_type: string, revision: number, updated_at: string, folder_id?: string | null}} graph  a GraphSummary
 * @param {{selection: object, onSelect: Function, onTag: Function, onDuplicate: Function, onDelete: Function, onMove?: Function, canMove?: boolean, pathOf?: ((id: string) => string | null) | null}} ctx
 * @returns {HTMLElement}
 */
export function graphCard(graph, ctx) {
  return h(
    "article",
    { class: "card graph-card", "data-testid": "graph-card", "data-graph-id": graph.id },
    h(
      "div",
      { class: "graph-card-head" },
      selectBox(graph, ctx),
      h("h2", { class: "graph-card-title" }, h("a", { class: "card-link", href: graphHref(graph.id), title: graph.name, "data-testid": "graph-open" }, graph.name)),
    ),
    graph.description ? h("p", { class: "graph-card-desc" }, graph.description) : null,
    folderChip(graph, ctx),
    tagList(graph.tags ?? [], ctx.onTag),
    meta(graph),
    actions(graph, ctx),
  );
}
