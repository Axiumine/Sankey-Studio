// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Page style sheets of the library, viewer and compare pages (css/pages-NAME.css below the static
 * root): the shared loader of `core/stylesheet.js` under the name those pages use. It resolves when
 * the sheet is applied or has failed, so a page never paints unstyled.
 */

export { ensureStylesheet as ensureStyles } from "../core/stylesheet.js";
