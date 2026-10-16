// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Tab "Manual": the links typed into an editable table and stored inside the graph
 * (`{type: "manual", links: [{source, target, value, category?}]}`, up to 5000 links).
 *
 * A row is sent to the preview only when source, target and a value above 0 are filled in, so
 * half-typed rows never cause errors. Links with the same source and target add up to ONE entry in
 * the entries table, and a category set there is written to every link of that pair; rows that
 * repeat a pair carry a badge so that is not a surprise. Rows can be pasted from a spreadsheet,
 * into a cell or with "Paste rows".
 * Test ids: manual-table, manual-row (each row), manual-add-row.
 */

import { confirmDialog } from "../../core/dialog.js";
import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { createRowTable } from "../meta/row-table.js";
import { isReservedCategory, knownCategories, knownNodeNames, parseNumber, sameJson } from "../meta/util.js";
import { openPasteRows } from "./paste-rows.js";

const LINKS = ["draft", "source", "links"];
export const MAX_LINKS = 5000;

function toLink(values) {
  const source = values.source.trim();
  const target = values.target.trim();
  const value = parseNumber(values.value);
  if (!source || !target || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  const category = values.category.trim();
  return category ? { source, target, value, category } : { source, target, value };
}

function problems(values) {
  const out = {};
  const text = values.value.trim();
  const n = parseNumber(text);
  if (text !== "" && !(Number.isFinite(n) && n > 0)) {
    out.value = "Use a number above 0.";
  }
  if (isReservedCategory(values.category)) {
    out.category = "Uncategorized and Other are reserved names. Pick another category.";
  }
  return out;
}

function pairBadges(rows) {
  const keyOf = (values) => `${values.source.trim()}\u0000${values.target.trim()}`;
  const counts = new Map();
  for (const values of rows) {
    if (values.source.trim() && values.target.trim()) {
      counts.set(keyOf(values), (counts.get(keyOf(values)) ?? 0) + 1);
    }
  }
  return rows.map((values) => ((counts.get(keyOf(values)) ?? 0) > 1 ? "Same source and target as another row: they add up to one entry" : ""));
}

function buildTable(store) {
  const names = () => knownNodeNames(store.get().bundle);
  const table = createRowTable({
    caption: "Links",
    addLabel: "Add a link",
    emptyMessage: "No links yet.",
    incompleteHint: "Not drawn yet: a link needs a source, a target and a value above 0.",
    maxRows: MAX_LINKS,
    footnote: "Links with the same source and target add up to one entry. A category set for that entry in the entries table applies to all of them.",
    testids: { table: "manual-table", row: "manual-row", add: "manual-add-row" },
    columns: [
      { key: "source", label: "Source", suggest: names, maxlength: 200, placeholder: "From" },
      { key: "target", label: "Target", suggest: names, maxlength: 200, placeholder: "To" },
      { key: "value", label: "Value", inputmode: "decimal", maxlength: 40, placeholder: "0", className: "ed-col-value" },
      { key: "category", label: "Category (optional)", suggest: () => knownCategories(store.get().bundle), maxlength: 100, placeholder: "None" },
    ],
    toValues: (link) => ({ source: link.source, target: link.target, value: String(link.value), category: link.category ?? "" }),
    toItem: toLink,
    validate: problems,
    badges: pairBadges,
    onCommit: (links) => {
      if (store.get().draft.source.type === "manual") {
        store.patch(LINKS, links);
      }
      if (table.rowCount() === 0) {
        table.addRow(false);
      }
    },
  });
  return table;
}

/**
 * Builds the tab.
 * @param {{store: object, fields: Record<string, object>, toast?: object}} options
 * @returns {{el: HTMLElement, resolve: (index: number, key: string) => object, dispose: () => void}}
 */
export function createManualTab({ store, toast }) {
  const table = buildTable(store);
  const pasteRows = h("button", { type: "button", class: "btn btn-sm", on: { click: () => openPasteRows(table, toast) } }, icon("copy", { size: 14 }), "Paste rows");
  const clearAll = h("button", { type: "button", class: "btn btn-sm btn-ghost", on: { click: () => wipe() } }, icon("trash", { size: 14 }), "Clear all");
  async function wipe() {
    const ok = await confirmDialog({ title: "Remove all links?", message: "Every row of the table is removed.", confirmLabel: "Remove all", danger: true });
    if (ok) {
      table.setItems([]);
      store.patch(LINKS, []);
      table.focusCell(0, "source");
    }
  }
  const off = store.subscribe(
    (links) => {
      if (links && !sameJson(links, table.committed())) {
        table.setItems(links);
      }
      if (table.rowCount() === 0) {
        table.addRow(false);
      }
    },
    { select: (state) => (state.draft.source.type === "manual" ? state.draft.source.links : null), immediate: true },
  );
  table.el.querySelector(".ed-rows-foot").append(pasteRows, clearAll);
  return {
    el: table.el,
    resolve: (index, key) => ({ setError: (message) => table.setCellError(index, key, message) }),
    dispose: off,
  };
}
