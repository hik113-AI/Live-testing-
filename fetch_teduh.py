"""
fetch_teduh.py — fetches ALL 24,712 TEDUH licensed private housing projects 
in one paginated pass, then filters to West Malaysia states.

The TEDUH API ignores the negeri (state) filter parameter — it always returns
all projects. So we fetch everything once and filter locally.

~1,236 pages at 100 per page with 0.3s delay = ~6 minutes total.
"""

import json
import time
import urllib.request
from datetime import datetime

WEST_MALAYSIA = {
    "01": "Johor", "02": "Kedah", "03": "Kelantan", "04": "Melaka",
    "05": "Negeri Sembilan", "06": "Pahang", "07": "Pulau Pinang", "08": "Perak",
    "09": "Perlis", "10": "Selangor", "11": "Terengganu",
    "14": "W.P. Kuala Lumpur", "15": "W.P. Labuan", "16": "W.P. Putrajaya",
    # Best-guess codes for East Malaysia, pending live confirmation — kept as a label lookup
    # only. Actual inclusion below does NOT depend on getting these numbers right: any
    # project is included if its own lat/lon falls in East Malaysia, regardless of what its
    # kod_negeri_id says, so a wrong guess here just means a wrong "state" text label on a
    # handful of projects, not a missing/broken project.
    "12": "Sabah", "13": "Sarawak",
}
EAST_MALAYSIA_BBOX = (0.8, 109.4, 7.5, 119.5)  # lat_min, lon_min, lat_max, lon_max
def in_scope(p):
    if p.get("kod_negeri_id") in WEST_MALAYSIA:
        return True
    try:
        lat, lon = float(p.get("latitud")), float(p.get("longitud"))
        return EAST_MALAYSIA_BBOX[0] <= lat <= EAST_MALAYSIA_BBOX[2] and EAST_MALAYSIA_BBOX[1] <= lon <= EAST_MALAYSIA_BBOX[3]
    except (TypeError, ValueError):
        return False
def east_malaysia_state_guess(lat, lon):
    """Rough Sabah/Sarawak split by longitude for projects whose kod_negeri_id we don't
    recognize but whose coordinates place them in East Malaysia. Sarawak is the western
    two-thirds of Borneo's Malaysian portion, Sabah the northeastern third — 115.0°E is a
    reasonable dividing line for this purpose (display label only, not used for placement)."""
    if lat is None or lon is None:
        return None
    if not (EAST_MALAYSIA_BBOX[0] <= lat <= EAST_MALAYSIA_BBOX[2] and EAST_MALAYSIA_BBOX[1] <= lon <= EAST_MALAYSIA_BBOX[3]):
        return None
    return "Sarawak" if lon < 115.0 else "Sabah"

STATUS_MAP = {
    "0": "Belum Mula", "1": "Lancar", "2": "Sakit", "3": "Lewat",
    "5": "Siap Dengan CCC", "7": "Siap Dengan CFO", "B": "Permit Dibatalkan",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    "Accept": "application/json",
    "Referer": "https://teduh.kpkt.gov.my/semakan-status-kemajuan",
}

BASE = "https://teduh.kpkt.gov.my/api/projek-swasta"


def fetch_page(page):
    url = f"{BASE}?page={page}&per_page=100&q=&search_type=projek"
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def clean(p):
    dev = p.get("pemaju") or {}
    sc = p.get("kod_negeri_id", "")
    lat = p.get("latitud")
    lon = p.get("longitud")
    try:
        lat = float(lat) if lat else None
        lon = float(lon) if lon else None
    except:
        lat = lon = None
    return {
        "id": p.get("id"),
        "name": p.get("nama"),
        "phase": p.get("kod_fasa"),
        "state_code": sc,
        "state": WEST_MALAYSIA.get(sc) or east_malaysia_state_guess(lat, lon) or "",
        "lat": lat,
        "lon": lon,
        "status": STATUS_MAP.get(p.get("status_projek", ""), p.get("status_projek", "")),
        "expected_completion": p.get("tarikh_jangkaan_ccc"),
        "bumi_quota_pct": p.get("peratus_kuotabumi"),
        "developer": {
            "name": dev.get("nama"),
            "phone": dev.get("telefon"),
            "phone2": dev.get("telefon2"),
            "email": dev.get("emel"),
            "website": dev.get("alamat_web"),
            "ssm": dev.get("no_ssm"),
            "address": " ".join(filter(None, [
                dev.get("alamat_perniagaan1"),
                dev.get("alamat_perniagaan2"),
                str(dev.get("poskod_perniagaan") or ""),
            ])).strip() or None,
        },
    }


# Fetch first page to get pagination info
print("Fetching page 1...")
raw = fetch_page(1)
proj_meta = raw.get("projects", {})
last_page = proj_meta.get("last_page", 1)
total_api = proj_meta.get("total", 0)
print(f"Total in API: {total_api} | Pages: {last_page}")

all_projects = []

def process_page(raw):
    proj_meta = raw.get("projects", {})
    data = proj_meta.get("data", [])
    for p in data:
        if in_scope(p):
            all_projects.append(clean(p))

process_page(raw)
time.sleep(0.3)

for page in range(2, last_page + 1):
    try:
        raw = fetch_page(page)
        process_page(raw)
        if page % 50 == 0 or page == last_page:
            print(f"  page {page}/{last_page} | WM projects so far: {len(all_projects)}")
        time.sleep(0.3)
    except Exception as e:
        print(f"  ERROR page {page}: {e} — retrying in 5s")
        time.sleep(5)
        try:
            raw = fetch_page(page)
            process_page(raw)
            time.sleep(0.3)
        except Exception as e2:
            print(f"  SKIPPED page {page}: {e2}")

# Stats
with_coords = sum(1 for p in all_projects if p["lat"] and p["lon"])
status_counts = {}
for p in all_projects:
    status_counts[p["status"]] = status_counts.get(p["status"], 0) + 1

output = {
    "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "total": len(all_projects),
    "with_coordinates": with_coords,
    "projects": all_projects,
}

# This is a LISTING refresh, not a detail crawl - it does not fetch unit types, pricing, or
# brochure URLs (that's fetch_teduh_daily.py's job, run incrementally over time). Blindly
# overwriting teduh_projects.json here would silently wipe out all of that accumulated detail
# data for every existing project (this happened once already - caught and fixed by hand from
# git history, this preserves it automatically from now on). Merge detail from whatever's
# already on disk, keyed by project id, before writing.
try:
    with open("teduh_projects.json") as f:
        existing = json.load(f)
    existing_detail = {p["id"]: p.get("detail") for p in existing.get("projects", []) if p.get("detail")}
    restored = 0
    for p in output["projects"]:
        d = existing_detail.get(p["id"])
        if d:
            p["detail"] = d
            restored += 1
    print(f"Preserved detail data for {restored} projects from the existing file", flush=True)
except (FileNotFoundError, json.JSONDecodeError):
    print("No existing teduh_projects.json found (or it's invalid) - nothing to preserve", flush=True)

with open("teduh_projects.json", "w") as f:
    json.dump(output, f, ensure_ascii=False)

print(f"\n=== DONE ===")
print(f"West Malaysia projects: {len(all_projects)}")
print(f"With coordinates: {with_coords} ({100*with_coords//max(1,len(all_projects))}%)")
print("By status:")
for s, n in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f"  {s}: {n}")
import os
print(f"\nteduh_projects.json: {os.path.getsize('teduh_projects.json')//1024} KB")
