// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/* Theme bootstrap: a classic (non-module) script loaded synchronously in <head>, before the first
 * paint, so the right theme never flashes. The server renders <html data-theme="system|light|dark">
 * from the stored settings, so a browser that never visited before already starts right; this
 * script only lets a cached device choice override it:
 *
 *   data-theme-source="server"  writes are allowed: the stored theme is the truth, nothing to do.
 *   data-theme-source="device"  read-only server (nothing can be saved): the theme chosen on this
 *                               device (localStorage "sankey-studio.theme") wins when it exists.
 *
 * core/theme.js owns everything else (switching, persisting, caching). Storage may be unavailable
 * (private window, blocked site data): every access is guarded and the server's theme then stays.
 */
(() => {
  const root = document.documentElement;
  const valid = (value) => value === "light" || value === "dark" || value === "system";
  if (!valid(root.dataset.theme)) {
    root.dataset.theme = "system";
  }
  if (root.dataset.themeSource !== "device") {
    return;
  }
  try {
    const stored = window.localStorage.getItem("sankey-studio.theme");
    if (valid(stored)) {
      root.dataset.theme = stored;
    }
  } catch {
    // keep the theme the server rendered
  }
})();
