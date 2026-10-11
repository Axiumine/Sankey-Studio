/**
 * Unsaved-changes guard of the editor.
 *
 * - Closing the tab, reloading or typing another address: the browser's own "leave site?" prompt
 *   (`beforeunload`), only while `status.dirty` is true.
 * - Following a link inside the app (library, settings, the graph's own viewer): the click is held
 *   and a dialog asks whether to leave. Modified clicks (new tab), downloads, other origins and
 *   in-page anchors are left alone (the browser prompt covers the cross-origin case).
 * - `bypass()` switches the guard off for the next navigation, for code that saved and is about to
 *   open the saved graph (the store is clean by then, so this is rarely needed).
 */

import { confirmDialog } from "../../core/dialog.js";

function isPlainLeftClick(event) {
  return event.button === 0 && !event.defaultPrevented && !(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey);
}

function leavingTarget(event) {
  const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!link || !isPlainLeftClick(event) || link.hasAttribute("download") || (link.target && link.target !== "_self")) {
    return null;
  }
  const url = new URL(link.href, window.location.href);
  const here = window.location;
  const samePage = url.pathname === here.pathname && url.search === here.search;
  return url.origin === here.origin && !samePage ? url : null;
}

/**
 * Installs the guard for a store.
 * @param {{get: () => {status: {dirty: boolean}}}} store
 * @returns {{bypass: () => void, dispose: () => void}}
 */
export function installLeaveGuard(store) {
  let bypassed = false;
  const dirty = () => !bypassed && store.get().status.dirty === true;
  const onBeforeUnload = (event) => {
    if (dirty()) {
      event.preventDefault();
      event.returnValue = ""; // some browsers need it to show the prompt
    }
  };
  const onClick = async (event) => {
    const url = dirty() ? leavingTarget(event) : null;
    if (!url) {
      return;
    }
    event.preventDefault();
    const leave = await confirmDialog({
      title: "Leave without saving?",
      message: "You have changes that are not saved. If you leave now they are lost.",
      confirmLabel: "Leave without saving",
      cancelLabel: "Stay and keep editing",
      danger: true,
    });
    if (leave) {
      bypassed = true;
      window.location.assign(url.href);
    }
  };
  window.addEventListener("beforeunload", onBeforeUnload);
  document.addEventListener("click", onClick, true);
  return {
    bypass() {
      bypassed = true;
    },
    dispose() {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    },
  };
}
