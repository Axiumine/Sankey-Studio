// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Publishes the height of the save bar as `--out-savebar-h` on <html> while the bar exists.
 *
 * The bar is sticky at the bottom of the window and covers whatever is behind it, and its height
 * changes (a conflict banner, a long status sentence, a narrow window that wraps the buttons). The
 * stylesheet reads the variable to keep the sticky preview pane above the bar and to give focus
 * scrolling (`scroll-padding-bottom`) the right margin, so a button reached with Tab is never left
 * hidden under the bar.
 */

const PROPERTY = "--out-savebar-h";

/**
 * @param {HTMLElement} bar  the `.savebar` element
 * @returns {() => void} stop tracking and remove the variable
 */
export function trackBarHeight(bar) {
  const root = document.documentElement;
  const publish = () => {
    const height = Math.ceil(bar.getBoundingClientRect().height);
    if (height > 0) {
      root.style.setProperty(PROPERTY, `${height}px`);
    }
  };
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(publish) : null;
  observer?.observe(bar);
  publish();
  return () => {
    observer?.disconnect();
    root.style.removeProperty(PROPERTY);
  };
}
