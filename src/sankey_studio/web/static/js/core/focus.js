/**
 * Focus management for dialogs and keyboard flows (re-exported by dom.js).
 *
 * - `focusable(container)`: visible, enabled, tabbable descendants.
 * - `focusFirst(container)`: focuses the first of them, or the container (give it tabindex="-1").
 * - `trapFocus(container, {onEscape, restore})`: Tab and Shift+Tab cycle inside `container`, Esc
 *   calls `onEscape`, focus that lands outside is pulled back. The returned function releases the
 *   trap and puts focus back where it was. Traps nest: only the newest one reacts.
 */

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type=\"hidden\"])",
  "select:not([disabled])", "textarea:not([disabled])", "summary",
  "[tabindex]:not([tabindex=\"-1\"])", "[contenteditable=\"true\"]",
].join(",");

/**
 * The focusable, visible descendants of `container` in tab order of the document.
 * @param {ParentNode} container
 * @returns {HTMLElement[]}
 */
export function focusable(container) {
  return Array.from(container.querySelectorAll(FOCUSABLE)).filter(
    (el) => !el.closest("[hidden],[inert]") && el.getClientRects().length > 0,
  );
}

/**
 * Focuses the first focusable descendant, or the container itself (give it tabindex="-1").
 * @param {HTMLElement} container
 * @returns {HTMLElement}
 */
export function focusFirst(container) {
  const target = focusable(container)[0] ?? container;
  target.focus();
  return target;
}

const trapStack = [];

function onTrapKey(event) {
  const top = trapStack[trapStack.length - 1];
  if (!top) {
    return;
  }
  if (event.key === "Escape" && top.onEscape) {
    event.preventDefault();
    event.stopPropagation();
    top.onEscape(event);
    return;
  }
  if (event.key === "Tab") {
    cycleFocus(event, top.container);
  }
}

function cycleFocus(event, container) {
  const items = focusable(container);
  if (items.length === 0) {
    event.preventDefault();
    container.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const outside = !container.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || outside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || outside)) {
    event.preventDefault();
    first.focus();
  }
}

function onTrapFocusIn(event) {
  const top = trapStack[trapStack.length - 1];
  if (top && !top.container.contains(event.target)) {
    (focusable(top.container)[0] ?? top.container).focus();
  }
}

/**
 * Keeps keyboard focus inside `container` (a dialog): Tab and Shift+Tab cycle, Esc calls
 * `options.onEscape`, focus coming from outside is pulled back. The returned function releases
 * the trap and puts focus back where it was. Traps nest: only the newest one reacts.
 * @param {HTMLElement} container  needs tabindex="-1" so it can hold focus when it is empty
 * @param {{onEscape?: (event: KeyboardEvent) => void, restore?: boolean, returnFocus?: HTMLElement}} [options]
 *   `returnFocus` defaults to the element that has focus when the trap starts
 * @returns {() => void}
 */
export function trapFocus(container, options = {}) {
  const entry = { container, onEscape: options.onEscape };
  const previous = options.returnFocus ?? document.activeElement;
  if (trapStack.length === 0) {
    document.addEventListener("keydown", onTrapKey, true);
    document.addEventListener("focusin", onTrapFocusIn);
  }
  trapStack.push(entry);
  return () => {
    const index = trapStack.indexOf(entry);
    if (index >= 0) {
      trapStack.splice(index, 1);
    }
    if (trapStack.length === 0) {
      document.removeEventListener("keydown", onTrapKey, true);
      document.removeEventListener("focusin", onTrapFocusIn);
    }
    if (options.restore !== false && previous instanceof HTMLElement && previous.isConnected) {
      previous.focus();
    }
  };
}
