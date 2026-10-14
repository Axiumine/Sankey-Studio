const cat = (category, extra = {}) => ({ source: "a", target: "b", category, ...extra });
{
  const f = fakes({ "/edits/plan": () => ok({ where: "draft", source: { type: "text", origin: "inline", content: "NEW" }, override: "drop", changed: 1 }) },
    { draft: { ...inline(), transform: { entry_categories: [{ source: "a", target: "b", category: "Old" }] } } });
  const result = await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  out.draftPath = { result: { ok: result.ok, where: result.where }, content: state(f).source.content, categories: state(f).transform.entry_categories, toasts: f.toasts, body: f.calls[0][1].edit, dirty: f.store.get().status.dirty, asked: f.asked };
}
{
  const f = fakes({ "/edits/plan": async () => { f.store.patch(["draft", "source"], { type: "manual", links: [] }); return ok({ where: "draft", source: { type: "manual", links: [{}] } }); } }, { draft: inline() });
  const result = await f.engine.setCategory({ source: "a", target: "b" }, null);
  out.stale = { result, toasts: f.toasts, source: state(f).source };
}
{
  const f = fakes({ "/edits/plan": () => ok({ reason: "aggregate_mode", notice: "Stays here." }), "/entries": () => ({}) }, { draft: mongo() });
  const one = await f.engine.setCategory({ source: "a", target: "b" }, "K");
  const two = await f.engine.setCategory({ source: "c", target: "d" }, "L");
  out.overlay = { ok: [one.ok, two.ok], where: one.where, notice: one.notice, toasts: f.toasts, categories: state(f).transform.entry_categories, paths: f.calls.map((c) => c[0]), validate: f.calls[1][2] };
}
{
  const f = fakes({ "/edits/plan": () => ok({ reason: "preference" }), "/entries": () => { throw Object.assign(new Error("x"), { friendly: "Cycle." }); } }, { draft: file() });
  const result = await f.engine.setCategory({ source: "a", target: "b" }, "K");
  out.overlayRefused = { result, categories: state(f).transform.entry_categories ?? [], toasts: f.toasts };
}
{
  const f = fakes({}, { draft: file({ path: null }) });
  out.blocked = [await f.engine.setCategory({ source: "a", target: "b" }, "K"), f.calls.length];
}
const askPlan = (extra) => ok({ where: "file", consent: "ask", target: "x.csv", target_key: "file:x.csv", changed: 1, ...extra });
const written = (extra) => ok({ where: "file", written: true, changed: 1, target: "x.csv", ...extra });
const fileFlow = async (answer, extra = {}) => {
  events.splice(0);
  const f = fakes({
    "/edits/plan": () => askPlan(extra.plan), "/edits/write": () => written(extra.write), "/entries": () => ({}),
  }, { draft: file(), answer });
  const result = await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  const paths = f.calls.map((call) => call[0]);
  const sent = f.calls.find((call) => call[0] === "/edits/write");
  return { result, paths, pref: state(f).source.write_back, sent: sent ? sent[1].draft.source.write_back : "no write", asked: f.asked, toasts: f.toasts, categories: state(f).transform.entry_categories ?? [], events: events.splice(0) };
};
out.accept = await fileFlow("accept");
out.acceptPins = await (async () => {
  const f = fakes({ "/edits/plan": () => askPlan(), "/edits/write": () => written({ source: { type: "text", origin: "file", path: "x.csv", category_column: 3 }, override: "drop" }) }, { draft: file(), answer: "accept" });
  await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  return state(f).source;
})();
out.decline = await fileFlow("decline");
out.never = await fileFlow("never");
out.cancel = await fileFlow(null);
out.granted = await (async () => {
  const f = fakes({ "/edits/plan": () => askPlan({ consent: "granted" }), "/edits/write": () => written({ changed: 2 }) }, { draft: file() });
  const result = await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  return { result, asked: f.asked, paths: f.calls.map((c) => c[0]), toasts: f.toasts, touched: f.store.get().status.dirty };
})();
out.mongoWrite = await (async () => {
  const f = fakes({ "/edits/plan": () => askPlan({ where: "mongo", consent: "granted", target: "main / db.t" }), "/edits/write": () => written({ where: "mongo", changed: 1, target: "main / db.t" }) }, { draft: mongo() });
  await f.engine.addEntry({ source: "a", target: "b", value: 5 });
  return f.toasts;
})();
out.writeRefused = await fileFlow("accept", { write: { where: "graph", written: false, reason: "no_match", notice: "No row matches.", changed: 0 } });
out.writeFails = await (async () => {
  const f = fakes({ "/edits/plan": () => askPlan({ consent: "granted" }), "/edits/write": () => { throw Object.assign(new Error("x"), { friendly: "Could not write." }); } }, { draft: file() });
  const result = await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  return { result, categories: state(f).transform.entry_categories ?? [], toasts: f.toasts };
})();
{
  const f = fakes({ "/edits/plan": () => ok({ where: "draft", source: { type: "manual", links: [{ source: "a", target: "b", value: 1 }, { source: "x", target: "y", value: 4 }] } }) }, { draft: manual() });
  const first = state(f).source;
  const result = await f.engine.addEntry({ source: "x", target: "y", value: 4 });
  const action = f.toasts.find((t) => t[2] === "Undo");
  const after = state(f).source.links.length;
  result.undo();
  out.addDraft = { ok: result.ok, after, undone: state(f).source === first, toasts: f.toasts, action: Boolean(action), body: f.calls[0][1].edit };
}
{
  const f = fakes({ "/edits/plan": () => ok({ reason: "aggregate_mode", notice: "Stays." }), "/entries": () => ({}) }, { draft: mongo() });
  const result = await f.engine.addEntry({ source: "x", target: "y", value: 4, category: "K" });
  const links = state(f).transform.extra_links;
  result.undo();
  out.addOverlay = { links, undone: state(f).transform.extra_links ?? null, toasts: f.toasts.map((t) => t.slice(0, 2)) };
}
{
  const draft = { ...inline(), transform: { extra_links: new Array(local.EXTRA_LINKS_MAX).fill({ source: "a", target: "b", value: 1 }) } };
  const f = fakes({ "/edits/plan": () => ok({ reason: "aggregate_mode" }) }, { draft });
  const result = await f.engine.addEntry({ source: "x", target: "y", value: 4 });
  out.addCap = { ok: result.ok, message: result.message };
}
{
  const f = fakes({ "/edits/plan": () => ok({ where: "draft", source: { type: "manual", links: [] } }) }, { draft: manual() });
  const result = await f.engine.reorder(["b", "a"]);
  out.reorderDraft = { order: state(f).style.node_order, links: state(f).source.links, toasts: f.toasts, undo: typeof result.undo };
  result.undo();
  out.reorderUndo = { order: state(f).style.node_order, links: state(f).source.links.length };
}
{ // a reorder that moved colour slots: the server's pins are merged with the new rows, one Undo takes both back
  const pins = { node_colors: { a: "#111111", b: "#333333" }, category_colors: { Red: "#222222" } };
  const draft = { ...manual(), style: { node_colors: { b: "#999999" } } };
  const f = fakes({ "/edits/plan": () => ok({ where: "draft", source: { type: "manual", links: [{}] }, pins }) }, { draft });
  const result = await f.engine.reorder(["b", "a"]);
  const applied = { colors: state(f).style.node_colors, categories: state(f).style.category_colors, links: state(f).source.links.length };
  result.undo();
  out.reorderPins = { applied, toasts: f.toasts.map((t) => t.slice(0, 2)), undone: { colors: state(f).style.node_colors, categories: state(f).style.category_colors ?? null, order: state(f).style.node_order ?? null } };
}
{ // one pin says "colour", several say "colours"; a file written without a new spec still gets its pins
  const f = fakes({ "/edits/plan": () => ok({ where: "file", consent: "granted" }), "/edits/write": () => ok({ where: "file", written: true, pins: { node_colors: { a: "#111111" } } }) }, { draft: file() });
  await f.engine.reorder(["b", "a"]);
  out.reorderFilePins = { colors: state(f).style.node_colors, source: state(f).source.path, toasts: f.toasts.map((t) => t[1]) };
}
{ // a plan that needs no pins pins nothing (an empty object, or none at all)
  const f = fakes({ "/edits/plan": () => ok({ where: "draft", source: { type: "manual", links: [] }, pins: { node_colors: {} } }) }, { draft: manual() });
  await f.engine.reorder(["b", "a"]);
  out.reorderNoPins = { style: state(f).style, toasts: f.toasts.map((t) => t[0]) };
}
{ // Undo undoes ONLY its own edit: a later edit of the same part makes the older Undo refuse (and the older toast goes away)
  const f = fakes({ "/edits/plan": () => ok({ reason: "aggregate_mode" }), "/entries": () => ({}) }, { draft: mongo() });
  const first = await f.engine.addEntry({ source: "x", target: "y", value: 4 });
  const second = await f.engine.addEntry({ source: "p", target: "q", value: 5 });
  first.undo();
  const kept = state(f).transform.extra_links.map((link) => link.source);
  second.undo();
  out.undoOwn = { kept, left: state(f).transform.extra_links.length, dismissed: f.dismissed, toasts: f.toasts.map((t) => t.slice(0, 2)) };
}
{ // an edit of ANOTHER part in between (a category) stays when the entry is undone
  const f = fakes({ "/edits/plan": () => ok({ reason: "aggregate_mode" }), "/entries": () => ({}) }, { draft: mongo() });
  const added = await f.engine.addEntry({ source: "x", target: "y", value: 4 });
  await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  added.undo();
  out.undoOther = { links: state(f).transform.extra_links ?? null, categories: (state(f).transform.entry_categories ?? []).map((item) => item.category) };
}
{ // two drags in a row: the visible Undo (the second toast's) takes back the second drag only; the first one cannot be undone any more
  const f = fakes({}, { draft: mongo() });
  const first = await f.engine.reorder(["c", "b", "a"]);
  const second = await f.engine.reorder(["a", "c", "b"]);
  first.undo();
  const refused = state(f).style.node_order;
  second.undo();
  out.undoDrags = { refused, restored: state(f).style.node_order, dismissed: f.dismissed.length, undos: f.undos.length };
}
{
  const f = fakes({}, { draft: mongo() });
  await f.engine.reorder(["b", "a"]);
  out.reorderMongo = { order: state(f).style.node_order, calls: f.calls.length };
}
{
  const f = fakes({ "/edits/plan": () => ok({ where: "file", consent: "granted", target_key: "file:x.csv" }), "/edits/write": () => ok({ where: "file", written: true, source: { type: "text", origin: "file", path: "x.csv", write_back: null } }) }, { draft: file() });
  await f.engine.reorder(["b", "a"]);
  out.reorderFile = { order: state(f).style.node_order, toasts: f.toasts.map((t) => t[1]), paths: f.calls.map((c) => c[0]), events: events.splice(0) };
}
{
  const f = fakes({ "/edits/plan": () => ok({ where: "file", consent: "granted" }), "/edits/write": () => ok({ reason: "write_rejected" }) }, { draft: file() });
  await f.engine.reorder(["b", "a"]);
  out.reorderKept = f.toasts.map((t) => t[1]);
}
{
  const f = fakes({ "/edits/plan": () => { throw new Error("down"); } }, { draft: file() });
  await f.engine.reorder(["b", "a"]);
  out.reorderDown = { order: state(f).style.node_order, toasts: f.toasts.map((t) => t[1]) };
  const g = fakes({ "/edits/plan": () => { throw new Error("down"); } }, { draft: inline() });
  await g.engine.reorder(["q"]);
  out.reorderDownDraft = { order: state(g).style.node_order, toasts: g.toasts.map((t) => t[1]) };
}
{
  const f = fakes({ "/edits/plan": () => ok({ reason: "would_recolour", notice: "Rows were not reordered." }) }, { draft: manual() });
  await f.engine.reorder(["b", "a"]);
  await f.engine.reorder(["a", "b"]);
  out.reorderRecolour = { order: state(f).style.node_order, toasts: f.toasts.filter((t) => t[0] === "info").length };
  const reset = await f.engine.resetOrder();
  out.reset = { ok: reset.ok, order: state(f).style.node_order };
}
{
  const order = [];
  const f = fakes({ "/edits/plan": async (body) => { order.push(`start ${body.edit.category}`); await new Promise((r) => setTimeout(r, body.edit.category === "1" ? 20 : 1)); order.push(`end ${body.edit.category}`); return ok({ reason: "preference" }); }, "/entries": () => ({}) }, { draft: file() });
  await Promise.all([f.engine.setCategory({ source: "a", target: "b" }, "1"), f.engine.setCategory({ source: "c", target: "d" }, "2")]);
  out.queue = order;
}
{
  const f = fakes({ "/edits/plan": () => ok({ where: "draft", source: { type: "manual", links: [] } }) }, { draft: manual() });
  f.store.patch("bundle", { entries: [{ source: "a", target: "b", category: null }, { source: "c", target: "d", category: null }], entries_total: 2 });
  await f.engine.setCategory({ source: "a", target: "b" }, "Fun");
  await f.engine.setCategory({ source: "c", target: "d" }, "Fun");
  out.hinted = f.toasts.filter((t) => t[2] === "Show them").map((t) => t[1]);
}
