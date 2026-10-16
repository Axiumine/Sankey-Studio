// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The conflict banner of the save bar (`conflict-banner`).
 *
 * `createConflictBanner({onReload, onCopy, onMount})` -> `{el, show({kind, revision, updatedAt}), hide(), setBusy(bool), focus()}`;
 * the banner is only in the page while it is shown: `onMount(el)` puts it into the bar, `hide()` removes it.
 * - kind `conflict` (409): the graph was saved elsewhere after this editor loaded it. Two ways out:
 *   `conflict-reload` ("Reload": fetch the saved version, discard my edits) and `conflict-save-copy`
 *   ("Save my version as a copy": a new graph from my edits, the other version is untouched).
 * - kind `deleted` (404): the graph is gone; only the copy button is offered.
 * Nothing is lost silently: the banner says that the edits are not saved.
 */

import { h } from "../../core/dom.js";
import { formatRelative } from "../../core/format.js";
import { icon } from "../../core/icons.js";

function message(info) {
  if (info.kind === "deleted") {
    return "This graph no longer exists: it was deleted after you opened it. Your changes are not saved.";
  }
  const when = info.updatedAt ? `, ${formatRelative(info.updatedAt)}` : "";
  const now = info.revision ? ` It is now at revision ${info.revision}${when}.` : "";
  return `This graph was saved somewhere else after you opened it.${now} Your changes are not saved.`;
}

/**
 * @param {{onReload: () => void, onCopy: () => void}} handlers
 * @returns {object}
 */
export function createConflictBanner({ onReload, onCopy, onMount }) {
  const text = h("p", { class: "out-conflict-text" });
  const reload = h("button", { type: "button", class: "btn", "data-testid": "conflict-reload", on: { click: () => onReload() } }, icon("refresh", { size: 15 }), "Reload (discard my changes)");
  const copy = h("button", { type: "button", class: "btn btn-primary", "data-testid": "conflict-save-copy", on: { click: () => onCopy() } }, icon("copy", { size: 15 }), "Save my version as a copy");
  const el = h(
    "div",
    { class: "notice out-conflict", "data-kind": "warning", role: "alert", "data-testid": "conflict-banner" },
    icon("alert", { size: 18 }),
    h("div", { class: "notice-body" }, text, h("div", { class: "notice-actions" }, reload, copy)),
  );
  return {
    el,
    show(info) {
      text.textContent = message(info);
      reload.hidden = info.kind === "deleted";
      copy.textContent = "";
      copy.append(icon("copy", { size: 15 }), info.kind === "deleted" ? "Save my version as a new graph" : "Save my version as a copy");
      if (!el.isConnected) {
        onMount(el);
      }
    },
    hide() {
      el.remove();
    },
    isVisible: () => el.isConnected,
    setBusy(busy) {
      reload.disabled = busy;
      copy.disabled = busy;
    },
    focus() {
      (reload.hidden ? copy : reload).focus();
    },
  };
}
