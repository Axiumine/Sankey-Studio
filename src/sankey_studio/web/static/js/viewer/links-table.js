/**
 * "Table view of the links": the accessible twin of the Sankey. A `<details>` block that builds a
 * sortable, paged table (core/table.js) of the bundle's entries the first time it is opened, and
 * keeps it current when the bundle changes (theme switch). Test id: links-table.
 */

import { createTable } from "../core/table.js";
import { h } from "../core/dom.js";
import { formatNumber } from "../core/format.js";
import { tableDisclosure } from "./parts.js";

const PAGE_SIZE = 20;

function columns(suffix) {
  return [
    { key: "source", label: "From", sortable: true, rowHeader: true },
    { key: "target", label: "To", sortable: true },
    { key: "value", label: "Value", sortable: true, numeric: true, render: (row) => `${formatNumber(row.value)}${suffix}` },
    { key: "category", label: "Category", sortable: true, value: (row) => (row.mixed ? "Several" : row.category), render: (row) => (row.mixed ? "Several" : row.category) },
  ];
}

/**
 * @param {{name: string}} graph
 * @returns {{el: HTMLElement, update: (bundle: object, suffix: string) => void}}
 */
export function createLinksTable(graph) {
  const noteSlot = h("div");
  const holder = h("div", { class: "stack stack-sm" }, noteSlot);
  const el = tableDisclosure({ testid: "links-table", label: "Table view of the links" }, holder);
  let table = null;
  let latest = { entries: [], entries_total: 0 };
  let unit = "";

  const rows = () => latest.entries.map((entry) => ({ ...entry }));
  const showNote = () => {
    const shown = latest.entries.length;
    const cut = latest.entries_total > shown;
    noteSlot.replaceChildren(
      ...(cut ? [h("p", { class: "hint" }, `The first ${formatNumber(shown, { maximumFractionDigits: 0 })} of ${formatNumber(latest.entries_total, { maximumFractionDigits: 0 })} links. The editor lists them all.`)] : []),
    );
  };
  const build = () => {
    table = createTable({
      caption: `Links of ${graph.name}`,
      columns: columns(unit),
      rows: rows(),
      pageSize: PAGE_SIZE,
      empty: "This graph has no links.",
      rowProps: (row) => ({ "data-source": row.source, "data-target": row.target }),
    });
    holder.append(table.el);
  };
  el.addEventListener("toggle", () => {
    if (el.open && !table) {
      showNote();
      build();
    }
  });
  return {
    el,
    update(bundle, suffix) {
      latest = bundle;
      unit = suffix;
      if (table) {
        showNote();
        table.update({ rows: rows() });
      }
    },
  };
}
