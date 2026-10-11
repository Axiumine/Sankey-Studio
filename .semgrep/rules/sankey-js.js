// Semgrep rule tests for the front-end sink rule.
function render(el, name) {
  // ruleid: sankey-js-no-dom-xss-sinks
  el.innerHTML = "<b>" + name + "</b>";
  // ruleid: sankey-js-no-dom-xss-sinks
  el.insertAdjacentHTML("beforeend", name);
  // ruleid: sankey-js-no-dom-xss-sinks
  eval(name);
  // ok: sankey-js-no-dom-xss-sinks
  el.textContent = name;
  // ok: sankey-js-no-dom-xss-sinks
  el.innerHTML = "";
}
