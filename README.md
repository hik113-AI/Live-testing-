# Malaysia Property Launches Explorer

**Live:** [interstellarsanctuary.com](https://interstellarsanctuary.com)

An interactive map of new private property launches across Peninsular Malaysia (2021 to 2025), layered with transit networks, district demographics, and a Claude-powered property analyst assistant.

---

## Features

**Map and data layers**
- Searchable, filterable property launch markers with price, take-up rate, tenure, and developer details
- Full Peninsular Malaysia rail and transit network overlay (LRT, MRT, KTM, ERL, BRT, Monorail, ECRL) with accurate OSM geometry and verified station coordinates
- State heatmap showing launch density by state
- Area scan: click any point on the map to see all projects within a configurable radius
- District demographics panel with household income, poverty rate, and population trend sparklines (2019 to 2025)
- Nearby amenities layer (schools, hospitals, shopping, parks)

**AI assistant**
- Conversational property analyst powered by Claude, with access to the full project dataset via a structured query tool
- Answers questions about price ranges, take-up rates, developers, areas, and project comparisons in plain language

**TEDUH take-up tracker**
- Automated crawler pulling live data from the TEDUH (KPKT) API
- Runs 4 times per day via GitHub Actions, rotating through the full project list in batches while always prioritising active projects
- Stores hourly take-up snapshots in `teduh_history.json` for momentum and liquidity analysis

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS, Leaflet 1.9.4, Leaflet.markercluster 1.5.3 |
| API | Vercel serverless functions (Node.js) |
| AI | Anthropic Claude (claude-sonnet-4-6) via `api/ask.js` |
| Crawler | Python 3, urllib, GitHub Actions |
| Hosting | Vercel |

---

## Data Files

| File | Description |
|---|---|
| `map_data.json` | Live TEDUH project data served to the site (2,800+ projects, regenerated after each crawl) |
| `teduh_projects.json` | Full TEDUH project store (~24k projects, 14MB, updated by crawler) |
| `teduh_history.json` | Rolling 90-day take-up snapshots per project (for momentum sparklines) |
| `ads.json` | Ad slot configuration — edit to change ads without touching code |
| `data.json` | DOSM district demographics GeoJSON (population, income, poverty) |
| `transit.json` | Rail network geometry and station coordinates (16 lines) |
| `amenities.json` | Nearby amenities (schools, hospitals, malls, supermarkets) |

---

## Running Locally

No build step required. Serve the repo root with any static file server:

```bash
npx serve .
# or
python3 -m http.server 8080
```

Open `http://localhost:8080`.

The AI assistant requires a Vercel deployment with `ANTHROPIC_API_KEY` set as an environment variable (see below). It will not work from a plain static server.

---

## Deployment

The project deploys to Vercel automatically on push to `main`. The `api/` directory is served as Vercel serverless functions.

**Required environment variable in Vercel project settings:**

```
ANTHROPIC_API_KEY=<your Anthropic API key>
```

---

## TEDUH Crawler

Two scripts handle data collection from [teduh.kpkt.gov.my](https://teduh.kpkt.gov.my):

- **`fetch_teduh.py`** — fetches the full project listing, filters to West Malaysia, and merges into `teduh_projects.json`
- **`fetch_teduh_daily.py`** — fetches per-project detail (unit types, take-up rates, pricing, developer info) and appends hourly snapshots to `teduh_history.json`

The GitHub Actions workflow at `.github/workflows/teduh-daily.yml` schedules 4 runs per day (09:00, 15:00, 21:00, 03:00 MYT). Each run crawls all active projects plus a rotating batch of the remainder, so the full dataset refreshes within 24 hours.

To run manually:

```bash
python3 fetch_teduh.py           # refresh project listing
python3 fetch_teduh_daily.py     # full detail crawl
python3 fetch_teduh_daily.py --batch 0 --of 4   # batch mode (1 of 4)
```

**Note:** GitHub Actions needs write permissions to commit crawled data back to the repo. In repository Settings, go to Actions and set Workflow permissions to "Read and write permissions".

---

## Project Structure

```
.
├── index.html                  # Entire frontend (map, UI, filters, AI chat)
├── map_data.json               # Served to site — generated from teduh_projects.json
├── teduh_projects.json         # Full TEDUH store (~24k projects)
├── teduh_history.json          # Rolling take-up history (360 snapshots)
├── ads.json                    # Ad slot config (edit to swap ads, no code change needed)
├── data.json                   # DOSM demographics GeoJSON
├── transit.json                # Rail network geometry
├── amenities.json              # Nearby amenities layer
├── generate_map_data.py        # Converts teduh_projects.json → map_data.json
├── fetch_teduh.py              # TEDUH listing refresh (batch 0, once/day)
├── fetch_teduh_daily.py        # TEDUH detail crawler (self-tuning parallel, 4x/day)
├── CLAUDE.md                   # Architecture reference for Claude Code sessions
├── api/
│   ├── ask.js                  # Claude AI assistant endpoint
│   ├── geo.js                  # State boundary helpers
│   └── data.json               # Dataset copy for API function
└── .github/workflows/
    └── teduh-daily.yml         # Scheduled crawler (09/15/21/03 MYT)
```
