// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Telling a fresh page from a replayed one.
 *
 * The server embeds the data a page starts from (the newest graphs, the graph summary) in the HTML.
 * When the person comes back with the browser's Back or Forward button, the browser may replay the
 * HTML it kept (navigation type `back_forward`, no request) or hand back the whole frozen page from
 * its back/forward cache (`pageshow` with `persisted`). In both cases that embedded data can be
 * older than what the person just did (duplicated or edited a graph in between), so the pages ask
 * the API again instead of trusting it.
 */

/**
 * True when this document was loaded by the Back or Forward button, so its embedded data may be
 * stale. False when the browser cannot say.
 * @returns {boolean}
 */
export function reachedByHistory() {
  try {
    return performance.getEntriesByType("navigation")[0]?.type === "back_forward";
  } catch {
    return false;
  }
}

/**
 * Calls `callback` when the browser restores this page, frozen as it was, from its back/forward cache.
 * @param {() => void} callback
 */
export function onRestored(callback) {
  addEventListener("pageshow", (event) => {
    if (event.persisted) {
      callback();
    }
  });
}
