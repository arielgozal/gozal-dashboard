# Gozal Growth Engine

The content pipeline + auto-updating growth metrics for Gozal App in one place.

**Team app (interactive):** https://gozal-engine.pages.dev
**Public preview (read-only):** https://arielgozal.github.io/gozal-dashboard/

## How it works

- `index.html` is the engine: a 6-stage pipeline (Data → Signals → Ideas →
  Script → Create → Approve & Publish). Nothing is generated or published
  without an explicit human click.
- `data.html` is the metrics dashboard, embedded as the Data stage.
- `scrape.py` collects every publicly readable metric (App Store + Play ratings,
  TikTok / Instagram / YouTube audience numbers). No credentials needed.
- A GitHub Action runs it **every 6 hours** and commits fresh data — no laptop required.
- `data/history.json` keeps a snapshot per run, which powers the trend lines.
- `data/manual.json` holds numbers we can't automate yet (edit it by hand to update).
- The team app's workflow state (pipeline, weights, idea pool) lives in
  Cloudflare KV behind `functions/api/`; the daily agent
  (`.github/workflows/engine-agent.yml` + `agent/DAILY.md`) keeps the idea
  pool stocked and drafts scripts/captions. It never moves stages or posts.

## What's live vs pending

| Source | Status | What unlocks it |
|---|---|---|
| App Store rating | ✅ live | — |
| Google Play rating | ✅ live | — |
| TikTok followers/likes/videos | ✅ live | — |
| Instagram followers/posts | ✅ live | — |
| YouTube subscribers/videos | ✅ live | — |
| Facebook followers + reach | ⏳ pending | Meta developer app + token |
| Instagram reach/impressions | ⏳ pending | Meta developer app + token |
| TikTok video views | ⏳ pending | TikTok Business API approval (1–2 weeks) |
| iOS download counts | ⏳ pending | App Store Connect vendor number (finance access) |
| Android download counts | ⏳ pending | Google Workspace admin approval |
| Website analytics (GA4) | ⏳ pending | Google Workspace admin approval |

## Updating manually

Run locally: `python3 scrape.py` then open `index.html`.
Or on GitHub: **Actions → Update dashboard data → Run workflow**.
