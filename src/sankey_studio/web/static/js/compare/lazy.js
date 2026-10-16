// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Lazy drawing: a callback runs once when an element comes near the viewport
 * (IntersectionObserver), so a grid of 12 charts draws what is on screen first. Without
 * IntersectionObserver every element is drawn at once.
 */

/**
 * @param {{rootMargin?: string}} [options]
 * @returns {{watch: (el: Element, draw: () => void) => void, unwatch: (el: Element) => void, disconnect: () => void}}
 */
export function createLazyDrawer(options = {}) {
  const jobs = new Map();
  const observer = typeof IntersectionObserver === "undefined"
    ? null
    : new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && jobs.has(entry.target)) {
            const run = jobs.get(entry.target);
            jobs.delete(entry.target);
            observer.unobserve(entry.target);
            run();
          }
        }
      },
      { rootMargin: options.rootMargin ?? "300px 0px" },
    );
  return {
    watch(el, draw) {
      if (!observer) {
        draw();
        return;
      }
      jobs.set(el, draw);
      observer.observe(el);
    },
    unwatch(el) {
      jobs.delete(el);
      observer?.unobserve(el);
    },
    disconnect() {
      jobs.clear();
      observer?.disconnect();
    },
  };
}
