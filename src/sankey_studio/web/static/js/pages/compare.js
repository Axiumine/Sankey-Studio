// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Compare page: up to 12 saved graphs side by side with one shared category colour map, a Sankey /
 * donut switch per card, summary tables, and lazy chart drawing. Everything lives in js/compare/.
 */

import { boot, pageActions, pageRoot } from "../core/boot.js";
import { mount } from "../core/dom.js";
import { errorState } from "../core/states.js";
import { startCompare } from "../compare/controller.js";
import { ensureStyles } from "../library/styles.js";

const { ids, graphs, missing } = boot();

await ensureStyles(new URL("../../css/pages-compare.css", import.meta.url).href);
if (Array.isArray(ids) && Array.isArray(graphs)) {
  const gone = Array.isArray(missing) ? missing.filter((id) => typeof id === "string") : [];
  startCompare({ ids, graphs, missing: gone, root: pageRoot(), actionsRoot: pageActions() });
} else {
  mount(pageRoot(), errorState({ title: "Nothing to compare", message: "The page did not receive any graphs. Pick two or more in the library." }));
}
