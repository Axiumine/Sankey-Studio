/**
 * The bar that appears while graphs are picked for a comparison: how many, the Compare link, a
 * Clear button, and the cap message.
 *
 * Test ids: selection-bar, compare-open (a link to `/compare?ids=...`; without a second graph it
 * stays visible but disabled, `aria-disabled`, no href), selection-clear, compare-limit-message
 * (shown at 12 graphs, the most the compare page draws).
 */

import { h } from "../core/dom.js";
import { formatCount } from "../core/format.js";
import { icon } from "../core/icons.js";
import { MAX_COMPARE } from "./state.js";

/**
 * @param {{selection: ReturnType<import("./state.js").createSelection>}} options
 * @returns {HTMLElement}  the bar; it updates itself when the selection changes
 */
export function createSelectionBar({ selection }) {
  const count = h("strong", { class: "selection-count" });
  const hint = h("span", { class: "text-muted text-sm", "data-role": "hint" });
  const open = h("a", { class: "btn btn-primary btn-sm", "data-testid": "compare-open" }, icon("columns", { size: 14 }), "Compare");
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
    h("div", { class: "selection-main" }, count, hint, h("div", { class: "selection-actions" }, open, clear)),
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
    hint.textContent = ready ? "" : "Pick at least two graphs to compare them.";
    limit.hidden = !selection.full();
  };
  selection.subscribe(render);
  render();
  return el;
}
