// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
// Scenarios of test_static_node_actions.py: node-actions.js and the pure parts of order-dialog.js.
globalThis.window = { addEventListener() {}, removeEventListener() {} }; // toast.js (reached through node-flow.js) watches the window
globalThis.document = { addEventListener() {}, removeEventListener() {}, getElementById: () => null, querySelector: () => null };
const actions = await import(`${dir}/editor/chart/node-actions.js`);
const dialog = await import(`${dir}/editor/chart/order-dialog.js`);

const names = ["Salary", "Budget", "Rent", "Food", "Groceries"];
const layers = [0, 1, 2, 2, 3];
const sources = [0, 1, 1, 3];
function bundle(extra = {}, trace = {}) {
  return {
    nodes: names.map((name, index) => ({ name, layer: layers[index], node_in: 0, node_out: 0 })),
    figure: { data: [{ orientation: "h", arrangement: "snap", node: { label: names }, link: { source: sources }, ...trace }] },
    ...extra,
  };
}
const recorder = () => {
  const calls = [];
  return { calls, edits: { reorder: async (order) => calls.push(order) } };
};
// positions per pointNumber: Rent (2) is in the last column with Groceries (4); Food (3) is alone in its column
const positions = (ys) => ({ xs: ys.map(() => 0), ys });
// the chart surface as Plotly drew it: one bar per node, `ys` the height of each (read at the press)
const drawnAt = (ys) => surfaceOf(ys.map((y, index) => [index, 0, y, 1, 0]));

{ // a drag becomes an order of the DRAWN columns and goes to edits.reorder
  const { calls, edits } = recorder();
  const listeners = actions.eventsFor(bundle(), { edits })();
  listeners.start(drawnAt([30, 50, 10, 20, 90])); // Rent above Groceries
  listeners.move(positions([0.3, 0.5, 0.9, 0.2, 0.1]));
  out.moved = calls;
}
{ // the order drawn when the press began, or numbers that cannot be trusted, store nothing
  const { calls, edits } = recorder();
  const listeners = actions.eventsFor(bundle(), { edits })();
  const drag = (found) => {
    listeners.start(drawnAt([30, 50, 10, 20, 90]));
    listeners.move(found);
  };
  drag(positions([0.3, 0.5, 0.1, 0.2, 0.9]));
  drag(positions([0.3, 0.5, Number.NaN, 0.2, 0.9]));
  drag(positions([0.3]));
  drag({ xs: [], ys: undefined });
  out.ignored = calls.length;
}
{ // without a stored order Plotly lays the columns out itself: the baseline is the DRAWN order, not the array order
  const { calls, edits } = recorder();
  const listeners = actions.eventsFor(bundle(), { edits })();
  const groceriesFirst = [30, 50, 90, 20, 10]; // drawn: Groceries above Rent; the arrays say Rent first
  listeners.start(drawnAt(groceriesFirst));
  listeners.move(positions([0.3, 0.5, 0.1, 0.2, 0.9])); // dragged back: equals the array order, but it IS a change
  listeners.start(drawnAt(groceriesFirst));
  listeners.move(positions([0.3, 0.5, 0.9, 0.2, 0.1])); // dropped where it was: nothing moved
  out.drawnBaseline = calls;
}
{ // when the drawing cannot be read (or no press was seen) every drag is stored, even one equal to the array order
  const { calls, edits } = recorder();
  const listeners = actions.eventsFor(bundle(), { edits })();
  listeners.start(drawnAt([30]));
  listeners.move(positions([0.3, 0.5, 0.1, 0.2, 0.9]));
  listeners.start(undefined);
  listeners.move(positions([0.3, 0.5, 0.1, 0.2, 0.9]));
  listeners.move(positions([0.3, 0.5, 0.1, 0.2, 0.9]));
  out.blind = calls.length;
}
{ // fixed bars and misaligned bundles cannot move; only aligned bundles can be clicked
  const { edits } = recorder();
  const fixed = actions.eventsFor(bundle({}, { arrangement: "fixed" }), { edits })();
  const short = actions.eventsFor(bundle({ nodes: [{ name: "a", layer: 0 }] }), { edits })();
  const none = actions.eventsFor(null, { edits })();
  const plain = actions.eventsFor(bundle(), { edits })();
  out.capable = [fixed, short, none, plain].map((l) => [typeof l.click, typeof l.move, typeof l.start]);
}
{ // the click hook: nothing by default, the option when given, with the node row
  const { edits } = recorder();
  const heard = [];
  const custom = actions.eventsFor(bundle(), { edits, click: (drawn, info) => heard.push([drawn.nodes.length, info]) })();
  custom.click({ index: 2, hasIn: true, hasOut: false, clientX: 1, clientY: 2 });
  custom.click({ index: 99, hasIn: false, hasOut: false, clientX: null, clientY: null });
  const quiet = actions.eventsFor(bundle(), { edits })();
  out.click = { heard, quiet: quiet.click({ index: 0, hasIn: false, hasOut: true, clientX: 0, clientY: 0 }) ?? null, hook: actions.onNodeClick(bundle(), {}) ?? null };
}
{ // listeners are the same object at every event (the figure on screen decides)
  const { edits } = recorder();
  const ask = actions.eventsFor(bundle(), { edits });
  out.same = ask() === ask();
}
{ // the wait signal: the drawn names in order, or gone
  const surface = { dataset: {} };
  actions.markNodeOrder(surface, bundle());
  const set = surface.dataset.nodeOrder;
  actions.markNodeOrder(surface, null);
  const cleared = "nodeOrder" in surface.dataset;
  actions.markNodeOrder(surface, { nodes: [] });
  out.signal = { set, cleared, empty: "nodeOrder" in surface.dataset };
}
function surfaceOf(boxes, extra = {}) {
  const bars = boxes.map(([index, left, top, width, height]) => ({
    __data__: index === null ? undefined : { node: { pointNumber: index } },
    querySelector: () => (width === null ? null : { getBoundingClientRect: () => ({ left, top, width, height }) }),
  }));
  return { querySelectorAll: () => bars, ...extra };
}
{ // where the bars stand now: the middle of each bar across its column (y for h, x for v)
  const boxes = [[0, 10, 100, 20, 40], [1, 10, 300, 20, 40], [2, 50, 20, 20, 10]];
  out.coords = {
    h: dialog.visibleCoords(surfaceOf(boxes), "h", 3),
    v: dialog.visibleCoords(surfaceOf(boxes), "v", 3),
    missing: dialog.visibleCoords(surfaceOf(boxes), "h", 4),
    outside: dialog.visibleCoords(surfaceOf([[7, 0, 0, 1, 1], [0, 0, 0, 1, 1]]), "h", 1),
    unknown: dialog.visibleCoords(surfaceOf([[null, 0, 0, 1, 1], [0, 0, 0, 1, 1]]), "h", 1),
    noRect: dialog.visibleCoords(surfaceOf([[0, 0, 0, null, null]]), "h", 1),
    negative: dialog.visibleCoords(surfaceOf([[-1, 0, 0, 1, 1], [0, 0, 0, 1, 1]]), "h", 1),
    fractional: dialog.visibleCoords(surfaceOf([[0.5, 0, 0, 1, 1]]), "h", 1),
  };
}
{ // the dialog lists the nodes as they are DRAWN (read from the SVG), by drawn column; no SVG: the figure order
  const boxes = [[0, 0, 100, 1, 10], [1, 0, 100, 1, 10], [2, 0, 300, 1, 10], [3, 0, 50, 1, 10], [4, 0, 200, 1, 10]];
  const drawn = dialog.listColumns(bundle(), surfaceOf(boxes));
  const blind = dialog.listColumns(bundle(), surfaceOf([]));
  const vertical = dialog.listColumns(bundle({}, { orientation: "v" }), surfaceOf([[0, 5, 0, 10, 1], [1, 5, 0, 10, 1], [2, 400, 0, 10, 1], [3, 50, 0, 10, 1], [4, 90, 0, 10, 1]]));
  out.columns = { drawn, blind, vertical };
}
