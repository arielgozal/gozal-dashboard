"""
Gozal Engine — studio worker.
Picks up items Ariel explicitly queued with the CREATE button
(stage == create_requested), generates the asset — Higgsfield video or
Nano Banana photos, depending on the item's chosen creator — attaches
the result, and moves the item to the Approve board. Never runs for
anything Ariel didn't CREATE.

Runs in GitHub Actions every 15 minutes (studio-worker.yml).
Env: HF_API_KEY, HF_API_SECRET, ENGINE_TEAM_KEY.
"""

import base64
import json
import os
import pathlib
import subprocess
import time
import urllib.request

ENGINE = "https://gozal-engine.pages.dev"
HF_BASE = "https://platform.higgsfield.ai"
MODEL = "kling-video/v3.0/pro/text-to-video"
VIDEO_PLATFORMS = ("TikTok", "Instagram Reels", "YouTube Shorts")

TEAM_KEY = os.environ["ENGINE_TEAM_KEY"]
HF_AUTH = f"Key {os.environ['HF_API_KEY']}:{os.environ['HF_API_SECRET']}"
UA = "gozal-studio-worker/1.0"


def engine(path, payload=None):
    req = urllib.request.Request(
        ENGINE + path,
        data=json.dumps(payload).encode() if payload else None,
        headers={"x-team-key": TEAM_KEY, "content-type": "application/json",
                 "User-Agent": "Mozilla/5.0 (gozal-studio-worker)"},
        method="POST" if payload else "GET",
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def hf(path, payload=None):
    req = urllib.request.Request(
        HF_BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": HF_AUTH, "content-type": "application/json", "User-Agent": UA},
        method="POST" if payload is not None else "GET",
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read()), None
    except urllib.error.HTTPError as e:
        return None, f"{e.code}: {e.read().decode()[:300]}"


def build_prompt(item):
    return (
        "Realistic vertical phone-footage style short video, handheld feel, natural lighting, "
        "warm authentic tone, real-looking people, no text overlays, no logos. "
        f"Story: {item.get('title')}. Opening tension: {item.get('hook')} "
        f"Direction notes: {item.get('notes', '')} "
        "Resolution of the story: the person opens a bright yellow app on their phone, connects "
        "directly with a local professional, and the problem is solved; end on visible relief."
    )


def extract_url(resp):
    # v2 responses: {jobs: [{results: {raw: {url}}}]} or {results: {raw: {url}}}
    for job in resp.get("jobs") or []:
        raw = ((job.get("results") or {}).get("raw") or {})
        if raw.get("url"):
            return raw["url"]
    raw = ((resp.get("results") or {}).get("raw") or {})
    return raw.get("url")


def creator_of(item):
    if item.get("creator"):
        return item["creator"]
    plats = item.get("platforms") or [item.get("platform")]
    return "higgsfield" if any(p in VIDEO_PLATFORMS for p in plats) else "claude-image"


def banana_prompt(item):
    return (
        "Photorealistic candid smartphone-style photo for a social post, natural light, "
        "authentic real people, believable home-service scene, no text, no logos, no watermarks. "
        f"Scene: {item.get('title')}. Moment of tension: {item.get('hook')} "
        f"Notes: {item.get('notes', '')} "
        "One subtle detail: a phone screen showing a bright yellow app."
    )


def banana_aspect(item):
    plats = item.get("platforms") or [item.get("platform")]
    return "9:16" if any(p in VIDEO_PLATFORMS for p in plats) else "1:1"


def commit_assets(item_id, images):
    """Write generated images into assets/<id>/ and push, returning raw URLs."""
    d = pathlib.Path("assets") / item_id
    d.mkdir(parents=True, exist_ok=True)
    urls = []
    for i, img in enumerate(images, 1):
        ext = "jpg" if "jpeg" in (img.get("mime") or "") else "png"
        f = d / f"banana-{i}.{ext}"
        f.write_bytes(base64.b64decode(img["data"]))
        urls.append(f"https://raw.githubusercontent.com/arielgozal/gozal-dashboard/main/{f.as_posix()}")
    run = lambda *cmd: subprocess.run(cmd, check=True)
    run("git", "config", "user.name", "gozal-studio")
    run("git", "config", "user.email", "bot@gozalapp.com")
    run("git", "add", str(d))
    run("git", "commit", "-m", f"studio: nano-banana images for {item_id}")
    run("git", "pull", "--rebase", "origin", "main")
    run("git", "push", "origin", "main")
    return urls


def generate_banana(item):
    print(f"BANANA {item['id']}: {item['title']}")
    resp = engine("/api/banana", {
        "prompt": banana_prompt(item),
        "count": 3,
        "aspect": banana_aspect(item),
    })
    if not resp.get("ok"):
        err = resp.get("error", "unknown error")
        print(f"  banana failed: {err}")
        if "[banana]" not in (item.get("notes") or ""):
            engine("/api/action", {"type": "update", "id": item["id"], "fields": {
                "notes": (item.get("notes") or "") + f"\n[banana] Generation waiting: {err}"}})
        return
    urls = commit_assets(item["id"], resp["images"])
    engine("/api/action", {"type": "update", "id": item["id"], "fields": {"asset_urls": urls}})
    engine("/api/action", {"type": "move", "id": item["id"], "to": "approve",
                           "note": "Photos generated by Nano Banana. Awaiting your go/no-go."})
    print(f"  DONE -> approve board: {len(urls)} images")


def main():
    state = engine("/api/state")
    queue = [i for i in state["pipeline"]["items"] if i.get("stage") == "create_requested"]
    if not queue:
        print("Queue empty — nothing to generate.")
        _emit_claude_count(0)
        return

    # hand claude-image and text items to the Claude step of this workflow
    claude_items = [i for i in queue if creator_of(i) in ("claude-image", "text")]
    _emit_claude_count(len(claude_items))

    for item in queue:
        if creator_of(item) == "nano-banana":
            try:
                generate_banana(item)
            except Exception as e:  # keep one failure from blocking the rest of the queue
                print(f"  banana error for {item['id']}: {e}")
            continue
        if creator_of(item) != "higgsfield":
            print(f"SKIP {item['id']}: creator={creator_of(item)} — handled by the Claude step.")
            continue

        print(f"GENERATING {item['id']}: {item['title']}")
        resp, err = hf("/" + MODEL, {
            "prompt": build_prompt(item),
            "aspect_ratio": "9:16",
            "duration": 10,
        })
        if err:
            print(f"  submit failed: {err}")
            if "not_enough_credits" in err:
                engine("/api/action", {"type": "update", "id": item["id"], "fields": {
                    "notes": (item.get("notes") or "") + "\n[studio] Generation waiting: Higgsfield API credits are empty — top up at cloud.higgsfield.ai."}})
            continue

        request_id = resp.get("request_id")
        status = resp.get("status")
        # poll until terminal state
        deadline = time.time() + 15 * 60
        while status not in ("completed", "failed", "nsfw") and time.time() < deadline:
            time.sleep(15)
            poll, perr = hf(f"/requests/{request_id}/status")
            if perr:
                print(f"  poll error: {perr}")
                continue
            resp, status = poll, poll.get("status")

        if status != "completed":
            print(f"  ended as {status}")
            engine("/api/action", {"type": "update", "id": item["id"], "fields": {
                "notes": (item.get("notes") or "") + f"\n[studio] Generation {status or 'timed out'} — will retry next cycle."}})
            continue

        url = extract_url(resp)
        if not url:
            print(f"  completed but no url in response: {json.dumps(resp)[:300]}")
            continue

        engine("/api/action", {"type": "update", "id": item["id"], "fields": {"asset_url": url}})
        engine("/api/action", {"type": "move", "id": item["id"], "to": "approve",
                               "note": f"Video generated by studio worker ({MODEL}). Awaiting your go/no-go."})
        print(f"  DONE -> approve board: {url}")


def _emit_claude_count(n):
    """Tell the workflow whether the Claude image/text step needs to run."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"claude_items={n}\n")
    print(f"claude-step items queued: {n}")


if __name__ == "__main__":
    main()
