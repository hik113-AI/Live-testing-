# CLAUDE.md — Malaysia Property Launches Explorer

This file is read by Claude Code at the start of every session. It describes the architecture, data pipeline, and conventions so no time is spent re-discovering them.

## What this project is

A single-page property analytics map at **interstellarsanctuary.com** (Vercel, auto-deploys on push to `main` of `hik113-AI/Live-testing-`). Built for EdgeProp Malaysia.

Key features: Leaflet map with ~2,800+ live TEDUH property project markers, transit overlay (16 rail lines), district demographics panel, area-scan tool, AI property assistant (Claude), and per-state choropleth view.

## Architecture

**No build step.** The entire frontend is `index.html` — one file, vanilla HTML/CSS/JS. Leaflet 1.9.4 + Leaflet.markercluster 1.5.3 loaded from CDN. No npm, no bundler, no framework.

**Backend:** Vercel serverless functions in `api/`. The only one actively used is `api/ask.js` (Claude AI assistant). Requires `ANTHROPIC_API_KEY` in Vercel environment variables.

**Data flow:**
```
TEDUH API (kpkt.gov.my)
    → fetch_teduh.py          (listing refresh, batch 0 only, once/day)
    → teduh_projects.json     (full store, 14MB, ~24k projects)
    → fetch_teduh_daily.py    (detail crawl, 4x/day via GitHub Actions)
    → generate_map_data.py    (filters + shapes data for the site)
    → map_data.json           (341KB, what the site actually loads)
```

## Key files

| File | Purpose |
|---|---|
| `index.html` | Entire frontend — map, UI, filters, AI chat |
| `map_data.json` | What the site loads — 2,800+ projects in 14-col arrays + SSTATS |
| `teduh_projects.json` | Full TEDUH store (14MB), updated by crawler |
| `teduh_history.json` | Rolling 360-snapshot take-up history for trend sparklines |
| `generate_map_data.py` | Converts teduh_projects.json → map_data.json after each crawl |
| `fetch_teduh.py` | Listing refresh — fetches all ~24k project IDs from TEDUH API |
| `fetch_teduh_daily.py` | Detail crawler — self-tuning parallel, all active projects 4x/day |
| `ads.json` | Ad config — edit this to swap ads, no code change needed |
| `data.json` | DOSM demographics GeoJSON (district polygons + stats) |
| `transit.json` | Rail network geometry (16 lines, OSM-sourced) |
| `amenities.json` | Schools, hospitals, malls, supermarkets (OSM) |
| `.github/workflows/teduh-daily.yml` | Scheduled crawler (01/07/13/19 UTC = 09/15/21/03 MYT) |

## The TEDUH crawler (fetch_teduh_daily.py)

Runs 4x daily on GitHub Actions. Self-tuning: probes API latency from first 20 projects, then auto-calculates how many parallel workers are needed to finish all ~2,948 active projects within 50 minutes. No hardcoded worker count — adapts as project count grows.

Parameters: 8s timeout per request, 2 retries, 0.2s sleep, MAX 20 workers, BUDGET 50 min.

Active statuses crawled every run: Lancar, Lewat, Sakit (~2,948 projects).
Completed (Siap Dengan CCC/CFO) only included in map if expected_completion >= 2021.

**Never modify the retry logic** — the old retry pass (removed) caused 75-min timeouts. Failed projects are picked up on the next run 6h later.

## map_data.json format

```
projects: array of 14-col arrays per project:
  [0] name
  [1] lat
  [2] lon
  [3] "active" | "done"   (status, replaces old tenure fh/lh)
  [4] 1=landed, 0=highrise
  [5] developer name
  [6] price_min (int, RM)
  [7] price_max (int, RM)
  [8] total units
  [9] sold units
  [10] area_min (m², float)
  [11] area_max (m², float)
  [12] date string "DD Mon YYYY"
  [13] "pjb" (first sale date) | "ccc" (expected completion)

sstats: per-state object { n, units, sold, landed, highrise, active, done, medP, ty, topdev }
```

## Site data loading

`map_data.json` is fetched async on page load with a 6-hour localStorage cache (key: `teduh_map_v1`). First load hits the network; subsequent loads within 6h use cache. To force a fresh load: clear localStorage.

## Ad system (ads.json)

Two ad slots: sidebar card (`#adSidebar`) and fixed top banner (`#adTopBanner`, desktop only).

`ads.json` is loaded async on page load. To change any ad, edit `ads.json` — no HTML/JS changes needed.

**Direct ad format:**
```json
{
  "sidebar": {
    "type": "direct",
    "icon": "🏠",
    "headline": "...",
    "description": "...",
    "url": "https://...",
    "sponsor": "CompanyName.com"
  }
}
```

**Google AdSense format** (when publisher account is approved):
```json
{
  "adsense_client": "ca-pub-XXXXXXXXXXXXXXXX",
  "sidebar": { "type": "adsense", "slot": "1234567890", "format": "auto" },
  "top_banner": { "type": "adsense", "slot": "9876543210", "format": "auto" }
}
```

**To set up AdSense:**
1. Sign up at adsense.google.com with the domain interstellarsanctuary.com
2. Get site approved (1-3 days)
3. Create two ad units in the AdSense dashboard: one for sidebar (~300×250 or responsive), one for top banner (~728×90 leaderboard or responsive)
4. Copy the `data-ad-client` (publisher ID) and `data-ad-slot` values for each unit
5. Update `ads.json` with the adsense format above — that's it, no code changes needed

**To hide a slot:** set its key to `null` in ads.json.

## Important constraints

- **No build step** — never introduce npm build tooling, bundlers, or frameworks. All changes are direct HTML/JS edits.
- **Single file frontend** — `index.html` is the entire app. Keep it that way.
- **Immutable DATA** — never mutate project objects in the DATA array. Read only.
- **No git force push** — crawler commits happen every 6h; always `git pull --rebase && git push` when pushing alongside active crawler runs.
- **GitHub Actions write permissions** — required for crawler to commit. Settings → Actions → General → "Read and write permissions".

## Deployment

Push to `main` → Vercel auto-deploys → live at interstellarsanctuary.com within ~30s.

Vercel env vars required:
- `ANTHROPIC_API_KEY` — for the Claude AI assistant in api/ask.js

## Running locally

```bash
python3 -m http.server 8080
# open http://localhost:8080
```

AI assistant won't work locally (needs Vercel function + API key). Everything else works.

## Recent changes (Jul 2026)

- Removed 2,800 hardcoded NAPIC launches; site now loads live TEDUH data from map_data.json
- Added 6h localStorage cache for map data
- Status filter (Active/Completed) replaced tenure filter (Freehold/Leasehold)
- Crawler fixed: self-tuning parallel workers, no retry pass, 60-min workflow cap
- Ad system added: ads.json drives both slots, supports direct deals and AdSense
- Dynamic project count: "2,800+" text updates from live DATA.length after load
