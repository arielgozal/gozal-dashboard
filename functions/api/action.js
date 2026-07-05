// Workflow actions. Every action is appended to an audit log in KV.
// Types:
//   move       { id, to, note? }          — move a pipeline item between stages
//   update     { id, fields: {..} }       — edit item content (whitelisted fields)
//   weights    { weights: {..} }          — update ideation weights (auto-normalized to 100)
//   draw_ideas { count? }                 — pull fresh ideas from the pool onto the Ideas board
//   add_pool   { items: [..] }            — refill the idea pool (used by the daily agent)
// Stage vocabulary: idea, script, create, create_requested, approve,
//                   approved, rejected, archived

const VALID_STAGES = ["idea", "script", "create", "create_requested", "approve", "approved", "rejected", "archived"];
const UPDATE_FIELDS = ["title", "hook", "notes", "caption", "scripts", "asset_url", "platforms", "audience", "pillar", "platform"];
const RAW = "https://raw.githubusercontent.com/arielgozal/gozal-dashboard/main/data/";

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

  if (body.type === "update") {
    const pipeline = (await kv.get("pipeline", "json")) || { items: [] };
    const item = (pipeline.items || []).find(i => i.id === body.id);
    if (!item) return new Response("no such item", { status: 404 });
    const applied = {};
    for (const [k, v] of Object.entries(body.fields || {})) {
      if (UPDATE_FIELDS.includes(k)) { item[k] = v; applied[k] = true; }
    }
    pipeline.updated = now;
    await kv.put("pipeline", JSON.stringify(pipeline));
    await appendLog(kv, { at: now, type: "update", id: body.id, fields: Object.keys(applied) });
    return Response.json({ ok: true, applied: Object.keys(applied) });
  }

  if (body.type === "weights") {
    const raw = body.weights || {};
    const total = Object.values(raw).reduce((a, b) => a + (Number(b) || 0), 0);
    if (total <= 0) return new Response("weights are all zero", { status: 400 });
    // auto-normalize so any slider combination saves
    const w = {};
    for (const [k, v] of Object.entries(raw)) w[k] = Math.round((Number(v) || 0) / total * 100);
    await kv.put("weights", JSON.stringify({ updated: now, weights: w }));
    await appendLog(kv, { at: now, type: "weights", weights: w });
    return Response.json({ ok: true, weights: w });
  }

  if (body.type === "draw_ideas") {
    const count = Math.min(Math.max(Number(body.count) || 3, 1), 6);
    let pool = await kv.get("idea_pool", "json");
    if (!pool) {
      const r = await fetch(RAW + "idea_pool.json", { cf: { cacheTtl: 0 } });
      pool = r.ok ? await r.json() : { items: [] };
    }
    const drawn = (pool.items || []).splice(0, count);
    if (!drawn.length) return Response.json({ ok: false, reason: "pool empty — the daily agent refills it, or ask Claude for a fresh batch" });
    const pipeline = (await kv.get("pipeline", "json")) || { items: [] };
    for (const d of drawn) {
      d.stage = "idea";
      d.created = now.slice(0, 10);
      if (!d.id) d.id = "idea-" + Math.random().toString(36).slice(2, 8);
      pipeline.items.push(d);
    }
    pipeline.updated = now;
    await kv.put("pipeline", JSON.stringify(pipeline));
    await kv.put("idea_pool", JSON.stringify(pool));
    await appendLog(kv, { at: now, type: "draw_ideas", count: drawn.length });
    return Response.json({ ok: true, drawn: drawn.length, pool_left: (pool.items || []).length });
  }

  if (body.type === "add_pool") {
    let pool = (await kv.get("idea_pool", "json")) || { items: [] };
    const items = (body.items || []).filter(i => i && i.title && i.audience);
    pool.items.push(...items);
    await kv.put("idea_pool", JSON.stringify(pool));
    await appendLog(kv, { at: now, type: "add_pool", count: items.length });
    return Response.json({ ok: true, pool_size: pool.items.length });
  }

  return new Response("unknown action", { status: 400 });
}

async function appendLog(kv, entry) {
  const log = (await kv.get("log", "json")) || [];
  log.push(entry);
  await kv.put("log", JSON.stringify(log.slice(-500)));
}
