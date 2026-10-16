// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Server paging of the entries table: `POST /entries?offset&limit&q&only_uncategorized&sort` with the
 * draft as body.
 *
 * `createLoader({api, store, onState, pageSize, debounceMs})` -> `{query, setQuery(patch), refresh({immediate}), dispose()}`
 * - `query` is `{q, onlyUncategorized, sort, page}` (page is 1-based; a filter or sort change goes
 *   back to page 1);
 * - `refresh()` runs the request after a short quiet period (draft edits arrive in bursts),
 *   `refresh({immediate: true})` at once; a sequence number drops answers that arrive late, so the
 *   table never shows an older page (requests are not aborted: that shows up as a failed request);
 * - `onState(state)` receives `{phase, rows, total, page, pages, error}` with `phase` one of
 *   `empty` (the draft has no input yet), `loading` (first load, no rows to show), `ready`,
 *   `refreshing` (a request is running, the previous rows stay), `error` (the rows of the last good
 *   answer stay, `error` is `{code, message, status, details}`).
 * A page past the end (a filter shrank the list) falls back to the last page by itself.
 * The first answer after a failure also asks the live preview again when the chart is showing its
 * own failure (../preview.js `retryFailedPreview`): both calls went to the same unreachable server.
 */

import { debounce } from "../../core/debounce.js";
import { hasSourceInput, retryFailedPreview } from "../preview.js";

export const PAGE_SIZE = 100;

function describe(error) {
  return {
    status: error.status ?? 0,
    code: error.code ?? "client_error",
    message: error.friendly ?? error.message ?? "The entries could not be loaded",
    details: error.details ?? [],
  };
}

class Loader {
  constructor({ api, store, onState, pageSize = PAGE_SIZE, debounceMs = 300 }) {
    this.api = api;
    this.store = store;
    this.onState = onState;
    this.pageSize = pageSize;
    this.query = { q: "", onlyUncategorized: false, sort: "value", page: 1 };
    this.data = { rows: [], total: 0 };
    this.sequence = 0;
    this.failed = false;
    this.schedule = debounce(() => this.run(), debounceMs);
  }

  pages() {
    return Math.max(1, Math.ceil(this.data.total / this.pageSize));
  }

  emit(phase, error = null) {
    this.onState({ phase, rows: this.data.rows, total: this.data.total, page: this.query.page, pages: this.pages(), error });
  }

  setQuery(patch) {
    const filtered = "q" in patch || "onlyUncategorized" in patch || "sort" in patch;
    this.query = { ...this.query, ...(filtered && !("page" in patch) ? { page: 1 } : {}), ...patch };
  }

  refresh({ immediate = false } = {}) {
    if (immediate) {
      this.schedule.cancel();
      return this.run();
    }
    this.schedule();
    return Promise.resolve();
  }

  params() {
    const { q, onlyUncategorized, sort, page } = this.query;
    return { offset: (page - 1) * this.pageSize, limit: this.pageSize, q: q.trim(), only_uncategorized: onlyUncategorized ? true : undefined, sort };
  }

  async run() {
    this.sequence += 1;
    const mine = this.sequence;
    const draft = this.store.get().draft;
    if (!hasSourceInput(draft)) {
      this.data = { rows: [], total: 0 };
      this.emit("empty");
      return;
    }
    this.emit(this.data.rows.length > 0 || this.data.total > 0 ? "refreshing" : "loading");
    try {
      const page = await this.api.post("/entries", draft, { query: this.params(), quiet: true });
      if (mine !== this.sequence) {
        return;
      }
      this.data = { rows: page.rows, total: page.total };
      if (page.rows.length === 0 && page.total > 0 && this.query.page > 1) {
        this.query.page = this.pages();
        await this.run();
        return;
      }
      this.emit("ready");
      this.recover();
    } catch (error) {
      if (mine === this.sequence) {
        this.failed = true;
        this.emit("error", describe(error));
      }
    }
  }

  /** The server answered after a failure: the chart may still be showing the same failure. */
  recover() {
    if (this.failed) {
      this.failed = false;
      retryFailedPreview(this.store);
    }
  }

  dispose() {
    this.sequence += 1;
    this.schedule.cancel();
  }
}

/**
 * Creates the loader.
 * @param {{api: object, store: object, onState: (state: object) => void, pageSize?: number, debounceMs?: number}} deps
 * @returns {{query: object, setQuery: Function, refresh: Function, dispose: Function}}
 */
export function createLoader(deps) {
  const loader = new Loader(deps);
  return {
    get query() {
      return loader.query;
    },
    setQuery: (patch) => loader.setQuery(patch),
    refresh: (options) => loader.refresh(options),
    pageSize: loader.pageSize,
    dispose: () => loader.dispose(),
  };
}
