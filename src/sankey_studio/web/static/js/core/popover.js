/**
 * A non-modal popover: a trigger button and a panel somewhere else in the page.
 *
 * `createPopover({trigger, panel, haspopup, align, onOpen, onClose, initialFocus})` wires the
 * trigger once (`aria-haspopup`, `aria-expanded`, `aria-controls`, click toggles) and returns
 * `{isOpen, open, close({focus}), toggle, place, dispose}`. At most one popover is open: opening
 * one closes the other (`closePopovers()` closes whatever is open, e.g. before a dialog opens).
 *
 * - Escape (on the trigger or in the panel) closes it and puts the focus back on the trigger.
 * - A pointer press outside the trigger and the panel closes it; the focus stays where it is.
 * - Focus that moves to an element outside both closes it too (the panel is focusable itself, so
 *   a press on blank space inside it keeps the focus inside). A focus change with no target
 *   (a native colour picker, a `<select>` list, the window losing focus) never closes it.
 * - Tab on the trigger while it is open moves into the panel, which may sit elsewhere in the DOM.
 * - `place()` positions a panel whose offset parent is not the trigger's parent: it writes the
 *   custom properties `--pop-top` and `--pop-right` (or `--pop-left` with `align: "start"`) in
 *   pixels, relative to the panel's offset parent. The CSS falls back to "right below, right edge".
 */

import { focusFirst } from "./focus.js";
import { uid } from "./dom.js";

let current = null;

/** Closes whatever popover is open (no focus change). */
export function closePopovers() {
  current?.close();
}

function px(value) {
  return `${Math.round(value)}px`;
}

class Popover {
  constructor(options) {
    this.trigger = options.trigger;
    this.panel = options.panel;
    this.options = options;
    this.align = options.align === "start" ? "start" : "end";
    this.onPointerDown = (event) => this.pointerDown(event);
    this.onResize = () => this.place();
    this.onFocusOut = (event) => this.focusOut(event);
    this.onKey = (event) => this.key(event);
    this.onTriggerClick = () => this.toggle();
    this.wire();
  }

  wire() {
    const { trigger, panel } = this;
    if (!panel.id) {
      panel.id = uid("pop");
    }
    if (!panel.hasAttribute("tabindex")) {
      panel.tabIndex = -1; // a press on blank panel space focuses the panel, not the page behind it
    }
    trigger.classList.add("pop-trigger");
    trigger.setAttribute("aria-haspopup", this.options.haspopup ?? "dialog");
    trigger.setAttribute("aria-expanded", String(this.isOpen()));
    trigger.setAttribute("aria-controls", panel.id);
    panel.dataset.align = this.align;
    trigger.addEventListener("click", this.onTriggerClick);
    for (const el of [trigger, panel]) {
      el.addEventListener("keydown", this.onKey);
      el.addEventListener("focusout", this.onFocusOut);
    }
  }

  isOpen() {
    return !this.panel.hidden;
  }

  toggle() {
    if (this.isOpen()) {
      this.close();
    } else {
      this.open();
    }
  }

  open() {
    if (this.isOpen()) {
      return;
    }
    if (current && current !== this) {
      current.close();
    }
    current = this;
    this.panel.hidden = false;
    this.trigger.setAttribute("aria-expanded", "true");
    this.place();
    document.addEventListener("pointerdown", this.onPointerDown);
    window.addEventListener("resize", this.onResize);
    this.options.onOpen?.();
    const target = this.options.initialFocus?.();
    if (target) {
      target.focus();
    } else {
      focusFirst(this.panel);
    }
  }

  /** @param {{focus?: boolean}} [options]  `focus: true` puts the focus back on the trigger */
  close(options = {}) {
    if (!this.isOpen()) {
      return;
    }
    this.panel.hidden = true;
    this.trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", this.onPointerDown);
    window.removeEventListener("resize", this.onResize);
    if (current === this) {
      current = null;
    }
    this.options.onClose?.();
    if (options.focus) {
      this.trigger.focus();
    }
  }

  place() {
    const parent = this.panel.offsetParent;
    if (!(parent instanceof HTMLElement) || parent === this.trigger.parentElement) {
      return;
    }
    const anchor = this.trigger.getBoundingClientRect();
    const box = parent.getBoundingClientRect();
    this.panel.style.setProperty("--pop-top", px(anchor.bottom - box.top + 4));
    if (this.align === "start") {
      this.panel.style.setProperty("--pop-left", px(anchor.left - box.left));
    } else {
      this.panel.style.setProperty("--pop-right", px(box.right - anchor.right));
    }
  }

  inside(node) {
    return node instanceof Node && (this.trigger.contains(node) || this.panel.contains(node));
  }

  pointerDown(event) {
    if (!this.inside(event.target)) {
      this.close();
    }
  }

  focusOut(event) {
    if (this.isOpen() && event.relatedTarget && !this.inside(event.relatedTarget)) {
      this.close();
    }
  }

  key(event) {
    if (!this.isOpen()) {
      return;
    }
    if (event.key === "Escape") {
      event.stopPropagation();
      this.close({ focus: true });
    } else if (event.key === "Tab" && !event.shiftKey && event.currentTarget === this.trigger) {
      event.preventDefault();
      focusFirst(this.panel);
    }
  }

  dispose() {
    this.close();
    this.trigger.removeEventListener("click", this.onTriggerClick);
    for (const el of [this.trigger, this.panel]) {
      el.removeEventListener("keydown", this.onKey);
      el.removeEventListener("focusout", this.onFocusOut);
    }
  }
}

/**
 * Wires a trigger and a panel.
 * @param {{trigger: HTMLElement, panel: HTMLElement, haspopup?: "menu"|"dialog"|"true", align?: "start"|"end", onOpen?: () => void, onClose?: () => void, initialFocus?: () => HTMLElement | null}} options
 * @returns {{isOpen: () => boolean, open: () => void, close: (options?: {focus?: boolean}) => void, toggle: () => void, place: () => void, dispose: () => void}}
 */
export function createPopover(options) {
  const popover = new Popover(options);
  return {
    isOpen: () => popover.isOpen(),
    open: () => popover.open(),
    close: (closeOptions) => popover.close(closeOptions),
    toggle: () => popover.toggle(),
    place: () => popover.place(),
    dispose: () => popover.dispose(),
  };
}
