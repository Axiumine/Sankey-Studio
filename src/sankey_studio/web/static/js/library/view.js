/**
 * The result area of the library: summary line, card grid, and the honest states around it
 * (empty library, no match, error). Created once; `show*` calls swap the content.
 *
 * - `showItems({items, total, truncated}, state)`: the grid, or an empty state when nothing is
 *   there. Nothing at all and no filter = the library is empty (`library-empty`, with the
 *   create-your-first-graph and import calls to action); nothing under a filter = no match.
 * - `showError(error, retry)`: error state with a retry button.
 * - `setStale(bool)`: dims the current content while a new page loads (no skeleton flash).
 * - the card checkboxes follow the selection (cap: the rest are disabled with an explanation).
 *
 * Test ids: library-empty, library-no-results, library-count, graph-card (see card.js).
 */

import { lockWriteControls, canWrite } from "../core/boot.js";
import { h } from "../core/dom.js";
import { formatNumber } from "../core/format.js";
import { emptyState, errorState, loadingState } from "../core/states.js";
import { stripBidi } from "../core/text.js";
import { graphCard } from "./card.js";
import { isGraphId } from "./data.js";
import { PAGE_SIZE } from "./state.js";

function emptyLibrary(onImport) {
  const writable = canWrite();
  const actions = writable
    ? [
      h("a", { class: "btn btn-primary", href: "/graphs/new" }, "Create your first graph"),
      h("button", { type: "button", class: "btn", on: { click: onImport } }, "Import a bundle"),
    ]
    : [];
  return emptyState({
    title: "No graphs yet",
    message: writable
      ? "Draw a Sankey diagram from pasted data, a file or MongoDB, or bring in graphs you exported before."
      : "This server is read-only, so graphs cannot be created or imported here.",
    icon: "bar-chart",
    actions,
    testid: "library-empty",
  });
}

function noMatch(state, onClear) {
  const what = [state.q ? `“${state.q}”` : null, state.tag ? `the tag “${state.tag}”` : null].filter(Boolean).join(" and ");
  return emptyState({
    title: "No graphs match",
    message: `Nothing in the library matches ${what}. Try other words or clear the filters.`,
    icon: "search",
    actions: [h("button", { type: "button", class: "btn", on: { click: onClear } }, "Clear filters")],
    testid: "library-no-results",
  });
}

function summaryText(result, state) {
  const first = (state.page - 1) * PAGE_SIZE + 1;
  const last = first + result.items.length - 1;
  const total = formatNumber(result.total, { maximumFractionDigits: 0 });
  const range = result.total <= PAGE_SIZE ? `${total}` : `${formatNumber(first, { maximumFractionDigits: 0 })}–${formatNumber(last, { maximumFractionDigits: 0 })} of ${total}`;
  const noun = result.total === 1 ? "graph" : "graphs";
  const filters = [state.q ? `matching “${state.q}”` : null, state.tag ? `tagged “${state.tag}”` : null].filter(Boolean).join(", ");
  return `${result.total <= PAGE_SIZE ? "" : "Showing "}${range} ${noun}${filters ? ` ${filters}` : ""}`;
}

class ResultsView {
  /** @param {{selection: object, handlers: object}} options  handlers: onSelect, onTag, onDuplicate, onDelete, onImport, onClear */
  constructor({ selection, handlers }) {
    this.selection = selection;
    this.handlers = handlers;
    this.summary = h("p", { class: "results-summary", tabindex: "-1", "data-testid": "library-count" });
    this.note = h("p", { class: "hint results-note", hidden: true });
    this.body = h("div", { class: "results-body" });
    this.el = h("section", { class: "results", "aria-label": "Graphs", tabindex: "-1" }, this.summary, this.note, this.body);
    selection.subscribe(() => this.syncBoxes());
  }

  /** Card checkboxes follow the selection; at the cap the unchecked ones are disabled. */
  syncBoxes() {
    for (const box of this.el.querySelectorAll('[data-testid="compare-select"]')) {
      const id = box.closest("[data-graph-id]")?.dataset.graphId;
      box.checked = this.selection.has(id);
      box.disabled = !box.checked && this.selection.full();
      box.title = box.disabled ? "You can compare up to 12 graphs at a time" : "";
    }
  }

  setStale(stale) {
    this.el.classList.toggle("is-stale", stale);
  }

  showLoading() {
    this.summary.hidden = true;
    this.body.replaceChildren(loadingState({ label: "Loading graphs", lines: 5 }));
  }

  /** Which card button holds the focus, so it can be given back after the list redraws. */
  rememberFocus(button) {
    const id = button.closest("[data-graph-id]")?.dataset.graphId;
    return id ? { id, testid: button.dataset.testid } : null;
  }

  /** Focuses the remembered button (or the summary when its card is gone). */
  restoreFocus(memo) {
    const card = memo ? this.el.querySelector(`[data-graph-id="${memo.id}"]`) : null;
    const target = card?.querySelector(`[data-testid="${memo.testid}"]`);
    (target ?? (this.summary.hidden ? this.el : this.summary)).focus();
  }

  showError(error, retry) {
    this.summary.hidden = true;
    this.note.hidden = true;
    this.body.replaceChildren(errorState({ title: "The library could not be loaded", message: error.friendly ?? error.message, onRetry: retry }));
  }

  /** Draws a page: the grid, or the empty library / no match state. */
  showItems(result, state) {
    const filtered = Boolean(state.q || state.tag);
    this.summary.hidden = result.items.length === 0;
    this.note.hidden = !result.truncated;
    this.note.textContent = result.truncated ? "This order covers the 1,000 most recently updated graphs that match." : "";
    if (result.items.length === 0) {
      const { onImport, onClear } = this.handlers;
      this.body.replaceChildren(result.total === 0 && !filtered ? emptyLibrary(onImport) : noMatch(state, onClear));
      return;
    }
    this.summary.textContent = stripBidi(summaryText(result, state));
    const context = { selection: this.selection, ...this.handlers };
    const cards = result.items.filter((item) => isGraphId(item.id)).map((item) => h("li", null, graphCard(item, context)));
    this.body.replaceChildren(h("ul", { class: "library-grid", role: "list" }, cards));
    lockWriteControls(this.body);
    this.syncBoxes();
  }
}

/**
 * Creates the result area.
 * @param {{selection: object, handlers: object}} options
 * @returns {ResultsView}
 */
export function createView(options) {
  return new ResultsView(options);
}
