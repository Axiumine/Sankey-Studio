// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Commits category edits of the entries table into the editor store.
 *
 * An edit is optimistic on screen and checked by the server before it reaches the draft:
 *   1. the typed text is checked locally (reserved "Other"/"Uncategorized", length, control
 *      characters, the 20,000 single-entry limit) for an instant, plain answer;
 *   2. the row shows the new category at once (`ui.applied`);
 *   3. `edits.setCategory` (the edit engine, ../edits/) asks the server where the category goes: into
 *      the data (manual links, pasted text, a file or a collection, the last two only after the
 *      person agreed in the consent dialog) or, when the data cannot hold it, into this graph
 *      (`transform.entry_categories`). On success the draft changes (so the preview, the donut and
 *      "unsaved changes" follow); on a refusal the row is rolled back (`ui.rejected`) and nothing
 *      was written; Cancel in the dialog or an outdated edit rolls back without a message.
 * Edits run one after another in the order they were made, each against the draft as it is when its
 * turn comes, so quick Enter, Enter, Enter never overwrite each other (and raise one dialog).
 *
 * `createCommitter({api, store, ui})` -> `{commitEntry(entry, text), addRule(query, text), undoRule(rule)}`. `ui` is `{known(): string[], row(entry), applied(entry, patch), pending(entry, bool),
 * rejected(entry, message, previous)}`.
 */

import { editsFor } from "../edits/index.js";
import { problemText } from "../edits/remote.js";
import { trackEdit } from "../output-panel-kit.js";
import {
  canonicalCategory,
  checkCategory,
  isManual,
  limitProblem,
  ruleFor,
  ruleProblem,
  withRule,
  withoutRuleLike,
} from "./edits.js";

/** One sentence for a failed validation request. */
export const editProblem = problemText;

function keyOf(entry) {
  return `${entry.source}\u0000${entry.target}`;
}

class Committer {
  constructor({ api, store, ui, edits }) {
    this.api = api;
    this.store = store;
    this.ui = ui;
    this.edits = edits ?? editsFor({ api, store });
    this.queue = Promise.resolve();
    this.inflight = new Map();
  }

  enqueue(job) {
    const run = this.queue.then(job, job);
    this.queue = run.then(
      () => undefined,
      () => undefined,
    );
    return run;
  }

  /** Asks the server whether `candidate` is a valid draft (cheap: one row is asked for). */
  validate(candidate) {
    return this.api.post("/entries", candidate, { query: { limit: 1 }, quiet: true });
  }

  commitEntry(entry, text) {
    const check = checkCategory(text);
    const previous = this.ui.row(entry);
    if (!check.ok) {
      this.ui.rejected(entry, check.message, previous);
      return Promise.resolve(false);
    }
    const category = check.value === null ? null : canonicalCategory(check.value, this.ui.known());
    const key = keyOf(entry);
    if (this.inflight.has(key) ? this.inflight.get(key) === category : previous?.category === category) {
      this.ui.applied(entry, { category });
      return Promise.resolve(true);
    }
    const problem = limitProblem(this.store.get().draft, entry);
    if (problem) {
      this.ui.rejected(entry, problem, previous);
      return Promise.resolve(false);
    }
    this.inflight.set(key, category);
    this.ui.applied(entry, { category, mixed: false, overridden: !isManual(this.store.get().draft) });
    this.ui.pending(entry, true);
    return trackEdit(this.enqueue(() => this.runEntry({ entry, category, previous }, key)));
  }

  async runEntry({ entry, category, previous }, key) {
    try {
      const result = await this.edits.setCategory(entry, category);
      if (!result.ok) {
        this.refused(entry, result, previous);
        return false;
      }
      this.ui.applied(entry, { category }, { confirmed: true });
      return true;
    } finally {
      this.inflight.delete(key);
      this.ui.pending(entry, false);
    }
  }

  /** A cancelled or outdated edit rolls the row back quietly; any other refusal says why. */
  refused(entry, result, previous) {
    if (result.cancelled || result.stale) {
      const row = previous ?? {};
      this.ui.applied(entry, { category: row.category ?? null, mixed: row.mixed ?? false, overridden: row.overridden ?? false });
      return;
    }
    this.ui.rejected(entry, result.message ?? "The change could not be checked.", previous);
  }

  /**
   * Adds the rule "names containing `query` get this category".
   * @returns {Promise<{ok: boolean, message?: string, rule?: object}>}
   */
  addRule(query, text) {
    const check = checkCategory(text);
    if (!check.ok) {
      return Promise.resolve({ ok: false, message: check.message });
    }
    if (check.value === null) {
      return Promise.resolve({ ok: false, message: "Type the category these entries should get." });
    }
    const rule = ruleFor(query, canonicalCategory(check.value, this.ui.known()));
    const problem = ruleProblem(this.store.get().draft, rule);
    if (problem) {
      return Promise.resolve({ ok: false, message: problem });
    }
    return trackEdit(this.enqueue(() => this.runRule(rule)));
  }

  async runRule(rule) {
    try {
      await this.validate(withRule(this.store.get().draft, rule));
      this.store.patch("draft", (draft) => withRule(draft, rule));
      return { ok: true, rule };
    } catch (error) {
      return { ok: false, message: editProblem(error) };
    }
  }

  /** Takes back a rule that `addRule` just added. */
  undoRule(rule) {
    this.store.patch("draft", (draft) => withoutRuleLike(draft, rule));
  }
}

/**
 * Creates the committer.
 * @param {{api: object, store: object, ui: object}} deps
 * @returns {Committer}
 */
export function createCommitter(deps) {
  return new Committer(deps);
}
