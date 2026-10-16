// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Tab "MongoDB": read flows from a collection of a configured connection (read-only).
 * (`{type: "mongo", connection, database?, collection, mode, filter, pipeline, source_field,
 * target_field, value_field, category_field, limit, max_time_ms}`.)
 *
 * Connections come from the settings; none configured gives a friendly pointer to Settings. The
 * sample viewer shows a few documents as a collapsed tree and offers the server's field
 * suggestions. Find mode takes a JSON filter, aggregate mode a JSON pipeline, both checked in the
 * browser (mongo-json.js) and again by the server, whose messages appear under the box.
 * Test ids: mongo-sample, mongo-suggest, mongo-no-connections (the pickers and editors have their
 * own, see their files).
 */

import { announce } from "../../core/a11y.js";
import { h } from "../../core/dom.js";
import { checkbox, field, numberInput, textInput } from "../../core/form.js";
import { icon } from "../../core/icons.js";
import { emptyState } from "../../core/states.js";
import { bindNumber, bindText, createSegmented } from "../meta/bind.js";
import { applyDerived } from "../meta/dirty.js";
import { jsonTree } from "./json-tree.js";
import { connectionToPreselect } from "./model.js";
import { createJsonEditor } from "./mongo-json.js";
import { createPickers, effectiveDatabase } from "./mongo-pickers.js";

const SRC = ["draft", "source"];

function fieldInput(store, fields, spec) {
  const f = field({ label: spec.label, control: textInput({ placeholder: spec.placeholder, maxlength: 200 }), hint: spec.hint });
  fields[spec.key] = f;
  return { f, off: bindText(store, f.control, [...SRC, spec.key], { removeEmpty: true }) };
}

function limitFields(store, fields) {
  const limit = field({ label: "Read at most (documents)", control: numberInput({ min: 1, max: 1000000, placeholder: "10000" }), hint: "1 to 1,000,000. The default is 10,000." });
  const time = field({ label: "Stop after (milliseconds, optional)", control: numberInput({ min: 100, max: 300000, placeholder: "No limit" }), hint: "100 to 300,000." });
  Object.assign(fields, { limit, max_time_ms: time });
  return {
    els: [limit.el, time.el],
    offs: [bindNumber(store, limit, [...SRC, "limit"], { min: 1, max: 1000000, int: true }), bindNumber(store, time, [...SRC, "max_time_ms"], { min: 100, max: 300000, int: true })],
  };
}

function countingSwitch(store, valueField) {
  const label = checkbox({ label: "Count documents instead of adding up a value field" });
  const input = label.querySelector("input");
  const path = [...SRC, "value_field"];
  let kept = null; // the field that was set before counting was switched on, brought back when it is switched off
  input.addEventListener("change", () => {
    const current = store.get().draft.source.value_field;
    if (input.checked) {
      kept = typeof current === "string" ? current : null;
      store.patch(path, null);
    } else if (kept) {
      store.patch(path, kept);
    } else {
      store.remove(path);
    }
  });
  const off = store.subscribe((value) => {
    input.checked = value === null;
    valueField.control.disabled = value === null;
  }, { select: (state) => state.draft.source.value_field, immediate: true });
  return { label, off };
}

function buildSample(store, data, connections, fields) {
  const body = h("div", { class: "ed-sample-docs", "data-testid": "mongo-sample", tabindex: "-1", role: "region", "aria-label": "Sample documents", hidden: true });
  const suggest = h("button", { type: "button", class: "btn btn-sm btn-primary", "data-testid": "mongo-suggest", hidden: true }, icon("check", { size: 14 }), "Use the suggested fields");
  const status = h("p", { class: "hint", role: "status" });
  const load = h("button", { type: "button", class: "btn btn-sm" }, icon("table", { size: 14 }), "Show sample documents");
  let suggested = null;
  const apply = () => {
    store.batch(() => {
      for (const [key, name] of [["source_field", suggested.source], ["target_field", suggested.target], ["value_field", suggested.value], ["category_field", suggested.category]]) {
        if (name) {
          store.patch([...SRC, key], name);
        }
      }
    });
    announce("Fields filled in from the sample");
  };
  suggest.addEventListener("click", apply);
  load.addEventListener("click", async () => {
    const source = store.get().draft.source;
    const database = effectiveDatabase(source, connections);
    if (!source.connection || !source.collection) {
      status.textContent = "Choose a connection and a collection first.";
      return;
    }
    status.textContent = "Loading sample documents";
    try {
      const answer = await data.sample(source.connection, database, source.collection);
      body.replaceChildren(...(answer.documents.length > 0 ? answer.documents.map((doc, i) => jsonTree(doc, { label: `Document ${i + 1}` })) : [h("p", { class: "hint" }, "The collection has no documents.")]));
      body.hidden = false;
      suggested = answer.suggested ?? null;
      suggest.hidden = !suggested || !Object.values(suggested).some(Boolean);
      status.textContent = suggest.hidden ? "" : "Suggested fields found. Check them, then apply.";
    } catch (error) {
      status.textContent = `Could not load a sample: ${error.friendly ?? error.message}`;
    }
  });
  fields.sample = { setError: (message) => { status.textContent = message; } };
  return { el: h("div", { class: "stack stack-sm ed-sample-block" }, h("div", { class: "cluster" }, load, suggest), status, body) };
}

/**
 * The mode switch. Only the active mode's field (`filter` for find, `pipeline` for aggregate) stays
 * in the draft: the other one is parked here, so the server never checks (or rejects) a stale one
 * and it comes back when the person switches back.
 */
function buildMode(store, filter, pipeline) {
  const parked = {};
  const segmented = createSegmented({
    label: "How to read the collection",
    options: [{ value: "find", label: "Find (filter)" }, { value: "aggregate", label: "Aggregate (pipeline)" }],
    onChange: (mode) => store.patch([...SRC, "mode"], mode),
  });
  const swap = (source, own, other) => {
    applyDerived(store, () => {
      if (other in source) {
        parked[other] = source[other];
        store.remove([...SRC, other]);
      }
      if (!(own in source) && own in parked) {
        store.patch([...SRC, own], parked[own]);
        delete parked[own];
      }
    });
  };
  const show = (source) => {
    const aggregate = source.mode === "aggregate";
    segmented.set(aggregate ? "aggregate" : "find");
    filter.field.el.hidden = aggregate;
    pipeline.field.el.hidden = !aggregate;
    if (source.type === "mongo") {
      swap(source, aggregate ? "pipeline" : "filter", aggregate ? "filter" : "pipeline");
    }
  };
  const off = store.subscribe(show, { select: (state) => state.draft.source, immediate: true });
  return { el: h("div", { class: "field" }, h("span", { class: "label" }, "How to read the collection"), segmented.el), off };
}

function emptyConnections(recheck) {
  return emptyState({
    title: "No MongoDB connections yet",
    message: "Add a connection in Settings, then come back here and check again to pick a collection.",
    icon: "database",
    compact: true,
    testid: "mongo-no-connections",
    actions: [
      h("a", { class: "btn btn-primary", href: "/settings" }, "Open Settings"),
      h("button", { type: "button", class: "btn", on: { click: recheck } }, icon("refresh", { size: 14 }), "Check again"),
    ],
  });
}

function unreadableSettings(recheck) {
  return emptyState({
    title: "Settings could not be read",
    message: "MongoDB sources need the list of connections from Settings.",
    icon: "alert",
    compact: true,
    actions: [h("button", { type: "button", class: "btn", on: { click: recheck } }, icon("refresh", { size: 14 }), "Try again")],
  });
}

function buildForm({ store, data, settings, fields }) {
  const connections = settings?.mongo_connections ?? [];
  const pickers = createPickers({ store, data, connections, fields });
  const filter = createJsonEditor({ store, kind: "filter", testid: "mongo-filter" });
  const pipeline = createJsonEditor({ store, kind: "pipeline", testid: "mongo-pipeline" });
  Object.assign(fields, { filter: filter.field, pipeline: pipeline.field });
  const mode = buildMode(store, filter, pipeline);
  const source = fieldInput(store, fields, { key: "source_field", label: "Source field", placeholder: "source", hint: "Dotted path allowed, such as meta.from." });
  const target = fieldInput(store, fields, { key: "target_field", label: "Target field", placeholder: "target" });
  const value = fieldInput(store, fields, { key: "value_field", label: "Value field", placeholder: "value" });
  const category = fieldInput(store, fields, { key: "category_field", label: "Category field (optional)", placeholder: "None", hint: "Entries without it stay uncategorised." });
  const counting = countingSwitch(store, value.f);
  const limits = limitFields(store, fields);
  const sample = buildSample(store, data, connections, fields);
  const offs = [source.off, target.off, value.off, category.off, counting.off, mode.off, filter.dispose, pipeline.dispose, pickers.dispose, ...limits.offs];
  const el = h(
    "div",
    { class: "stack" },
    h("div", { class: "form-grid ed-grid" }, pickers.els),
    sample.el,
    mode.el,
    filter.field.el,
    pipeline.field.el,
    h("div", { class: "form-grid ed-grid" }, source.f.el, target.f.el, value.f.el, category.f.el),
    counting.label,
    h("div", { class: "form-grid ed-grid" }, limits.els),
  );
  return { el, onShow: () => pickers.loadSoon(), dispose: () => offs.forEach((off) => off()) };
}

/** After "Check again": a lone connection is chosen for a draft without one, as a manual pick would (database cleared). */
function preselect(store, connections) {
  const name = connectionToPreselect(store.get().draft.source, connections);
  if (name !== null) {
    store.batch(() => {
      store.patch([...SRC, "connection"], name);
      store.remove([...SRC, "database"]);
    });
  }
}

/**
 * Builds the tab. Without any connection it shows where to add one and a "Check again" button
 * that re-reads the settings (so a connection added in another window shows up without a reload).
 * @param {{store: object, api: object, data: object, settings: object | null, fields: Record<string, object>}} options
 * @returns {{el: HTMLElement, onShow: () => void, dispose: () => void}}
 */
export function createMongoTab(options) {
  const el = h("div", { class: "ed-mongo" });
  let part = null;
  let shown = false;
  const show = (settings) => {
    part?.dispose();
    const connections = settings?.mongo_connections ?? [];
    const usable = connections.length > 0 || Boolean(options.store.get().draft.source.connection);
    part = usable ? buildForm({ ...options, settings }) : { el: settings ? emptyConnections(recheck) : unreadableSettings(recheck), onShow: () => undefined, dispose: () => undefined };
    el.replaceChildren(part.el);
    if (shown) {
      part.onShow();
    }
  };
  async function recheck() {
    try {
      const settings = await options.api.get("/settings", { quiet: true });
      preselect(options.store, settings?.mongo_connections ?? []);
      show(settings);
    } catch {
      show(null);
    }
  }
  show(options.settings);
  return {
    el,
    onShow: () => {
      shown = true;
      part.onShow();
    },
    dispose: () => part.dispose(),
  };
}
