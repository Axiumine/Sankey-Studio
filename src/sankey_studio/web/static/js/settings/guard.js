// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Unsaved-changes guard.
 *
 * - A click on a link of this app (header navigation, brand) while the form is dirty opens a
 *   confirmation dialog ("Keep editing" / "Discard and leave") instead of throwing the changes
 *   away. Modified clicks (new tab), downloads and same-page anchors pass.
 * - Everything else that leaves the page (reload, back button, closing the tab, typing a URL) gets
 *   the browser's own "Leave site?" prompt through `beforeunload`.
 * The guard is removed after a confirmed leave so the browser prompt does not follow the dialog.
 */

import { confirmDialog } from "../core/dialog.js";

function isPlainLeftClick(event) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function leavesPage(link) {
  if (link.target === "_blank" || link.hasAttribute("download")) {
    return false;
  }
  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin) {
    return false;
  }
  return !(url.pathname === window.location.pathname && url.search === window.location.search && url.hash !== "");
}

/**
 * Installs the guard. The `beforeunload` listener exists only while the form is dirty (a page with
 * such a listener cannot enter the browser's back/forward cache).
 * @param {{isDirty: () => boolean, subscribe: (listener: () => void) => () => void}} source
 * @returns {() => void} removes the guard
 */
export function installLeaveGuard(source) {
  const { isDirty } = source;
  let leaving = false;
  let attached = false;
  const onBeforeUnload = (event) => {
    if (!leaving && isDirty()) {
      event.preventDefault();
      event.returnValue = "";
    }
  };
  const onClick = async (event) => {
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!link || event.defaultPrevented || !isPlainLeftClick(event) || !isDirty() || !leavesPage(link)) {
      return;
    }
    event.preventDefault();
    const leave = await confirmDialog({
      title: "Discard unsaved changes?",
      message: "You changed settings that are not saved yet. If you leave now, those changes are lost.",
      confirmLabel: "Discard and leave",
      cancelLabel: "Keep editing",
      danger: true,
    });
    if (leave) {
      leaving = true;
      window.location.assign(link.href);
    }
  };
  const follow = () => {
    const dirty = isDirty();
    if (dirty && !attached) {
      window.addEventListener("beforeunload", onBeforeUnload);
    } else if (!dirty && attached) {
      window.removeEventListener("beforeunload", onBeforeUnload);
    }
    attached = dirty;
  };
  document.addEventListener("click", onClick);
  const unsubscribe = source.subscribe(follow);
  follow();
  return () => {
    unsubscribe();
    window.removeEventListener("beforeunload", onBeforeUnload);
    document.removeEventListener("click", onClick);
  };
}
