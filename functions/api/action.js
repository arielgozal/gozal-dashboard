// Workflow actions. Every action is appended to an audit log in KV.
// Types:
//   move    { id, to, note? }      — move a pipeline item between stages
//   weights { weights: {..} }      — update Ariel's ideation weights
// Stage vocabulary: idea, script, create, create_requested, approve,
//                   approved, rejected, archived

const VALID_STAGES = ["idea", "script", "create", "create_requested", "approve", "approved", "rejected", "archived"];

function authorized(ctx) {
  return ctx.request.headers.get("x-team-key") === ctx.env.TEAM_PASSWORD;
}

export async function onRequestPost(ctx) {
  if (!authorized(ctx)) return new Response("unauthorized", { status: 401 });
  let body;
  try { body = await ctx.request.json(); } catch { return new Response("bad json", { status: 400 }); }
  const kv = ctx.env.ENGINE_KV;
  const now = new Date().toISOString();

  if (body.type === "move") {
    if (!VALID_STAGES.includes(body.to)) return new Response("bad stage", { status: 400 });
    const pipeline = (await kv.get("pipeline", "json")) || { items: [] };
    const item = (pipeline.items || []).find(i => i.id === body.id);
    if (!item) return new Response("no such item", { status: 404 });
    const from = item.stage;
    item.stage = body.to;
    if (body.note) item.notes = ((item.notes || "") + "\n[" + now.slice(0, 10) + "] " + body.note).trim();
    pipeline.updated = now;
    await kv.put("pipeline", JSON.stringify(pipeline));
    await appendLog(kv, { at: now, type: "move", id: body.id, from, to: body.to, note: body.note || null });
    return Response.json({ ok: true });
  }

  if (body.type === "weights") {
    const w = body.weights || {};
    const total = Object.values(w).reduce((a, b) => a + (Number(b) || 0), 0);
    if (total < 95 || total > 105) return new Response("weights must sum to ~100", { status: 400 });
    await kv.put("weights", JSON.stringify({ updated: now, weights: w }));
    await appendLog(kv, { at: now, type: "weights", weights: w });
    return Response.json({ ok: true });
  }

  return new Response("unknown action", { status: 400 });
}

async function appendLog(kv, entry) {
  const log = (await kv.get("log", "json")) || [];
  log.push(entry);
  await kv.put("log", JSON.stringify(log.slice(-500)));
}
