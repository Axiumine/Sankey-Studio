// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The edit engine: ONE place that decides where a change of the data goes.
 *
 * `createEditEngine({store, api, toast, ask})` -> `{setCategory, addEntry, reorder, resetOrder}`.
 * Every operation resolves to `{ok: true, where, notice?, undo?}` or to
 * `{ok: false, cancelled?, stale?, message?}` and never throws. Operations run one after another
 * (one promise chain) and each is wrapped in `trackEdit`, so Save waits for them.
 *
 * Where an edit goes (see classify.js):
 * - manual links and pasted text ("draft"): `POST /edits/plan`; the server rewrites the source and the
 *   answer replaces `draft.source` (an ordinary unsaved change);
 * - a file or a MongoDB collection: ALWAYS `plan` first and decide from the answer. `consent:
 *   "granted"` writes at once; `"ask"` opens the consent dialog (`ask`); the dialog's "Update the
 *   source" stores the SERVER's `target_key` in `source.write_back` and writes;
 * - a drag also rewrites the rows; the server's `pins` (colours that would move) join them in the same step;
 * - anything the data cannot hold (aggregate pipelines, refused edits, a read-only server): the
 *   edit stays in the graph as an overlay (`entry_categories`, `extra_links`, `style.node_order`),
 *   with the server's fixed sentence shown once per reason and source.
 * A write to a file or collection is immediate and not part of Save or Undo. An ambiguous failure
 * (network, 409, 5xx) never falls back to an overlay: nothing is changed and the person is told.
 * Undo (draft-level edits) puts back only what ITS edit changed, and only while those parts are still
 * what the edit left (local.js `undoEdit`); otherwise it says so and changes nothing. A new Undo toast
 * replaces the previous one (the toast text repeats, so a second toast would keep the first Undo).
 */

import { announce } from "../../core/a11y.js";
import { trackEdit } from "../output-panel-kit.js";
import { addProblem, applyOverride, noun, overlayAdd, pinsText, snapshotFor, sourceKey, undoEdit, withOrder, withPins, withPref } from "./local.js";
import { classify } from "./classify.js";
import { withCategory } from "../entries/edits.js";
import { plan as askPlan, problemText, write as sendWrite } from "./remote.js";
import { offerHint, uncategorisedCount } from "./hint.js";
import { announceWritten, touchSource } from "./touch.js";
import { stripBidi } from "../../core/text.js";

/** Row reorder after a drag (best effort); false keeps the order in the graph only. */
export const ROW_REORDER = true;

const STALE = "The data changed while saving your edit. Nothing was changed. Try again.";
const ORDER_SAVED = "Node order saved with this graph. Editing the data rows does not move the bars until you press Reset order.";
const ORDER_KEPT = "Order kept in this graph only.";
const NO_UNDO = "Undo is no longer possible: the graph changed after this edit.";

function failure(error) {
  return { ok: false, message: problemText(error) };
}

class EditEngine {
  constructor({ store, api, toast, ask }) {
    this.store = store;
    this.api = api;
    this.toast = toast;
    this.ask = ask;
    this.queue = Promise.resolve();
    this.noticed = new Set();
    this.undoToast = null; // the toast whose Undo is on screen
    this.hinted = false; // the "other entries have no category" toast is offered once per page
  }

  enqueue(job) {
    const run = this.queue.then(job, job);
    this.queue = run.then(
      () => undefined,
      () => undefined,
    );
    return trackEdit(run);
  }

  setCategory(entry, category) {
    return this.enqueue(() => this.run({ op: "set_category", source: entry.source, target: entry.target, category }));
  }

  addEntry(entry) {
    return this.enqueue(() => this.run({ op: "add_entry", source: entry.source, target: entry.target, value: entry.value, category: entry.category ?? null }));
  }

  reorder(order) {
    return this.enqueue(() => this.run({ op: "reorder", order }));
  }

  resetOrder() {
    return this.enqueue(async () => {
      this.store.patch(["draft", "style", "node_order"], []);
      return { ok: true, where: "graph" };
    });
  }

  async run(edit) {
    const draft = this.store.get().draft;
    const kind = classify(draft.source);
    const others = uncategorisedCount(this.store.get().bundle, edit);
    try {
      if (edit.op === "reorder") {
        return await this.reorderFlow(edit, kind, draft);
      }
      if (kind.where === "blocked") {
        return { ok: false, message: kind.message };
      }
      const result = kind.where === "draft" ? await this.viaDraft(edit, draft) : await this.viaSource(edit, draft);
      if (result.ok && result.where !== "graph" && !this.hinted) {
        this.hinted = offerHint(this.toast, others);
      }
      return result;
    } catch (error) {
      return failure(error);
    }
  }

  moved(draft) {
    return this.store.get().draft.source !== draft.source;
  }

  stale() {
    this.toast.warning(STALE);
    return { ok: false, stale: true, message: STALE };
  }

  /** The server's sentence, once per reason and source (silent reasons come without one). */
  noticeOnce(info, draft) {
    if (!info.notice) {
      return;
    }
    const key = `${info.reason}|${sourceKey(draft.source)}`;
    if (!this.noticed.has(key)) {
      this.noticed.add(key);
      this.toast.info(stripBidi(info.notice));
    }
  }

  async viaDraft(edit, draft) {
    const info = await askPlan(this.api, draft, edit);
    if (this.moved(draft)) {
      return this.stale();
    }
    if (info.where !== "draft" || !info.source) {
      return this.overlay(edit, info);
    }
    const before = snapshotFor(draft);
    this.store.batch(() => {
      this.store.patch(["draft", "source"], info.source);
      this.store.patch("draft", (current) => applyOverride(current, info.override, edit));
    });
    this.noticeOnce(info, draft);
    return this.finished(edit, { ok: true, where: "draft" }, before);
  }

  async viaSource(edit, draft) {
    const info = await askPlan(this.api, draft, edit);
    if (this.moved(draft)) {
      return this.stale();
    }
    if (info.where === "graph") {
      return this.overlay(edit, info);
    }
    if (info.consent === "granted") {
      return this.viaWrite(edit, draft, info);
    }
    const choice = await this.ask(info, edit, draft.source);
    if (choice === "accept") {
      const pref = { mode: "source", target: info.target_key };
      this.store.patch(["draft", "source", "write_back"], pref);
      return this.viaWrite(edit, withPref(this.store.get().draft, pref), info);
    }
    if (choice === "never") {
      this.store.patch(["draft", "source", "write_back"], { mode: "graph", target: info.target_key });
    }
    return choice === "never" || choice === "decline" ? this.overlay(edit, info) : { ok: false, cancelled: true };
  }

  async viaWrite(edit, draft, info) {
    const out = await sendWrite(this.api, draft, edit);
    if (out.where === "graph") {
      return this.overlay(edit, out);
    }
    this.store.batch(() => {
      this.store.patch("draft", (current) => applyOverride(current, out.override, edit));
      if (out.source) {
        this.store.patch(["draft", "source"], out.source);
      } else {
        touchSource(this.store);
      }
    });
    announceWritten(draft.source.path);
    const verb = edit.op === "add_entry" ? "Added" : "Updated";
    this.toast.success(`${verb} ${noun(out.where, out.changed)} in ${stripBidi(info.target ?? out.target ?? "the source")}.`);
    return { ok: true, where: out.where, written: true };
  }

  /** Keeps the edit in the graph (the server checks the candidate first; a 422 is the answer). */
  async overlay(edit, info) {
    const draft = this.store.get().draft;
    const adding = edit.op === "add_entry";
    const problem = adding ? addProblem(draft) : null;
    if (problem) {
      return { ok: false, message: problem };
    }
    const apply = (current) => (adding ? overlayAdd(current, edit) : withCategory(current, edit, edit.category));
    await this.api.post("/entries", apply(draft), { query: { limit: 1 }, quiet: true });
    if (this.moved(draft)) {
      return this.stale();
    }
    const before = snapshotFor(draft);
    this.store.patch("draft", apply);
    this.noticeOnce(info, draft);
    return this.finished(edit, { ok: true, where: "graph", notice: info.notice ?? undefined }, before);
  }

  /** The Undo of the edit that turned `before` into what the draft is now. */
  undoer(before) {
    const after = snapshotFor(this.store.get().draft);
    return () => {
      const next = undoEdit(this.store.get().draft, before, after);
      if (next === null) {
        this.toast.info(NO_UNDO);
        return;
      }
      this.store.patch("draft", () => next);
    };
  }

  /** Shows a success toast with Undo; the previous Undo toast goes away first. */
  offerUndo(text, undo) {
    this.undoToast?.dismiss();
    this.undoToast = this.toast.success(text, { action: { label: "Undo", onClick: undo } });
  }

  /** Announces, offers Undo for an added entry, and returns the result. */
  finished(edit, result, before) {
    const undo = this.undoer(before);
    if (edit.op === "add_entry") {
      announce("Entry added");
      this.offerUndo("Entry added.", undo);
    } else if (result.where === "draft") {
      announce("Category saved in your data");
    }
    return { ...result, undo };
  }

  async reorderFlow(edit, kind, draft) {
    let rows = null;
    let pins = null;
    let kept = false;
    if (ROW_REORDER && (kind.where === "draft" || kind.where === "file")) {
      try {
        const outcome = await this.reorderRows(edit, draft);
        rows = outcome.rows;
        pins = outcome.pins ?? null;
        kept = outcome.kept;
      } catch {
        kept = kind.where === "file"; // the order is stored anyway; only a file write is worth a word
      }
    }
    const before = snapshotFor(this.store.get().draft);
    this.store.batch(() => {
      if (rows) {
        this.store.patch(["draft", "source"], rows);
      }
      this.store.patch("draft", (current) => withOrder(withPins(current, pins), edit.order));
    });
    const undo = this.undoer(before);
    this.offerUndo(kept ? ORDER_KEPT : ORDER_SAVED, undo);
    const pinned = pinsText(pins);
    if (pinned) {
      this.toast.info(pinned);
    }
    return { ok: true, where: "graph", undo };
  }

  /** Best-effort row reorder: the new source (and the colour pins that keep the chart's colours) for a draft-held or file source, `rows: null` when nothing moved. */
  async reorderRows(edit, draft) {
    const info = await askPlan(this.api, draft, edit);
    if (this.moved(draft)) {
      return { rows: null, kept: false };
    }
    if (info.where === "draft" && info.source) {
      return { rows: info.source, pins: info.pins, kept: false };
    }
    if (info.where === "file" && info.consent === "granted") {
      const out = await sendWrite(this.api, draft, edit);
      if (out.where === "file") {
        announceWritten(draft.source.path);
        return { rows: out.source ?? null, pins: out.pins, kept: false };
      }
      return { rows: null, kept: true };
    }
    this.noticeOnce(info, draft);
    return { rows: null, kept: false };
  }
}

/**
 * Creates an engine.
 * @param {{store: object, api: object, toast: object, ask: (plan: object, edit: object, source: object) => Promise<string | null>}} deps
 * @returns {EditEngine}
 */
export function createEditEngine(deps) {
  return new EditEngine(deps);
}
