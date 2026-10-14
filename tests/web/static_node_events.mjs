// Scenarios of test_static_node_events.py: the pointer logic of core/chart-nodes.js with a fake div and window.
const windowListeners = new Map();
globalThis.window = {
  addEventListener: (name, fn) => windowListeners.set(name, [...(windowListeners.get(name) ?? []), fn]),
  removeEventListener: (name, fn) => windowListeners.set(name, (windowListeners.get(name) ?? []).filter((item) => item !== fn)),
};
const fireWindow = (name, event) => (windowListeners.get(name) ?? []).forEach((fn) => fn(event));
const windowCount = () => [...windowListeners.values()].reduce((sum, list) => sum + list.length, 0);
const { attachNodeEvents, detachNodeEvents, MOVE_PX } = await import(`${dir}/core/chart-nodes.js`);

function fakeDiv(count = 3) {
  const handlers = {};
  const dom = {};
  return {
    data: [{ node: { label: Array.from({ length: count }, (_, i) => `n${i}`) } }],
    on: (name, fn) => (handlers[name] = [...(handlers[name] ?? []), fn]),
    emit: (name, payload) => (handlers[name] ?? []).forEach((fn) => fn(payload)),
    handlerCount: (name) => (handlers[name] ?? []).length,
    addEventListener: (name, fn) => (dom[name] = fn),
    removeEventListener: (name, fn) => dom[name] === fn && delete dom[name],
    press: (event) => dom.pointerdown?.(event),
    hasPress: () => "pointerdown" in dom,
  };
}
const bar = { closest: (selector) => (selector === ".sankey-node" ? {} : null) };
const background = { closest: () => null };
const down = (x, y, extra = {}) => ({ button: 0, clientX: x, clientY: y, target: bar, ...extra });
const up = (x, y) => ({ clientX: x, clientY: y });
const node = (index, extra = {}) => ({ pointNumber: index, sourceLinks: [{}], targetLinks: [{}, {}], originalEvent: { clientX: 7, clientY: 8 }, ...extra });
const update = (n = 3) => [{ "node.x": [Array.from({ length: n }, (_, i) => i / 10)], "node.y": [Array.from({ length: n }, (_, i) => i / 5)] }, [0]];
const later = () => new Promise((resolve) => setTimeout(resolve, 5));

function setup(count = 3) {
  const div = fakeDiv(count);
  const seen = { clicks: [], moves: [] };
  attachNodeEvents(div, () => ({ click: (info) => seen.clicks.push(info), move: (found) => seen.moves.push(found) }));
  return { div, seen };
}

{ // a plain click restyles too, and is neither a drag nor lost
  const { div, seen } = setup();
  div.emit("plotly_hover", { points: [node(1)] });
  div.press(down(100, 100));
  div.emit("plotly_unhover", {});
  fireWindow("pointerup", up(101, 102));
  div.emit("plotly_restyle", update());
  await later();
  out.plain = { clicks: seen.clicks, moves: seen.moves };
}
{ // a drag (snap: the restyle comes after the release) is forwarded once; no click
  const { div, seen } = setup();
  div.emit("plotly_hover", { points: [node(1)] });
  div.press(down(100, 100));
  div.emit("plotly_restyle", update()); // while the button is still down: not yet
  fireWindow("pointerup", up(100, 150));
  div.emit("plotly_restyle", update());
  div.emit("plotly_restyle", update());
  await later();
  out.drag = { moves: seen.moves, clicks: seen.clicks.length };
}
{ // the threshold: MOVE_PX is still a click, one pixel more is a drag
  const edge = setup();
  edge.div.emit("plotly_hover", { points: [node(0)] });
  edge.div.press(down(0, 0));
  fireWindow("pointerup", up(MOVE_PX, 0));
  edge.div.emit("plotly_restyle", update());
  await later();
  const over = setup();
  over.div.emit("plotly_hover", { points: [node(0)] });
  over.div.press(down(0, 0));
  fireWindow("pointerup", up(MOVE_PX + 0.5, 0));
  over.div.emit("plotly_restyle", update());
  await later();
  out.threshold = { MOVE_PX, edge: [edge.seen.clicks.length, edge.seen.moves.length], over: [over.seen.clicks.length, over.seen.moves.length] };
}
{ // a payload that does not have one number per label is ignored, never guessed, and does not use up the drag
  const { div, seen } = setup(3);
  div.press(down(0, 0));
  fireWindow("pointerup", up(0, 90));
  div.emit("plotly_restyle", update(2));
  div.emit("plotly_restyle", [{ "node.x": [[1, 2, 3]] }, [0]]);
  div.emit("plotly_restyle", [{ "node.y": [[1, 2, 3]] }, [0]]);
  div.emit("plotly_restyle", [{ "node.x": [[1, 2, 3]], "node.y": [[1, 2]] }, [0]]);
  div.emit("plotly_restyle", [{ "marker.color": ["red"] }, [0]]);
  div.emit("plotly_restyle", [{}, [0]]);
  div.emit("plotly_restyle", undefined);
  const refused = seen.moves.length;
  div.emit("plotly_restyle", update(3));
  out.mismatch = { refused, moves: seen.moves.length, forwarded: seen.moves[0] };
}
{ // a figure without labels refuses every payload
  const div = fakeDiv(3);
  div.data = [{}];
  const seen = [];
  attachNodeEvents(div, () => ({ move: (found) => seen.push(found) }));
  div.press(down(0, 0));
  fireWindow("pointerup", up(0, 90));
  div.emit("plotly_restyle", update(3));
  out.noLabels = seen.length;
}
{ // presses that are not on a bar, or not the main button, arm nothing
  const { div, seen } = setup();
  div.emit("plotly_hover", { points: [node(1)] });
  div.press(down(0, 0, { target: background }));
  fireWindow("pointerup", up(0, 90));
  div.emit("plotly_restyle", update());
  div.press(down(0, 0, { button: 2 }));
  fireWindow("pointerup", up(0, 90));
  div.emit("plotly_restyle", update());
  div.press(down(0, 0, { target: undefined }));
  fireWindow("pointerup", up(0, 90));
  div.emit("plotly_restyle", update());
  fireWindow("pointerup", up(0, 90)); // no press at all
  await later();
  out.unarmed = { moves: seen.moves.length, clicks: seen.clicks.length };
}
{ // Plotly's own click (fixed bars) and the pointer click are ONE click, either order
  const first = setup();
  first.div.emit("plotly_hover", { points: [node(2)] });
  first.div.press(down(10, 10));
  fireWindow("pointerup", up(10, 10));
  first.div.emit("plotly_click", { points: [node(2)] });
  await later();
  const second = setup();
  second.div.emit("plotly_hover", { points: [node(2)] });
  second.div.press(down(10, 10));
  fireWindow("pointerup", up(10, 10));
  await later();
  second.div.emit("plotly_click", { points: [node(2)] });
  out.once = { natural: first.seen.clicks, pointer: second.seen.clicks };
}
{ // the info of a click: index, flow roles and where the pointer was
  const { div, seen } = setup();
  div.emit("plotly_click", { points: [node(1, { sourceLinks: [], targetLinks: [{}] })] });
  div.emit("plotly_click", { points: [node(0, { sourceLinks: [{}], targetLinks: [] })] });
  div.emit("plotly_click", { points: [node(2, { sourceLinks: [{}], targetLinks: undefined, originalEvent: undefined })] });
  out.info = seen.clicks;
}
{ // links, empty events and a click that ends a drag are not node clicks
  const { div, seen } = setup();
  div.emit("plotly_click", { points: [{ pointNumber: 0, source: {}, target: {} }] });
  div.emit("plotly_click", { points: [] });
  div.emit("plotly_click", {});
  div.emit("plotly_click", undefined);
  div.emit("plotly_click", { points: [null] });
  div.press(down(0, 0));
  fireWindow("pointerup", up(0, 90));
  div.emit("plotly_click", { points: [node(1)] });
  await later();
  out.notClicks = seen.clicks.length;
}
{ // hovering a link, or leaving a bar, forgets the node: a press has nothing to report
  const { div, seen } = setup();
  div.emit("plotly_hover", { points: [node(1)] });
  div.emit("plotly_hover", { points: [{ source: {}, target: {} }] });
  div.press(down(5, 5));
  fireWindow("pointerup", up(5, 5));
  div.emit("plotly_hover", { points: [node(1)] });
  div.emit("plotly_unhover", {});
  div.press(down(5, 5));
  fireWindow("pointerup", up(5, 5));
  div.emit("plotly_hover", {});
  div.emit("plotly_hover", undefined);
  div.press(down(5, 5));
  fireWindow("pointerup", up(5, 5));
  await later();
  out.forgotten = seen.clicks.length;
}
{ // a press on a bar tells `start` (with the chart div) before anything moves; other presses do not
  const div = fakeDiv();
  const heard = [];
  attachNodeEvents(div, () => ({ start: (surface) => heard.push(surface === div) }));
  div.press(down(0, 0));
  fireWindow("pointerup", up(0, 0));
  div.press(down(0, 0, { target: background }));
  div.press(down(0, 0, { button: 2 }));
  div.press(down(0, 0));
  fireWindow("pointerup", up(0, 90));
  out.start = heard;
}
{ // listeners are asked at the event: a redraw swaps the callbacks and never stacks handlers
  const base = windowCount();
  const div = fakeDiv();
  const log = [];
  const counts = () => [div.handlerCount("plotly_click"), div.handlerCount("plotly_restyle"), div.handlerCount("plotly_hover"), div.handlerCount("plotly_unhover"), windowCount() - base];
  attachNodeEvents(div, () => ({ click: () => log.push("old") }));
  const before = counts();
  attachNodeEvents(div, () => ({ click: () => log.push("new") }));
  div.emit("plotly_click", { points: [node(0)] });
  out.swap = { before, after: counts(), log };
}
{ // a missing callback, or no listeners at all, is fine
  const none = fakeDiv();
  attachNodeEvents(none, () => null);
  none.emit("plotly_click", { points: [node(0)] });
  none.press(down(0, 0));
  fireWindow("pointerup", up(0, 90));
  none.emit("plotly_restyle", update());
  const empty = fakeDiv();
  attachNodeEvents(empty, () => ({}));
  empty.emit("plotly_click", { points: [node(0)] });
  empty.press(down(0, 0));
  fireWindow("pointerup", up(0, 90));
  empty.emit("plotly_restyle", update());
  out.silent = "ok";
}
{ // detaching stops the pointer listeners; a chart drawn again in the same div attaches again
  const before = windowCount();
  const div = fakeDiv();
  const seen = [];
  const listen = () => ({ move: (found) => seen.push(found) });
  attachNodeEvents(div, listen);
  const attachedCount = windowCount() - before;
  detachNodeEvents(div);
  const detached = [windowCount() - before, div.hasPress()];
  detachNodeEvents(div);
  attachNodeEvents(div, listen);
  out.detach = { attachedCount, detached, again: windowCount() - before, handlers: div.handlerCount("plotly_restyle") };
}
{ // a cancelled pointer ends a press like a release
  const { div, seen } = setup();
  div.press(down(0, 0));
  fireWindow("pointercancel", up(0, 90));
  div.emit("plotly_restyle", update());
  out.cancel = seen.moves.length;
}
