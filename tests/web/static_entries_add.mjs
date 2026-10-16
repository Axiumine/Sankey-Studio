// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
// Node scenarios of test_static_entries_add.py: the pure parts of the Entries card additions.
// argv[2] is the js/ directory of the shipped files; the result is printed as JSON.
const dir = process.argv[2];
globalThis.document = { getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} };
const load = (file) => import(`${dir}/editor/entries/${file}`);
const form = await load("add-form.js");
const stale = await load("stale-overrides.js");
const list = await load("overlay-list.js");
const bulk = await load("bulk.js");
const out = {};

const base = { source: " Budget ", target: "Gifts", value: "50", category: "" };
const check = (patch, known = []) => form.checkEntry({ ...base, ...patch }, known);
const verdict = (result) => (result.ok ? result.entry : { field: result.field, message: result.message });

out.entry = {
  plain: verdict(check({})),
  category: verdict(check({ category: "  fun  " })),
  spelling: verdict(check({ category: "housing" }, ["Housing"])),
  reserved: verdict(check({ category: "Other" })),
  longCategory: verdict(check({ category: "x".repeat(101) })),
  noSource: verdict(check({ source: "  ", target: "" })),
  noTarget: verdict(check({ target: " " })),
  same: verdict(check({ source: "A", target: " A" })),
  max: check({ source: "s".repeat(200) }).ok,
  over: verdict(check({ source: "s".repeat(201) })),
  control: verdict(check({ target: "a\nb" })),
  lone: verdict(check({ target: "a\ud800" })),
};
out.values = Object.fromEntries(
  ["", "0", "-1", "abc", "1,5", "1e999", "NaN", "12.5", " 1 200 ", "0.001", "+3", "1e3"].map((text) => [text, verdict(check({ value: text }))]),
);
out.values.missing = verdict(form.checkEntry({ source: "a", target: "b" }));

const nodes = form.nodeNameSet({ nodes: [{ name: "Budget" }, { name: "Rent" }] });
out.hints = {
  names: [...nodes],
  empty: form.nodeNameSet(null).size,
  none: form.nodeNameSet({}).size,
  known: form.newNodeHint("Budget", nodes),
  unknown: form.newNodeHint("  Gifts ", nodes),
  blank: form.newNodeHint("   ", nodes),
  nothingKnown: form.newNodeHint("Gifts", new Set()),
  bidi: form.newNodeHint("A‮B", nodes),
  caseMatters: form.newNodeHint("budget", nodes),
};
out.limits = [form.NODE_NAME_MAX, form.SUGGESTION_MAX];

out.unmatched = {
  none: stale.unmatchedCount([]),
  notArray: stale.unmatchedCount("2 entry_categories matched no entry"),
  one: stale.unmatchedCount(["1 entry_categories matched no entry"]),
  sum: stale.unmatchedCount(["2 entry_categories matched no entry", "other", 7, "3 entry_categories matched no entry"]),
  loose: stale.unmatchedCount(["x 2 entry_categories matched no entry", "2 entry_categories matched no entry."]),
  undefinedList: stale.unmatchedCount(undefined),
  textOne: stale.unmatchedText(1),
  textMany: stale.unmatchedText(3),
};

const link = { source: "A", target: "B", value: 12, category: "Fun" };
const bare = { source: "C", target: "D", value: 5, category: null };
const edit = { source: "A", target: "B", category: null };
const state = (extra = {}) => ({
  draft: { source: { type: "text" }, transform: { entry_categories: [edit, { ...edit, category: "X" }], extra_links: [link, bare] }, style: { node_order: ["a", "b", "c"] }, ...extra },
});
const items = list.overlayItems(state());
out.items = { texts: items.map((item) => item.text), kinds: items.map((item) => item.kind), count: list.overlayCount(state()) };
out.empty = { items: list.overlayItems({ draft: { transform: {}, style: {} } }).length, count: list.overlayCount({}), one: list.overlayItems({ draft: { style: { node_order: ["a"] } } })[0].text };
out.many = list.overlayItems({ draft: { transform: { entry_categories: Array.from({ length: 300 }, (_, i) => ({ source: `s${i}`, target: "t", category: "c" })) } } }).length;
out.listedMax = list.LISTED_MAX;

const draft = state().draft;
const removed = (item) => list.withoutItem(draft, item);
const noEdit = removed(items[0]);
out.remove = {
  category: noEdit.transform.entry_categories,
  untouched: noEdit.transform.extra_links === draft.transform.extra_links && noEdit.style === draft.style,
  link: removed(items[2]).transform.extra_links,
  order: removed(items[4]).style.node_order,
  original: draft.transform.entry_categories.length,
  noSection: list.withoutItem({ source: 1 }, { kind: "draft.transform.extra_links", value: link }),
};
out.hostile = list.overlayItems({ draft: { transform: { extra_links: [{ source: "<b>x</b>‮", target: "y", value: 1, category: null }] } } })[0].text;

const calls = [];
const panel = (over = {}) => ({
  toolbar: { values: () => ({ q: "rent" }) },
  state: { phase: "loading", rows: [], total: 0 },
  bulk: { button: { disabled: false }, category: { value: "Home", focus: () => calls.push("focus") }, setBusy: (b) => calls.push(`busy:${b}`) },
  committer: { addRule: async (q, t) => { calls.push(`rule:${q}:${t}`); return { ok: true, rule: { match: "either", pattern: "*rent*", category: "Home" } }; }, undoRule: (r) => calls.push(`undo:${r.category}`) },
  names: { add: (n) => calls.push(`name:${n}`) },
  toast: { show: (text, opts) => { calls.push(`toast:${text}`); calls.push(opts.action.label); opts.action.onClick(); } },
  showError: (m) => calls.push(`error:${m}`),
  clearError: () => calls.push("clear"),
  ...over,
});
const run = async (p) => { calls.length = 0; await bulk.applyBulk(p, "Home"); return [...calls]; };
const noMatch = { phase: "ready", rows: [{ source: "a", target: "b" }], total: 1 };
out.bulk = {
  ok: await run(panel()),
  busy: await run(panel({ bulk: { button: { disabled: true } } })),
  problem: await run(panel({ state: noMatch })),
  failed: await run(panel({ committer: { addRule: async () => ({ ok: false, message: "nope" }) } })),
  noToast: await run(panel({ toast: undefined })),
};
process.stdout.write(JSON.stringify(out));
