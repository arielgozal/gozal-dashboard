// Nano Banana (Google Gemini image generation) for the Studio tab and the
// studio worker's nano-banana creator. Needs the GEMINI_API_KEY secret:
//   npx wrangler pages secret put GEMINI_API_KEY --project-name gozal-engine
// GET  -> { configured }   (is the key set?)
// POST -> { prompt, count?, aspect? } -> { ok, images: [{ mime, data(base64) }] }

const MODEL = "gemini-2.5-flash-image";
const API = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent`;
const ASPECTS = ["1:1", "9:16", "16:9", "4:5", "3:4", "4:3"];

function authorized(ctx) {
  return ctx.request.headers.get("x-team-key") === ctx.env.TEAM_PASSWORD;
}

export async function onRequestGet(ctx) {
  if (!authorized(ctx)) return new Response("unauthorized", { status: 401 });
  return Response.json({ configured: Boolean(ctx.env.GEMINI_API_KEY), model: MODEL });
}

export async function onRequestPost(ctx) {
  if (!authorized(ctx)) return new Response("unauthorized", { status: 401 });
  if (!ctx.env.GEMINI_API_KEY) {
    return Response.json({ ok: false, error: "GEMINI_API_KEY isn't set on the Cloudflare project yet — see the Studio tab for setup." });
  }
  let body;
  try { body = await ctx.request.json(); } catch { return new Response("bad json", { status: 400 }); }
  const prompt = String(body.prompt || "").trim();
  if (!prompt) return Response.json({ ok: false, error: "empty prompt" });
  const count = Math.min(Math.max(Number(body.count) || 1, 1), 4);
  const aspect = ASPECTS.includes(body.aspect) ? body.aspect : null;

  const results = await Promise.all(
    Array.from({ length: count }, () => generateOne(ctx.env.GEMINI_API_KEY, prompt, aspect))
  );
  const images = results.filter(r => r.image).map(r => r.image);
  const errors = results.filter(r => r.error).map(r => r.error);
  if (!images.length) {
    return Response.json({ ok: false, error: errors[0] || "the model returned no image — try rephrasing the prompt" });
  }
  return Response.json({ ok: true, images, failed: errors.length || undefined });
}

async function generateOne(key, prompt, aspect) {
  const contents = [{ parts: [{ text: prompt }] }];
  const withAspect = aspect
    ? { contents, generationConfig: { imageConfig: { aspectRatio: aspect } } }
    : { contents };
  let r = await callGemini(key, withAspect);
  // if the aspect config is rejected by the API, retry without it
  if (!r.ok && aspect) r = await callGemini(key, { contents });
  if (!r.ok) return { error: `Gemini ${r.status}: ${(await r.text()).slice(0, 300)}` };
  const data = await r.json();
  const parts = data.candidates?.[0]?.content?.parts || [];
  for (const p of parts) {
    const inline = p.inlineData || p.inline_data;
    if (inline?.data) {
      return { image: { mime: inline.mimeType || inline.mime_type || "image/png", data: inline.data } };
    }
  }
  const text = parts.map(p => p.text).filter(Boolean).join(" ").slice(0, 300);
  return { error: text || "no image in the response" };
}

function callGemini(key, body) {
  return fetch(API, {
    method: "POST",
    headers: { "x-goog-api-key": key, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
