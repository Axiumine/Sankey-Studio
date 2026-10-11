/**
 * Appearance section: the colour theme as three choice cards (System, Light, Dark).
 *
 * The theme applies at once and is saved by core/theme.js `setTheme` (PUT /settings {theme}) when
 * the server allows writes; on a read-only server the choice stays on this device. It is not part
 * of the form's dirty state: like the switch in the page header it is an instant preference, and
 * both stay in step through the `sankey:theme` event. A theme change and the form's Save take
 * turns in one queue (core/theme.js `queueSettingsWrite`), so a change made while a save runs is
 * saved right after it and neither update is lost.
 */

import { announce } from "../core/a11y.js";
import { canWrite } from "../core/boot.js";
import { h, uid } from "../core/dom.js";
import { getTheme, onSystemThemeChange, onThemeChange, setTheme, systemTheme } from "../core/theme.js";
import { toast } from "../core/toast.js";
import { icon } from "../core/icons.js";
import { section } from "./ui.js";

const OPTIONS = [
  { value: "system", label: "System", icon: "monitor", text: "Follows your device." },
  { value: "light", label: "Light", icon: "sun", text: "Dark text on a light page." },
  { value: "dark", label: "Dark", icon: "moon", text: "Light text on a dark page." },
];

function choice(option, onPick) {
  const labelId = uid("theme-label");
  const textId = uid("theme-text");
  const input = h("input", {
    type: "radio",
    class: "choice-input",
    name: "settings-theme",
    value: option.value,
    "aria-labelledby": labelId,
    "aria-describedby": textId,
    "data-testid": "settings-theme-option",
    on: { change: () => onPick(option.value) },
  });
  const text = h("span", { class: "choice-text", id: textId }, option.text);
  const body = h(
    "span",
    { class: "choice-body" },
    h("span", { class: "choice-icon" }, icon(option.icon, { size: 20 })),
    h("span", { class: "choice-label", id: labelId }, option.label),
    text,
  );
  return { input, text, el: h("label", { class: "choice" }, input, body) };
}

function describeSystem() {
  return `Follows your device (now ${systemTheme()}).`;
}

/**
 * Builds the section.
 * @returns {{el: HTMLElement}}
 */
export function buildAppearance() {
  const status = h("p", { class: "hint", hidden: true });
  const say = (text) => {
    status.textContent = text;
    status.hidden = text === "";
    announce(text);
  };
  const choices = OPTIONS.map((option) => choice(option, (value) => pick(value)));

  const reflect = () => {
    for (const item of choices) {
      item.input.checked = item.input.value === getTheme();
    }
    choices[0].text.textContent = describeSystem();
  };

  async function pick(value) {
    const result = await setTheme(value);
    if (result.error) {
      toast.info(`Theme not saved, so it lasts until you reload. ${result.error.friendly ?? result.error.message}`);
      say("Applied, but not saved.");
    } else {
      say(canWrite() ? "Theme saved." : "Kept on this device only: this server is read-only.");
    }
  }

  onThemeChange(reflect);
  onSystemThemeChange(reflect);
  reflect();
  const group = h(
    "fieldset",
    { class: "choice-group" },
    h("legend", { class: "visually-hidden" }, "Colour theme"),
    choices.map((item) => item.el),
  );
  const el = section({
    id: "settings-appearance",
    title: "Appearance",
    text: "Choose how Sankey Studio and its charts look.",
    body: [group, status],
  });
  return { el };
}
