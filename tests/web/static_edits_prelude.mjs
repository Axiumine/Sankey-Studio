// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
// Shared setup of the node scenarios of test_static_edits_*.py (see run_driver).
const dir = process.argv[2];
const events = [];
globalThis.document = {
  dispatchEvent: (event) => events.push([event.type, event.detail]),
  addEventListener() {}, removeEventListener() {}, getElementById: () => null, querySelector: () => null,
};
const load = (file) => import(`${dir}/editor/${file}`);
const local = await load("edits/local.js");
const classify = (await load("edits/classify.js")).classify;
const choices = (await load("edits/choices.js")).createChoices;
const remote = await load("edits/remote.js");
const hint = await load("edits/hint.js");
const touch = await load("edits/touch.js");
const { createEditEngine } = await load("edits/engine.js");
const { createStore, emptyDraft } = await load("store.js");
const out = {};

function fakes(handlers, options = {}) {
  const calls = [];
  const toasts = [];
  const api = {
    async post(path, body, opts) {
      calls.push([path, body, opts]);
      const handler = handlers[path];
      if (!handler) throw new Error(`no handler for ${path}`);
      return handler(body, calls.length);
    },
  };
  const dismissed = [];
  const undos = []; // the onClick of every toast that offered Undo, oldest first
  const rec = (kind) => (text, opts) => {
    toasts.push([kind, text, opts?.action?.label ?? null]);
    if (opts?.action) undos.push(opts.action.onClick);
    return { dismiss: () => dismissed.push(text) };
  };
  const toast = { info: rec("info"), success: rec("success"), warning: rec("warning"), error: rec("error") };
  const store = createStore();
  store.patch("draft", options.draft ?? emptyDraft(), { clean: true });
  const asked = [];
  const ask = async (plan, edit, source) => { asked.push([plan.target_key, edit.op, source.path ?? null]); return options.answer ?? null; };
  const engine = createEditEngine({ store, api, toast, ask });
  return { calls, toasts, store, engine, asked, dismissed, undos };
}

const inline = (extra = {}) => ({
  source: { type: "text", origin: "inline", format: "csv", content: "source,target,value\na,b,1\n", ...extra },
  transform: {}, style: {},
});
const file = (extra = {}) => ({ source: { type: "text", origin: "file", path: "x.csv", ...extra }, transform: {}, style: {} });
const manual = () => ({ source: { type: "manual", links: [{ source: "a", target: "b", value: 1 }] }, transform: {}, style: {} });
const mongo = () => ({ source: { type: "mongo", connection: "main", collection: "t", mode: "find", filter: {} }, transform: {}, style: {} });
const ok = (extra) => ({ where: "graph", written: false, consent: "none", reason: null, notice: null, target: null, target_key: null, changed: 0, source: null, override: null, ...extra });
const entries = () => ({ async post() { return {}; } });
const state = (f) => f.store.get().draft;
