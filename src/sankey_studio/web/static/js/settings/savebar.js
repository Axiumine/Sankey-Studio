// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The sticky save bar: what state the form is in ("All changes saved", "Unsaved changes",
 * "Saving...", "Read-only"), a "Discard changes" button (only while there is something to
 * discard) and the global "Save settings" button (`data-testid="settings-save"`).
 *
 * The save button is inert only while a save is running (`aria-disabled`, still focusable) or on a
 * read-only server (`disabled`), so a double click can never send two requests. The status is a
 * polite live region.
 */

import { canWrite } from "../core/boot.js";
import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";

const READ_ONLY_TITLE = "Not available: this server is read-only";

function stateOf(store) {
  if (!canWrite()) {
    return ["readonly", "Read-only: settings cannot be changed on this server."];
  }
  if (store.saving) {
    return ["saving", "Saving..."];
  }
  return store.isDirty() ? ["dirty", "You have unsaved changes."] : ["clean", "All changes saved."];
}

/**
 * Builds the bar.
 * @param {import("./store.js").SettingsStore} store
 * @param {{save: () => void, discard: () => void}} actions
 * @returns {{el: HTMLElement, sync: () => void, saveButton: HTMLButtonElement}}
 */
export function buildSavebar(store, actions) {
  const status = h("p", { class: "savebar-status", role: "status", "data-testid": "settings-save-status" });
  const dot = h("span", { class: "status-dot", "aria-hidden": "true" });
  const discard = h("button", { type: "button", class: "btn", hidden: true, "data-testid": "settings-discard", on: { click: actions.discard } }, "Discard changes");
  const saveButton = h("button", { type: "button", class: "btn btn-primary", "data-testid": "settings-save", on: { click: actions.save } }, icon("check"), "Save settings");
  const el = h(
    "div",
    { class: "savebar", role: "region", "aria-label": "Save settings" },
    h("div", { class: "savebar-state" }, dot, status),
    h("div", { class: "savebar-actions" }, discard, saveButton),
  );
  return {
    el,
    saveButton,
    sync() {
      const writable = canWrite();
      const [state, text] = stateOf(store);
      if (status.textContent !== text) {
        status.textContent = text;
      }
      el.dataset.state = state;
      discard.hidden = state !== "dirty" && state !== "saving";
      discard.disabled = store.saving;
      // not `disabled` while saving: a disabled button drops keyboard focus, and giving it back
      // makes the browser scroll to the bar's place in the page flow instead of where it sticks
      saveButton.classList.toggle("is-busy", store.saving);
      saveButton.toggleAttribute("aria-busy", store.saving);
      if (store.saving) {
        saveButton.setAttribute("aria-disabled", "true");
      } else {
        saveButton.removeAttribute("aria-disabled");
      }
      saveButton.disabled = !writable;
      saveButton.title = writable ? "" : READ_ONLY_TITLE;
    },
  };
}
