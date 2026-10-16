// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Limits section: the four number settings (links per graph, links drawn, upload size, MongoDB
 * timeout), each with its allowed range as a hint and an inline error from the early checks or
 * from a 422 of the server.
 */

import { h } from "../core/dom.js";
import { formatNumber } from "../core/format.js";
import { numberInput } from "../core/form.js";
import { LIMITS } from "./constants.js";
import { boundField, section } from "./ui.js";

function hintFor(spec) {
  const range = `${formatNumber(spec.min)} to ${formatNumber(spec.max)} (default ${formatNumber(spec.def)}).`;
  return `Allowed: ${range} ${spec.help}`;
}

function limitField(store, spec) {
  const id = `limits.${spec.key}`;
  const control = numberInput({
    value: store.draft.limits[spec.key],
    min: spec.min,
    max: spec.max,
    step: 1,
    inputmode: "numeric",
    "data-testid": spec.testid,
    on: {
      input: () => {
        store.draft.limits[spec.key] = control.value;
        store.edit(id);
      },
    },
  });
  return boundField(store, id, { label: spec.label, control, hint: hintFor(spec) });
}

/**
 * Builds the section.
 * @param {import("./store.js").SettingsStore} store
 * @returns {{el: HTMLElement, sync: () => void}}
 */
export function buildLimits(store) {
  const fields = LIMITS.map((spec) => limitField(store, spec));
  const el = section({
    id: "settings-limits",
    title: "Limits",
    text: "Keep big files and slow databases from overwhelming the app. Changes apply as soon as you save.",
    body: [h("div", { class: "settings-limits" }, fields.map((item) => item.el))],
  });
  return {
    el,
    sync() {
      for (const item of fields) {
        item.sync();
      }
      for (const [index, spec] of LIMITS.entries()) {
        const value = store.draft.limits[spec.key];
        if (fields[index].control.value !== value) {
          fields[index].control.value = value;
        }
      }
    },
  };
}
