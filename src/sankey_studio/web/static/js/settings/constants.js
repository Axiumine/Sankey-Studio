// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * Fixed facts of the settings page: the limits table (bounds mirror the server models, API.md
 * section 2.4) and the name rules the form checks before it asks the server.
 *
 * The server is the authority: these bounds only give early, friendly feedback and the hints
 * under each field. A 422 from the server is still mapped onto the same fields (errors.js).
 */

/**
 * One row per number setting. `key` is the JSON key of `PUT /settings`.
 * @type {ReadonlyArray<{key: string, testid: string, label: string, min: number, max: number, def: number, help: string}>}
 */
export const LIMITS = Object.freeze([
  {
    key: "max_links",
    testid: "settings-max-links",
    label: "Maximum links per graph",
    min: 100,
    max: 5_000_000,
    def: 200_000,
    help: "A data source with more rows than this is refused, so a huge file cannot freeze the app.",
  },
  {
    key: "max_drawn_links",
    testid: "settings-max-drawn-links",
    label: "Maximum links drawn",
    min: 50,
    max: 20_000,
    def: 3_000,
    help: "Charts and image exports draw the largest links up to this number and say how many were left out.",
  },
  {
    key: "max_upload_mb",
    testid: "settings-max-upload-mb",
    label: "Largest upload (MB)",
    min: 1,
    max: 100,
    def: 25,
    help: "Biggest data file you can upload. A change applies to the very next upload.",
  },
  {
    key: "mongo_timeout_ms",
    testid: "settings-mongo-timeout",
    label: "MongoDB timeout (ms)",
    min: 500,
    max: 300_000,
    def: 15_000,
    help: "How long to wait for MongoDB before giving up. 1000 ms is one second.",
  },
]);

/** Connections the server accepts. */
export const MAX_CONNECTIONS = 20;

/** `^[A-Za-z0-9_.-]{1,64}$` of the API: what a connection name may be. */
export const NAME_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;

/** Characters MongoDB database names cannot contain (mongo_safety.py). */
export const DB_FORBIDDEN = /[/\\. "$*<>:|?\u0000]/;

/** Databases the app never reads or writes. */
export const SYSTEM_DATABASES = Object.freeze(["admin", "local", "config"]);

/** Longest database name. */
export const DB_NAME_MAX = 64;

/** A connection string must start like this (the server checks the rest). */
export const URI_PREFIX = /^mongodb(\+srv)?:\/\//;

/** Control characters are refused inside a connection string. */
export const URI_CONTROL = /[\u0000-\u001f\u007f]/;

/** The storage backends of the select. */
export const BACKENDS = Object.freeze([
  { value: "file", label: "Files on this computer" },
  { value: "mongo", label: "MongoDB" },
]);
