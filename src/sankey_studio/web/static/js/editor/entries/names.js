// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The category suggestions of the entries table (the `<datalist>` of every category input).
 *
 * `createCategoryNames({store, datalist})` -> `{known(), paint(), add(name)}`
 * - `known()`: the categories the last preview reports (`bundle.category_names`);
 * - `paint()`: fills the datalist with them plus the ones just typed that the preview has not seen yet;
 * - `add(name)`: remembers a category that was just typed or ruled and repaints.
 */

import { h } from "../../core/dom.js";

/**
 * @param {{store: object, datalist: HTMLElement}} options
 * @returns {{known: () => string[], paint: () => void, add: (name: string) => void}}
 */
export function createCategoryNames({ store, datalist }) {
  const local = new Set();
  const known = () => store.get().bundle?.category_names ?? [];
  const paint = () => {
    const names = known();
    const lower = new Set(names.map((name) => name.toLowerCase()));
    for (const name of Array.from(local)) {
      if (lower.has(name.toLowerCase())) {
        local.delete(name);
      }
    }
    datalist.replaceChildren(...[...names, ...local].map((name) => h("option", { value: name })));
  };
  return {
    known,
    paint,
    add(name) {
      local.add(name);
      paint();
    },
  };
}
