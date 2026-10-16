// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * One MongoDB connection of the settings page: name, default database, connection string, a
 * "Test connection" button with its result (and latency) and a "Delete" button.
 *
 * Secrets: the connection string input is `type=password` with the placeholder "(unchanged)" for a
 * stored connection. What the user types lives in `row.uri` (memory) and the input's value
 * property only; the stored string is never available here, just the masked copy the API sends
 * (`uri_masked`), which is shown as text. Rows are rebuilt after every save, which empties the
 * input.
 */

import { canWrite } from "../core/boot.js";
import { h, setBusy } from "../core/dom.js";
import { formatNumber } from "../core/format.js";
import { icon } from "../core/icons.js";
import { passwordInput, textInput } from "../core/form.js";
import { stripBidi } from "../core/text.js";
import { toast } from "../core/toast.js";
import { probeMessage } from "./errors.js";
import { probeConnection, slowProbeText } from "./probes.js";
import { boundField, resultLine } from "./ui.js";

const URI_PLACEHOLDER = "mongodb://user:password@host:27017";

function latencyNode(ms) {
  return h("strong", { class: "nums", "data-testid": "connection-latency" }, `${formatNumber(ms, { maximumFractionDigits: 1 })} ms`);
}

function uriHint(row) {
  if (!canWrite()) {
    const shown = row.has_secret && row.uri_masked ? `Stored: ${row.uri_masked}. ` : "";
    return `${shown}Connection strings cannot be changed because this server is read-only.`;
  }
  if (row.has_secret) {
    const shown = row.uri_masked ? `Stored: ${row.uri_masked}. ` : "";
    return `${shown}Leave this empty to keep it, or paste a new connection string to replace it.`;
  }
  return "One server: mongodb://user:password@host:27017/. Replica set: list the members and name the set, mongodb://user:password@h1:27017,h2:27017,h3:27017/?replicaSet=rs0. Atlas: mongodb+srv://user:password@cluster.example.com/. It is saved in this app's settings file and never shown again.";
}

function nameHint(row, name) {
  if (row.previous_name && name !== row.previous_name) {
    return `Renaming keeps the stored connection string. Graphs that use the name "${stripBidi(row.previous_name)}" must be pointed at the new name.`;
  }
  return "Letters, digits, dots, dashes and underscores. Graphs refer to the connection by this name.";
}

function fieldsOf(store, row, result) {
  const edit = (apply, part) => () => {
    apply();
    result.clear();
    store.edit(`row.${row.key}.${part}`);
  };
  const name = textInput({ value: row.name, maxlength: 64, "data-testid": "connection-name" });
  const uri = passwordInput({ value: row.uri, placeholder: row.has_secret ? "(unchanged)" : URI_PLACEHOLDER, "data-testid": "connection-uri" });
  const db = textInput({ value: row.default_database, maxlength: 64, placeholder: "(none)", "data-testid": "connection-default-db" });
  name.addEventListener("input", edit(() => { row.name = name.value; }, "name"));
  uri.addEventListener("input", edit(() => { row.uri = uri.value; }, "uri"));
  db.addEventListener("input", edit(() => { row.default_database = db.value; }, "database"));
  return {
    name: boundField(store, `row.${row.key}.name`, { label: "Name", control: name, hint: nameHint(row, row.name) }),
    uri: boundField(store, `row.${row.key}.uri`, { label: "Connection string", control: uri, hint: uriHint(row) }),
    db: boundField(store, `row.${row.key}.database`, { label: "Default database", control: db, hint: "Used by graphs that do not name a database. Optional." }),
  };
}

function runTest(store, row, parts) {
  const { button, result } = parts;
  return async () => {
    setBusy(button, true);
    const ticket = result.begin();
    result.busy("Testing the connection...", slowProbeText(store, "the connection", true));
    const label = stripBidi(row.name.trim());
    try {
      const outcome = await probeConnection(store, row, result.signal());
      if (!result.isCurrent(ticket)) {
        return; // the row was edited meanwhile: this answer is about other values
      }
      if (outcome.invalid) {
        result.clear();
      } else if (outcome.latency_ms === undefined) {
        result.show("ok", "Reachable with the values above. Save to keep them.");
        toast.success(`Connection "${label}" is reachable.`, { near: result.el });
      } else {
        result.show("ok", "Connected in ", latencyNode(outcome.latency_ms));
        toast.success(`Connected to "${label}" in ${formatNumber(outcome.latency_ms, { maximumFractionDigits: 1 })} ms.`, { near: result.el });
      }
    } catch (error) {
      if (!result.isCurrent(ticket)) {
        return;
      }
      const message = probeMessage(error);
      result.show("error", message);
      toast.error(`Connection "${label}": ${message}`, { near: result.el });
    } finally {
      setBusy(button, false);
    }
  };
}

function actionButtons() {
  const test = h("button", { type: "button", class: "btn btn-sm", "data-testid": "connection-test" }, icon("refresh"), "Test connection");
  const remove = h("button", { type: "button", class: "btn btn-sm", "data-testid": "connection-delete" }, icon("trash"), "Delete");
  return { test, remove, el: h("div", { class: "connection-actions" }, test, remove) };
}

/**
 * Builds the row for `row` of the draft.
 * @param {import("./store.js").SettingsStore} store
 * @param {object} row  an entry of `store.draft.connections`
 * @param {{remove: (key: string) => void}} actions
 * @returns {{el: HTMLElement, sync: () => void, dispose: () => void}}
 */
export function buildRow(store, row, actions) {
  const result = resultLine({ testid: "connection-status" });
  const fields = fieldsOf(store, row, result);
  const buttons = actionButtons();
  buttons.remove.addEventListener("click", () => actions.remove(row.key));
  buttons.test.addEventListener("click", runTest(store, row, { button: buttons.test, result }));
  const title = h("h3", { class: "connection-title", id: `${row.key}-title` });
  const badge = h("span", { class: "badge badge-accent", hidden: true }, "Holds your graphs");
  const card = h(
    "div",
    { class: "connection", role: "group", "aria-labelledby": title.id, "data-testid": "settings-connection" },
    h("div", { class: "connection-head" }, h("div", { class: "cluster connection-heading" }, icon("database", { size: 18 }), title, badge), buttons.el),
    h("div", { class: "connection-fields" }, fields.name.el, fields.db.el, h("div", { class: "span-all" }, fields.uri.el)),
    result.el,
  );
  return {
    el: h("li", { class: "connection-item" }, card),
    sync() {
      const name = row.name.trim();
      title.textContent = name || "New connection";
      card.setAttribute("data-connection-name", stripBidi(name));
      badge.hidden = store.draft.storage_backend !== "mongo" || store.draft.storage_connection !== row.key;
      buttons.test.setAttribute("aria-label", stripBidi(`Test connection ${name}`.trim()));
      buttons.remove.setAttribute("aria-label", stripBidi(`Delete connection ${name}`.trim()));
      fields.name.field.setHint(nameHint(row, name));
      for (const item of [fields.name, fields.uri, fields.db]) {
        item.sync();
      }
    },
    dispose: () => result.clear(), // the row is gone: a test still running for it is aborted and forgotten
  };
}
