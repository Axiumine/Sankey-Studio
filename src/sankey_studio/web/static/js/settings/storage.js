// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Storage section: where graphs are kept (files on this computer, or a MongoDB connection), the
 * "copy existing graphs" box, the "Test storage" probe and the report of the last copy.
 *
 * The connection picker lists the connection rows of the draft (by row, so renaming a connection
 * does not lose the choice). The Mongo-only fields are hidden while the backend is "file".
 */

import { announce } from "../core/a11y.js";
import { canWrite } from "../core/boot.js";
import { h, setBusy } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { selectInput, textInput } from "../core/form.js";
import { icon } from "../core/icons.js";
import { toast } from "../core/toast.js";
import { stripBidi } from "../core/text.js";
import { BACKENDS } from "./constants.js";
import { probeStorage, slowProbeText } from "./probes.js";
import { probeMessage } from "./errors.js";
import { copyReportNotice } from "./report.js";
import { boundField, resultLine, section } from "./ui.js";

const BACKEND_HINTS = {
  file: "Graphs are saved as files in the app's data folder on this computer.",
  mongo: "Graphs are kept in a MongoDB database, so several computers can share them.",
};

function connectionOptions(draft) {
  const named = draft.connections.filter((row) => row.name.trim() !== "");
  const first = { value: "", label: named.length ? "Choose a connection" : "No connections yet" };
  return [first, ...named.map((row) => ({ value: row.key, label: stripBidi(row.name.trim()) }))];
}

function fillOptions(select, options, value) {
  select.replaceChildren(
    ...options.map((item) => h("option", { value: item.value }, item.label)),
  );
  select.value = options.some((item) => item.value === value) ? value : "";
}

/** The folder the "file" backend keeps the graphs in (read-only: set when the server started). */
function folderLine(store) {
  const path = h("code", { class: "break", "data-testid": "settings-storage-folder" }, store.settings.bootstrap.graphs_dir);
  return h("p", { class: "hint" }, "Graphs folder: ", path);
}

function backendField(store) {
  const control = selectInput({
    options: BACKENDS,
    value: store.draft.storage_backend,
    "data-testid": "settings-storage-backend",
    on: {
      change: () => {
        store.draft.storage_backend = control.value;
        store.edit("storage.backend");
      },
    },
  });
  return boundField(store, "storage.backend", { label: "Store graphs in", control });
}

function mongoFields(store) {
  const connection = selectInput({
    options: [{ value: "", label: "No connections yet" }],
    value: "",
    "data-testid": "settings-storage-connection",
    on: {
      change: () => {
        store.draft.storage_connection = connection.value || null;
        store.edit("storage.connection");
      },
    },
  });
  const database = textInput({
    value: store.draft.storage_database,
    maxlength: 64,
    "data-testid": "settings-storage-database",
    on: {
      input: () => {
        store.draft.storage_database = database.value;
        store.edit("storage.database");
      },
    },
  });
  return {
    connection: boundField(store, "storage.connection", { label: "Connection", control: connection }),
    database: boundField(store, "storage.database", {
      label: "Database",
      control: database,
      hint: "The graphs go into the MongoDB collection sankey_studio_graphs of this database, and the library's own collections (groups of graphs) into sankey_studio_collections.",
    }),
  };
}

function migrateBox(store) {
  const input = h("input", {
    type: "checkbox",
    checked: store.draft.migrate && canWrite(),
    "data-testid": "settings-migrate",
    "aria-describedby": "settings-migrate-hint",
    on: {
      change: () => {
        store.draft.migrate = input.checked;
        store.notify();
      },
    },
  });
  const text = h("span", null, "Copy my existing graphs to the new location");
  const hint = h("p", { class: "hint", id: "settings-migrate-hint" });
  return { input, text, hint, el: h("div", { class: "stack stack-sm" }, h("label", { class: "check" }, input, text), hint) };
}

function migrateHint(store) {
  if (!canWrite()) {
    return "Not available: this server is read-only, so nothing can be copied.";
  }
  if (!store.storageChanged()) {
    return "Used only when you switch to a different storage location. Nothing is copied now.";
  }
  if (store.draft.migrate) {
    return "Copying never deletes anything: the originals stay where they are, and graphs that are already there are skipped.";
  }
  return "Without copying, the graphs you have now stay in the old location and will not appear here.";
}

function testButton(store, line) {
  const button = h("button", { type: "button", class: "btn", "data-testid": "settings-test-storage" }, icon("refresh"), "Test storage");
  button.addEventListener("click", async () => {
    setBusy(button, true);
    const ticket = line.begin();
    const revision = store.probeRevision;
    const stale = () => store.probeRevision !== revision || !line.isCurrent(ticket);
    line.revision = revision;
    const mongo = store.draft.storage_backend === "mongo";
    line.busy("Testing the storage location...", slowProbeText(store, "the storage location", mongo));
    try {
      const outcome = await probeStorage(store, line.signal());
      if (stale()) {
        return; // the form changed meanwhile: this answer is about other values
      }
      if (outcome.ok) {
        line.show("ok", "Storage is reachable and writable.");
        toast.success("Storage is reachable and writable.", { near: line.el });
      } else {
        line.clear();
      }
    } catch (error) {
      if (stale()) {
        return;
      }
      const message = probeMessage(error);
      line.show("error", message);
      toast.error(message, { near: line.el });
    } finally {
      setBusy(button, false);
    }
  });
  return button;
}

function copyLabel(count) {
  if (count === null) {
    return "Copy my existing graphs to the new location";
  }
  if (count === 0) {
    return "Copy my existing graphs to the new location (there are none yet)";
  }
  return `Copy my ${formatCount(count, "existing graph")} to the new location`;
}

function optionsSync(store, select) {
  let last = null;
  return () => {
    const options = connectionOptions(store.draft);
    const key = JSON.stringify([options, store.draft.storage_connection]);
    if (key !== last) {
      last = key;
      fillOptions(select, options, store.draft.storage_connection ?? "");
    }
  };
}

function reportSync(store, host, returnFocusTo) {
  let shown = null;
  // the dismiss button is what had focus, and it leaves with the report: focus goes to the
  // storage test, the control that comes right before the report on the page
  const dismiss = () => {
    store.setReport(null);
    returnFocusTo.focus();
  };
  return () => {
    if (shown === store.report) {
      return;
    }
    shown = store.report;
    host.replaceChildren(...(shown ? [copyReportNotice(shown, dismiss)] : []));
    if (shown) {
      announce(`${formatCount(shown.copied, "graph")} copied.`);
      host.firstElementChild.scrollIntoView({ block: "nearest" });
    }
  };
}

function syncValues(store, parts) {
  const { draft } = store;
  parts.backend.control.value = draft.storage_backend;
  parts.hint.textContent = BACKEND_HINTS[draft.storage_backend];
  parts.folder.hidden = draft.storage_backend !== "file";
  parts.mongoBlock.hidden = draft.storage_backend !== "mongo";
  if (parts.mongo.database.control.value !== draft.storage_database) {
    parts.mongo.database.control.value = draft.storage_database;
  }
  const named = draft.connections.some((row) => row.name.trim() !== "");
  parts.mongo.connection.field.setHint(named ? "" : "Add a MongoDB connection under MongoDB connections first.");
  parts.migrate.input.checked = draft.migrate && canWrite(); // a read-only server copies nothing
  parts.migrate.text.textContent = copyLabel(store.graphCount);
  parts.migrate.hint.textContent = migrateHint(store);
  for (const item of [parts.backend, parts.mongo.connection, parts.mongo.database]) {
    item.sync();
  }
}

/**
 * Builds the section.
 * @param {import("./store.js").SettingsStore} store
 * @returns {{el: HTMLElement, sync: () => void}}
 */
export function buildStorage(store) {
  const mongo = mongoFields(store);
  const line = resultLine({ testid: "settings-storage-status" });
  const test = testButton(store, line);
  const parts = {
    backend: backendField(store),
    mongo,
    migrate: migrateBox(store),
    hint: h("p", { class: "hint" }),
    folder: folderLine(store),
    mongoBlock: h("div", { class: "stack settings-mongo-block" }, mongo.connection.el, mongo.database.el),
    reportHost: h("div", { class: "settings-report-host" }),
  };
  const el = section({
    id: "settings-storage",
    title: "Storage",
    text: "Choose where your saved graphs live. Your data files and connection strings are never moved.",
    body: [
      parts.backend.el,
      parts.hint,
      parts.folder,
      parts.mongoBlock,
      parts.migrate.el,
      h("div", { class: "cluster" }, test, line.el),
      parts.reportHost,
    ],
  });
  const syncOptions = optionsSync(store, mongo.connection.control);
  const syncReport = reportSync(store, parts.reportHost, test);
  return {
    el,
    sync() {
      if (!line.el.hidden && line.revision !== store.probeRevision) {
        line.clear(); // the form changed after the test: its result no longer applies
      }
      syncValues(store, parts);
      syncOptions();
      syncReport();
    },
  };
}
