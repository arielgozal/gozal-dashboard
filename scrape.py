"""
Gozal Growth Dashboard — data collector.
Pulls every metric that is publicly readable (no credentials needed):
  - App Store rating + rating count       (iTunes lookup API)
  - Google Play rating + review count      (public store listing)
  - TikTok followers, likes, video count   (public profile)
  - Instagram followers, post count        (public profile)
  - YouTube subscribers, video count       (public channel page)
Facebook, GA4, and store download counts need credentials — they stay
null until access is granted (see README) and merge in from data/manual.json.

Writes data/metrics.json and appends a snapshot to data/history.json.
"""

import json
import os
import re
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

APP_STORE_ID = "6752485832"
PLAY_PACKAGE = "com.gozal.app"
TIKTOK_HANDLE = "gozalapp3"
INSTAGRAM_HANDLE = "appgozalapp"
YOUTUBE_HANDLE = "Gozal-app"
FACEBOOK_PAGE_ID = "61583856832151"


def _num(raw):
    """'1.2K' -> 1200, '3,456' -> 3456"""
    raw = raw.replace(",", "").strip()
    mult = 1
    if raw.upper().endswith("K"):
        mult, raw = 1_000, raw[:-1]
    elif raw.upper().endswith("M"):
        mult, raw = 1_000_000, raw[:-1]
    return int(float(raw) * mult)


def appstore():
    r = requests.get(
        f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country=us",
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return {}
    app = results[0]
    return {
        "ios_rating": round(app.get("averageUserRating", 0), 1),
        "ios_ratings_count": app.get("userRatingCount"),
    }


def playstore():
    r = requests.get(
        f"https://play.google.com/store/apps/details?id={PLAY_PACKAGE}&hl=en_US",
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    html = r.text
    out = {}
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            agg = json.loads(m.group(1)).get("aggregateRating") or {}
            if agg.get("ratingValue") is not None:
                out["android_rating"] = round(float(agg["ratingValue"]), 1)
                out["android_ratings_count"] = int(agg.get("ratingCount", 0))
                return out
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    m = re.search(r'"ratingValue"\s*:\s*"?([0-9.]+)', html)
    if m:
        out["android_rating"] = round(float(m.group(1)), 1)
    m = re.search(r'"ratingCount"\s*:\s*"?([0-9]+)', html)
    if m:
        out["android_ratings_count"] = int(m.group(1))
    return out


def tiktok():
    r = requests.get(f"https://www.tiktok.com/@{TIKTOK_HANDLE}", headers=UA, timeout=20)
    r.raise_for_status()
    out = {}
    for key, name in [("followerCount", "tiktok_followers"),
                      ("heartCount", "tiktok_likes"),
                      ("videoCount", "tiktok_videos")]:
        m = re.search(rf'"{key}"\s*:\s*(\d+)', r.text)
        if m:
            out[name] = int(m.group(1))
    return out


def instagram():
    try:
        r = requests.get(
            "https://i.instagram.com/api/v1/users/web_profile_info/",
            params={"username": INSTAGRAM_HANDLE},
            headers={**UA, "x-ig-app-id": "936619743392459"},
            timeout=20,
        )
        if r.status_code == 200:
            user = r.json().get("data", {}).get("user", {})
            followers = user.get("edge_followed_by", {}).get("count")
            if followers is not None:
                return {
                    "instagram_followers": followers,
                    "instagram_posts": user.get("edge_owner_to_timeline_media", {}).get("count"),
                }
    except requests.RequestException:
        pass
    r = requests.get(f"https://www.instagram.com/{INSTAGRAM_HANDLE}/", headers=UA, timeout=20)
    r.raise_for_status()
    m = re.search(r'([\d,.]+[KM]?)\s+Followers', r.text)
    if not m:
        return {}
    return {"instagram_followers": _num(m.group(1))}


def facebook():
    """Facebook page follower count. Facebook usually serves a login wall to
    non-browser requests, so this often returns nothing — the carry-forward
    keeps the last browser-seeded value alive when that happens."""
    r = requests.get(
        f"https://www.facebook.com/profile.php?id={FACEBOOK_PAGE_ID}",
        headers=UA, timeout=20,
    )
    r.raise_for_status()
    out = {}
    m = re.search(r'([\d,.]+[KM]?)\s+followers', r.text, re.I)
    if m:
        out["facebook_followers"] = _num(m.group(1))
    m = re.search(r'([\d,.]+[KM]?)\s+likes', r.text, re.I)
    if m:
        out["facebook_likes"] = _num(m.group(1))
    return out


def youtube():
    r = requests.get(f"https://www.youtube.com/@{YOUTUBE_HANDLE}", headers=UA, timeout=20)
    r.raise_for_status()
    out = {}
    m = re.search(r'([\d.,]+[KM]?)\s+subscribers', r.text)
    if m:
        out["youtube_subscribers"] = _num(m.group(1))
    m = re.search(r'([\d.,]+[KM]?)\s+videos', r.text)
    if m:
        out["youtube_videos"] = _num(m.group(1))
    return out


SOURCE_KEYS = {
    "app_store":   ["ios_rating", "ios_ratings_count"],
    "google_play": ["android_rating", "android_ratings_count"],
    "tiktok":      ["tiktok_followers", "tiktok_likes", "tiktok_videos"],
    "instagram":   ["instagram_followers", "instagram_posts"],
    "youtube":     ["youtube_subscribers", "youtube_videos"],
    "facebook":    ["facebook_followers", "facebook_likes"],
}


def main():
    sources = {
        "app_store": appstore,
        "google_play": playstore,
        "tiktok": tiktok,
        "instagram": instagram,
        "youtube": youtube,
        "facebook": facebook,
    }

    # Last known values — a blocked scrape keeps yesterday's number instead of a hole
    prev_metrics, prev_updated = {}, {}
    prev_path = os.path.join(HERE, "data", "metrics.json")
    if os.path.exists(prev_path):
        try:
            with open(prev_path) as f:
                prev = json.load(f)
            prev_metrics = prev.get("metrics", {})
            prev_updated = prev.get("sources_updated", {})
        except json.JSONDecodeError:
            pass

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data = {}
    status = {}
    sources_updated = {}
    for name, fn in sources.items():
        got = {}
        try:
            got = fn()
        except Exception as e:
            print(f"  FAIL {name}: {e}")
        # keys the scrape didn't return this time keep their last known value
        carried = {k: prev_metrics[k] for k in SOURCE_KEYS.get(name, [])
                   if k in prev_metrics and k not in got}
        data.update(carried)
        data.update(got)
        status[name] = bool(got or carried)
        sources_updated[name] = now if got else prev_updated.get(name)
        if got:
            print(f"  OK   {name}: {got}" + (f" (+carried {carried})" if carried else ""))
        else:
            print(f"  MISS {name}: carried forward {carried or 'nothing'}")

    # These need credentials or team access — see README
    status["ga4_website"] = False
    status["download_counts"] = False

    # Manual numbers (from Play Console / App Store Connect screenshots etc.)
    manual = {}
    manual_path = os.path.join(HERE, "data", "manual.json")
    if os.path.exists(manual_path):
        with open(manual_path) as f:
            manual = json.load(f)

    payload = {
        "last_updated": now,
        "metrics": data,
        "manual": manual,
        "status": status,
        "sources_updated": sources_updated,
    }
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    with open(os.path.join(HERE, "data", "metrics.json"), "w") as f:
        json.dump(payload, f, indent=2)

    # Append to history (one snapshot per run, keep last 500)
    hist_path = os.path.join(HERE, "data", "history.json")
    history = []
    if os.path.exists(hist_path):
        try:
            with open(hist_path) as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []
    history.append({"ts": now, **data})
    history = history[-500:]
    with open(hist_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nWrote data/metrics.json + history ({len(history)} snapshots)")


if __name__ == "__main__":
    main()
