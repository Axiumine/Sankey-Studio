// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Puts server validation errors next to the field they are about.
 *
 * The preview and the save answer a 422 with details such as
 *   "body.source.links.2.value: Input should be greater than 0"
 *   "body.source.text.format: Input should be 'auto', 'csv', ..."   (a discriminated union adds its tag)
 *   "body.transform.top_links: Input should be greater than or equal to 1"
 * `parseDetails` turns them into `{path: ["source","links",2,"value"], message}` (prefix and union
 * tag removed, pydantic's "Value error, " noise removed). `createErrorSink` hands each message to
 * the field the panel resolves for that path; whatever has no field goes to the section notice.
 * The store keeps the last failure in `status.error` ({status, code, message, details}).
 */

import { h } from "../../core/dom.js";
import { icon } from "../../core/icons.js";
import { stripBidi } from "../../core/text.js";

const UNION_TAGS = new Set(["manual", "text", "mongo"]);
const NOISE = /^(Value error|Assertion failed),\s*/;

/**
 * Splits an error's details into `{path, message}` entries.
 * @param {{details?: string[]} | null | undefined} error
 * @returns {{path: (string|number)[], message: string}[]}
 */
export function parseDetails(error) {
  return (error?.details ?? []).map((detail) => {
    const cut = detail.indexOf(": ");
    const where = cut > 0 ? detail.slice(0, cut) : "";
    const message = (cut > 0 ? detail.slice(cut + 2) : detail).replace(NOISE, "");
    const parts = where.replace(/^(body|query)\.?/, "").split(".").filter(Boolean);
    const path = parts.map((part) => (/^\d+$/.test(part) ? Number(part) : part));
    if (path[0] === "source" && UNION_TAGS.has(path[1])) {
      path.splice(1, 1);
    }
    return { path, message };
  });
}

/**
 * Creates the sink of one panel.
 * @param {{owns: (path: (string|number)[]) => boolean, resolve: (path: (string|number)[]) => ({setError: (message?: string) => void} | null), codes?: string[], notice: (messages: string[]) => void}} options
 *   `owns` says whether a path belongs to the panel, `resolve` finds the field for it (null = none),
 *   `codes` are error codes without a location the panel shows itself (e.g. "source_error"),
 *   `notice` receives the messages that have no field (an empty list clears it).
 * @returns {{apply: (error: object | null) => number}}  `apply` returns how many problems it showed
 */
export function createErrorSink(options) {
  let active = [];
  const clear = () => {
    for (const field of active) {
      field.setError("");
    }
    active = [];
  };
  return {
    apply(error) {
      clear();
      if (!error) {
        options.notice([]);
        return 0;
      }
      const loose = [];
      const own = parseDetails(error).filter((entry) => options.owns(entry.path));
      for (const entry of own) {
        const field = options.resolve(entry.path);
        if (field) {
          field.setError(entry.message);
          active.push(field);
        } else {
          loose.push(entry.message);
        }
      }
      if (own.length === 0 && options.codes?.includes(error.code)) {
        loose.push(error.message);
      }
      options.notice(loose);
      return active.length + loose.length;
    },
  };
}

/**
 * A section-level error notice: hidden when empty. `set(messages)` replaces the list.
 * @returns {{el: HTMLElement, set: (messages: string[]) => void}}
 */
export function createNotice() {
  const list = h("ul", { class: "ed-notice-list" });
  const el = h("div", { class: "notice ed-notice", role: "alert", "data-kind": "error", hidden: true }, icon("alert", { size: 16 }), h("div", { class: "notice-body" }, list));
  return {
    el,
    set(messages) {
      const clean = Array.from(new Set(messages.map((text) => stripBidi(text))));
      list.replaceChildren(...clean.map((text) => h("li", null, text)));
      el.hidden = clean.length === 0;
    },
  };
}
