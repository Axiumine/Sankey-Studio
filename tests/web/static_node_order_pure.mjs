// Scenarios of test_static_node_order.py: the pure order functions (editor/chart/node-order.js).
const order = await import(`${dir}/editor/chart/node-order.js`);
const rows = (...items) => items.map(([name, layer]) => ({ name, layer }));
const grid = rows(["a", 0], ["b", 0], ["c", 1], ["d", 1], ["e", 1], ["f", 2]);

out.swap = order.orderFromPositions({ nodes: grid, coords: [0.9, 0.1, 0.5, 0.3, 0.2, 0.4] });
out.keep = order.orderFromPositions({ nodes: grid, coords: [0.1, 0.9, 0.2, 0.3, 0.4, 0.5] });
out.ties = order.orderFromPositions({ nodes: grid, coords: [0.5, 0.5, 0.1, 0.1, 0.1, 0.2] });
out.layersAscending = order.orderFromPositions({ nodes: rows(["x", 2], ["y", 0], ["z", 1]), coords: [0, 0, 0] });
out.beyondOne = order.orderFromPositions({ nodes: rows(["p", 0], ["q", 0]), coords: [2.5, 1.5] });
out.negative = order.orderFromPositions({ nodes: rows(["p", 0], ["q", 0]), coords: [-1, -2] });
out.zero = order.orderFromPositions({ nodes: rows(["p", 0], ["q", 0]), coords: [0, 0] });
out.refused = {
  short: order.orderFromPositions({ nodes: grid, coords: [0.1] }),
  long: order.orderFromPositions({ nodes: rows(["a", 0]), coords: [0.1, 0.2] }),
  nan: order.orderFromPositions({ nodes: rows(["a", 0], ["b", 0]), coords: [0.1, Number.NaN] }),
  infinite: order.orderFromPositions({ nodes: rows(["a", 0], ["b", 0]), coords: [0.1, Infinity] }),
  text: order.orderFromPositions({ nodes: rows(["a", 0], ["b", 0]), coords: [0.1, "0.2"] }),
  nothing: order.orderFromPositions({ nodes: [], coords: [] }),
  noNodes: order.orderFromPositions({ nodes: null, coords: [1] }),
  noCoords: order.orderFromPositions({ nodes: rows(["a", 0]), coords: null }),
};
out.axis = [order.axisFor("h"), order.axisFor("v"), order.axisFor(undefined)];
out.current = order.currentOrder(rows(["b", 1], ["a", 0], ["c", 1], ["d", 0]));
out.layers = order.layersOf(rows(["b", 1], ["a", 0], ["c", 1]));
out.names = order.namesOf(rows(["b", 1], ["a", 0]));
out.same = [
  order.sameOrder(["a", "b"], ["a", "b"]),
  order.sameOrder(["a", "b"], ["b", "a"]),
  order.sameOrder(["a"], ["a", "b"]),
  order.sameOrder([], []),
];

const bundle = (nodes, source) => ({ nodes, figure: { data: [{ link: { source } }] } });
out.visual = order.visualNodes(bundle(
  [{ name: "Salary", layer: 0 }, { name: "Budget", layer: 1 }, { name: "Rent", layer: 2 }, { name: "Food", layer: 2 }, { name: "Groceries", layer: 3 }],
  [0, 1, 1, 3],
));
out.visualEmpty = [order.visualNodes(null), order.visualNodes({}), order.visualNodes({ nodes: [{ name: "a", layer: 0 }] })];

const labelled = (count, extra = {}) => ({
  nodes: Array.from({ length: count }, (_, i) => ({ name: `n${i}`, layer: 0 })),
  figure: { data: [{ node: { label: Array.from({ length: count }, (_, i) => `n${i}`) }, ...extra }] },
});
out.aligned = [order.isAligned(labelled(2)), order.isAligned({ ...labelled(2), nodes: [] }), order.isAligned({ ...labelled(2), nodes: labelled(3).nodes }), order.isAligned(null), order.isAligned({ nodes: [{}] }), order.isAligned({ figure: { data: [{ node: { label: ["a"] } }] } })];
out.reorderable = [order.isReorderable(labelled(2)), order.isReorderable(labelled(2, { arrangement: "snap" })), order.isReorderable(labelled(2, { arrangement: "fixed" })), order.isReorderable(labelled(2, { arrangement: "freeform" })), order.isReorderable(null)];
