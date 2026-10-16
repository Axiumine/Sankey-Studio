// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Live preview: keeps `store.bundle` in step with `store.draft`.
 *
 * `createPreview(store, options)` subscribes to the draft and, 300 ms after the last change,
 * POSTs it to `/api/v1/preview?theme=<effective theme>`. Each new request aborts the previous
 * one (AbortController) and a sequence number drops any answer that still arrives late, so a slow
 * old response can never overwrite a newer bundle.
 *
 * Writes (never under `draft`/`meta`, so previews never make the graph "dirty"):
 *   status.previewing   true while a request is in flight
 *   bundle              the new RenderBundle on success; the previous bundle is KEPT on failure
 *                       and when it is cleared only if the source has no input at all
 *   status.error        `{source: "preview", status, code, message, details}` of the envelope on
 *                       failure, else null. `source` is the tag every writer of `status.error`
 *                       sets ("save" for the save bar), so a reader can tell whose failure it is
 *                       (see chart/errors.js `previewError`).
 *
 * A draft without input (empty paste, no file, no manual rows, no Mongo collection) is not sent:
 * the bundle is cleared and no error is shown, so the preview pane can show its empty state.
 *
 * options: `{api, theme: () => "light"|"dark", debounceMs: 300, canPreview: (draft) => boolean}`.
 * Result: `{refresh({immediate}), dispose()}`. A theme change (core/theme.js) re-requests at once.
 */

import { api as defaultApi, isAbort } from "../core/api.js";
import { debounce } from "../core/debounce.js";
import { effectiveTheme, onThemeChange } from "../core/theme.js";

/**
 * True when the draft's source has anything to draw from.
 * @param {{source?: object}} draft
 * @returns {boolean}
 */
export function hasSourceInput(draft) {
  const source = draft?.source ?? {};
  if (source.type === "manual") {
    return Array.isArray(source.links) && source.links.length > 0;
  }
  if (source.type === "mongo") {
    return Boolean(source.connection && source.collection);
  }
  if (source.origin === "file") {
    return Boolean(source.path);
  }
  return typeof source.content === "string" && source.content.trim() !== "";
}

/**
 * Asks the live preview for a new bundle without changing what the draft says: a new draft object
 * with the same content makes the preview request again (`clean`, so the graph does not turn dirty).
 * @param {object} store  from editor/store.js
 */
export function requestPreview(store) {
  store.patch("draft", (draft) => ({ ...draft }), { clean: true });
}

/**
 * `requestPreview` only when the chart is showing a failure of the preview (`status.error.source`
 * "preview"): the entries table calls it once the server answered it again, so the chart does not
 * keep saying "cannot be reached" until its own "Try again".
 * @param {object} store  from editor/store.js
 */
export function retryFailedPreview(store) {
  if (store.get().status.error?.source === "preview") {
    requestPreview(store);
  }
}

function describe(error) {
  return {
    source: "preview",
    status: error.status ?? 0,
    code: error.code ?? "client_error",
    message: error.friendly ?? error.message ?? "The preview failed",
    details: error.details ?? [],
  };
}

class Preview {
  constructor(store, options) {
    this.store = store;
    this.client = options.api ?? defaultApi;
    this.theme = options.theme ?? effectiveTheme;
    this.canPreview = options.canPreview ?? hasSourceInput;
    this.sequence = 0;
    this.controller = null;
    this.working = false;
    this.schedule = debounce(() => this.run(), options.debounceMs ?? 300);
    this.offStore = store.subscribe(() => this.touch(), { select: (state) => state.draft });
    this.offTheme = onThemeChange(() => this.refresh({ immediate: true }));
  }

  /** A draft change: the preview is now pending until its answer (or a clear) arrives. */
  touch() {
    this.setWorking(true);
    this.schedule();
  }

  /** Tells the page shell (`#main[data-loading]`, core/shell.js) that a preview is pending or running. */
  setWorking(working) {
    if (this.working !== working) {
      this.working = working;
      document.dispatchEvent(new CustomEvent("sankey:work", { detail: { pending: working ? 1 : 0 } }));
    }
  }

  refresh({ immediate = true } = {}) {
    if (immediate) {
      this.schedule.cancel();
      return this.run();
    }
    this.schedule();
    return Promise.resolve();
  }

  clear() {
    this.store.batch(() => {
      this.store.patch("bundle", null);
      this.store.patch("status", (status) => ({ ...status, previewing: false, error: null }), { clean: true });
    });
  }

  async run() {
    this.sequence += 1;
    const mine = this.sequence;
    this.controller?.abort();
    this.controller = null;
    const draft = this.store.get().draft;
    if (!this.canPreview(draft)) {
      this.clear();
      this.setWorking(false);
      return;
    }
    this.setWorking(true);
    this.controller = new AbortController();
    this.store.patch("status.previewing", true, { clean: true });
    try {
      const bundle = await this.client.post("/preview", draft, {
        query: { theme: this.theme() },
        signal: this.controller.signal,
        quiet: true,
      });
      if (mine === this.sequence) {
        this.finish({ bundle, error: null });
      }
    } catch (error) {
      if (!isAbort(error) && mine === this.sequence) {
        this.finish({ error: describe(error) });
      }
    }
  }

  finish({ bundle, error }) {
    this.store.batch(() => {
      if (bundle !== undefined) {
        this.store.patch("bundle", bundle, { clean: true });
      }
      this.store.patch("status", (status) => ({ ...status, previewing: false, error }), { clean: true });
    });
    this.setWorking(false);
  }

  dispose() {
    this.sequence += 1;
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
      this.store.patch("status.previewing", false, { clean: true });
    }
    this.schedule.cancel();
    this.setWorking(false);
    this.offStore();
    this.offTheme();
  }
}

/**
 * Starts the live preview for a store.
 * @param {object} store  from editor/store.js
 * @param {object} [options]
 * @returns {{refresh: (options?: {immediate?: boolean}) => Promise<void>, dispose: () => void}}
 */
export function createPreview(store, options = {}) {
  const preview = new Preview(store, options);
  return {
    refresh: (opts) => preview.refresh(opts),
    dispose: () => preview.dispose(),
  };
}
