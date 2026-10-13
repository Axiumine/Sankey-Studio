/**
 * Viewer page: one saved graph with its Sankey and (when entries have categories) donut chart,
 * legend and tables, numbers, warnings, and the export panel. Everything lives in js/viewer/.
 */

import { boot, pageActions, pageRoot } from "../core/boot.js";
import { mount } from "../core/dom.js";
import { errorState } from "../core/states.js";
import { ensureStyles } from "../library/styles.js";
import { startViewer } from "../viewer/controller.js";

const { graph } = boot();

await ensureStyles(new URL("../../css/pages-viewer.css", import.meta.url).href);
if (graph && typeof graph.id === "string") {
  startViewer({ graph, root: pageRoot(), actionsRoot: pageActions() });
} else {
  mount(pageRoot(), errorState({ title: "No graph to show", message: "The page did not receive a graph. Open one from the library." }));
}
