/**
 * The compare page: a responsive grid of up to 12 cards (one per graph), all drawn with the same
 * category colours.
 *
 * Flow: `reload()` asks `GET /compare/render?ids=&theme=` through `resolve` (data.js), which sets
 * aside graphs that are missing or broken instead of failing the page. Adding or removing a graph
 * reloads the whole set (the shared colour map can re-rank when the set changes) and keeps the
 * address (`/compare?ids=...`) in sync. A theme switch reloads with the other `?theme=`.
 * The page starts from the boot data: `ids` (empty = the "Nothing to compare yet" state, no request),
 * `graphs` (the summaries the server knows) and an optional `missing` list of ids it knows are gone,
 * which become missing cards at once; an id the server did not vouch for is found out the slow way
 * by `resolve`. Charts draw lazily, when their card nears the viewport (lazy.js); each card remembers whether it
 * shows the Sankey or the donut across reloads.
 *
 * The address always names what is on screen: `/compare?ids=...`, and plain `/compare` once the
 * last graph is removed (a reload then does not bring a removed graph back). After a removal the
 * focus moves to the remove button of the card that took its place (or the count line when the
 * grid is empty), because the grid is redrawn and keyboard users must not be sent to the top.
 *
 * Test ids: compare-grid (data-count), compare-card, compare-missing, compare-limit-message.
 */

import { api, isAbort, reportError } from "../core/api.js";
import { h, mount } from "../core/dom.js";
import { emptyState, errorState, loadingState } from "../core/states.js";
import { effectiveTheme, onThemeChange } from "../core/theme.js";
import { toast } from "../core/toast.js";
import { onRestored, reachedByHistory } from "../library/freshness.js";
import { withDisplayName } from "../library/names.js";
import { MAX_COMPARE } from "../library/state.js";
import { brokenCard, createChartCard, missingCard } from "./card.js";
import { resolve } from "./data.js";
import { createLazyDrawer } from "./lazy.js";
import { createCompareToolbar } from "./toolbar.js";

/** Chart height of a card: roomier when there are only one or two. */
function cardHeight(count) {
  return count <= 2 ? 480 : 400;
}

class ComparePage {
  /** @param {{ids: string[], graphs: object[], missing?: string[], root: HTMLElement, actionsRoot: HTMLElement}} options */
  constructor({ ids, graphs, missing = [], root, actionsRoot }) {
    // ids the server already knows are gone: shown as missing cards without asking the API (no 404)
    this.missing = new Set(missing);
    this.ids = [...ids, ...missing.filter((id) => !ids.includes(id))];
    this.names = new Map(graphs.map((graph) => [graph.id, withDisplayName(graph)]));
    this.choice = new Map();
    this.cards = [];
    this.warned = "";
    this.focusAt = null;
    this.running = null;
    this.lazy = createLazyDrawer();
    this.toolbar = createCompareToolbar({ onAdd: (id) => this.add(id) });
    this.body = h("div", { class: "compare-body" });
    this.grid = null;
    root.replaceChildren(this.toolbar.el, this.body);
    actionsRoot.replaceChildren(h("a", { class: "btn", href: "/" }, "Back to the library"));
  }

  async start() {
    onThemeChange(() => this.reload({ keep: true }));
    // restored from the back/forward cache: the graphs may have changed or gone meanwhile
    onRestored(async () => {
      await this.loadLibrary();
      this.reload();
    });
    this.toolbar.setCount(this.ids.length, this.ids);
    // the names in the page are as old as its HTML: after Back, read them before the cards are named
    const names = this.loadLibrary();
    if (reachedByHistory()) {
      await names;
    }
    return this.reload();
  }

  graphOf(id) {
    return this.names.get(id) ?? { id, name: "" };
  }

  async loadLibrary() {
    try {
      const page = await api.get("/graphs", { query: { limit: 200 }, quiet: true });
      const items = page.items.map(withDisplayName);
      items.forEach((graph) => this.names.set(graph.id, graph));
      this.toolbar.setLibrary(items, this.ids);
    } catch {
      // the add menu is a convenience: the comparison itself does not need it
    }
  }

  /** Replaces the note and the grid as one block (a fresh grid, so nothing already on screen shifts). */
  mountGrid(children, note = null) {
    this.grid = h("div", { class: "compare-grid", "data-testid": "compare-grid", "data-count": String(this.ids.length) }, children);
    mount(this.body, note, this.grid);
  }

  syncAddress() {
    const next = this.ids.length > 0 ? `/compare?ids=${this.ids.join(",")}` : "/compare";
    if (next !== `${location.pathname}${location.search}`) {
      history.replaceState(null, "", next);
    }
    if (this.grid) {
      this.grid.dataset.count = String(this.ids.length);
    }
    this.toolbar.setCount(this.ids.length, this.ids);
  }

  add(id) {
    if (this.ids.includes(id) || this.ids.length >= MAX_COMPARE) {
      return;
    }
    this.ids.push(id);
    this.syncAddress();
    this.reload();
  }

  remove(graph) {
    this.focusAt = Math.max(0, this.ids.indexOf(graph.id));
    this.ids = this.ids.filter((id) => id !== graph.id);
    this.missing.delete(graph.id);
    this.syncAddress();
    this.reload();
  }

  /** @param {{keep?: boolean}} [options]  keep: redraw the cards that are there (theme switch) */
  async reload({ keep = false } = {}) {
    this.running?.abort();
    const mine = new AbortController();
    this.running = mine;
    if (this.ids.length === 0) {
      this.showEmpty();
      return;
    }
    if (this.cards.length === 0) {
      this.mountGrid([h("div", { class: "card compare-card is-loading" }, loadingState({ block: true, label: "Loading the graphs" }))]);
    }
    const theme = effectiveTheme();
    try {
      const result = await resolve(this.ids.filter((id) => !this.missing.has(id)), theme, mine.signal);
      this.missing.forEach((id) => result.problems.set(id, { kind: "missing", message: "" }));
      if (this.running === mine) {
        this.show(result, { theme, keep });
      }
    } catch (error) {
      if (!isAbort(error)) {
        this.showError(reportError(error));
      }
    }
  }

  showEmpty() {
    this.disposeCards();
    this.mountGrid([emptyState({
      title: "Nothing to compare yet",
      message: "Add a graph from the menu above, or go back to the library and pick two or more.",
      icon: "columns",
      actions: [h("a", { class: "btn btn-primary", href: "/" }, "Back to the library")],
    })]);
    this.restoreFocus();
  }

  /**
   * After a removal the card that had the focus is gone: hand the focus to the remove button that
   * now sits at the same place (the last one when the removed card was last), or to the count line.
   * Does nothing when the person has already moved on to another control.
   */
  restoreFocus() {
    const index = this.focusAt;
    this.focusAt = null;
    if (index === null || (document.activeElement && document.activeElement !== document.body)) {
      return;
    }
    const buttons = this.grid?.querySelectorAll('[data-testid="compare-remove"]') ?? [];
    (buttons[Math.min(index, buttons.length - 1)] ?? this.toolbar.countEl).focus();
  }

  showError(failure) {
    this.focusAt = null;
    this.disposeCards();
    this.mountGrid([errorState({ title: "The comparison could not be drawn", message: failure.friendly, onRetry: () => this.reload() })]);
  }

  disposeCards() {
    this.lazy.disconnect();
    this.lazy = createLazyDrawer();
    this.cards.forEach((card) => card.dispose());
    this.cards = [];
  }

  /** True when the cards on screen are exactly the graphs that loaded, in order. */
  sameCards(bundles, problems) {
    return problems.size === 0 && this.cards.length === this.ids.length && this.cards.every((card, index) => card.graph.id === this.ids[index] && bundles.has(card.graph.id));
  }

  show({ bundles, problems }, { theme, keep }) {
    if (keep && this.sameCards(bundles, problems)) {
      this.cards.forEach((card) => card.update(bundles.get(card.graph.id), theme));
      mount(this.body, this.toolbar.colourNote(Array.from(bundles.values())), this.grid);
      return;
    }
    for (const card of this.cards) {
      this.choice.set(card.graph.id, card.chart);
    }
    this.disposeCards();
    const height = cardHeight(this.ids.length);
    const nodes = this.ids.map((id) => this.cardFor(id, { bundles, problems, height, theme }));
    this.mountGrid(nodes, this.toolbar.colourNote(Array.from(bundles.values())));
    this.restoreFocus();
    const key = Array.from(problems.keys()).join(",");
    if (key !== this.warned && problems.size > 0) {
      toast.warning(`${problems.size === 1 ? "One graph" : `${problems.size} graphs`} could not be drawn. The others are shown.`);
    }
    this.warned = key;
  }

  cardFor(id, { bundles, problems, height, theme }) {
    const graph = this.graphOf(id);
    const onRemove = (item) => this.remove(item);
    const problem = problems.get(id);
    if (problem) {
      return problem.kind === "missing" ? missingCard(graph, onRemove) : brokenCard(graph, problem, onRemove);
    }
    const card = createChartCard({ graph, bundle: bundles.get(id), height, chart: this.choice.get(id) ?? "sankey", onRemove, theme });
    this.cards.push(card);
    this.lazy.watch(card.el, () => card.paint(theme));
    return card.el;
  }
}

/**
 * Starts the compare page.
 * @param {{ids: string[], graphs: object[], missing?: string[], root: HTMLElement, actionsRoot: HTMLElement}} options
 * @returns {ComparePage}
 */
export function startCompare(options) {
  const page = new ComparePage(options);
  page.start();
  return page;
}
