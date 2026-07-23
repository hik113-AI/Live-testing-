"""
extract_brochures.py — downloads brochure PDFs from hims.kpkt.gov.my,
picks the best embedded JPEG (scored by aspect ratio to prefer facade/hero
shots over floor plans), compresses to ≤90KB, and saves to b/{id}.jpg.

Run once to bulk-populate, then 4x daily by GitHub Actions for new projects.
Images are served directly as static files — no proxy, no per-user PDF download.
"""
import json, os, io, time, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    print("Pillow not installed — run: pip3 install Pillow")
    sys.exit(1)

OUTDIR         = "b"
MAX_W          = 900      # px — enough for a 190px-tall popup preview
QUALITY        = 68       # JPEG quality target
MAX_SIZE       = 90_000   # bytes — re-compress if still over this
WORKERS        = 12
DELAY          = 0.15     # seconds between requests per worker
MIN_JPEG_BYTES = 40_000   # skip logos / thumbnails
MAX_CANDIDATES = 8        # stop scanning after collecting this many large JPEGs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    "Referer":    "https://teduh.kpkt.gov.my/",
}

os.makedirs(OUTDIR, exist_ok=True)


def score_jpeg(jpeg_bytes: bytes) -> float:
    """Score a JPEG by how likely it is to be a property cover/facade image.
    Landscape images (wider than tall) score highest; floor plans (portrait)
    and site maps (very wide) score low."""
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        w, h = img.size
    except Exception:
        return 0.0
    if h == 0:
        return 0.0
    ratio = w / h
    if 1.2 <= ratio <= 2.5:   # ideal: landscape property hero / facade photo
        return 1.0
    if 1.0 <= ratio < 1.2:    # nearly square — possible but less likely cover
        return 0.6
    if ratio > 2.5:            # very wide: site plan / location map
        return 0.25
    return 0.1                 # portrait: floor plan


def extract_cover_jpeg(data: bytes) -> bytes | None:
    """Collect up to MAX_CANDIDATES embedded JPEGs ≥ MIN_JPEG_BYTES and return
    the one most likely to be the property cover (scored by aspect ratio;
    file size breaks ties — bigger raw bytes = higher quality image)."""
    candidates: list[bytes] = []
    i = 0
    while i < len(data) - 3 and len(candidates) < MAX_CANDIDATES:
        if data[i] == 0xFF and data[i + 1] == 0xD8 and data[i + 2] == 0xFF:
            j = i + 2
            while j < len(data) - 1:
                if data[j] == 0xFF and data[j + 1] == 0xD9:
                    chunk = data[i:j + 2]
                    if len(chunk) >= MIN_JPEG_BYTES:
                        candidates.append(chunk)
                    i = j + 2
                    break
                j += 1
            else:
                i += 1  # no end marker — skip start byte and keep scanning
        else:
            i += 1
    if not candidates:
        return None
    return max(candidates, key=lambda b: (score_jpeg(b), len(b)))


def compress(jpeg_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    if img.width > MAX_W:
        img = img.resize((MAX_W, int(img.height * MAX_W / img.width)), Image.LANCZOS)
    q = QUALITY
    while q >= 40:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        result = buf.getvalue()
        if len(result) <= MAX_SIZE:
            return result
        q -= 8
    return result


def process(project_id: str, url: str) -> tuple[str, str]:
    """Returns (project_id, 'ok'|'skip'|'error:<reason>')."""
    out_path = os.path.join(OUTDIR, f"{project_id}.jpg")
    if os.path.exists(out_path):
        return project_id, "skip"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        data = urllib.request.urlopen(req, timeout=20).read()
        time.sleep(DELAY)
    except Exception as e:
        return project_id, f"error:fetch:{e}"

    jpeg = extract_cover_jpeg(data)
    if not jpeg:
        return project_id, "error:no_jpeg"

    try:
        compressed = compress(jpeg)
        with open(out_path, "wb") as f:
            f.write(compressed)
        return project_id, "ok"
    except Exception as e:
        return project_id, f"error:compress:{e}"


print("Loading teduh_projects.json …")
with open("teduh_projects.json") as f:
    raw = json.load(f)

# Build work list: projects with a brochure URL that we haven't extracted yet
work = []
for p in raw["projects"]:
    pid = p.get("id")
    detail = p.get("detail") or {}
    url = detail.get("brochure_url") or ""
    if not pid or not url:
        continue
    if os.path.exists(os.path.join(OUTDIR, f"{pid}.jpg")):
        continue
    work.append((str(pid), url))

already = len(os.listdir(OUTDIR))
print(f"  {already} already extracted | {len(work)} to process")

if not work:
    print("Nothing to do.")
    sys.exit(0)

ok = err = 0
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    futures = {pool.submit(process, pid, url): pid for pid, url in work}
    for i, fut in enumerate(as_completed(futures), 1):
        pid, status = fut.result()
        if status == "ok":
            ok += 1
        elif status != "skip":
            err += 1
        if i % 50 == 0 or i == len(work):
            print(f"  {i}/{len(work)} — ok:{ok} err:{err}", flush=True)

total = len(os.listdir(OUTDIR))
print(f"\nDone. {ok} new | {err} errors | {total} total in {OUTDIR}/")
size_mb = sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in os.listdir(OUTDIR)) / 1_048_576
print(f"Folder size: {size_mb:.1f} MB")
