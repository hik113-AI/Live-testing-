"""
generate_map_data.py — builds map_data.json from teduh_projects.json.

Filters TEDUH projects for the map:
  - All active projects (Lancar/Lewat/Sakit) regardless of date
  - Completed projects (Siap Dengan CCC/CFO) with expected_completion >= 2021

Output: map_data.json with:
  - projects: 14-column arrays matching the site's DATA format
  - sstats: per-state stats for the state choropleth view

Run after each detail crawl via GitHub Actions.
"""
import json
import re
import os
from collections import defaultdict

ACTIVE_STATUSES = {"Lancar", "Lewat", "Sakit"}
LANDED_KW = {"teres", "banglo", "semi", "cluster", "bungalow", "villa", "townhouse", "kotej"}
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
TIER_THRESHOLDS = [300000, 600000, 1000000]

STATE_NORMALIZE = {
    "W.P. Kuala Lumpur": "Kuala Lumpur",
    "W.P. Putrajaya": "Putrajaya",
    "W.P. Labuan": "Labuan",
    "Pulau Pinang": "Penang",
}


def to_date_str(s):
    """Convert TEDUH date to 'DD Mon YYYY'. Returns '' if unparseable."""
    if not s or s in ("null", "NULL"):
        return ""
    s = s.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            return f"{d:02d} {MONTH_ABBR[mo-1]} {y}"
    m = re.match(r"(\d{4})-(\d{2})$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"01 {MONTH_ABBR[mo-1]} {y}"
    return ""


def is_landed(unit_types):
    for ut in unit_types:
        t = (ut.get("type") or "").lower()
        if any(kw in t for kw in LANDED_KW):
            return 1
    return 0


def to_float(v):
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def tier_idx(pmin):
    if not pmin or pmin <= 0:
        return None
    for i, threshold in enumerate(TIER_THRESHOLDS):
        if pmin < threshold:
            return i
    return 3


def year_bucket(date_str):
    if not date_str:
        return "n.d."
    m = re.search(r"\b(\d{4})\b", date_str)
    if not m:
        return "n.d."
    y = int(m.group(1))
    if y <= 2021:
        return "≤2021"
    if y in (2022, 2023, 2024, 2025, 2026):
        return str(y)
    return "n.d."


print("Loading teduh_projects.json...")
with open("teduh_projects.json") as f:
    raw = json.load(f)

all_projects = raw["projects"]
print(f"  {len(all_projects)} total projects in file")

map_projects = []
skipped_no_coords = 0
skipped_old = 0

# Per-state accumulators for SSTATS
ss_n       = defaultdict(int)
ss_units   = defaultdict(int)
ss_sold    = defaultdict(int)
ss_landed  = defaultdict(int)
ss_active  = defaultdict(int)
ss_done    = defaultdict(int)
ss_prices  = defaultdict(list)
ss_ty      = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
ss_devunit = defaultdict(lambda: defaultdict(int))

for p in all_projects:
    lat, lon = p.get("lat"), p.get("lon")
    if not lat or not lon:
        skipped_no_coords += 1
        continue

    status = p.get("status", "")
    exp_comp = p.get("expected_completion") or ""
    is_active = status in ACTIVE_STATUSES

    if not is_active:
        if not exp_comp or exp_comp[:4] < "2021":
            skipped_old += 1
            continue

    detail = p.get("detail") or {}
    unit_types = detail.get("unit_types") or []

    total_units = sum(int(ut.get("units") or 0) for ut in unit_types)
    sold_units = 0
    if total_units > 0:
        for ut in unit_types:
            u = int(ut.get("units") or 0)
            pct = float(ut.get("takeup_pct") or 0)
            sold_units += round(u * pct / 100)

    prices_min = [to_float(ut.get("price_min")) for ut in unit_types if to_float(ut.get("price_min")) > 0]
    prices_max = [to_float(ut.get("price_max")) for ut in unit_types if to_float(ut.get("price_max")) > 0]
    price_min = int(min(prices_min)) if prices_min else 0
    price_max = int(max(prices_max)) if prices_max else 0

    areas = [to_float(ut.get("area")) for ut in unit_types if to_float(ut.get("area")) > 0]
    area_min = round(min(areas), 1) if areas else 0
    area_max = round(max(areas), 1) if areas else 0

    # Date: prefer first_pjb_date (actual first sale), fall back to expected_completion
    first_pjb = to_date_str(detail.get("first_pjb_date") or "")
    date_str = first_pjb or to_date_str(exp_comp)
    date_type = "pjb" if first_pjb else "ccc"

    status_code = "active" if is_active else "done"
    landed = is_landed(unit_types)
    dev = p.get("developer") or {}
    dev_name = dev.get("name") or ""

    state_raw = p.get("state") or ""
    state = STATE_NORMALIZE.get(state_raw, state_raw)

    map_projects.append([
        p["name"],        # d[0]  name
        lat,              # d[1]  lat
        lon,              # d[2]  lon
        status_code,      # d[3]  "active"/"done" (replaces tenure)
        landed,           # d[4]  1=landed, 0=highrise
        dev_name,         # d[5]  developer name
        price_min,        # d[6]  price_min
        price_max,        # d[7]  price_max
        total_units,      # d[8]  units total
        sold_units,       # d[9]  units sold
        area_min,         # d[10] area_min m²
        area_max,         # d[11] area_max m²
        date_str,         # d[12] "DD Mon YYYY"
        date_type,        # d[13] "pjb"=first sale date, "ccc"=expected completion
        p.get("id", ""),  # d[14] TEDUH project ID (for momentum/history lookup)
    ])

    # Accumulate state stats
    if state:
        ss_n[state] += 1
        ss_units[state] += total_units
        ss_sold[state] += sold_units
        ss_landed[state] += landed
        ss_active[state] += 1 if is_active else 0
        ss_done[state] += 0 if is_active else 1
        if price_min > 0:
            ss_prices[state].append(price_min)
        ti = tier_idx(price_min)
        yb = year_bucket(date_str)
        if ti is not None:
            ss_ty[state][yb][ti] += 1
        if dev_name and total_units > 0:
            ss_devunit[state][dev_name] += total_units

print(f"  Included: {len(map_projects)} | No coords: {skipped_no_coords} | Pre-2021/unknown: {skipped_old}")

# Build SSTATS
sstats = {}
all_states = set(ss_n.keys())
for state in all_states:
    if not state:
        continue
    prices = sorted(ss_prices[state])
    med_p = prices[len(prices) // 2] if prices else 0
    top_devs = sorted(ss_devunit[state].items(), key=lambda x: -x[1])[:3]
    ty_plain = {yb: list(counts) for yb, counts in ss_ty[state].items()}
    sstats[state] = {
        "n":       ss_n[state],
        "units":   ss_units[state],
        "sold":    ss_sold[state],
        "landed":  ss_landed[state],
        "highrise": ss_n[state] - ss_landed[state],
        "active":  ss_active[state],
        "done":    ss_done[state],
        "medP":    med_p,
        "ty":      ty_plain,
        "topdev":  [[d[0], d[1]] for d in top_devs],
    }

output = {
    "updated": raw.get("updated", ""),
    "projects": map_projects,
    "sstats": sstats,
}

with open("map_data.json", "w") as f:
    json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

size_kb = os.path.getsize("map_data.json") // 1024
print(f"map_data.json: {len(map_projects)} projects, {len(sstats)} states — {size_kb} KB")
