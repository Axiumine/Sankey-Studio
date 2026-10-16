// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Node events of a Plotly Sankey: a click on a bar and a drag of a bar, as plain data.
 *
 * `attachNodeEvents(div, getListeners)` listens ONCE per div (a second call only swaps the callbacks,
 * so a redraw never stacks listeners). `getListeners()` is asked at the moment of each event and
 * returns `{click?, move?}`, so the callbacks of the figure that is on screen are always the ones
 * that run. Nothing from Plotly is passed on: only numbers.
 *
 * - `click({index, hasIn, hasOut, clientX, clientY})`: a node (not a link) was clicked; `index` is the
 *   `pointNumber`, i.e. the position in `node.label` and in `bundle.nodes`. Plotly's own
 *   `plotly_click` does NOT fire for a plain click while the nodes can be dragged (snap,
 *   perpendicular, freeform: the drag behaviour swallows it), so a press that ends within
 *   `MOVE_PX` of where it started on a bar is reported from the pointer events and the hovered node.
 *   Whichever of the two arrives first is the click; the other one is dropped.
 * - `move({xs, ys})`: a bar was dragged. At the end of a drag Plotly restyles `node.x` and `node.y`
 *   of EVERY node (one number per node, in `node.label` order). A plain click restyles too, so the
 *   restyle only counts after a press on a bar that moved more than `MOVE_PX`. In `snap` mode the
 *   restyle comes after the pointer is released (when the bars settle); the answer to a drag is
 *   consumed once. A payload whose length is not the number of labels is ignored, never guessed.
 * - `start(div)`: a press on a bar began (before any movement), so the callback can read how the bars
 *   stand BEFORE the drag; the editor compares the dropped order with that, not with the figure order.
 */

export const MOVE_PX = 4;

const attached = new WeakMap(); // div -> {listeners, gesture, hovered, off}

function isNodePoint(point) {
  return point !== null && typeof point === "object" && Array.isArray(point.sourceLinks);
}

function infoOf(point, origin) {
  return {
    index: point.pointNumber,
    hasIn: Array.isArray(point.targetLinks) && point.targetLinks.length > 0,
    hasOut: point.sourceLinks.length > 0,
    clientX: origin?.clientX ?? null,
    clientY: origin?.clientY ?? null,
  };
}

function listenersOf(state) {
  return state.getListeners() ?? {};
}

function fireClick(state, info, gesture) {
  if (gesture?.fired) {
    return;
  }
  if (gesture) {
    gesture.fired = true;
  }
  listenersOf(state).click?.(info);
}

function onNaturalClick(state, event) {
  const point = event?.points?.[0];
  const gesture = state.gesture;
  if (!isNodePoint(point) || gesture?.moved) {
    return;
  }
  fireClick(state, infoOf(point, point.originalEvent), gesture);
}

function onHover(state, event) {
  const point = event?.points?.[0];
  state.hovered = isNodePoint(point) ? infoOf(point, null) : null;
}

function onPointerDown(state, event) {
  const onBar = event.button === 0 && event.target?.closest?.(".sankey-node");
  state.gesture = onBar ? { x: event.clientX, y: event.clientY, hovered: state.hovered, up: false, moved: false, fired: false, answered: false } : null;
  if (state.gesture) {
    listenersOf(state).start?.(state.div);
  }
}

function onPointerUp(state, event) {
  const gesture = state.gesture;
  if (!gesture || gesture.up) {
    return;
  }
  gesture.up = true;
  gesture.moved = Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > MOVE_PX;
  if (gesture.moved || !gesture.hovered) {
    return;
  }
  const info = { ...gesture.hovered, clientX: event.clientX, clientY: event.clientY };
  setTimeout(() => fireClick(state, info, gesture), 0);
}

function positions(div, update) {
  const xs = update?.["node.x"]?.[0];
  const ys = update?.["node.y"]?.[0];
  const labels = div.data?.[0]?.node?.label;
  const same = Array.isArray(xs) && Array.isArray(ys) && Array.isArray(labels) && xs.length === labels.length && ys.length === labels.length;
  return same ? { xs: Array.from(xs), ys: Array.from(ys) } : null;
}

function onRestyle(state, div, event) {
  const gesture = state.gesture;
  if (!gesture?.up || !gesture.moved || gesture.answered) {
    return;
  }
  const found = positions(div, event?.[0]);
  if (found) {
    gesture.answered = true;
    listenersOf(state).move?.(found);
  }
}

/**
 * Starts reporting node clicks and drags of the chart in `div` (after `Plotly.react`).
 * @param {HTMLElement} div  a div that Plotly drew a Sankey into
 * @param {() => ({click?: (info: object) => void, move?: (positions: {xs: number[], ys: number[]}) => void, start?: (div: HTMLElement) => void} | null)} getListeners
 */
export function attachNodeEvents(div, getListeners) {
  const known = attached.get(div);
  if (known) {
    known.getListeners = getListeners;
    return;
  }
  const state = { div, getListeners, gesture: null, hovered: null, off: null };
  const down = (event) => onPointerDown(state, event);
  const up = (event) => onPointerUp(state, event);
  div.on("plotly_hover", (event) => onHover(state, event));
  div.on("plotly_unhover", () => {
    state.hovered = null;
  });
  div.on("plotly_click", (event) => onNaturalClick(state, event));
  div.on("plotly_restyle", (event) => onRestyle(state, div, event));
  div.addEventListener("pointerdown", down, true);
  window.addEventListener("pointerup", up, true);
  window.addEventListener("pointercancel", up, true);
  state.off = () => {
    div.removeEventListener("pointerdown", down, true);
    window.removeEventListener("pointerup", up, true);
    window.removeEventListener("pointercancel", up, true);
  };
  attached.set(div, state);
}

/**
 * Stops reporting (the chart was purged: Plotly dropped its own listeners with it).
 * @param {HTMLElement} div
 */
export function detachNodeEvents(div) {
  attached.get(div)?.off();
  attached.delete(div);
}
