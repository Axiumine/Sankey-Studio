/**
 * `editsFor(ctx)`: the edit engine of an editor page.
 *
 * One engine per store (a WeakMap), created on first use from `ctx.store`, `ctx.api` and
 * `ctx.toast` (the shared toast when the caller has none), so every panel that asks gets the SAME
 * queue and the same page-session memory. The consent dialog is wired here.
 * `forgetChoices()` drops the plain "Keep in this graph" answers of this page ("Ask me again").
 */

import { toast as sharedToast } from "../../core/toast.js";
import { askConsent, choices } from "./consent.js";
import { createEditEngine } from "./engine.js";

const engines = new WeakMap();

/**
 * @param {{store: object, api: object, toast?: object}} ctx
 * @returns {ReturnType<typeof createEditEngine>}
 */
export function editsFor(ctx) {
  let engine = engines.get(ctx.store);
  if (!engine) {
    engine = createEditEngine({ store: ctx.store, api: ctx.api, toast: ctx.toast ?? sharedToast, ask: askConsent });
    engines.set(ctx.store, engine);
  }
  return engine;
}

/** Forgets the answers remembered for this page session. */
export function forgetChoices() {
  choices.forget();
}
