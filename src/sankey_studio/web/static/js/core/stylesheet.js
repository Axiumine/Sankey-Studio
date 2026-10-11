/**
 * Loads a stylesheet on demand, once per page. The promise resolves when the sheet is applied (or
 * failed: the page then looks plain but still works), so a panel that awaits it never paints
 * unstyled and nothing shifts when the sheet arrives. A `<link>` already in the page is reused.
 */

import { h } from "./dom.js";

/** @type {Map<string, Promise<void>>} */
const loads = new Map();

/**
 * @param {string} href
 * @returns {Promise<void>}
 */
function load(href) {
  const existing = document.querySelector(`link[rel="stylesheet"][href="${CSS.escape(href)}"]`);
  const link = existing ?? h("link", { rel: "stylesheet", href });
  return new Promise((resolve) => {
    if (existing?.sheet) {
      resolve();
      return;
    }
    link.addEventListener("load", () => resolve(), { once: true });
    link.addEventListener("error", () => resolve(), { once: true });
    if (!existing) {
      document.head.append(link);
    }
  });
}

/**
 * Loads `href` as a stylesheet (once) and resolves when it is applied or has failed.
 * @param {string} href  the same-origin path of the stylesheet
 * @returns {Promise<void>}
 */
export function ensureStylesheet(href) {
  let pending = loads.get(href);
  if (!pending) {
    pending = load(href);
    loads.set(href, pending);
  }
  return pending;
}
