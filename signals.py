"""
Gozal Signals collector — competitor watch for the content engine.
Scrapes competitor TikTok accounts weekly via Apify (needs APIFY_TOKEN),
ranks their recent posts by engagement, and writes data/signals.json.
Runs in GitHub Actions (signals.yml). Costs ~ $0.01/run against Apify credit.
"""

import json
import os
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))

COMPETITORS = ["thumbtack", "angi", "taskrabbit"]
VIDEOS_PER_PROFILE = 5


def scrape_competitor_tiktoks(token):
    r = requests.post(
        "https://api.apify.com/v2/acts/clockworks~tiktok-profile-scraper/run-sync-get-dataset-items",
        params={"token": token, "timeout": 240},
        json={
            "profiles": COMPETITORS,
            "resultsPerPage": VIDEOS_PER_PROFILE,
            "profileScrapeSections": ["videos"],
            "profileSorting": "latest",
        },
        timeout=280,
    )
    r.raise_for_status()
    return r.json()


def main():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise SystemExit("APIFY_TOKEN not set")

    items = scrape_competitor_tiktoks(token)

    profiles = {}
    posts = []
    for it in items:
        am = it.get("authorMeta") or {}
        name = am.get("name")
        if name and name not in profiles:
            profiles[name] = {
                "handle": name,
                "followers": am.get("fans"),
                "total_likes": am.get("heart"),
                "videos": am.get("video"),
            }
        if it.get("playCount") is None:
            continue
        posts.append({
            "account": name,
            "text": (it.get("text") or "")[:180],
            "plays": it.get("playCount"),
            "likes": it.get("diggCount"),
            "comments": it.get("commentCount"),
            "shares": it.get("shareCount"),
            "posted": it.get("createTimeISO"),
            "url": it.get("webVideoUrl"),
        })

    posts.sort(key=lambda p: p["plays"] or 0, reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "competitor_profiles": list(profiles.values()),
        "competitor_posts": posts,
    }
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    with open(os.path.join(HERE, "data", "signals.json"), "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote data/signals.json: {len(profiles)} profiles, {len(posts)} posts")


if __name__ == "__main__":
    main()
