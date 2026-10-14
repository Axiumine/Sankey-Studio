/**
 * The library page: wires the toolbar, the result grid, the pager, the selection bar and the
 * bundle actions around one query state.
 *
 * Flow: every change (typing, tag, sort, page, delete, import) calls `load(patch)`, which merges the
 * patch into the state, keeps the address in sync, dims the current cards, asks the API, and
 * redraws. A newer load cancels the older request, so a slow answer never overwrites a fast one.
 * The first paint uses the boot data (the server embeds the newest graphs of the open collection and
 * the list of collections), so a plain visit makes no list request at all. A visit by the Back or Forward button (or a page restored from the
 * browser's back/forward cache) never trusts it: the person may have duplicated, edited or deleted a
 * graph since the HTML was made, so the list is asked again.
 */

import { announce } from "../core/a11y.js";
import { reportError } from "../core/api.js";
import { boot, canWrite, pageRoot } from "../core/boot.js";
import { h, mount, setBusy } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { formatCount, formatNumber } from "../core/format.js";
import { toast } from "../core/toast.js";
import { createActions } from "./actions.js";
import { exportGraphs, startImport } from "./bundle.js";
import { fetchExportIds, fetchPage, fetchTags } from "./data.js";
import { onRestored, reachedByHistory } from "./freshness.js";
import { createFolders } from "./folders.js";
import { fetchFolders } from "./folders-data.js";
import { withDisplayName } from "./names.js";
import { createPager } from "./pager.js";
import { createRowActions } from "./row-actions.js";
import { createSelectionBar } from "./selection-bar.js";
import { createSelection, DEFAULT_SORT, isScoped, MAX_COMPARE, PAGE_SIZE, readQuery, writeQuery } from "./state.js";
import { createToolbar } from "./toolbar.js";
import { createView } from "./view.js";

/** A bundle holds at most this many graphs. */
const EXPORT_MAX = 200;
const NOTHING = Object.freeze({ items: [], total: 0, truncated: false });

/** True when the address asks for what the server embedded: its collection, newest first, page 1. */
function isDefault(state) {
  return isScoped(state) && state.sort === DEFAULT_SORT && state.page === 1 && state.folder === (boot().folder ?? "");
}

class LibraryPage {
  /** @param {HTMLElement} actionsRoot  where the Import / Export buttons go */
  constructor(actionsRoot) {
    this.state = readQuery(location.search);
    this.selection = createSelection();
    this.ticket = 0;
    this.last = { items: [], total: 0, truncated: false };
    this.actions = createActions({
      onFile: (file) => startImport(file, { onDone: () => this.reloadAll(), returnFocus: () => this.actions.focusImport() }),
      onExport: (button) => this.runExport(button),
    });
    this.folders = createFolders({ state: this.state, selection: this.selection, onChange: () => this.reloadAll() });
    this.toolbar = createToolbar({ state: this.state, onChange: (patch) => this.load(patch) });
    this.pager = createPager({ onPage: (page) => this.load({ page }) });
    this.view = createView({
      selection: this.selection,
      handlers: {
        onSelect: (graph, input) => this.pick(graph, input),
        onTag: (tag) => this.load({ tag, page: 1 }),
        onDuplicate: (graph, button) => this.rows.copy(graph, button),
        onDelete: (graph, button) => this.rows.remove(graph, button),
        onMove: (graph, button) => this.moveOne(graph, button),
        onImport: () => this.actions.openPicker(),
        onClear: () => this.load({ q: "", tag: "", page: 1 }),
      },
    });
    this.rows = createRowActions({ view: this.view, selection: this.selection, reload: () => this.reloadAll() });
    this.selection.subscribe(() => this.showExport());
    actionsRoot.replaceChildren(this.folders.actionsEl, this.actions.el);
    const readOnly = canWrite()
      ? null
      : h("p", { class: "hint readonly-note" }, icon("lock", { size: 14 }), "Read-only server: duplicating, deleting, moving and importing are turned off. You can still open, preview and export graphs.");
    this.bar = createSelectionBar({ selection: this.selection, canMove: () => this.folders.scope().folders > 0, onMove: () => this.moveSelected() });
    mount(pageRoot(), readOnly, this.folders.pathEl, this.toolbar.el, this.folders.el, this.view.el, this.pager.el, this.bar.el);
  }

  start() {
    const first = boot();
    this.folders.setIndex(Array.isArray(first.folders) ? first.folders : []);
    // the tag chips of the graphs the server already sent: no empty row that fills in later
    const known = Array.isArray(first.graphs) ? first.graphs.flatMap((graph) => graph.tags ?? []) : [];
    this.toolbar.setTags(Array.from(new Set(known)).sort((a, b) => a.localeCompare(b)));
    onRestored(() => this.reloadAll());
    if (isDefault(this.state) && Array.isArray(first.graphs) && !reachedByHistory()) {
      this.paint({ items: first.graphs.slice(0, PAGE_SIZE).map(withDisplayName), total: first.total ?? first.graphs.length, truncated: false });
    } else {
      this.view.showLoading();
      this.load();
    }
    this.refreshTags();
  }

  showExport() {
    const { total } = this.last;
    const picked = this.selection.size();
    let label = "Export";
    let title = "Save the graphs as a bundle file";
    if (picked > 0) {
      label = `Export selected (${picked})`;
    } else if (total > EXPORT_MAX) {
      // a bundle holds 200 graphs: say so on the button, not in a toast after the download
      label = `Export newest ${EXPORT_MAX} of ${formatNumber(total, { maximumFractionDigits: 0 })}`;
      title = `A bundle holds at most ${EXPORT_MAX} graphs, so this file has the ${EXPORT_MAX} most recently updated ones. Pick graphs to export others.`;
    } else if (total > 0) {
      label = `Export ${this.exportWhat()} (${total})`;
    }
    this.actions.setExport({ label, disabled: picked === 0 && total === 0, title });
  }

  /** What the Export button exports, in words: the list as it is shown. */
  exportWhat() {
    const scope = this.folders.scope();
    if (!isScoped(this.state)) {
      return "results";
    }
    if (scope.inFolder) {
      return "this collection";
    }
    return scope.folders > 0 ? "top-level graphs" : "all";
  }

  paint(result) {
    this.last = result;
    this.folders.update();
    this.bar.refresh(); // Move is offered only while a collection exists
    this.view.showItems(result, this.state, this.folders.scope());
    this.pager.update({ page: this.state.page, total: result.total, pageSize: PAGE_SIZE });
    this.showExport();
  }

  pick(graph, input) {
    if (this.selection.toggle(graph.id, graph.name)) {
      return;
    }
    input.checked = false;
    announce(`You can compare up to ${MAX_COMPARE} graphs at a time.`, { assertive: true });
  }

  async load(patch = {}) {
    Object.assign(this.state, patch);
    // a newer load takes over: older answers are dropped, not cancelled (no aborted requests)
    this.ticket += 1;
    const mine = this.ticket;
    writeQuery(this.state);
    this.toolbar.sync(this.state);
    this.view.setStale(true);
    try {
      const result = this.folders.scope().missing ? NOTHING : await fetchPage(this.state);
      if (mine !== this.ticket) {
        return undefined;
      }
      if (result.items.length === 0 && result.total > 0 && this.state.page > 1) {
        return await this.load({ page: Math.ceil(result.total / PAGE_SIZE) });
      }
      this.paint(result);
      announce(result.total === 0 ? "No graphs found" : `${formatCount(result.total, "graph")} found`);
    } catch (error) {
      if (mine === this.ticket) {
        this.fail(error);
      }
    } finally {
      if (mine === this.ticket) {
        this.view.setStale(false);
      }
    }
    return undefined;
  }

  /** Shows the error card and takes down what belonged to the query that failed (pager, export count). */
  fail(error) {
    this.last = { items: [], total: 0, truncated: false };
    this.view.showError(reportError(error), () => this.load());
    this.pager.hide();
    this.showExport();
  }

  async refreshTags() {
    try {
      const tags = await fetchTags();
      this.toolbar.setTags(tags);
      return tags;
    } catch {
      return null; // the chips are a convenience: the list works without them
    }
  }

  /** Asks for the collections again; the cards keep the last list when that fails. */
  async refreshFolders() {
    try {
      this.folders.setIndex(await fetchFolders());
    } catch {
      // the page works from the list it has
    }
  }

  async reloadAll() {
    const [tags] = await Promise.all([this.refreshTags(), this.refreshFolders()]);
    const gone = tags && this.state.tag && !tags.includes(this.state.tag);
    await this.load(gone ? { tag: "", page: 1 } : {});
  }

  async moveOne(graph, button) {
    const memo = this.view.rememberFocus(button);
    await this.folders.moveGraphs([graph]);
    this.view.restoreFocus(memo);
  }

  async moveSelected() {
    await this.folders.moveGraphs(this.selection.items());
    this.view.restoreFocus(null);
  }

  async runExport(button) {
    setBusy(button, true);
    try {
      let ids = this.selection.ids();
      if (ids.length === 0) {
        const found = await fetchExportIds(this.state);
        ids = found.ids;
        if (found.total > EXPORT_MAX) {
          toast.info(`A bundle holds at most ${EXPORT_MAX} graphs, so this file has the ${EXPORT_MAX} most recently updated of ${formatNumber(found.total, { maximumFractionDigits: 0 })}.`);
        }
      }
      const saved = await exportGraphs(ids);
      toast.success(`Saved ${saved.filename}.`);
    } catch (error) {
      reportError(error, toast);
    } finally {
      setBusy(button, false);
    }
  }
}

/**
 * Starts the library page.
 * @param {{actionsRoot: HTMLElement}} options
 * @returns {LibraryPage}
 */
export function startLibrary({ actionsRoot }) {
  const page = new LibraryPage(actionsRoot);
  page.start();
  return page;
}
