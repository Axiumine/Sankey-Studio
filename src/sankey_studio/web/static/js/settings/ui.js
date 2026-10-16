// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Small building blocks shared by the sections of the settings page.
 *
 * - `section({id, title, text, body})`: a titled block (`<section aria-labelledby>`): the heading
 *   and a short explanation on the left from 900px up, the controls in a card on the right. The
 *   first page that is assembled from these also gets the "On this page" list (toc.js).
 * - `boundField(store, id, parts)`: a labelled control (core/form.js `field`) tied to a store field
 *   id: it is registered for the error summary, marks itself touched on blur and shows
 *   `store.message(id)` when `sync()` runs.
 * - `resultLine()`: an icon and a sentence for the outcome of a probe (`show(kind, text)`).
 */

import { h } from "../core/dom.js";
import { field } from "../core/form.js";
import { icon } from "../core/icons.js";
import { ensureToc } from "./toc.js";

/**
 * @param {{id: string, title: string, text: string, body: unknown[]}} options
 * @returns {HTMLElement}
 */
export function section({ id, title, text, body }) {
  const titleId = `${id}-title`;
  const el = h(
    "section",
    { class: "settings-section", id, "aria-labelledby": titleId },
    h("div", { class: "settings-section-head" }, h("h2", { id: titleId }, title), h("p", null, text)),
    h("div", { class: "card" }, h("div", { class: "card-body stack" }, body)),
  );
  // the page is assembled right after this call: the list of sections is added once it is there
  queueMicrotask(() => ensureToc(el.closest(".settings")));
  return el;
}

/**
 * Wraps a control with its label, hint and error line and ties it to the store.
 * @param {import("./store.js").SettingsStore} store
 * @param {string} id  field id (see validate.js)
 * @param {{label: string, control: HTMLElement, hint?: string}} parts
 * @returns {{el: HTMLElement, control: HTMLElement, field: ReturnType<typeof field>, sync: () => void}}
 */
export function boundField(store, id, parts) {
  const built = field(parts);
  store.register(id, parts.control);
  parts.control.addEventListener("blur", () => store.touch(id));
  return {
    el: built.el,
    control: parts.control,
    field: built,
    sync: () => built.setError(store.message(id)),
  };
}

/** Milliseconds a probe may run before its line says that it can take a while. */
const SLOW_AFTER_MS = 1500;

const RESULT_ICONS = { ok: "check-circle", error: "x-circle", busy: "refresh", info: "info" };

/**
 * A line that tells the outcome of a probe. `show("ok"|"error"|"busy"|"info", text, extra)` fills
 * it (`extra` is an optional node appended after the text); `clear()` empties and hides it. It is
 * not a live region: the toast that goes with the outcome is what screen readers hear.
 *
 * A probe takes a ticket with `begin()` before it starts and drops its answer when
 * `isCurrent(ticket)` is false: `clear()` (the form was edited, the row was deleted) and a newer
 * `begin()` void every earlier ticket, so a slow answer never describes values that are no longer
 * in the form. The same two calls abort the request of the voided ticket (`signal()` is the one to
 * pass to the API call), so a stale probe stops holding one of the browser's connections.
 *
 * `busy(text, slowText)` shows the "working" line and swaps in `slowText` if no answer (`show` or
 * `clear`) has come after `SLOW_AFTER_MS`: the fast case never flashes the longer sentence.
 * @param {{testid?: string}} [options]
 * @returns {{el: HTMLElement, show: (kind: string, text: string, extra?: Node) => void,
 *   busy: (text: string, slowText: string) => void, clear: () => void, begin: () => number,
 *   isCurrent: (ticket: number) => boolean, signal: () => AbortSignal | undefined, revision: number}}
 */
export function resultLine(options = {}) {
  const el = h("p", { class: "result-line", hidden: true, "data-testid": options.testid ?? null });
  let ticket = 0;
  let slowTimer = 0;
  let controller = null;
  const paint = (kind, text, extra) => {
    el.dataset.kind = kind;
    el.hidden = false;
    el.replaceChildren(
      h("span", { class: "result-icon" }, icon(RESULT_ICONS[kind] ?? "info", { size: 16 })),
      h("span", { class: "result-text" }, text, extra ?? null),
    );
  };
  return {
    el,
    revision: 0,
    begin() {
      controller?.abort();
      controller = new AbortController();
      return (ticket += 1);
    },
    isCurrent: (value) => value === ticket,
    signal: () => controller?.signal,
    show(kind, text, extra) {
      clearTimeout(slowTimer);
      paint(kind, text, extra);
    },
    busy(text, slowText) {
      clearTimeout(slowTimer);
      paint("busy", text);
      slowTimer = setTimeout(() => paint("busy", slowText), SLOW_AFTER_MS);
    },
    clear() {
      clearTimeout(slowTimer);
      controller?.abort();
      controller = null;
      ticket += 1;
      el.hidden = true;
      el.removeAttribute("data-kind");
      el.replaceChildren();
    },
  };
}
