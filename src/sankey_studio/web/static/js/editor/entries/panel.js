/**
 * The entries panel: the categorising table of the editor.
 *
 * One row per (source, target) pair, server-paged (`POST /entries`), searchable, with an
 * "uncategorised only" filter and a sort. Categories are OPTIONAL everywhere: an empty cell is a
 * normal row, nothing here is required to draw, save or export.
 *
 * - Category cell: a text input with a datalist of `bundle.category_names`; Enter (moves to the next
 *   row), blur or picking a suggestion commits, Esc reverts, "x" clears. Commits go through
 *   ./commit.js (optimistic row, server-checked, written to `draft.transform.entry_categories`, or to
 *   `Link.category` of every link of the pair for a manual source).
 * - "Categorise all entries matching this filter" adds ONE glob rule (./bulk.js).
 * - Hints: categorised entries the donut basis ignores (./hints.js), the 20,000 single-entry limit.
 * Test ids: `entries-table`, `entries-row`, `entries-search`, `entries-uncategorized-only`,
 * `entries-sort`, `entries-pager-next`, `entries-pager-prev`, `entries-total`, `category-cell`,
 * `category-clear`, `category-datalist`, `categorise-all-matching`, `category-error`, plus
 * `entries-basis-hint` and `categorise-category` (./bulk.js).
 */

import { announce } from "../../core/a11y.js";
import { h, uid } from "../../core/dom.js";
import { formatNumber } from "../../core/format.js";
import { icon } from "../../core/icons.js";
import { present, slot } from "../output-panel-kit.js";
import { createBulk } from "./bulk.js";
import { createCommitter } from "./commit.js";
import { bulkProblem, describeRule } from "./edits.js";
import { basisHint } from "./hints.js";
import { createCategoryNames } from "./names.js";
import { createStaleNotice } from "./notice.js";
import { createLoader, PAGE_SIZE } from "./query.js";
import { CATEGORY_DATALIST_ID, createRowsView } from "./rows.js";
import { createPager } from "./pager.js";
import { placeholderFor } from "./placeholders.js";
import { createToolbar } from "./toolbar.js";

const SEARCH_DELAY_MS = 250;

class EntriesPanel {
  constructor(container, ctx) {
    this.container = container;
    this.store = ctx.store;
    this.toast = ctx.toast;
    this.state = { phase: "loading", rows: [], total: 0, page: 1, pages: 1, error: null };
    this.searchTimer = null;
    this.loader = createLoader({ api: ctx.api, store: ctx.store, onState: (state) => this.onState(state) });
    this.committer = createCommitter({ api: ctx.api, store: ctx.store, ui: this.feedback() });
    this.build();
    this.unsubscribe = this.subscribe();
    this.paintBundle();
    this.loader.refresh({ immediate: true });
  }

  /** What the committer needs from the screen. */
  feedback() {
    return {
      known: () => this.names.known(),
      row: (entry) => this.rows.rowOf(entry),
      pending: (entry, pending) => this.rows.setPending(entry, pending),
      applied: (entry, patch, options) => this.applied(entry, patch, options),
      rejected: (entry, message, previous) => this.rejected(entry, message, previous),
    };
  }

  build() {
    const titleId = uid("entries-title");
    this.rows = createRowsView({ onCommit: (entry, text) => this.committer.commitEntry(entry, text), onNext: (entry, step) => this.focusNeighbour(entry, step) });
    this.toolbar = createToolbar({ onSearch: () => this.searchSoon(), onFilter: () => this.filterNow() });
    this.bulk = createBulk({ onApply: (text) => this.applyBulk(text) });
    this.total = h("span", { class: "out-total nums", "data-testid": "entries-total" });
    this.error = h("p", { class: "field-error out-category-error", role: "alert", "data-testid": "category-error" });
    this.basis = h("div", { class: "notice out-basis", "data-kind": "info", "data-testid": "entries-basis-hint" });
    this.stale = createStaleNotice({ onRetry: () => this.retry() });
    this.slots = { error: slot(), bulk: slot(), basis: slot(), loadError: slot() };
    this.datalist = h("datalist", { id: CATEGORY_DATALIST_ID, "data-testid": "category-datalist" });
    this.names = createCategoryNames({ store: this.store, datalist: this.datalist });
    this.overlay = h("div", { class: "out-overlay" });
    this.pager = createPager({ onPage: (page) => this.goTo(page), pageSize: PAGE_SIZE });
    this.block = h("div", { class: "table-block out-table-block" }, h("div", { class: "table-wrap", role: "region", tabindex: "0", "aria-label": "Entries table" }, this.rows.el), this.pager.el);
    this.rows.el.addEventListener("input", () => this.clearError());
    this.container.replaceChildren(
      h(
        "section",
        { class: "card out-card out-entries-card", "aria-labelledby": titleId },
        h("div", { class: "card-header" }, h("h2", { class: "card-title", id: titleId }, "Entries"), this.total),
        h(
          "div",
          { class: "card-body out-stack" },
          h("p", { class: "out-note" }, "Each row is one flow from a source to a target. Giving a flow a category is optional: it unlocks the donut chart and colouring by category."),
          this.toolbar.el,
          this.slots.error,
          this.slots.bulk,
          this.slots.basis,
          this.slots.loadError,
          h("div", { class: "out-list" }, this.overlay, this.block),
        ),
        this.datalist,
      ),
    );
  }

  subscribe() {
    const refresh = () => this.loader.refresh();
    return [
      this.store.subscribe(refresh, { select: (state) => state.draft?.source }),
      this.store.subscribe(refresh, { select: (state) => state.draft?.transform }),
      this.store.subscribe(() => this.bundleChanged(), { select: (state) => state.bundle }),
      this.store.subscribe(() => this.paintBundle(), { select: (state) => state.draft?.style?.donut }),
    ];
  }

  /** A new preview means the server answers again (the chart's "Try again", or any later edit): fetch the entries that failed. */
  bundleChanged() {
    this.paintBundle();
    if (this.state.phase === "error") {
      this.loader.refresh({ immediate: true });
    }
  }

  /** "Try again" of the stale notice. The notice leaves while the request runs, so focus is put back afterwards. */
  retry() {
    this.loader.refresh({ immediate: true }).then(() => {
      const idle = document.activeElement === document.body || !document.activeElement;
      const target = this.state.phase === "error" && this.stale.button.isConnected ? this.stale.button : this.block.querySelector(".table-wrap");
      if (idle && target) {
        target.focus();
      }
    });
  }

  paintBundle() {
    this.names.paint();
    const { bundle, draft } = this.store.get();
    const hint = basisHint(bundle, draft?.style?.donut?.basis ?? "all");
    present(this.slots.basis, this.basis, Boolean(hint));
    if (hint) {
      this.basis.replaceChildren(icon("info", { size: 16 }), h("div", { class: "notice-body" }, hint.text));
    }
    this.paintTotal();
  }

  paintTotal() {
    const { phase, total } = this.state;
    const all = this.store.get().bundle?.entries_total;
    this.total.hidden = phase === "empty" || phase === "loading" || (phase === "error" && this.state.rows.length === 0);
    const word = total === 1 ? "entry" : "entries";
    const filtered = this.toolbar.hasFilter() && typeof all === "number" && all > total;
    this.total.textContent = filtered ? `${formatNumber(total, { maximumFractionDigits: 0 })} of ${formatNumber(all, { maximumFractionDigits: 0 })} entries` : `${formatNumber(total, { maximumFractionDigits: 0 })} ${word}`;
  }

  onState(state) {
    this.state = state;
    if (state.phase !== "empty" && state.phase !== "loading") {
      this.rows.update(state.rows);
    }
    this.block.classList.toggle("out-updating", state.phase === "refreshing");
    this.block.toggleAttribute("aria-busy", state.phase === "refreshing");
    this.paintOverlay(state);
    this.pager.update(state);
    this.paintTotal();
    this.paintBulk(state.total, state.phase === "loading" || state.phase === "refreshing");
    const stale = state.phase === "error" && state.rows.length > 0;
    present(this.slots.loadError, this.stale.el, stale);
    if (stale) {
      this.stale.update(state.error);
    }
  }

  paintBulk(total, loading) {
    const query = this.toolbar.values().q;
    present(this.slots.bulk, this.bulk.el, query.trim() !== "");
    this.bulk.update({ query, total, loading });
  }

  paintOverlay(state) {
    const model = { phase: state.phase, hasRows: state.rows.length > 0, hasFilter: this.toolbar.hasFilter(), error: state.error, retry: () => this.loader.refresh({ immediate: true }) };
    const placeholder = placeholderFor(model, () => this.clearFilters());
    this.block.hidden = Boolean(placeholder);
    this.overlay.hidden = !placeholder;
    this.overlay.replaceChildren(...(placeholder ? [placeholder] : []));
  }

  goTo(page) {
    const target = Math.min(Math.max(1, page), this.state.pages);
    if (target === this.state.page) {
      return;
    }
    const forward = target > this.state.page;
    this.loader.setQuery({ page: target });
    this.loader.refresh({ immediate: true }).then(() => {
      announce(this.pager.label.textContent);
      this.pager.focusAfter(forward);
    });
  }

  searchSoon() {
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.filterNow(), SEARCH_DELAY_MS);
  }

  filterNow() {
    clearTimeout(this.searchTimer);
    this.loader.setQuery(this.toolbar.values());
    this.paintBulk(this.state.total, true);
    this.loader.refresh({ immediate: true });
  }

  clearFilters() {
    this.toolbar.clear();
    this.filterNow();
    this.toolbar.search.focus();
  }

  focusNeighbour(entry, step) {
    const next = this.rows.neighbour(entry, step);
    if (next) {
      this.rows.focusInput(next);
    }
  }

  showError(message) {
    this.error.textContent = message;
    present(this.slots.error, this.error, true);
    announce(message, { assertive: true });
  }

  clearError() {
    present(this.slots.error, this.error, false);
    this.error.textContent = "";
  }

  applied(entry, patch, options = {}) {
    this.rows.setValue(entry, patch);
    this.rows.setInvalid(entry, false);
    if (patch.category) {
      this.names.add(patch.category);
    }
    if (options.confirmed) {
      this.clearError();
      announce(patch.category ? `Category ${patch.category} set` : "Category cleared");
    }
  }

  rejected(entry, message, previous) {
    if (previous) {
      this.rows.setValue(entry, { category: previous.category, mixed: previous.mixed, overridden: previous.overridden }, { keepText: true });
    }
    this.rows.setInvalid(entry, true);
    this.showError(message);
  }

  async applyBulk(text) {
    const query = this.toolbar.values().q;
    const problem = bulkProblem(this.state, query);
    if (this.bulk.button.disabled) {
      return; // a rule is being added: Enter held down or pressed twice must not add copies
    }
    if (problem) {
      this.showError(problem);
      return;
    }
    this.bulk.setBusy(true);
    const result = await this.committer.addRule(query, text);
    this.bulk.setBusy(false);
    if (!result.ok) {
      this.showError(result.message);
      this.bulk.category.focus();
      return;
    }
    this.clearError();
    this.bulk.category.value = "";
    this.names.add(result.rule.category);
    this.toast?.show(`Rule added: ${describeRule(result.rule)} get "${result.rule.category}". You can edit it under Transform.`, {
      kind: "success",
      action: { label: "Undo", onClick: () => this.committer.undoRule(result.rule) },
    });
  }

  dispose() {
    clearTimeout(this.searchTimer);
    this.loader.dispose();
    for (const off of this.unsubscribe) {
      off();
    }
    this.container.replaceChildren();
  }
}

/**
 * Builds the entries panel into `container`.
 * @param {HTMLElement} container
 * @param {{store: object, api: object, toast?: object}} ctx
 * @returns {{dispose: () => void}}
 */
export function createEntriesPanel(container, ctx) {
  const panel = new EntriesPanel(container, ctx);
  return { dispose: () => panel.dispose() };
}

