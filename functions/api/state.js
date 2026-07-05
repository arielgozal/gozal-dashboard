// Engine state: pipeline / weights / aso live in Cloudflare KV.
// Seeded from the GitHub repo's data/*.json on first read.
// Metrics/signals/history stay in GitHub (written by Actions crons) and are
// fetched by the front end directly — this API only owns the workflow state.

const KEYS = ["pipeline", "weights", "aso"];
const RAW = "https://raw.githubusercontent.com/arielgozal/gozal-dashboard/main/data/";

function authorized(ctx) {
  return ctx.request.headers.get("x-team-key") === ctx.env.TEAM_PASSWORD;
}

export async function onRequestGet(ctx) {
  if (!authorized(ctx)) return new Response("unauthorized", { status: 401 });
  const out = {};
  for (const k of KEYS) {
    let v = await ctx.env.ENGINE_KV.get(k, "json");
    if (!v) {
      const r = await fetch(RAW + k + ".json", { cf: { cacheTtl: 0 } });
      if (r.ok) {
        v = await r.json();
        await ctx.env.ENGINE_KV.put(k, JSON.stringify(v));
      }
    }
    out[k] = v;
  }
  // idea pool size for the "new ideas" button
  let pool = await ctx.env.ENGINE_KV.get("idea_pool", "json");
  if (!pool) {
    const r = await fetch(RAW + "idea_pool.json", { cf: { cacheTtl: 0 } });
    if (r.ok) {
      pool = await r.json();
      await ctx.env.ENGINE_KV.put("idea_pool", JSON.stringify(pool));
    }
  }
  out.pool_count = pool ? (pool.items || []).length : 0;
  return Response.json(out);
}
