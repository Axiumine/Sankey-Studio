// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * "On this page": the short list of the page's sections that sits in the free column right of the
 * settings from 1280px up (the layout is in css/pages/settings.css; below that width the list is
 * hidden and the sections simply follow each other).
 *
 * It is added by `ui.js section()` once the page is assembled (`ensureToc`), built from the
 * sections that are there (id and heading text), and follows the reading position: the link of
 * the section under the top of the window carries `aria-current="location"`. Links are plain
 * in-page anchors, so they work with the keyboard and without any script in the list itself.
 */

import { h } from "../core/dom.js";
import { stripBidi } from "../core/text.js";

const BAND = "-80px 0px -60% 0px"; // a section counts as "current" while it is in the upper part

/** Interactions that scroll the page by hand: from then on the position decides again. */
const MANUAL = ["wheel", "touchstart", "keydown", "pointerdown"];

function follow(nav, sections) {
  const links = new Map(sections.map((el) => [el.id, nav.querySelector(`a[href="#${el.id}"]`)]));
  const visible = new Set();
  let pinned = null; // the link just used: the last sections can never reach the top of a short page
  const paint = () => {
    const current = pinned ?? sections.find((el) => visible.has(el.id))?.id;
    for (const [id, link] of links) {
      if (id === current) {
        link.setAttribute("aria-current", "location");
      } else if (current) {
        link.removeAttribute("aria-current");
      }
    }
  };
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        visible[entry.isIntersecting ? "add" : "delete"](entry.target.id);
      }
      paint();
    },
    { rootMargin: BAND },
  );
  sections.forEach((el) => observer.observe(el));
  for (const type of MANUAL) {
    window.addEventListener(type, () => { pinned = null; paint(); }, { capture: true, passive: true });
  }
  nav.addEventListener("click", (event) => {
    const link = event.target instanceof Element ? event.target.closest("a") : null;
    pinned = link ? link.hash.slice(1) : null;
    paint();
  });
}

/**
 * Adds the list to the page root `.settings` (once).
 * @param {HTMLElement | null} root
 */
export function ensureToc(root) {
  if (!root || root.querySelector(":scope > .settings-toc")) {
    return;
  }
  const sections = Array.from(root.querySelectorAll(":scope .settings-section[id]"));
  if (sections.length < 2) {
    return;
  }
  const items = sections.map((el) => h("li", null, h("a", { href: `#${el.id}` }, stripBidi(el.querySelector("h2")?.textContent ?? el.id))));
  const nav = h(
    "nav",
    { class: "settings-toc", "aria-label": "Settings sections" },
    h("div", { class: "settings-toc-inner" }, h("p", { class: "settings-toc-title", "aria-hidden": "true" }, "On this page"), h("ul", { class: "list-reset" }, items)),
  );
  root.append(nav);
  if ("IntersectionObserver" in window) {
    follow(nav, sections);
  }
}
