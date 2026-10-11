/**
 * DOM helpers: the only way pages build markup.
 *
 * Contract
 * - `h(tag, props, ...children)` builds elements with createElement/setAttribute/createTextNode
 *   only. Every string child is a text node, so user text (graph names, categories, node names,
 *   file names, error messages) can never become markup.
 * - Props: `class` (string or array), `dataset` (object), `on` (object of event handlers),
 *   `style` (object of CSS properties, custom properties allowed), `value`/`checked`/`selected`/
 *   `indeterminate` (set as properties), HTML boolean attributes (true = present, false = absent),
 *   `aria-*` and `data-*` (any value is stringified), everything else is setAttribute. Attributes
 *   named `on...` and URL attributes with a scripting scheme are refused.
 * - Children: strings and numbers (text), Nodes, arrays (flattened); null, undefined and booleans
 *   are skipped, so `cond && h(...)` works.
 * - `createScope()` collects listeners and cleanups so a page or panel can dispose them at once.
 * - Text and attribute strings lose bidirectional override/embedding/isolate characters (text.js
 *   `stripBidi`): U+202E in a graph name must not reverse nearby words. An input's `value` is
 *   not touched: it is what the user is editing.
 * - Focus helpers (`focusable`, `focusFirst`, `trapFocus`) live in focus.js and are re-exported.
 */

import { stripBidi } from "./text.js";

export { focusable, focusFirst, trapFocus } from "./focus.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const HTML_BOOLEAN = new Set([
  "disabled", "hidden", "required", "readonly", "multiple", "autofocus", "open", "inert",
  "novalidate",
]);
const PROPERTY_KEYS = new Set(["value", "checked", "selected", "indeterminate"]);
const URL_ATTRS = new Set(["href", "src", "action", "formaction", "poster"]);

let counter = 0;
const focusHeld = new WeakSet();

/**
 * Returns `value` when it is safe to put in an href/src attribute: a relative URL, http(s), blob:
 * or an image data: URL. Anything else (scripting schemes, protocol-relative hosts) becomes
 * `about:blank`.
 * @param {string} value
 * @returns {string}
 */
export function safeUrl(value) {
  const text = String(value);
  const probe = text.replace(/[\u0000- \u007f]/g, "").toLowerCase();
  if (probe.startsWith("//")) {
    return "about:blank";
  }
  const scheme = /^([a-z][a-z0-9+.-]*):/.exec(probe);
  if (!scheme) {
    return text;
  }
  const allowed = ["http", "https", "blob"].includes(scheme[1]) || probe.startsWith("data:image/");
  return allowed ? text : "about:blank";
}

function setStyle(el, styles) {
  for (const [name, value] of Object.entries(styles)) {
    if (value != null) {
      el.style.setProperty(name, String(value));
    }
  }
}

function setSpecial(el, key, value) {
  if (key === "class" || key === "className") {
    el.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
  } else if (key === "dataset") {
    for (const [name, item] of Object.entries(value)) {
      if (item != null) {
        el.dataset[name] = String(item);
      }
    }
  } else if (key === "style") {
    setStyle(el, value);
  } else if (key === "on") {
    for (const [type, handler] of Object.entries(value)) {
      el.addEventListener(type, handler);
    }
  } else {
    return false;
  }
  return true;
}

function setAttr(el, key, value) {
  if (key.startsWith("aria-") || key.startsWith("data-")) {
    el.setAttribute(key, stripBidi(value));
  } else if (HTML_BOOLEAN.has(key)) {
    el.toggleAttribute(key, value !== false);
  } else if (URL_ATTRS.has(key)) {
    el.setAttribute(key, safeUrl(stripBidi(value)));
  } else {
    el.setAttribute(key === "htmlFor" ? "for" : key, value === true ? "" : stripBidi(value));
  }
}

/** Sets the attributes now and returns the property assignments to make once children exist. */
function applyProps(el, props) {
  const deferred = [];
  for (const [key, value] of Object.entries(props ?? {})) {
    if (/^on/i.test(key) && key !== "on") {
      throw new TypeError(`Attribute "${key}" is not allowed; pass handlers in the "on" prop`);
    }
    if (value == null || (value === false && !/^(aria|data)-/.test(key) && !PROPERTY_KEYS.has(key))) {
      continue;
    }
    if (PROPERTY_KEYS.has(key) && key in el) {
      deferred.push([key, value]);
    } else if (!setSpecial(el, key, value)) {
      setAttr(el, key, value);
    }
  }
  return deferred;
}

function build(el, props, children) {
  const deferred = applyProps(el, props);
  el.append(...toNodes(children));
  for (const [key, value] of deferred) {
    el[key] = value;
  }
  return el;
}

/**
 * Turns children (text, nodes, nested arrays) into a flat list of Nodes.
 * @param {unknown[]} children
 * @returns {Node[]}
 */
export function toNodes(children) {
  const out = [];
  for (const child of children) {
    if (child == null || typeof child === "boolean") {
      continue;
    }
    if (Array.isArray(child)) {
      out.push(...toNodes(child));
    } else {
      out.push(child instanceof Node ? child : document.createTextNode(stripBidi(child)));
    }
  }
  return out;
}

/**
 * Builds an HTML element.
 * @param {string} tag
 * @param {Record<string, unknown> | null} [props]
 * @param {...unknown} children
 * @returns {HTMLElement}
 */
export function h(tag, props, ...children) {
  return build(document.createElement(tag), props, children);
}

/**
 * Builds an SVG element (same props and children rules as `h`).
 * @param {string} tag
 * @param {Record<string, unknown> | null} [props]
 * @param {...unknown} children
 * @returns {SVGElement}
 */
export function svg(tag, props, ...children) {
  return build(document.createElementNS(SVG_NS, tag), props, children);
}

/**
 * A DocumentFragment holding the children.
 * @param {...unknown} children
 * @returns {DocumentFragment}
 */
export function fragment(...children) {
  const frag = document.createDocumentFragment();
  frag.append(...toNodes(children));
  return frag;
}

/**
 * Removes every child of `node`.
 * @param {Node} node
 * @returns {Node}
 */
export function clear(node) {
  node.replaceChildren();
  return node;
}

/**
 * Replaces the content of `parent` with the children.
 * @param {Node} parent
 * @param {...unknown} children
 * @returns {Node}
 */
export function mount(parent, ...children) {
  parent.replaceChildren(...toNodes(children));
  return parent;
}

/**
 * First element matching `selector` below `root`, or null.
 * @param {string} selector
 * @param {ParentNode} [root]
 * @returns {Element | null}
 */
export function qs(selector, root = document) {
  return root.querySelector(selector);
}

/**
 * Every element matching `selector` below `root` as an array.
 * @param {string} selector
 * @param {ParentNode} [root]
 * @returns {Element[]}
 */
export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

/**
 * The element whose data-testid attribute equals `id`, below `root`, or null.
 * @param {string} id
 * @param {ParentNode} [root]
 * @returns {Element | null}
 */
export function byTestId(id, root = document) {
  return root.querySelector(`[data-testid="${CSS.escape(id)}"]`);
}

/**
 * Adds a listener and returns the function that removes it.
 * @param {EventTarget} target
 * @param {string} type
 * @param {EventListener} handler
 * @param {AddEventListenerOptions | boolean} [options]
 * @returns {() => void}
 */
export function on(target, type, handler, options) {
  target.addEventListener(type, handler, options);
  return () => target.removeEventListener(type, handler, options);
}

/**
 * A disposable bag of listeners and cleanups: `scope.on(...)`, `scope.add(cleanup)`,
 * `scope.dispose()` (runs everything once, newest first, and never throws).
 * @returns {{on: typeof on, add: (fn: () => void) => () => void, dispose: () => void}}
 */
export function createScope() {
  const cleanups = [];
  return {
    on(target, type, handler, options) {
      const off = on(target, type, handler, options);
      cleanups.push(off);
      return off;
    },
    add(cleanup) {
      cleanups.push(cleanup);
      return cleanup;
    },
    dispose() {
      while (cleanups.length > 0) {
        try {
          cleanups.pop()();
        } catch {
          // one failing cleanup must not keep the others from running
        }
      }
    },
  };
}

/**
 * A page-unique id such as `field-3`, for label/aria wiring.
 * @param {string} [prefix]
 * @returns {string}
 */
export function uid(prefix = "id") {
  counter += 1;
  return `${prefix}-${counter}`;
}

/**
 * Toggles the busy state (aria-busy, `is-busy` spinner); a focused button gets its focus back after.
 * @param {HTMLElement} el
 * @param {boolean} busy
 */
export function setBusy(el, busy) {
  const hadFocus = document.activeElement === el;
  el.classList.toggle("is-busy", busy);
  el.toggleAttribute("aria-busy", busy);
  if ("disabled" in el) {
    el.disabled = busy;
  }
  if (busy && hadFocus) {
    focusHeld.add(el); // a disabled control drops focus to <body>: give it back when the work is done
  } else if (!busy && focusHeld.delete(el) && document.activeElement === document.body) {
    el.focus();
  }
}
