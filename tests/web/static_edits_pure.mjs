// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
out.classify = [
  classify(null), classify({ type: "manual", links: [] }), classify({ type: "text", origin: "inline" }),
  classify({ type: "text", origin: "file", path: null }), classify({ type: "text", origin: "file", path: "a.csv" }),
  classify({ type: "mongo", connection: "m", collection: "" }), classify({ type: "mongo", connection: "m", collection: "c" }),
  classify({ type: "mongo", connection: "", collection: "c" }),
];
const d = { source: { type: "text" }, transform: { entry_categories: [{ source: "a", target: "b", category: "X" }, { source: "c", target: "d", category: null }] }, style: {} };
const edit = { source: "a", target: "b", category: "Y" };
const dropped = local.applyOverride(d, "drop", edit);
out.override = {
  drop: dropped.transform.entry_categories,
  dropMissing: local.applyOverride(d, "drop", { source: "z", target: "z" }) === d,
  set: local.applyOverride(d, "set", edit).transform.entry_categories,
  setNew: local.applyOverride(d, "set", { source: "n", target: "m", category: null }).transform.entry_categories.at(-1),
  none: local.applyOverride(d, null, edit) === d,
  noList: local.applyOverride({ source: {} }, "drop", edit).transform === undefined,
};
const added = local.overlayAdd(inline(), { source: "x", target: "y", value: 4 });
out.add = {
  links: added.transform.extra_links,
  more: local.overlayAdd(added, { source: "p", target: "q", value: 1, category: "K" }).transform.extra_links.length,
  problem: local.addProblem(added),
  atCap: local.addProblem({ transform: { extra_links: new Array(local.EXTRA_LINKS_MAX).fill({}) } }),
};
const withAll = { source: { s: 1 }, transform: { entry_categories: [1], extra_links: [2], keep: 3 }, style: { node_order: ["a"], other: 4 } };
const snap = local.snapshotFor(withAll);
const changed = { source: { s: 2 }, transform: { keep: 3, entry_categories: [9] }, style: { other: 4 } };
const restored = local.restore(changed, snap);
const bare = local.restore({ source: 1, transform: { x: 1 }, style: {} }, local.snapshotFor({ source: 0 }));
out.snapshot = {
  snap,
  restored,
  bare,
  order: local.withOrder({ style: { a: 1 } }, ["z"]).style,
  pref: local.withPref({ source: { a: 1 } }, { mode: "graph", target: "k" }).source,
};
const pinned = local.withPins({ style: { node_colors: { b: "#999999" }, keep: 1 } }, { node_colors: { a: "#111111", b: "#222222" }, category_colors: { R: "#333333" } });
const justCats = local.withPins({ style: { node_colors: { b: 1 } } }, { node_colors: {}, category_colors: { R: "#333333" } });
const noStyle = local.withPins({ source: 1 }, { node_colors: { a: "#111111" } });
const same = { style: {} };
const colourSnap = local.snapshotFor({ source: 1, style: { node_colors: { a: 1 }, category_colors: { R: 2 } } });
out.pins = {
  pinned: pinned.style,
  justCats: justCats.style,
  noStyle: noStyle.style,
  none: [local.withPins(same, null) === same, local.withPins(same, undefined) === same, local.withPins(same, {}).style],
  snap: [colourSnap.node_colors, colourSnap.category_colors],
  restored: local.restore({ source: 2, style: { node_colors: { z: 1 }, category_colors: { Q: 1 } } }, colourSnap).style,
  cleared: local.restore({ source: 2, style: { node_colors: { z: 1 } } }, local.snapshotFor({ source: 1 })).style,
};
const c = choices();
let started = 0;
const slow = () => { started += 1; return new Promise((resolve) => setTimeout(() => resolve("accept"), 5)); };
const first = c.share("k", slow);
const second = c.share("k", slow);
const results = [await first, await second];
const third = await c.share("k", slow);
c.remember("k");
const before = c.remembered("k");
c.forget();
out.choices = { same: first === second, started, results, third, before, after: c.remembered("k"), other: c.remembered("z") };
out.problem = [
  remote.problemText({ details: ["body.edit.value: Value error, must be greater than 0"] }),
  remote.problemText({ friendly: "Nope" }), remote.problemText({ message: "Raw" }), remote.problemText(null),
];
const bundle = (rows, total = rows.length) => ({ entries: rows.map(([source, target, category]) => ({ source, target, category })), entries_total: total });
const rows = [["a", "b", null], ["b", "c", null], ["c", "d", null]];
out.hint = {
  fresh: hint.uncategorisedCount(bundle(rows), { source: "a", target: "b", category: "K" }),
  clear: hint.uncategorisedCount(bundle(rows), { source: "a", target: "b", category: null }),
  has: hint.uncategorisedCount(bundle([["a", "b", "K"], ["b", "c", null]]), { source: "b", target: "c", category: "J" }),
  partial: hint.uncategorisedCount(bundle(rows, 5), { source: "a", target: "b", category: "K" }),
  none: hint.uncategorisedCount(null, { source: "a", target: "b", category: "K" }),
  empty: hint.uncategorisedCount(bundle([]), { source: "a", target: "b", category: "K" }),
};
const shown = [];
out.offer = [hint.offerHint({ info: (...args) => shown.push(args) }, 0), hint.offerHint({ info: (...args) => shown.push(args) }, 1), hint.offerHint({ info: (...args) => shown.push(args) }, 3)];
out.offerText = shown.map(([text, options]) => [text, options.action.label]);
const store = createStore();
const before2 = store.get().draft.source;
touch.touchSource(store);
out.touch = { sameContent: JSON.stringify(store.get().draft.source) === JSON.stringify(before2), newObject: store.get().draft.source !== before2, dirty: store.get().status.dirty };
touch.announceWritten("a/b.csv");
touch.announceWritten(undefined);
out.events = events.splice(0);
