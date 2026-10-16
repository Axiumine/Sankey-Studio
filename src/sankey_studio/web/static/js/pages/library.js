// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Library page: search, tag filter, sort and paging over the saved graphs, cards with open / edit /
 * duplicate / delete, bundle import and export, and a selection for the compare page.
 * Everything lives in js/library/; the page data is the boot block (core/boot.js).
 */

import { pageActions } from "../core/boot.js";
import { startLibrary } from "../library/controller.js";
import { ensureStyles } from "../library/styles.js";

await ensureStyles(new URL("../../css/pages-library.css", import.meta.url).href);
startLibrary({ actionsRoot: pageActions() });
