// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The gear next to the page title: a menu with "Edit details" and "Change data source".
 *
 * `mountTitleMenu({store, switcher, settings, openDetails})` puts a `core/menu.js` menu right
 * after the `<h1>` of the page (a SIBLING of the heading: `setHeading` rewrites the heading's text
 * and would remove a child) and returns the disposer. The items open modal dialogs; later features
 * append their entries to `itemsFor` in this file only.
 * The gear shows a problem dot while the server rejected the name, description or tags (a failed
 * preview or save), so the person knows where to look.
 * Test ids: graph-settings-button, graph-settings-menu, graph-settings-details,
 * graph-settings-source.
 */

import { createMenu } from "../core/menu.js";
import { parseDetails } from "./meta/errors.js";
import { openChangeSourceDialog } from "./source/change-dialog.js";

const LABEL = "Graph settings";
const DETAIL_FIELDS = new Set(["name", "description", "tags"]);

/** How many validation problems of the last failed preview or save are about the graph details. */
function detailsProblemCount(error) {
  return parseDetails(error).filter((entry) => DETAIL_FIELDS.has(entry.path[0])).length;
}

function itemsFor({ store, switcher, settings, openDetails }) {
  return [
    { id: "details", label: "Edit details", icon: "edit", testid: "graph-settings-details", onSelect: () => openDetails() },
    {
      id: "source",
      label: "Change data source",
      icon: "database",
      testid: "graph-settings-source",
      onSelect: () => openChangeSourceDialog({ store, switcher, settings }),
    },
  ];
}

/**
 * Mounts the menu.
 * @param {{store: object, switcher: object, settings: object | null, openDetails: (options?: object) => unknown}} options
 * @returns {() => void} the disposer
 */
export function mountTitleMenu(options) {
  const heading = document.querySelector("#main h1");
  const menu = createMenu({
    label: LABEL,
    icon: "settings",
    testid: "graph-settings-button",
    panelTestid: "graph-settings-menu",
    items: itemsFor(options),
  });
  heading?.after(menu.el);
  const off = options.store.subscribe((count) => menu.setBadge(count, LABEL), {
    select: (state) => detailsProblemCount(state.status.error),
    immediate: true,
  });
  return () => {
    off();
    menu.dispose();
  };
}
