// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The shell script every page loads (templates/page.html), independent of the page module:
 * wires the header theme switch and the global loading bar.
 *
 * - Theme switch: `[data-testid="theme-switch"] [data-theme-value]` buttons call
 *   `setTheme(value)`; `aria-pressed` follows `<html data-theme>`. A failed save is reported once
 *   as a toast (the theme then lasts until the page is reloaded); in read-only mode nothing is
 *   saved remotely and the choice stays cached on this device.
 * - Loading bar: `#loading-bar` (data-testid="loading") is visible while API requests are in
 *   flight (`sankey:busy` events from core/api.js), shown after 150 ms so quick calls do not flash.
 * - `#main[data-loading]` ("true" / "false", always present) is the timing hook for tests and scripts:
 *   "true" while any API request that shows the loading bar is in flight or the editor's live
 *   preview is scheduled or running (`sankey:work` events from editor/preview.js), at once and
 *   without the 150 ms delay of the bar.
 * - `body[data-shell="ready"]` is set when the wiring is done.
 */

import { onThemeChange, getTheme, setTheme } from "./theme.js";
import { toast } from "./toast.js";

const SHOW_DELAY_MS = 150;

function wireThemeSwitch() {
  const group = document.querySelector('[data-testid="theme-switch"]');
  if (!group) {
    return;
  }
  const buttons = Array.from(group.querySelectorAll("[data-theme-value]"));
  const reflect = () => {
    for (const button of buttons) {
      button.setAttribute("aria-pressed", String(button.dataset.themeValue === getTheme()));
    }
  };
  for (const button of buttons) {
    button.addEventListener("click", async () => {
      const result = await setTheme(button.dataset.themeValue);
      if (result.error) {
        toast.info(`Theme not saved, so it lasts until you reload. ${result.error.friendly ?? result.error.message}`);
      }
    });
  }
  onThemeChange(reflect);
  reflect();
}

function wireLoadingBar() {
  const bar = document.getElementById("loading-bar");
  if (!bar) {
    return;
  }
  let timer = null;
  document.addEventListener("sankey:busy", (event) => {
    if (event.detail.pending > 0) {
      timer ??= setTimeout(() => {
        bar.hidden = false;
      }, SHOW_DELAY_MS);
      return;
    }
    clearTimeout(timer);
    timer = null;
    bar.hidden = true;
  });
}

function wireLoadingState() {
  const main = document.getElementById("main");
  if (!main) {
    return;
  }
  const pending = { busy: 0, work: 0 };
  const paint = () => {
    main.dataset.loading = String(pending.busy + pending.work > 0);
  };
  document.addEventListener("sankey:busy", (event) => {
    pending.busy = event.detail.pending;
    paint();
  });
  document.addEventListener("sankey:work", (event) => {
    pending.work = event.detail.pending;
    paint();
  });
  paint();
}

wireThemeSwitch();
wireLoadingBar();
wireLoadingState();
document.body.dataset.shell = "ready";
