/**
 * Commits category edits of the entries table into the editor store.
 *
 * An edit is optimistic on screen and checked by the server before it reaches the draft:
 *   1. the typed text is checked locally (reserved "Other"/"Uncategorized", length, control
 *      characters, the 20,000 single-entry limit) for an instant, plain answer;
 *   2. the row shows the new category at once (`ui.applied`);
 *   3. `POST /entries?limit=1` with the candidate draft asks the server whether the draft is still
 *      valid; on 200 the edit is written to `store.draft` (so the preview, the donut and "unsaved
 *      changes" follow), on any failure the row is rolled back (`ui.rejected`) and nothing was
 *      written. An invalid draft therefore never reaches the live preview.
 * Edits run one after another in the order they were made, each against the draft as it is when its
 * turn comes, so quick Enter, Enter, Enter never overwrite each other.
 *
 * `createCommitter({api, store, ui})` -> `{commitEntry(entry, text), addRule(query, text), undoRule(rule)}`. `ui` is `{known(): string[], row(entry), applied(entry, patch), pending(entry, bool),
 * rejected(entry, message, previous)}`.
 */

import { fieldErrors } from "../../core/api.js";
import { trackEdit } from "../output-panel-kit.js";
import {
  canonicalCategory,
  checkCategory,
  isManual,
  limitProblem,
  ruleFor,
  ruleProblem,
  withCategory,
  withRule,
  withoutRuleLike,
} from "./edits.js";

const NOISE = /^(Value error|Assertion failed),\s*/;

/**
 * One sentence for a failed validation request.
 * @param {unknown} error
 * @returns {string}
 */
export function editProblem(error) {
  const first = error?.details?.length ? fieldErrors(error)[0] : null;
  if (first?.message) {
    return `The server did not accept that: ${first.message.replace(NOISE, "")}`;
  }
  return error?.friendly ?? error?.message ?? "The change could not be checked.";
}

function keyOf(entry) {
  return `${entry.source}\u0000${entry.target}`;
}

class Committer {
  constructor({ api, store, ui }) {
    this.api = api;
    this.store = store;
    this.ui = ui;
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
      await this.validate(withCategory(this.store.get().draft, entry, category));
      this.store.patch("draft", (draft) => withCategory(draft, entry, category));
      this.ui.applied(entry, { category }, { confirmed: true });
      return true;
    } catch (error) {
      this.ui.rejected(entry, editProblem(error), previous);
      return false;
    } finally {
      this.inflight.delete(key);
      this.ui.pending(entry, false);
    }
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
