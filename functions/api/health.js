// Unauthenticated: lets the front end detect it's running on the interactive deployment.
export async function onRequestGet() {
  return Response.json({ ok: true, mode: "interactive" });
}
