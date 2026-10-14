/**
 * The sticky save bar of the editor: a `.savebar` element inside the container (the container is
 * set to `display: contents`, so `position: sticky` works against the page, not a wrapper).
 *
 * - Status: "Not saved yet" / "Unsaved changes" / "All changes saved" with the revision and when it
 *   was saved (`status.dirty` and `meta` of the store), "Saving..." while a request runs, or the
 *   reason the last save failed.
 * - Save (`save-button`, Ctrl/Cmd+S): POST the first time, PUT with the revision afterwards. The
 *   name is required: an empty one explains itself and opens the details dialog (`ctx.openDetails`,
 *   else it focuses the name field). After the very
 *   first save the address becomes /graphs/{id}/edit (history.replaceState), no reload.
 * - Save as copy (`save-as-copy`): a new graph from the current draft; the editor continues on it.
 * - Optimistic concurrency: a 409 shows the conflict banner (`conflict-banner`) with Reload
 *   (`conflict-reload`) and Save my version as a copy (`conflict-save-copy`); a 404 (deleted
 *   elsewhere) offers the copy only. Nothing is overwritten and nothing is thrown away unasked.
 * - Read-only server (`boot.writes_allowed === false`): both buttons are disabled and the bar says why.
 * Test ids: `save-button`, `save-as-copy`, `conflict-banner`, `conflict-reload`, `conflict-save-copy`,
 * plus `save-status` (the status line; `data-state` is `new|dirty|saved|saving|error|readonly`).
 */

import { announce } from "../../core/a11y.js";
import { reportError } from "../../core/api.js";
import { h, setBusy } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { editsSettled, focusTestId, plainError } from "../output-panel-kit.js";
import { reloadGraph, saveCopy, saveGraph } from "./actions.js";
import { createConflictBanner } from "./banner.js";
import { trackBarHeight } from "./metrics.js";
import { describeSave, statusNode } from "./status.js";

const REFRESH_MS = 30000;
const NAME_PROBLEM = "Give the graph a name before saving.";

function conflictInfo(error) {
  const detail = (prefix) => error.details?.find((item) => item.startsWith(prefix))?.slice(prefix.length);
  return { kind: "conflict", revision: detail("revision="), updatedAt: detail("updated_at=") };
}

class SaveBar {
  constructor(container, ctx) {
    this.container = container;
    this.store = ctx.store;
    this.api = ctx.api;
    this.toast = ctx.toast;
    this.writable = ctx.boot?.writes_allowed !== false;
    this.openDetails = ctx.openDetails ?? null;
    this.problem = "";
    this.busy = false;
    this.lastKey = "";
    this.build();
    this.unsubscribe = [
      this.store.subscribe(() => this.paint(), { select: (state) => state.status }),
      this.store.subscribe(() => this.paint(), { select: (state) => state.meta }),
      this.store.subscribe(() => this.forgetProblem(), { select: (state) => state.draft }),
    ];
    this.onKey = (event) => this.shortcut(event);
    document.addEventListener("keydown", this.onKey);
    this.timer = setInterval(() => this.paint(), REFRESH_MS);
    this.paint();
  }

  build() {
    this.banner = createConflictBanner({ onReload: () => this.reload(), onCopy: () => this.copy(), onMount: (el) => this.bar.prepend(el) });
    this.status = h("div", { class: "savebar-status out-save-status", "data-testid": "save-status" });
    this.saveButton = h("button", { type: "button", class: "btn btn-primary", title: "Save (Ctrl+S)", "data-testid": "save-button", "data-writes": "", on: { click: () => this.save() } }, icon("check", { size: 15 }), "Save");
    this.copyButton = h("button", { type: "button", class: "btn", "data-testid": "save-as-copy", "data-writes": "", on: { click: () => this.copy() } }, icon("copy", { size: 15 }), "Save as copy");
    // the container takes no box of its own, so the bar below is sticky against the page itself
    this.container.style.setProperty("display", "contents");
    this.bar = h("div", { class: "savebar out-savebar", role: "region", "aria-label": "Save" }, this.status, h("div", { class: "savebar-actions" }, this.copyButton, this.saveButton));
    this.container.replaceChildren(this.bar);
    this.stopMetrics = trackBarHeight(this.bar);
  }

  shortcut(event) {
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (this.writable && !this.busy) {
        this.save();
      }
    }
  }

  paint() {
    const meta = this.store.get().meta;
    if (this.problem === NAME_PROBLEM && meta.name.trim() !== "") {
      this.problem = "";
    }
    const view = describeSave({ meta, status: this.store.get().status, busy: this.busy, problem: this.problem, writable: this.writable });
    const key = JSON.stringify(view);
    if (key !== this.lastKey) {
      this.lastKey = key;
      this.status.dataset.state = view.state;
      this.status.replaceChildren(...view.parts.map((part) => statusNode(part)).filter(Boolean));
    }
    const locked = !this.writable;
    setBusy(this.saveButton, this.busy);
    this.saveButton.disabled = locked || this.busy;
    this.copyButton.disabled = locked || this.busy || !meta.id;
    this.saveButton.title = locked ? "Not available: this server is read-only" : "Save (Ctrl+S)";
    this.copyButton.title = locked ? "Not available: this server is read-only" : meta.id ? "Save the current draft as a new graph" : "Save the graph once first, then you can save copies of it";
  }

  /** An old failure message goes away as soon as the draft changes. */
  forgetProblem() {
    if (this.problem && !this.busy) {
      this.problem = "";
      this.paint();
    }
  }

  async run(job) {
    this.busy = true;
    this.problem = "";
    this.store.patch("status.saving", true, { clean: true });
    this.paint();
    try {
      return await job();
    } finally {
      this.busy = false;
      this.store.patch("status.saving", false, { clean: true });
      this.paint();
      this.keepFocus();
    }
  }

  /** The conflict banner (and the button that had focus) is gone: keep the keyboard on the save bar. */
  keepFocus() {
    if (document.activeElement === document.body || document.activeElement === null) {
      this.saveButton.focus({ preventScroll: true });
    }
  }

  nameMissing() {
    if (this.store.get().meta.name.trim() !== "") {
      return false;
    }
    this.problem = NAME_PROBLEM;
    this.paint();
    announce(this.problem, { assertive: true });
    if (this.openDetails) {
      this.openDetails({ problem: "name" });
    } else {
      focusTestId("editor-name");
    }
    return true;
  }

  /** Lets a category that is still being typed or checked reach the draft before it is sent. */
  async flushEdits() {
    const active = document.activeElement;
    if (active instanceof HTMLInputElement && active.closest('[data-panel="entries"]')) {
      active.blur(); // the blur commits the typed text
      active.focus({ preventScroll: true });
    }
    await editsSettled();
  }

  async save() {
    if (this.busy || this.nameMissing()) {
      return;
    }
    await this.run(async () => {
      await this.flushEdits();
      try {
        const { definition, created } = await saveGraph({ store: this.store, api: this.api });
        this.banner.hide();
        this.afterSave(definition, created ? "Graph saved." : `Saved as revision ${definition.revision}.`);
      } catch (error) {
        this.failed(error);
      }
    });
  }

  async copy() {
    if (this.busy || this.nameMissing()) {
      return;
    }
    await this.run(async () => {
      await this.flushEdits();
      this.banner.setBusy(true);
      try {
        const definition = await saveCopy({ store: this.store, api: this.api });
        this.banner.hide();
        this.afterSave(definition, `Saved as a copy: ${definition.name}.`);
      } catch (error) {
        this.failed(error);
      } finally {
        this.banner.setBusy(false);
      }
    });
  }

  async reload() {
    await this.run(async () => {
      this.banner.setBusy(true);
      try {
        const definition = await reloadGraph({ store: this.store, api: this.api });
        this.banner.hide();
        this.toast?.info(`Reloaded the saved version (revision ${definition.revision}). Your edits were discarded.`);
        announce("Reloaded the saved version");
      } catch (error) {
        this.failed(error);
      } finally {
        this.banner.setBusy(false);
      }
    });
  }

  afterSave(definition, message) {
    const target = `/graphs/${definition.id}/edit`;
    if (window.location.pathname !== target) {
      window.history.replaceState(window.history.state, "", target);
    }
    this.toast?.success(message);
    announce(message);
  }

  failed(error) {
    if (error?.conflict) {
      this.toast?.clear?.(); // an old "Saved" toast would sit on top of the buttons below
      this.banner.show(conflictInfo(error));
      this.banner.focus();
      return;
    }
    if (error?.status === 404 && this.store.get().meta.id) {
      this.toast?.clear?.();
      this.banner.show({ kind: "deleted" });
      this.banner.focus();
      return;
    }
    if (error?.code === "validation_error") {
      // the form panels put each detail next to its field (they read status.error); the tag tells
      // the chart panel this is not a failed preview
      this.store.patch("status.error", { source: "save", status: error.status, code: error.code, message: error.message, details: error.details ?? [] }, { clean: true });
      this.problem = "Some settings need fixing before this can be saved. Check the highlighted fields.";
      this.toast?.error(this.problem);
      return;
    }
    this.problem = error?.readOnly ? "This server is read-only, so nothing was saved." : plainError(error);
    reportError(error, this.toast);
  }

  dispose() {
    document.removeEventListener("keydown", this.onKey);
    clearInterval(this.timer);
    this.stopMetrics();
    for (const off of this.unsubscribe) {
      off();
    }
    this.container.style.removeProperty("display");
    this.container.replaceChildren();
  }
}

/**
 * Builds the save bar into `container`.
 * @param {HTMLElement} container
 * @param {{store: object, api: object, boot?: object, toast?: object}} ctx
 * @returns {{dispose: () => void}}
 */
export function createSaveBar(container, ctx) {
  const bar = new SaveBar(container, ctx);
  return { dispose: () => bar.dispose() };
}
