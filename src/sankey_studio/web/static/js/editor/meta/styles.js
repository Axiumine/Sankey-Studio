/**
 * Loads the stylesheet of the editor input panels (`/static/css/pages-editor.css`) once and
 * resolves when it is applied (or failed: the editor then looks plain but still works), so the
 * page never paints unstyled and nothing shifts when the sheet arrives.
 */

import { ensureStylesheet } from "../../core/stylesheet.js";

const HREF = "/static/css/pages-editor.css";

/**
 * Loads the editor stylesheet (once).
 * @returns {Promise<void>}
 */
export function ensureEditorStyles() {
  return ensureStylesheet(HREF);
}
