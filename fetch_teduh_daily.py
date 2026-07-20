"""
fetch_teduh_deep.py — scheduled deep crawler for TEDUH project details.

Extracts per project:
  - unit_types: type, floors, bedrooms, bathrooms, area, units, price_min,
    price_max, takeup_pct, ccc, vp
  - first_pjb_date (Tarikh PJB Pertama - date of first Sale & Purchase Agreement)
  - pjb_type, pjb_original_period
  - brochure_url
  - developer registered/business address, status, offense flag, project count

Also appends a lean hourly snapshot (id, takeup per unit type, timestamp) to
teduh_history.json so sales momentum can be computed once 2+ data points exist.

Batch mode (--batch N --of M):
  Always crawls all active projects (Lancar/Lewat/Sakit) for maximum freshness.
  Rotates through the rest in M equal batches — run M times per day to achieve
  full coverage every 24 hours while keeping each individual run short.

Designed to run via GitHub Actions (see .github/workflows/teduh-daily.yml).
"""
import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument('--batch', type=int, default=0,
                    help='Batch index (0-based, default 0)')
parser.add_argument('--of', type=int, default=1, dest='num_batches',
                    help='Total number of batches (default 1 = crawl all)')
args = parser.parse_args()

ACTIVE_STATUSES = {"Lancar", "Lewat", "Sakit"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    "Accept": "application/json",
    "Referer": "https://teduh.kpkt.gov.my/semakan-status-kemajuan",
}
BASE = "https://teduh.kpkt.gov.my/api/projek-swasta/"


def fetch_detail(project_id, max_retries=4):
    url = BASE + project_id
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            resp = urllib.request.urlopen(req, timeout=25)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 502, 504) and attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
                continue
            return {"_error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
                continue
            return {"_error": str(e)}
    return {"_error": "max retries exceeded"}


def extract_detail(raw):
    if "_error" in raw:
        return None
    unit_types = []
    for row in raw.get("status", {}).get("rows", []):
        unit_types.append({
            "type": row.get("jenis"),
            "floors": row.get("tingkat"),
            "bedrooms": row.get("bilik"),
            "bathrooms": row.get("tandas"),
            "area": row.get("keluasan"),
            "units": row.get("unit"),
            "price_min": row.get("hargaMin"),
            "price_max": row.get("hargaMax"),
            "takeup_pct": row.get("peratus"),
            "ccc": row.get("ccc"),
            "vp": row.get("vp"),
        })
    pemaju = raw.get("pemaju", {}) or {}
    pjb = raw.get("pjb", {}) or {}
    return {
        "unit_types": unit_types,
        "brochure_url": (raw.get("brochure") or {}).get("dokumen_url"),
        "developer_registered_address": pemaju.get("alamat_daftar"),
        "developer_business_address": pemaju.get("alamat_perniagaan"),
        "developer_status": pemaju.get("statusPemaju"),
        "developer_has_offenses": bool(pemaju.get("mempunyaiKesalahan")),
        "developer_project_count": pemaju.get("bilanganProjek"),
        "development_phase_info": (raw.get("status") or {}).get("maklumatPembangunan"),
        "first_pjb_date": pjb.get("tarikhPjbPertama"),
        "pjb_type": pjb.get("jenis"),
        "pjb_original_period": pjb.get("tempohAsal"),
    }


print("Loading existing teduh_projects.json...")
with open("teduh_projects.json") as f:
    base_data = json.load(f)

projects = base_data["projects"]
print(f"  {len(projects)} projects total")

# Build the crawl list for this run.
# Active projects are always included for maximum take-up freshness.
# The remainder is split into num_batches rotating slices.
if args.num_batches > 1:
    priority = [p for p in projects if p.get("status") in ACTIVE_STATUSES]
    priority_ids = {p["id"] for p in priority}
    others = [p for p in projects if p["id"] not in priority_ids]
    batch_others = [p for i, p in enumerate(others) if i % args.num_batches == args.batch]
    projects_to_crawl = priority + batch_others
    print(f"  Batch {args.batch}/{args.num_batches}: "
          f"{len(priority)} priority (active) + {len(batch_others)} batch = "
          f"{len(projects_to_crawl)} to crawl")
else:
    projects_to_crawl = projects
    print(f"  Full crawl: {len(projects_to_crawl)} projects")

enriched = 0
failed = 0
no_price_data = 0
failed_ids = []
t0 = time.time()

# Hourly snapshot for the momentum log — deduped by timestamp so multiple
# runs per day each produce a distinct history entry.
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")
snapshot = {"date": ts, "projects": {}}

for i, p in enumerate(projects_to_crawl):
    pid = p.get("id")
    if not pid:
        continue
    raw = fetch_detail(pid)
    detail = extract_detail(raw)
    if detail is None:
        failed += 1
        failed_ids.append(pid)
    else:
        p["detail"] = detail
        if detail["unit_types"]:
            enriched += 1
            snapshot["projects"][pid] = {
                t["type"]: t["takeup_pct"] for t in detail["unit_types"] if t.get("type")
            }
        else:
            no_price_data += 1

    if (i + 1) % 200 == 0:
        elapsed = time.time() - t0
        rate = (i + 1) / elapsed
        remaining = (len(projects_to_crawl) - i - 1) / rate
        print(f"  {i+1}/{len(projects_to_crawl)} | enriched={enriched} failed={failed} "
              f"no_price={no_price_data} | ~{remaining/60:.1f} min remaining")

    time.sleep(0.4)

if failed_ids:
    print(f"\nRetry pass: {len(failed_ids)} failed IDs...")
    still_failed = []
    id_to_project = {p["id"]: p for p in projects}
    for j, pid in enumerate(failed_ids):
        time.sleep(0.6)
        raw = fetch_detail(pid, max_retries=5)
        detail = extract_detail(raw)
        if detail is None:
            still_failed.append(pid)
        else:
            id_to_project[pid]["detail"] = detail
            enriched += 1
            failed -= 1
            if detail["unit_types"]:
                snapshot["projects"][pid] = {
                    t["type"]: t["takeup_pct"] for t in detail["unit_types"] if t.get("type")
                }
        if (j + 1) % 100 == 0:
            print(f"  retry {j+1}/{len(failed_ids)}")
    print(f"Retry done. Still failed: {len(still_failed)}")
    failed = len(still_failed)

print(f"\n=== DONE ===")
print(f"Crawled: {len(projects_to_crawl)} | Enriched: {enriched} | "
      f"No price rows: {no_price_data} | Failed: {failed}")

output = {**base_data, "projects": projects, "deep_crawl": True, "last_crawled": ts}
with open("teduh_projects.json", "w") as f:
    json.dump(output, f, ensure_ascii=False)

# Append hourly snapshot to the history log (create if it doesn't exist).
# Keeps 90 days × 4 runs = 360 entries max to bound file size.
try:
    with open("teduh_history.json") as f:
        history = json.load(f)
except FileNotFoundError:
    history = {"snapshots": []}

history["snapshots"] = [s for s in history["snapshots"] if s.get("date") != ts]
history["snapshots"].append(snapshot)
history["snapshots"] = history["snapshots"][-360:]

with open("teduh_history.json", "w") as f:
    json.dump(history, f, ensure_ascii=False)

import os
print(f"teduh_projects.json: {os.path.getsize('teduh_projects.json')//1024} KB")
print(f"teduh_history.json: {os.path.getsize('teduh_history.json')//1024} KB "
      f"({len(history['snapshots'])} snapshots)")
