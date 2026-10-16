// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The error summary (`data-testid="settings-error"`): after a save that did not go through, it
 * lists every visible field problem as a button that jumps to the field, plus the messages that
 * belong to no field (storage unreachable, read-only, network). Focus moves here when there is no
 * field to focus. It is not a live region: the failure toast is what screen readers announce.
 */

import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { stripBidi } from "../core/text.js";
import { LIMITS } from "./constants.js";

const FIXED_LABELS = {
  "storage.backend": "Storage location",
  "storage.connection": "Storage connection",
  "storage.database": "Storage database",
  connections: "MongoDB connections",
};
const ROW_PARTS = { name: "Name", uri: "Connection string", database: "Default database" };

/**
 * A human name for a field id (see validate.js).
 * @param {string} id
 * @param {import("./store.js").SettingsStore} store
 * @returns {string}
 */
export function labelFor(id, store) {
  if (FIXED_LABELS[id]) {
    return FIXED_LABELS[id];
  }
  const limit = LIMITS.find((spec) => id === `limits.${spec.key}`);
  if (limit) {
    return limit.label;
  }
  const match = /^row\.([^.]+)\.(\w+)$/.exec(id);
  const row = match && store.draft.connections.find((item) => item.key === match[1]);
  if (!row) {
    return id;
  }
  return `${ROW_PARTS[match[2]] ?? match[2]} (${row.name.trim() || "new connection"})`;
}

function itemNode(item, store) {
  const jump = h("button", { type: "button", class: "link-button", on: { click: () => store.focus(item.id) } }, item.label);
  return h("li", null, jump, ": ", item.message);
}

/**
 * Builds the summary.
 * @param {import("./store.js").SettingsStore} store
 * @returns {{el: HTMLElement, sync: () => void, focus: () => void}}
 */
export function buildSummary(store) {
  const list = h("ul", { class: "summary-list" });
  const title = h("p", { class: "text-strong", id: "settings-error-title" }, "Settings were not saved");
  const el = h(
    "div",
    { class: "notice settings-summary", "data-kind": "error", role: "group", "aria-labelledby": title.id, tabindex: "-1", hidden: true, "data-testid": "settings-error" },
    icon("x-circle", { size: 18 }),
    h("div", { class: "notice-body stack stack-sm" }, title, list),
  );
  let last = "";
  return {
    el,
    focus: () => el.focus(),
    sync() {
      const failed = store.attempted || store.server.general.length > 0;
      const found = failed ? store.visibleErrors() : [];
      const items = found.map((item) => ({ ...item, label: stripBidi(labelFor(item.id, store)) }));
      const general = failed ? store.server.general : [];
      const key = JSON.stringify([items, general]);
      el.hidden = items.length + general.length === 0;
      if (key === last) {
        return;
      }
      last = key;
      list.replaceChildren(...items.map((item) => itemNode(item, store)), ...general.map((message) => h("li", null, message)));
    },
  };
}
