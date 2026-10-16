// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The viewer's header under the page title: description, tags (each opens the library filtered by
 * that tag), and a meta line with the source badge, the update time and the revision.
 * All text comes from the GraphSummary in the boot data and is set as text.
 */

import { h } from "../core/dom.js";
import { formatDate, formatRelative } from "../core/format.js";
import { icon } from "../core/icons.js";

const SOURCES = {
  text: { label: "Text data", icon: "file" },
  manual: { label: "Manual table", icon: "table" },
  mongo: { label: "MongoDB", icon: "database" },
};

/**
 * @param {{description: string, tags: string[], source_type: string, revision: number, updated_at: string}} graph
 * @returns {HTMLElement}
 */
export function graphHeader(graph) {
  const source = SOURCES[graph.source_type] ?? { label: String(graph.source_type), icon: "file" };
  const tags = (graph.tags ?? []).map((tag) =>
    h("li", null, h("a", { class: "chip", href: `/?tag=${encodeURIComponent(tag)}`, title: `Show graphs tagged “${tag}”` }, tag)),
  );
  return h(
    "header",
    { class: "viewer-header stack stack-sm" },
    graph.description ? h("p", { class: "viewer-description" }, graph.description) : null,
    tags.length > 0 ? h("ul", { class: "tag-list", role: "list", "aria-label": "Tags" }, tags) : null,
    h(
      "p",
      { class: "viewer-meta" },
      h("span", { class: "badge", "data-source-type": graph.source_type }, icon(source.icon, { size: 12 }), source.label),
      h("time", { datetime: graph.updated_at, title: formatDate(graph.updated_at, { time: true }) }, `Updated ${formatRelative(graph.updated_at)}`),
      h("span", { title: `Revision ${graph.revision}` }, `Revision ${graph.revision}`),
    ),
  );
}
