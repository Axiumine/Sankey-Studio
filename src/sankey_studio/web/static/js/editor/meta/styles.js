// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Loads the stylesheet of the editor input panels (`css/pages-editor.css`) once and
 * resolves when it is applied (or failed: the editor then looks plain but still works), so the
 * page never paints unstyled and nothing shifts when the sheet arrives.
 */

import { ensureStylesheet } from "../../core/stylesheet.js";

const HREF = new URL("../../../css/pages-editor.css", import.meta.url).href;

/**
 * Loads the editor stylesheet (once).
 * @returns {Promise<void>}
 */
export function ensureEditorStyles() {
  return ensureStylesheet(HREF);
}
