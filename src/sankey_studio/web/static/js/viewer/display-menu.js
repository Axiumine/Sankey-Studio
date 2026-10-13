/**
 * The display menu of the viewer's chart card: an icon at the right of the tab row that opens a
 * small panel of switches for what the charts print on themselves.
 *
 * - Sankey: the value under the name of each node.
 * - Donut (only when the graph has a donut): the percentage and/or the value on each slice.
 *
 * The switches are view-only: they are sent with the render and export requests and never change
 * the saved graph. `values` is `{node_values, donut_percent, donut_value}` (booleans); `onChange`
 * receives the changed key and the new boolean. The panel closes on Escape (focus goes back to the
 * icon), on a click elsewhere and when focus leaves it.
 *
 * Test ids: display-menu-button, display-menu-panel, display-node-values, display-donut-percent,
 * display-donut-value.
 */

import { h, uid } from "../core/dom.js";
import { checkbox } from "../core/form.js";
import { icon } from "../core/icons.js";

const GROUPS = [
  {
    id: "sankey",
    title: "Sankey",
    switches: [{ key: "node_values", label: "Show values under the node names", testid: "display-node-values" }],
  },
  {
    id: "donut",
    title: "Donut",
    switches: [
      { key: "donut_percent", label: "Show percentages", testid: "display-donut-percent" },
      { key: "donut_value", label: "Show values", testid: "display-donut-value" },
    ],
  },
];

class DisplayMenu {
  /** @param {{values: object, donut: boolean, onChange: (key: string, on: boolean) => void}} options */
  constructor({ values, donut, onChange }) {
    const panelId = uid("display-panel");
    this.onChange = onChange;
    this.inputs = new Map();
    this.button = h(
      "button",
      {
        type: "button",
        class: "btn btn-ghost btn-icon display-button",
        "aria-label": "Chart display options",
        title: "Chart display options",
        "aria-haspopup": "true",
        "aria-expanded": "false",
        "aria-controls": panelId,
        "data-testid": "display-menu-button",
        on: { click: () => this.toggle() },
      },
      icon("sliders", { size: 16 }),
    );
    this.groups = new Map(GROUPS.map((group) => [group.id, this.buildGroup(group, values)]));
    this.groups.get("donut").hidden = !donut;
    this.panel = h(
      "div",
      { class: "display-panel", id: panelId, role: "group", "aria-label": "Chart display options", hidden: true, "data-testid": "display-menu-panel" },
      [...this.groups.values()],
    );
    this.el = h("div", { class: "display-menu", on: { keydown: (event) => this.onKey(event), focusout: (event) => this.onFocusOut(event) } }, this.button, this.panel);
    this.onOutside = (event) => !this.el.contains(event.target) && this.close();
  }

  buildGroup(group, values) {
    const rows = group.switches.map((spec) => {
      const row = checkbox({ label: spec.label, checked: Boolean(values[spec.key]), "data-testid": spec.testid });
      const input = row.querySelector("input");
      input.addEventListener("change", () => this.onChange(spec.key, input.checked));
      this.inputs.set(spec.key, input);
      return row;
    });
    return h("fieldset", { class: "display-group" }, h("legend", { class: "display-legend" }, group.title), rows);
  }

  isOpen() {
    return !this.panel.hidden;
  }

  toggle() {
    if (this.isOpen()) {
      this.close();
      return;
    }
    this.panel.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    document.addEventListener("pointerdown", this.onOutside);
  }

  close() {
    this.panel.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", this.onOutside);
  }

  onKey(event) {
    if (event.key === "Escape" && this.isOpen()) {
      event.stopPropagation();
      this.close();
      this.button.focus();
    }
  }

  onFocusOut(event) {
    if (this.isOpen() && event.relatedTarget && !this.el.contains(event.relatedTarget)) {
      this.close();
    }
  }

  /** Puts a switch back (a redraw with it failed). */
  set(key, on) {
    this.inputs.get(key).checked = on;
  }

  dispose() {
    document.removeEventListener("pointerdown", this.onOutside);
  }
}

/**
 * Builds the menu.
 * @param {{values: object, donut: boolean, onChange: (key: string, on: boolean) => void}} options
 * @returns {DisplayMenu}
 */
export function createDisplayMenu(options) {
  return new DisplayMenu(options);
}
