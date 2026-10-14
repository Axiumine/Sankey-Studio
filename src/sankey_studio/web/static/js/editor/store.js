/**
 * The editor store: one small observable object shared by every editor panel.
 *
 * State shape
 *   draft   a GraphDraft: `{source, transform, style}` exactly as the API takes it (POST /preview,
 *           /entries, /export) - the single source of truth for what is drawn.
 *   meta    `{id, name, description, tags, revision, created_at, updated_at, folder_id}`: what is saved
 *           around the draft (`id`/`revision` are null for a graph that was never saved).
 *           `folder_id` (the collection the graph sits in, or the one a new graph will be created
 *           in) is read-only metadata: it is not editable and `toPayload()` never sends it.
 *   bundle  the last RenderBundle from POST /preview (or null).
 *   status  `{saving, dirty, previewing, error}`; `error` is `{source, status, code, message,
 *           details}` from the last failed preview/save, or null. `source` says who wrote it:
 *           "preview" (the preview loop, editor/preview.js) or "save" (the save bar,
 *           editor/savebar/panel.js, which writes a 422 so the form panels can mark the fields).
 *           A reader that is only about one of them filters on it (chart/errors.js `previewError`
 *           ignores "save"); the form panels read both, because both carry field details.
 *
 * API
 *   createStore(initial?) -> store
 *   store.get()                         current state (treat as immutable: never mutate it)
 *   store.subscribe(listener, {select, immediate})   listener(selected, state, previous); fires
 *                                       only when `select(state)` (default: the whole state)
 *                                       changes by reference; returns the unsubscribe function
 *   store.patch(path, valueOrUpdater, {clean})   immutable update at a path with structural
 *                                       sharing; unchanged values notify nobody. `path` is
 *                                       "draft.source.content" or an array (use an array when a
 *                                       key contains a dot, e.g. ["draft","transform","merge_nodes",
 *                                       "a.b"]); numeric segments index arrays. A function value is
 *                                       an updater `(previous) => next`. Edits under `draft` or
 *                                       `meta` set `status.dirty` unless `{clean: true}`.
 *   store.remove(path)                  deletes a key or array item
 *   store.batch(fn)                     several patches, ONE notification
 *   store.load(definition)              replaces draft+meta from a GraphDefinition (clean)
 *   store.markSaved(definition)         after a save: meta from the answer, dirty=false. Edits made
 *                                       while the save was in flight (since the last `toPayload()`)
 *                                       are kept and keep `status.dirty` true
 *   store.reset(initial?)               back to an empty (or given) state
 *   store.toPayload()                   body for POST /graphs; `{..., revision}` for PUT /graphs/{id}
 * Helpers: `emptyDraft()`, `initialState(overrides)`.
 */

const DRAFT_KEYS = ["source", "transform", "style"];
const META_KEYS = ["id", "name", "description", "tags", "revision", "created_at", "updated_at", "folder_id"];
const EDITABLE_META = ["name", "description", "tags"];

/** A new, empty draft: an inline text source. */
export function emptyDraft() {
  return { source: { type: "text", origin: "inline", format: "auto", content: "" }, transform: {}, style: {} };
}

/** A fresh state; `overrides` may replace draft/meta/bundle/status parts. */
export function initialState(overrides = {}) {
  return {
    draft: emptyDraft(),
    meta: { id: null, name: "", description: "", tags: [], revision: null, created_at: null, updated_at: null, folder_id: null },
    bundle: null,
    status: { saving: false, dirty: false, previewing: false, error: null },
    ...overrides,
  };
}

function parsePath(path) {
  const parts = Array.isArray(path) ? path : String(path).split(".");
  return parts.map((part) => (typeof part === "string" && /^\d+$/.test(part) ? Number(part) : part));
}

function own(container, key) {
  return container != null && Object.hasOwn(Object(container), key) ? container[key] : undefined;
}

function setIn(node, keys, apply) {
  if (keys.length === 0) {
    return apply(node);
  }
  const [head, ...rest] = keys;
  const base = node ?? (typeof head === "number" ? [] : {});
  const current = own(base, head);
  const next = setIn(current, rest, apply);
  if (Object.is(next, current) && node != null) {
    return node;
  }
  if (Array.isArray(base)) {
    const copy = base.slice();
    copy[head] = next;
    return copy;
  }
  return { ...base, [head]: next };
}

function removeIn(node, keys) {
  const [head, ...rest] = keys;
  if (node == null || !Object.hasOwn(Object(node), head)) {
    return node;
  }
  if (rest.length > 0) {
    const next = removeIn(node[head], rest);
    return Object.is(next, node[head]) ? node : setIn(node, [head], () => next);
  }
  if (Array.isArray(node)) {
    return node.filter((_, index) => index !== head);
  }
  const { [head]: _removed, ...others } = node;
  return others;
}

function pick(source, keys) {
  return Object.fromEntries(keys.filter((key) => key in source).map((key) => [key, source[key]]));
}

/** True when the user changed the draft or the editable meta after `sent` was taken by toPayload(). */
function editedSince(state, sent) {
  if (!sent) {
    return false;
  }
  return state.draft !== sent.draft || EDITABLE_META.some((key) => state.meta[key] !== sent.meta[key]);
}

/** The meta the server answered, without overwriting what the user typed while the save ran. */
function savedMeta(definition, meta, sent) {
  const answer = pick(definition, META_KEYS);
  for (const key of EDITABLE_META) {
    if (sent && meta[key] !== sent.meta[key]) {
      delete answer[key];
    }
  }
  return answer;
}

const PUBLIC = ["get", "subscribe", "patch", "remove", "batch", "load", "markSaved", "reset", "toPayload"];

function markDirty(state, keys) {
  const editsDraft = keys[0] === "draft" || keys[0] === "meta";
  return editsDraft ? setIn(state, ["status", "dirty"], () => true) : state;
}

class Store {
  #state;
  #depth = 0;
  #before = null;
  #sent = null;
  #subscribers = new Set();

  constructor(initial) {
    this.#state = initial;
    for (const name of PUBLIC) {
      this[name] = this[name].bind(this);
    }
  }

  /** The current state (immutable by convention). */
  get() {
    return this.#state;
  }

  #emit(previous) {
    for (const sub of Array.from(this.#subscribers)) {
      const next = sub.select(this.#state);
      if (!Object.is(next, sub.last)) {
        sub.last = next;
        sub.listener(next, this.#state, previous);
      }
    }
  }

  #commit(next) {
    if (next === this.#state) {
      return;
    }
    const previous = this.#state;
    this.#state = next;
    if (this.#depth === 0) {
      this.#emit(previous);
    } else {
      this.#before ??= previous;
    }
  }

  subscribe(listener, options = {}) {
    const sub = { listener, select: options.select ?? ((state) => state), last: null };
    sub.last = sub.select(this.#state);
    this.#subscribers.add(sub);
    if (options.immediate) {
      listener(sub.last, this.#state, this.#state);
    }
    return () => this.#subscribers.delete(sub);
  }

  patch(path, value, options = {}) {
    const keys = parsePath(path);
    const next = setIn(this.#state, keys, typeof value === "function" ? value : () => value);
    this.#commit(options.clean || next === this.#state ? next : markDirty(next, keys));
  }

  remove(path) {
    const keys = parsePath(path);
    const next = removeIn(this.#state, keys);
    this.#commit(next === this.#state ? next : markDirty(next, keys));
  }

  batch(fn) {
    this.#depth += 1;
    try {
      fn();
    } finally {
      this.#depth -= 1;
      if (this.#depth === 0 && this.#before !== null) {
        const previous = this.#before;
        this.#before = null;
        this.#emit(previous);
      }
    }
  }

  load(definition) {
    this.#sent = null;
    this.#commit({
      ...initialState(),
      draft: pick(definition, DRAFT_KEYS),
      meta: { ...initialState().meta, ...pick(definition, META_KEYS) },
    });
  }

  markSaved(definition) {
    const sent = this.#sent;
    this.#sent = null;
    const dirty = editedSince(this.#state, sent);
    this.batch(() => {
      this.patch("meta", (meta) => ({ ...meta, ...savedMeta(definition, meta, sent) }), { clean: true });
      this.patch("status", (status) => ({ ...status, dirty, saving: false, error: null }), { clean: true });
    });
  }

  reset(next = initialState()) {
    this.#sent = null;
    this.#commit(next);
  }

  toPayload() {
    const { meta, draft } = this.#state;
    this.#sent = { meta, draft };
    const body = { name: meta.name, description: meta.description, tags: meta.tags, ...pick(draft, DRAFT_KEYS) };
    return meta.id ? { ...body, revision: meta.revision } : body;
  }
}

/**
 * Creates a store; every method is bound, so `const {patch} = store` works.
 * @param {object} [initial]
 * @returns {Store}
 */
export function createStore(initial = initialState()) {
  return new Store(initial);
}
