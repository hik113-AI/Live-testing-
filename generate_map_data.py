"""
generate_map_data.py — builds map_data.json from teduh_projects.json.

Filters TEDUH projects for the map:
  - All active projects (Lancar/Lewat/Sakit) regardless of date
  - Completed projects (Siap Dengan CCC/CFO) with expected_completion >= 2021

Output: map_data.json with:
  - projects: 16-column arrays matching the site's DATA format
  - sstats: per-state stats for the state choropleth view

Run after each detail crawl via GitHub Actions.
"""
import json
import re
import os
import statistics
from collections import defaultdict

ACTIVE_STATUSES = {"Lancar", "Lewat", "Sakit"}
LANDED_KW = {"teres", "banglo", "semi", "cluster", "bungalow", "villa", "townhouse", "kotej"}

def in_malaysia(lat, lon):
    """Return True if (lat, lon) falls within Peninsular Malaysia, Sarawak, or Sabah."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if 1.15 <= lat <= 6.75 and 99.4 <= lon <= 104.8:  return True  # Peninsular (south tip ~1.26°N)
    if 0.85 <= lat <= 5.15 and 109.3 <= lon <= 115.7:  return True  # Sarawak
    if 4.00 <= lat <= 7.50 and 115.4 <= lon <= 119.5:  return True  # Sabah
    return False

# ── Land polygon (shapely) — catches offshore coordinates bounding-box misses ──

_MALAYSIA_STRICT = None  # exact land polygon
_MALAYSIA_LOOSE  = None  # polygon + ~5 km buffer (keeps coastal/reclaimed projects)
_family_valid: dict = {}  # family prefix -> [(lat, lon)] for sibling correction

try:
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union as _union
    _geo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'malaysia_land.geojson')
    with open(_geo_path) as _f:
        _geo_feat = json.load(_f)
    _base = _union([shape(f['geometry']) for f in _geo_feat['features']])
    _MALAYSIA_STRICT = _base
    _MALAYSIA_LOOSE  = _base.buffer(0.05)  # ~5 km
    _USE_POLYGON = True
except Exception as _e:
    _USE_POLYGON = False


def _sibling_correct(pid: str, la: float, lo: float):
    """Return family-median coords when this project is a tight-cluster outlier."""
    fam = pid.rsplit('-', 1)[0] if '-' in pid else pid
    siblings = [(sla, slo) for sla, slo in _family_valid.get(fam, [])
                if not (abs(sla - la) < 1e-4 and abs(slo - lo) < 1e-4)]
    if len(siblings) < 2:
        return la, lo
    s_lats = [s[0] for s in siblings]
    s_lons = [s[1] for s in siblings]
    if max(max(s_lats) - min(s_lats), max(s_lons) - min(s_lons)) > 0.03:
        return la, lo  # siblings spread too wide — not a single-site development
    med_lat = statistics.median(s_lats)
    med_lon = statistics.median(s_lons)
    if abs(la - med_lat) > 0.20 or abs(lo - med_lon) > 0.20:
        return med_lat, med_lon  # this point is a clear outlier from the cluster
    return la, lo


def clean_coords(raw_lat, raw_lon, pid: str = ''):
    """Return (lat, lon) if valid Malaysian coords.

    Steps:
    1. Bounding-box check (in_malaysia), try lat/lon swap if needed.
    2. If shapely polygon available, check against strict polygon + 5 km buffer.
       - Strictly on land → accept.
       - Within 5 km buffer (coastal/reclaimed land) → accept.
       - Offshore → attempt sibling correction; if corrected to valid location accept,
         otherwise reject (returns None, None).
    """
    if not raw_lat or not raw_lon:
        return None, None

    def _validate(la, lo):
        if not in_malaysia(la, lo):
            return None, None
        la, lo = float(la), float(lo)
        if not _USE_POLYGON:
            return la, lo
        from shapely.geometry import Point as _Pt
        pt = _Pt(lo, la)
        if _MALAYSIA_STRICT.contains(pt):
            return la, lo
        if _MALAYSIA_LOOSE.contains(pt):
            # Near-coast: try sibling improvement, otherwise keep original
            cla, clo = _sibling_correct(pid, la, lo)
            if (cla != la or clo != lo) and _MALAYSIA_STRICT.contains(_Pt(clo, cla)):
                return cla, clo
            return la, lo
        # Offshore: require sibling correction to a valid location
        cla, clo = _sibling_correct(pid, la, lo)
        if _MALAYSIA_LOOSE.contains(_Pt(clo, cla)):
            return cla, clo
        return None, None

    result = _validate(raw_lat, raw_lon)
    if result[0] is not None:
        return result
    return _validate(raw_lon, raw_lat)  # try swapped
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
TIER_THRESHOLDS = [300000, 600000, 1000000]

STATE_NORMALIZE = {
    "W.P. Kuala Lumpur": "Kuala Lumpur",
    "W.P. Putrajaya": "Putrajaya",
    "W.P. Labuan": "Labuan",
    "Pulau Pinang": "Penang",
}

UNIT_TYPE_EN = {
    "Rumah Teres":               "Terrace",
    "Rumah Berkembar":           "Semi-D",
    "Rumah Pangsa/Kondo":        "Condo",
    "Rumah Sesebuah":            "Detached",
    "Pangsapuri Servis":         "Serviced Apt",
    "Rumah Kluster":             "Cluster",
    "Rumah Bandar":              "Townhouse",
    "Soho":                      "SoHo",
    "Pangsapuri Suite":          "Apt Suite",
    "Rumah Kedai (G)":           "Shop-House",
    "Rumah Kedai (H)":           "Shop-House",
    "Rumah Berpagar":            "Gated",
    "Rumah Berpagar & Berpengawal": "Gated & Guarded",
    "Suite Homes":               "Suite",
}


def to_date_str(s):
    """Convert TEDUH date to 'DD Mon YYYY'. Returns '' if unparseable."""
    if not s or s in ("null", "NULL", "-"):
        return ""
    s = s.strip()
    # Already in target format e.g. "14 Dec 2025"
    if re.match(r"\d{1,2}\s+\w{3}\s+\d{4}$", s):
        return s
    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            return f"{d:02d} {MONTH_ABBR[mo-1]} {y}"
    # YYYY-MM
    m = re.match(r"(\d{4})-(\d{2})$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"01 {MONTH_ABBR[mo-1]} {y}"
    return ""


def get_bedrooms(unit_types):
    """Return bedroom range string e.g. '3' or '2–5'. Empty if no data."""
    beds = set()
    for ut in unit_types:
        for x in (ut.get("bedrooms") or "").split(","):
            x = x.strip()
            if x.isdigit():
                beds.add(int(x))
    if not beds:
        return ""
    mn, mx = min(beds), max(beds)
    return str(mn) if mn == mx else f"{mn}–{mx}"


def get_unit_types_str(unit_types):
    """Return translated unit type string e.g. 'Terrace' or 'Condo / SoHo'."""
    seen = []
    for ut in unit_types:
        t = ut.get("type") or ""
        label = UNIT_TYPE_EN.get(t, t)
        if label and label not in seen:
            seen.append(label)
    return " / ".join(seen[:3])


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

# Build family coordinate map for sibling correction (uses all bounding-box-valid coords)
_fv: dict = defaultdict(list)
for _p in all_projects:
    _pid = str(_p.get('id', ''))
    _fam = _pid.rsplit('-', 1)[0] if '-' in _pid else _pid
    try:
        _la, _lo = float(_p['lat']), float(_p['lon'])
        if in_malaysia(_la, _lo):
            _fv[_fam].append((_la, _lo))
    except Exception:
        pass
_family_valid.update(_fv)
if _USE_POLYGON:
    print(f"  Land polygon active — sibling correction enabled for {len(_family_valid)} families.")

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
ss_psf     = defaultdict(list)   # median PSF per state
ss_ty      = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
ss_devunit = defaultdict(lambda: defaultdict(int))

for p in all_projects:
    lat, lon = clean_coords(p.get("lat"), p.get("lon"), pid=str(p.get('id', '')))
    if lat is None:
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
    dev_phone = dev.get("phone") or ""

    state_raw = p.get("state") or ""
    state = STATE_NORMALIZE.get(state_raw, state_raw)

    bumi = p.get("bumi_quota_pct") or ""
    bumi_pct = round(float(bumi)) if bumi else 0

    has_offenses = 1 if detail.get("developer_has_offenses") else 0

    # Compact unit types: "TypeEN|beds|area_m2|pmin|pmax|units" joined by "~"
    ut_parts = []
    for ut in unit_types:
        type_en = UNIT_TYPE_EN.get(ut.get("type") or "", ut.get("type") or "")
        beds = (ut.get("bedrooms") or "").replace(" ", "")
        area = int(to_float(ut.get("area")))
        pmin_ut = int(to_float(ut.get("price_min")))
        pmax_ut = int(to_float(ut.get("price_max")))
        u_count = int(ut.get("units") or 0)
        if type_en or pmin_ut:
            ut_parts.append(f"{type_en}|{beds}|{area}|{pmin_ut}|{pmax_ut}|{u_count}")
    units_compact = "~".join(ut_parts)

    # Completion/launch year (for year filter) — from date_str (first_pjb_date for
    # active projects, expected_completion for done). Active projects never have
    # expected_completion populated, so date_str is the only reliable source.
    comp_year = 0
    if date_str:
        m = re.search(r"\b(\d{4})\b", date_str)
        if m: comp_year = int(m.group(1))
    elif exp_comp:
        m2 = str(exp_comp)[:4]
        if m2.isdigit(): comp_year = int(m2)

    map_projects.append([
        p["name"],        # d[0]  name
        lat,              # d[1]  lat
        lon,              # d[2]  lon
        status_code,      # d[3]  "active"/"done"
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
        p.get("id", ""),  # d[14] TEDUH project ID
        detail.get("brochure_url") or "",  # d[15] brochure PDF URL
        state,            # d[16] state name
        bumi_pct,         # d[17] bumi quota % (0 = none/unknown)
        dev_phone,        # d[18] developer phone
        get_bedrooms(unit_types),       # d[19] bedroom range e.g. "3" or "2–5"
        get_unit_types_str(unit_types), # d[20] unit type e.g. "Terrace" or "Condo / SoHo"
        has_offenses,     # d[21] 1 if developer has KPKT offenses
        units_compact,    # d[22] compact unit types "TypeEN|beds|area|pmin|pmax|units~..."
        comp_year,        # d[23] completion year int (0 if unknown)
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
        M2_TO_SQFT = 10.7639
        if price_min > 0 and area_max > 0:
            psf = round(price_min / (area_max * M2_TO_SQFT))
            ss_psf[state].append(psf)
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
    psf_list = sorted(ss_psf[state])
    med_psf = psf_list[len(psf_list) // 2] if psf_list else 0
    sstats[state] = {
        "n":       ss_n[state],
        "units":   ss_units[state],
        "sold":    ss_sold[state],
        "landed":  ss_landed[state],
        "highrise": ss_n[state] - ss_landed[state],
        "active":  ss_active[state],
        "done":    ss_done[state],
        "medP":    med_p,
        "medPsf":  med_psf,
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
