// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Giovanni Manzoni
/**
 * The connection, database and collection pickers of the Mongo tab.
 *
 * - Connection: a select of the connection NAMES from the settings (URIs never reach this page).
 * - Database / collection: text inputs with suggestion lists from the server
 *   (`GET /mongo/{name}/databases`, `.../collections?database=`). They stay usable when listing
 *   fails (no permission, server down): the person can type the name. Loading and failures are
 *   said in words under the field.
 * - The database may stay empty: the connection's default database is used.
 * Test ids: mongo-connection, mongo-database, mongo-collection.
 */

import { h, uid } from "../../core/dom.js";
import { field, selectInput, textInput } from "../../core/form.js";
import { bindText } from "../meta/bind.js";

const SRC = ["draft", "source"];

/** The database the server will use: the typed one, else the connection's default. */
export function effectiveDatabase(source, connections) {
  const connection = connections.find((item) => item.name === source.connection);
  return source.database || connection?.default_database || "";
}

function connectionOptions(connections, current) {
  const options = connections.map((item) => ({ value: item.name, label: item.name }));
  if (current && !connections.some((item) => item.name === current)) {
    options.unshift({ value: current, label: `${current} (not in Settings)` });
  }
  return options.length > 0 ? options : [{ value: "", label: "No connections" }];
}

const fill = (list, names) => list.replaceChildren(...names.map((name) => h("option", { value: name })));

class Pickers {
  constructor({ store, data, connections, fields }) {
    this.store = store;
    this.data = data;
    this.connections = connections;
    this.runs = 0;
    this.select = selectInput({ options: connectionOptions(connections, store.get().draft.source.connection), "data-testid": "mongo-connection" });
    this.connection = field({ label: "Connection", control: this.select, hint: "Configured in Settings." });
    this.dbList = h("datalist", { id: uid("dbs") });
    this.collList = h("datalist", { id: uid("colls") });
    this.database = field({ label: "Database", control: textInput({ list: this.dbList.id, maxlength: 64, "data-testid": "mongo-database" }), hint: "" });
    this.collection = field({ label: "Collection", control: textInput({ list: this.collList.id, maxlength: 120, "data-testid": "mongo-collection" }), hint: "" });
    Object.assign(fields, { connection: this.connection, database: this.database, collection: this.collection });
    this.els = [this.connection.el, this.database.el, this.collection.el, this.dbList, this.collList];
    this.select.addEventListener("change", () => this.onConnectionChange());
    this.database.control.addEventListener("change", () => this.loadCollections());
    this.offs = [
      bindText(store, this.database.control, [...SRC, "database"], { removeEmpty: true }),
      bindText(store, this.collection.control, [...SRC, "collection"]),
      store.subscribe((value) => this.showConnection(value), { select: (state) => state.draft.source.connection, immediate: true }),
    ];
  }

  source() {
    return this.store.get().draft.source;
  }

  known() {
    return this.connections.some((item) => item.name === this.source().connection);
  }

  showConnection(value) {
    const found = this.connections.find((item) => item.name === value);
    this.database.control.placeholder = found?.default_database ?? "Default database";
    if (value != null && this.select.value !== value) {
      this.select.replaceChildren(...connectionOptions(this.connections, value).map((o) => h("option", { value: o.value }, o.label)));
      this.select.value = value;
    }
  }

  onConnectionChange() {
    this.store.batch(() => {
      this.store.patch([...SRC, "connection"], this.select.value);
      this.store.remove([...SRC, "database"]);
    });
    this.loadAll();
  }

  loadAll() {
    return this.loadDatabases().then(() => this.loadCollections());
  }

  async loadDatabases() {
    const source = this.source();
    fill(this.dbList, []);
    if (!source.connection || !this.known()) {
      this.database.setHint(source.connection ? "This connection is not in Settings, so databases cannot be listed." : "");
      return;
    }
    this.database.setHint("Loading databases");
    try {
      fill(this.dbList, await this.data.databases(source.connection));
      this.database.setHint(source.database ? "" : "Leave empty to use the connection's default database.");
    } catch (error) {
      this.database.setHint(`Could not list databases (${error.friendly ?? error.message}). You can still type a name.`);
    }
  }

  async loadCollections() {
    this.runs += 1;
    const mine = this.runs;
    const source = this.source();
    const name = effectiveDatabase(source, this.connections);
    fill(this.collList, []);
    if (!source.connection || !this.known() || !name) {
      this.collection.setHint(source.connection && this.known() ? "Choose or type a database first." : "");
      return;
    }
    this.collection.setHint("Loading collections");
    try {
      const names = await this.data.collections(source.connection, name);
      if (mine === this.runs) {
        fill(this.collList, names);
        this.collection.setHint(names.length === 0 ? `No collections found in ${name}.` : "");
      }
    } catch (error) {
      if (mine === this.runs) {
        this.collection.setHint(`Could not list collections (${error.friendly ?? error.message}). You can still type a name.`);
      }
    }
  }
}

/**
 * Builds the three pickers and keeps the suggestion lists current.
 * @param {{store: object, data: ReturnType<typeof import("./mongo-data.js").createMongoData>, connections: object[], fields: Record<string, object>}} options
 * @returns {{els: HTMLElement[], loadSoon: () => void, dispose: () => void}}
 */
export function createPickers(options) {
  const pickers = new Pickers(options);
  return {
    els: pickers.els,
    loadSoon: () => pickers.loadAll(),
    dispose: () => pickers.offs.forEach((off) => off()),
  };
}
