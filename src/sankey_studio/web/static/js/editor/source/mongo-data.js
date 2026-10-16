// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The three read-only MongoDB discovery calls the Mongo tab uses (API.md section 2.5), with a
 * small cache per connection so switching tabs does not ask the server again.
 *
 * - databases(connection)                  GET /mongo/{name}/databases
 * - collections(connection, database)      GET /mongo/{name}/collections?database=
 * - sample(connection, database, collection)  GET /mongo/{name}/sample?...&n=5
 * The server never lists admin/local/config or system.* and only ever reads. Connection URIs never
 * reach the browser: only the connection NAME is used here.
 */

/**
 * Creates the data access.
 * @param {typeof import("../../core/api.js").api} api
 * @returns {{databases: Function, collections: Function, sample: Function, forget: () => void}}
 */
export function createMongoData(api) {
  const cache = new Map();
  const remember = async (key, load) => {
    if (!cache.has(key)) {
      cache.set(key, await load());
    }
    return cache.get(key);
  };
  const base = (connection) => `/mongo/${encodeURIComponent(connection)}`;
  return {
    databases: (connection) => remember(`db|${connection}`, () => api.get(`${base(connection)}/databases`, { quiet: true })),
    collections: (connection, database) => remember(`coll|${connection}|${database}`, () => api.get(`${base(connection)}/collections`, { query: { database }, quiet: true })),
    sample: (connection, database, collection) => api.get(`${base(connection)}/sample`, { query: { database, collection, n: 5 }, quiet: true }),
    forget: () => cache.clear(),
  };
}
