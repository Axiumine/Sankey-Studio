// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Toasts: short messages in the `#toast-region` live region of the shell.
 *
 * `toast.error(msg)`, `toast.success(msg)`, `toast.info(msg)`, `toast.warning(msg)` or
 * `toast.show(msg, {kind, title, timeout, action, near})`. Each toast is
 * `<div data-testid="toast" data-kind="error|success|info|warning">` with a close button;
 * errors use role="alert" and stay 9 s, the others 5 s (hover or keyboard focus pauses the
 * timer, `timeout: 0` keeps it until closed). `action` is `{label, onClick}` (one extra button).
 * `near` is an element the message is about (the result line next to the button just pressed):
 * it is kept clear of the stack like the control that has focus.
 * Messages are always text nodes, so an API error text can never inject markup. Identical
 * messages that are still visible are not stacked. At most 4 toasts are visible (fewer on a short
 * window: 1 below 520px, 2 below 640px, so a page zoomed to 200% is not half covered).
 *
 * `show` returns `{dismiss()}`; `toast.clear()` removes all.
 *
 * Placement (the stack is fixed, bottom right on wide screens and along the bottom on phones, see
 * components.css): it never hides the control the user is working with. The module remembers the
 * last control that took focus or a click; when a toast appears (or focus moves while toasts are
 * showing, as it does when a failed form focuses its error summary) and that control would sit
 * under the stack, the page is scrolled just far enough to bring it above the stack. A sticky save
 * bar (`.savebar`) is not covered either: the stack is lifted above it (custom property
 * `--toast-bottom` on the region). While a dialog is open on a phone the stack goes to the top
 * (components.css), where nothing can be scrolled away from it.
 */

import { icon } from "./icons.js";
import { h } from "./dom.js";

const MAX_VISIBLE = 4;
const GAP = 8; // px kept between the stack and the control it makes room for
const CONTROL = "button, a[href], input, select, textarea, summary, [role='button'], [tabindex]";
const DEFAULT_TIMEOUT = { error: 9000, warning: 7000, success: 5000, info: 5000 };
const ICONS = { error: "x-circle", warning: "alert", success: "check-circle", info: "info" };

function region() {
  let node = document.getElementById("toast-region");
  if (!node) {
    node = h("div", { id: "toast-region", class: "toast-region", "aria-live": "polite" });
    document.body.append(node);
  }
  return node;
}

function startTimer(state, ms) {
  state.timer = setTimeout(state.dismiss, ms);
  state.started = Date.now();
  state.remaining = ms;
}

function pause(state) {
  if (state.timer !== null && state.timeout > 0) {
    clearTimeout(state.timer);
    state.timer = null;
    state.remaining = Math.max(1000, state.remaining - (Date.now() - state.started));
  }
}

function resume(state) {
  if (state.timer === null && state.timeout > 0) {
    startTimer(state, state.remaining);
  }
}

function buildToast(message, options, state) {
  const kind = options.kind;
  const actionButton = options.action
    ? h("button", { type: "button", class: "btn btn-sm", on: { click: () => { options.action.onClick(); state.dismiss(); } } }, options.action.label)
    : null;
  return h(
    "div",
    { class: "toast", "data-testid": "toast", "data-kind": kind, role: kind === "error" ? "alert" : null },
    h("span", { class: "toast-icon" }, icon(ICONS[kind], { size: 18 })),
    h(
      "div",
      { class: "toast-body" },
      options.title ? h("div", { class: "toast-title" }, options.title) : null,
      h("div", { class: options.title ? "toast-message" : "" }, message),
      actionButton ? h("div", { class: "toast-actions" }, actionButton) : null,
    ),
    h("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": "Dismiss notification", on: { click: () => state.dismiss() } }, icon("x")),
  );
}

const keys = new WeakMap();

// ---------------------------------------------------------------------------------- placement

const acted = { el: null, near: null };

function maxVisible() {
  const height = window.innerHeight;
  return height < 520 ? 1 : height < 640 ? 2 : MAX_VISIBLE;
}

function rememberActed(event) {
  const control = event.target instanceof Element ? event.target.closest(CONTROL) : null;
  if (control && !control.closest("#toast-region") && control !== document.getElementById("main")) {
    acted.el = control;
    if (event.type === "click") {
      acted.near = null; // the user moved on: the output of the earlier action no longer matters
    }
  }
}

/** How far up from the bottom of the window the sticky save bar reaches (0: none is docked). */
function dockHeight() {
  let top = window.innerHeight;
  for (const bar of document.querySelectorAll(".savebar")) {
    const box = bar.getBoundingClientRect();
    if (box.height > 0 && box.bottom > window.innerHeight / 2 && box.top < top) {
      top = box.top;
    }
  }
  return window.innerHeight - top;
}

/** Lifts the stack above a docked save bar; with no toast the page-height help goes away too. */
function layout() {
  const host = document.getElementById("toast-region");
  if (!host) {
    return;
  }
  const visible = host.firstElementChild !== null;
  const dock = visible ? dockHeight() : 0;
  if (dock > 0) {
    host.style.setProperty("--toast-bottom", `${Math.ceil(dock + GAP)}px`);
  } else {
    host.style.removeProperty("--toast-bottom");
  }
  if (!visible) {
    document.documentElement.style.removeProperty("--toast-clearance");
    acted.near = null;
  }
}

function scrollUp(pixels) {
  const root = document.documentElement;
  const room = root.scrollHeight - window.innerHeight - window.scrollY;
  if (pixels > room) {
    // the page ends before the control can clear the stack: give it that much extra length
    const extra = Number.parseFloat(root.style.getPropertyValue("--toast-clearance")) || 0;
    root.style.setProperty("--toast-clearance", `${Math.ceil(extra + pixels - room)}px`);
  }
  window.scrollBy({ top: pixels, behavior: "instant" });
}

function covers(zone, box) {
  return box.left < zone.right + GAP && box.right > zone.left - GAP && box.top < zone.bottom + GAP && box.bottom > zone.top - GAP;
}

function union(boxes) {
  return {
    left: Math.min(...boxes.map((box) => box.left)),
    right: Math.max(...boxes.map((box) => box.right)),
    top: Math.min(...boxes.map((box) => box.top)),
    bottom: Math.max(...boxes.map((box) => box.bottom)),
  };
}

/** What the stack must stay clear of: the control worked with and the element the toast is about. */
function protectedBox(limit) {
  // a control inside a dialog stays where it is when the page scrolls: nothing to make room for
  const boxes = [acted.el, acted.near]
    .filter((el) => el?.isConnected && !el.closest(".dialog-backdrop, [role='dialog']"))
    .map((el) => el.getBoundingClientRect())
    .filter((box) => box.height > 0 && box.bottom > 0 && box.top < window.innerHeight);
  if (boxes.length === 0) {
    return null;
  }
  const both = union(boxes);
  const [first] = boxes;
  return both.bottom - both.top < limit ? both : first;
}

/** Scrolls the page when the stack covers the control the user last worked with. */
function clearOfStack() {
  const host = document.getElementById("toast-region");
  if (!host?.firstElementChild) {
    return;
  }
  const zone = host.getBoundingClientRect();
  const height = window.innerHeight;
  const box = protectedBox(height * 0.6);
  // a stack in the top half (a dialog is open on a phone) cannot be scrolled away from
  if (!box || zone.top <= height / 2 || box.bottom - box.top >= height * 0.6 || !covers(zone, box)) {
    return;
  }
  const header = document.querySelector(".app-header")?.getBoundingClientRect().bottom ?? 0;
  const wanted = box.bottom - (zone.top - GAP);
  const allowed = Math.max(0, box.top - header - GAP); // never push it under the sticky header
  scrollUp(Math.min(wanted, allowed));
}

function watchPlacement() {
  const queued = new Set();
  const later = (job) => {
    if (!queued.has(job)) {
      queued.add(job);
      requestAnimationFrame(() => {
        queued.delete(job);
        job();
      });
    }
  };
  document.addEventListener("click", rememberActed, true);
  document.addEventListener(
    "focusin",
    (event) => {
      rememberActed(event);
      later(clearOfStack); // after the browser's own scroll to the focused element
    },
    true,
  );
  const relayout = () => {
    if (document.getElementById("toast-region")?.firstElementChild) {
      later(layout); // the save bar docks and undocks while the page scrolls or is resized
    }
  };
  window.addEventListener("resize", relayout, { passive: true });
  window.addEventListener("scroll", relayout, { passive: true });
}

watchPlacement();

/**
 * Shows a toast.
 * @param {string} message
 * @param {{kind?: "error"|"success"|"info"|"warning", title?: string, timeout?: number, action?: {label: string, onClick: () => void}, near?: Element}} [options]
 * @returns {{dismiss: () => void}}
 */
function show(message, options = {}) {
  const kind = options.kind ?? "info";
  const host = region();
  if (options.near instanceof Element) {
    acted.near = options.near;
  }
  const text = String(message);
  const key = `${kind}\u0000${text}`;
  const existing = Array.from(host.children).find((node) => keys.get(node) === key);
  if (existing) {
    return { dismiss: () => { existing.remove(); layout(); } };
  }
  const timeout = options.timeout ?? DEFAULT_TIMEOUT[kind] ?? DEFAULT_TIMEOUT.info;
  const state = { timer: null, timeout, started: 0, remaining: timeout, dismiss: null };
  const node = buildToast(text, { ...options, kind }, state);
  keys.set(node, key);
  state.dismiss = () => {
    clearTimeout(state.timer);
    state.timer = null;
    node.remove();
    layout();
  };
  node.addEventListener("mouseenter", () => pause(state));
  node.addEventListener("mouseleave", () => resume(state));
  node.addEventListener("focusin", () => pause(state));
  node.addEventListener("focusout", () => resume(state));
  host.append(node);
  while (host.children.length > maxVisible()) {
    host.firstElementChild.remove();
  }
  layout();
  clearOfStack();
  if (timeout > 0) {
    startTimer(state, timeout);
  }
  return { dismiss: state.dismiss };
}

export const toast = {
  show,
  error: (message, options) => show(message, { ...options, kind: "error" }),
  success: (message, options) => show(message, { ...options, kind: "success" }),
  info: (message, options) => show(message, { ...options, kind: "info" }),
  warning: (message, options) => show(message, { ...options, kind: "warning" }),
  clear: () => {
    region().replaceChildren();
    layout();
  },
};
