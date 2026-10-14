/**
 * The bar that appears while graphs are picked for a comparison: how many, the Compare link, a
 * Clear button, and the cap message.
 *
 * The same picked graphs can be moved into a collection (`selection-move`, only offered while a
 * collection exists and writes are allowed).
 *
 * Test ids: selection-bar, compare-open (a link to `/compare?ids=...`; without a second graph it
 * stays visible but disabled, `aria-disabled`, no href), selection-move, selection-clear,
 * compare-limit-message (shown at 12 graphs, the most the compare page draws).
 */

import { lockWriteControls } from "../core/boot.js";
import { h } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { icon } from "../core/icons.js";
import { MAX_COMPARE } from "./state.js";

/**
 * @param {{selection: ReturnType<import("./state.js").createSelection>, canMove?: () => boolean, onMove?: (button: HTMLButtonElement) => void}} options
 *   `canMove` is asked whenever the selection changes or `refresh` runs; `onMove` runs when "Move to collection" is pressed
 * @returns {{el: HTMLElement, refresh: () => void}}  the bar; it updates itself when the selection changes, and `refresh`
 *   repaints it when something else changed (the collection index, which decides whether Move is offered)
 */
export function createSelectionBar({ selection, canMove = () => false, onMove = () => {} }) {
  const count = h("strong", { class: "selection-count" });
  const hint = h("span", { class: "text-muted text-sm", "data-role": "hint" });
  const open = h("a", { class: "btn btn-primary btn-sm", "data-testid": "compare-open" }, icon("columns", { size: 14 }), "Compare");
  const move = h("button", { type: "button", class: "btn btn-sm", "data-writes": true, hidden: true, "data-testid": "selection-move", on: { click: (event) => onMove(event.currentTarget) } }, icon("folder", { size: 14 }), "Move to collection");
  const clear = h("button", { type: "button", class: "btn btn-sm btn-ghost", "data-testid": "selection-clear", on: { click: () => selection.clear() } }, icon("x", { size: 14 }), "Clear selection");
  const limit = h(
    "p",
    { class: "selection-limit text-sm", role: "status", "data-testid": "compare-limit-message", hidden: true },
    icon("info", { size: 14 }),
    `You can compare up to ${MAX_COMPARE} graphs at a time. Clear one to pick another.`,
  );
  const el = h(
    "section",
    { class: "selection-bar", "aria-label": "Selected graphs", "data-testid": "selection-bar", hidden: true },
    h("div", { class: "selection-main" }, count, hint, h("div", { class: "selection-actions" }, open, move, clear)),
    limit,
  );

  const render = () => {
    const size = selection.size();
    el.hidden = size === 0;
    count.textContent = `${formatCount(size, "graph")} selected`;
    const ready = size >= 2;
    if (ready) {
      open.setAttribute("href", `/compare?ids=${selection.ids().join(",")}`);
      open.removeAttribute("aria-disabled");
    } else {
      open.removeAttribute("href");
      open.setAttribute("aria-disabled", "true");
    }
    move.hidden = !canMove();
    hint.textContent = ready ? "" : "Pick at least two graphs to compare them.";
    limit.hidden = !selection.full();
  };
  selection.subscribe(render);
  render();
  lockWriteControls(el);
  return { el, refresh: render };
}
