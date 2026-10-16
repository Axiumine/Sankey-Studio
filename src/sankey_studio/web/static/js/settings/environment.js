// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * "This server" section: facts the operator set when the server started (sources folder, whether
 * it can be reached from other machines, whether it accepts changes). They come from the
 * `bootstrap` block of GET /settings and are shown as text only; changing them means restarting
 * the server with other options.
 */

import { h } from "../core/dom.js";
import { icon } from "../core/icons.js";
import { section } from "./ui.js";

function row(label, ...value) {
  return [h("dt", null, label), h("dd", null, ...value)];
}

function badge({ status, text, testid }) {
  return h("span", { class: "badge", "data-status": status, "data-testid": testid }, text);
}

/**
 * Builds the section.
 * @param {{sources_dir: string, remote_mode: boolean, writes_allowed: boolean}} bootstrap
 * @returns {{el: HTMLElement}}
 */
export function buildEnvironment(bootstrap) {
  const remote = bootstrap.remote_mode === true;
  const writes = bootstrap.writes_allowed === true;
  const facts = h(
    "dl",
    { class: "meta-list" },
    row(
      "Data files folder",
      h("code", { class: "break", "data-testid": "settings-sources-dir" }, bootstrap.sources_dir),
      h("p", { class: "hint" }, "Uploaded files are stored here. Start the server with --sources-dir to use another folder."),
    ),
    row(
      "Network access",
      remote
        ? badge({ status: "warning", text: "Remote: reachable from other machines", testid: "settings-remote-mode" })
        : badge({ status: "good", text: "Local only: this computer", testid: "settings-remote-mode" }),
      h("p", { class: "hint" }, remote ? "There is no login, so anyone who can reach this address can open the app." : "Only this computer can open the app."),
    ),
    row(
      "Changes",
      writes
        ? badge({ status: "good", text: "Allowed", testid: "settings-writes-allowed" })
        : h("span", { class: "cluster" }, icon("lock", { size: 14 }), badge({ status: "serious", text: "Read-only", testid: "settings-writes-allowed" })),
      h("p", { class: "hint" }, writes ? "You can save graphs, upload files and change these settings." : "Looking, previewing and exporting work. Saving and uploading are off on this server."),
    ),
  );
  const el = section({
    id: "settings-server",
    title: "This server",
    text: "Set when the server was started. These values are read-only here.",
    body: [facts],
  });
  return { el };
}
