// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * MongoDB connections section: the list of connection rows, "Add connection" and the undo toast
 * after a delete.
 *
 * Rows are kept as long as their key is in the draft, so typing never rebuilds a row (focus and
 * caret stay). A save replaces the draft with fresh keys, which rebuilds every row with an empty
 * connection string.
 */

import { announce } from "../core/a11y.js";
import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { emptyState } from "../core/states.js";
import { stripBidi } from "../core/text.js";
import { toast } from "../core/toast.js";
import { MAX_CONNECTIONS } from "./constants.js";
import { buildRow } from "./connection-row.js";
import { section } from "./ui.js";

function nameOf(row) {
  return stripBidi(row.name.trim() || "New connection");
}

function removalHandler(store, addButton) {
  return (key) => {
    const removed = store.removeRow(key);
    if (!removed) {
      return;
    }
    const label = nameOf(removed.row);
    announce(`Connection ${label} removed.`);
    toast.info(`Connection "${label}" removed. It is deleted when you save.`, {
      action: { label: "Undo", onClick: () => store.restoreRow(removed) },
    });
    const rows = store.draft.connections;
    const next = rows[Math.min(removed.index, rows.length - 1)];
    if (!next || !store.focus(`row.${next.key}.name`)) {
      addButton.focus();
    }
  };
}

function createReconciler(store, list, remove) {
  const views = new Map();
  return {
    views,
    run() {
      const rows = store.draft.connections;
      const wanted = new Set(rows.map((row) => row.key));
      for (const key of [...views.keys()]) {
        if (!wanted.has(key)) {
          views.get(key).dispose(); // a test still running for this row is dropped, not announced
          views.delete(key);
        }
      }
      for (const row of rows) {
        if (!views.has(row.key)) {
          views.set(row.key, buildRow(store, row, { remove }));
        }
      }
      const order = rows.map((row) => views.get(row.key).el);
      if (order.length !== list.children.length || order.some((el, index) => list.children[index] !== el)) {
        list.replaceChildren(...order);
      }
    },
  };
}

function parts() {
  return {
    list: h("ul", { class: "connection-list list-reset", "aria-label": "MongoDB connections" }),
    empty: emptyState({
      title: "No connections yet",
      message: "Add one to read graph data from MongoDB or to keep your graphs there.",
      icon: "database",
      compact: true,
    }),
    error: h("p", { class: "field-error", hidden: true }),
    limit: h("p", { class: "hint", hidden: true }, `You can keep up to ${MAX_CONNECTIONS} connections.`),
    addButton: h("button", { type: "button", class: "btn", "data-testid": "connection-add" }, icon("plus"), "Add connection"),
  };
}

function syncChrome(store, ui) {
  const count = store.draft.connections.length;
  ui.empty.hidden = count > 0;
  ui.list.hidden = count === 0;
  ui.addButton.disabled = count >= MAX_CONNECTIONS;
  ui.limit.hidden = count < MAX_CONNECTIONS;
  const message = store.message("connections");
  ui.error.textContent = stripBidi(message);
  ui.error.hidden = !message;
}

/**
 * Builds the section.
 * @param {import("./store.js").SettingsStore} store
 * @returns {{el: HTMLElement, sync: () => void, addButton: HTMLButtonElement}}
 */
export function buildConnections(store) {
  const ui = parts();
  const reconciler = createReconciler(store, ui.list, removalHandler(store, ui.addButton));
  ui.addButton.addEventListener("click", () => {
    const row = store.addRow();
    store.focus(`row.${row.key}.name`);
    announce("Connection added. Enter its name and connection string.");
  });
  const el = section({
    id: "settings-connections",
    title: "MongoDB connections",
    text: "Named connections that graphs can read from. Connection strings are kept in this app's settings and never shown again.",
    body: [ui.empty, ui.list, ui.error, h("div", { class: "cluster" }, ui.addButton, ui.limit)],
  });
  return {
    el,
    addButton: ui.addButton,
    sync() {
      reconciler.run();
      for (const view of reconciler.views.values()) {
        view.sync();
      }
      syncChrome(store, ui);
    },
  };
}
