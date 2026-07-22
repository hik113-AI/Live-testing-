"""
fetch_teduh_daily.py — scheduled detail crawler for TEDUH housing projects.

Extracts per project:
  - unit_types: type, floors, bedrooms, bathrooms, area, units, price_min,
    price_max, takeup_pct, ccc, vp
  - first_pjb_date (Tarikh PJB Pertama - date of first Sale & Purchase Agreement)
  - pjb_type, pjb_original_period
  - brochure_url
  - developer registered/business address, status, offense flag, project count

Also appends a lean snapshot (id, takeup per unit type, timestamp) to
teduh_history.json so sales momentum can be computed once 2+ data points exist.

Self-tuning parallel mode (--of > 1, used by GitHub Actions):
  Crawls ALL active projects every run. First probes API latency with 20 sample
  requests, then auto-calculates the number of parallel workers needed to finish
  within BUDGET_MINUTES. No hardcoded worker count — adapts automatically as the
  project list grows or API speed changes.

Full mode (--of 1, manual):
  Crawls all projects including completed ones. Use locally for a one-off refresh.

Designed to run via GitHub Actions (see .github/workflows/teduh-daily.yml).
"""
import argparse
import json
import math
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument('--batch', type=int, default=0,
                    help='Batch index (0-based, default 0)')
parser.add_argument('--of', type=int, default=1, dest='num_batches',
                    help='Total number of batches (default 1 = crawl all)')
args = parser.parse_args()

ACTIVE_STATUSES = {"Lancar", "Lewat", "Sakit"}
BUDGET_MINUTES = 50   # target finish time; 60-min workflow cap gives 10-min headroom
PROBE_N = 20          # projects to sample before calculating worker count

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    "Accept": "application/json",
    "Referer": "https://teduh.kpkt.gov.my/semakan-status-kemajuan",
}
BASE = "https://teduh.kpkt.gov.my/api/projek-swasta/"


def fetch_detail(project_id, max_retries=2):
    url = BASE + project_id
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            resp = urllib.request.urlopen(req, timeout=8)
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

if args.num_batches > 1:
    projects_to_crawl = [p for p in projects if p.get("status") in ACTIVE_STATUSES]
    print(f"  {len(projects_to_crawl)} active projects (Lancar/Lewat/Sakit)")
else:
    projects_to_crawl = projects
    print(f"  Full crawl: {len(projects_to_crawl)} projects")

enriched = 0
failed = 0
no_price_data = 0
t0 = time.time()

ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")
snapshot = {"date": ts, "projects": {}}


def record(p, pid, detail):
    """Apply a completed detail result to the project and snapshot."""
    global enriched, failed, no_price_data
    if detail is None:
        failed += 1
        return
    p["detail"] = detail
    if detail["unit_types"]:
        enriched += 1
        if pid:
            snapshot["projects"][pid] = {
                ut["type"]: ut["takeup_pct"]
                for ut in detail["unit_types"] if ut.get("type")
            }
    else:
        no_price_data += 1


def crawl_one(p):
    pid = p.get("id")
    if not pid:
        return p, None, None
    return p, pid, extract_detail(fetch_detail(pid))


# ── Phase 1: latency probe ────────────────────────────────────────────────────
# Crawl PROBE_N evenly-spaced projects sequentially to measure actual API speed
# on this runner/network. Then compute exactly how many parallel workers are
# needed to finish the rest within BUDGET_MINUTES. No hardcoded worker count.
probe_step = max(1, len(projects_to_crawl) // PROBE_N)
probe = projects_to_crawl[::probe_step][:PROBE_N]
probe_ids = {id(p) for p in probe}

t_probe = time.time()
for p in probe:
    p, pid, detail = crawl_one(p)
    record(p, pid, detail)
probe_elapsed = time.time() - t_probe

avg_lat = probe_elapsed / max(len(probe), 1)
rest = [p for p in projects_to_crawl if id(p) not in probe_ids]
remaining_budget = max(BUDGET_MINUTES * 60 - probe_elapsed, 1)
workers = max(2, min(math.ceil(len(rest) * avg_lat / remaining_budget), 20))
print(f"  Probe: {avg_lat:.2f}s avg over {len(probe)} samples "
      f"| {len(rest)} remaining | budget {remaining_budget/60:.0f} min "
      f"→ {workers} workers auto-selected")

# ── Phase 2: parallel crawl ───────────────────────────────────────────────────
with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = {executor.submit(crawl_one, p): p for p in rest}
    for i, future in enumerate(as_completed(futures)):
        record(*future.result())
        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (len(probe) + i + 1) / elapsed
            remaining_n = len(rest) - i - 1
            print(f"  {len(probe)+i+1}/{len(projects_to_crawl)} | "
                  f"enriched={enriched} failed={failed} | "
                  f"~{remaining_n/rate/60:.1f} min remaining")

if failed:
    print(f"  {failed} projects failed — will pick up next run")

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
