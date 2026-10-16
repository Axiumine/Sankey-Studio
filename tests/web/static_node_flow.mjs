// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
// Scenarios of test_static_node_flow.py: F2 (click a node to add a flow), the parts that need no DOM.
// argv[2] is the js/ directory of the shipped files; the result is printed as JSON.
const dir = process.argv[2];
globalThis.window = { addEventListener() {}, removeEventListener() {} };
globalThis.document = { getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} };
const flow = await import(`${dir}/editor/chart/node-flow.js`);
const form = await import(`${dir}/editor/entries/add-form.js`);
const actions = await import(`${dir}/editor/chart/node-actions.js`);
const { toast } = await import(`${dir}/core/toast.js`);
const out = {};

const heard = [];
toast.info = (message) => heard.push(message);
const storeOf = (source) => ({ get: () => ({ draft: { source } }) });

out.prefill = {
  sink: flow.prefillFor({ name: "Rent", node_in: 1200, node_out: 0 }),
  source: flow.prefillFor({ name: "Salary", node_in: 0, node_out: 3000 }),
  middle: flow.prefillFor({ name: "Budget", node_in: 3000, node_out: 2800 }),
  noNumbers: flow.prefillFor({ name: "X" }),
  nullOut: flow.prefillFor({ name: "Y", node_out: null }),
  hostile: flow.prefillFor({ name: "<img src=x onerror=alert(1)>", node_out: 0 }),
};

const blocked = (message) => flow.openNodeFlow({ edits: { store: storeOf(message) }, node: { name: "Rent", node_out: 0 } });
out.nothing = {
  noEdits: flow.openNodeFlow({ edits: null, node: { name: "A" } }),
  noStore: flow.openNodeFlow({ edits: {}, node: { name: "A" } }),
  noNode: flow.openNodeFlow({ edits: { store: storeOf(null) }, node: null }),
  noName: flow.openNodeFlow({ edits: { store: storeOf(null) }, node: { name: 7 } }),
  none: flow.openNodeFlow({}),
};
out.blocked = {
  file: blocked({ type: "text", origin: "file", path: null }),
  mongo: blocked({ type: "mongo", connection: "main", collection: "" }),
  toasts: [...heard],
};

heard.length = 0;
{ // the default click of the chart: no engine or no row does nothing; a blocked source says so
  const bundle = { nodes: [{ name: "Rent", layer: 1, node_in: 1, node_out: 0 }], figure: { data: [{ orientation: "h", node: { label: ["Rent"] }, link: { source: [] } }] } };
  const info = { index: 0, hasIn: true, hasOut: false, clientX: 1, clientY: 2 };
  const edits = { reorder: async () => ({}) };
  const bare = actions.eventsFor(bundle, { edits })();
  bare.click(info);
  actions.onNodeClick(bundle, { index: 5, node: null }, { edits });
  actions.onNodeClick(bundle, undefined);
  const stuck = { ...edits, store: storeOf({ type: "text", origin: "file", path: "" }) };
  actions.eventsFor(bundle, { edits: stuck })().click(info);
  actions.eventsFor(bundle, { edits: stuck })().click({ ...info, index: 9 });
  out.click = [...heard];
}

out.titles = {
  plain: form.titleFor({}),
  none: form.titleFor(undefined),
  from: form.titleFor({ node: "Budget", direction: "from" }),
  to: form.titleFor({ node: "Rent", direction: "to" }),
  unknown: form.titleFor({ node: "Rent" }),
  bidi: form.titleFor({ node: "a‮b", direction: "to" }),
  exact: form.titleFor({ node: "n".repeat(60), direction: "from" }).length,
  long: form.titleFor({ node: "n".repeat(61), direction: "from" }),
};
process.stdout.write(JSON.stringify(out));
