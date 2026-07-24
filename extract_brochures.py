"""
extract_brochures.py — downloads brochure PDFs from hims.kpkt.gov.my,
picks the best embedded JPEG using Claude Vision (Haiku), compresses to
≤90KB, and saves to b/{id}.jpg.

Run automatically 4x daily by GitHub Actions for new projects.
Pass --reextract to reprocess all existing images (e.g. after algorithm update).
"""
import json, os, io, time, sys, base64, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    print("Pillow not installed — run: pip3 install Pillow")
    sys.exit(1)

try:
    import anthropic
    _claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    USE_CLAUDE = bool(os.environ.get("ANTHROPIC_API_KEY"))
except ImportError:
    _claude = None
    USE_CLAUDE = False

OUTDIR         = "b"
MAX_W          = 900      # px
QUALITY        = 68       # JPEG quality target
MAX_SIZE       = 90_000   # bytes
WORKERS        = 12
DELAY          = 0.15     # seconds between requests per worker
MIN_JPEG_BYTES = 40_000   # skip logos / thumbnails
MAX_CANDIDATES = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    "Referer":    "https://teduh.kpkt.gov.my/",
}

os.makedirs(OUTDIR, exist_ok=True)
REEXTRACT = "--reextract" in sys.argv


# ── heuristic scorer (fallback when Claude is unavailable) ────────────────

def _heuristic_score(jpeg_bytes: bytes, position: int, total: int) -> float:
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        w, h = img.size
    except Exception:
        return 0.0
    if h == 0:
        return 0.0
    ratio = w / h

    if 1.2 <= ratio <= 2.5:
        ar_score = 1.0
    elif 1.0 <= ratio < 1.2:
        ar_score = 0.6
    elif ratio > 2.5:
        ar_score = 0.25
    else:
        ar_score = 0.1

    try:
        small = img.resize((64, 32), Image.LANCZOS).convert("L")
        pix = small.load()
        edges = sum(
            1 for y in range(32) for x in range(63)
            if abs(pix[x, y] - pix[x + 1, y]) > 25
        )
        photo_score = max(0.0, 1.0 - (edges / (64 * 32)) * 3)
    except Exception:
        photo_score = 0.5

    pos_bonus = (1 - position / max(1, total)) * 0.3
    return ar_score * 0.6 + photo_score * 0.4 + pos_bonus


def _pick_heuristic(candidates: list[bytes]) -> bytes:
    return max(
        enumerate(candidates),
        key=lambda t: _heuristic_score(t[1], t[0], len(candidates)),
    )[1]


# ── Claude Vision picker ──────────────────────────────────────────────────

def _pick_with_claude(candidates: list[bytes]) -> bytes:
    """Ask Claude Haiku which candidate is the best property thumbnail."""
    if len(candidates) == 1:
        return candidates[0]

    content = []
    for i, b in enumerate(candidates, 1):
        content.append({
            "type": "text",
            "text": f"Image {i}:"
        })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(b).decode(),
            },
        })

    content.append({
        "type": "text",
        "text": (
            f"These {len(candidates)} images were extracted from a Malaysian property "
            "brochure PDF. Reply with ONLY a single number — the index (1 to "
            f"{len(candidates)}) of the image most suitable as a property listing "
            "thumbnail. Prefer exterior renders or photos of the building. "
            "Reject floor plans, location maps, and marketing flyers with price "
            "text or bullet points overlaid on the image."
        ),
    })

    try:
        resp = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            messages=[{"role": "user", "content": content}],
        )
        idx = int(resp.content[0].text.strip()) - 1
        return candidates[max(0, min(idx, len(candidates) - 1))]
    except Exception:
        return _pick_heuristic(candidates)


# ── JPEG extraction from raw PDF bytes ────────────────────────────────────

def extract_cover_jpeg(data: bytes) -> bytes | None:
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
                i += 1
        else:
            i += 1

    if not candidates:
        return None
    if USE_CLAUDE:
        return _pick_with_claude(candidates)
    return _pick_heuristic(candidates)


# ── compression ───────────────────────────────────────────────────────────

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


# ── per-project processing ────────────────────────────────────────────────

def process(project_id: str, url: str) -> tuple[str, str]:
    out_path = os.path.join(OUTDIR, f"{project_id}.jpg")
    if os.path.exists(out_path) and not REEXTRACT:
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


# ── main ──────────────────────────────────────────────────────────────────

print("Loading teduh_projects.json …")
with open("teduh_projects.json") as f:
    raw = json.load(f)

mode = "Claude Vision" if USE_CLAUDE else "heuristic (no API key)"
print(f"  Image selection: {mode}")
if REEXTRACT:
    print("  Mode: --reextract (overwriting existing images)")

work = []
for p in raw["projects"]:
    pid = p.get("id")
    detail = p.get("detail") or {}
    url = detail.get("brochure_url") or ""
    if not pid or not url:
        continue
    if not REEXTRACT and os.path.exists(os.path.join(OUTDIR, f"{pid}.jpg")):
        continue
    work.append((str(pid), url))

already = len(os.listdir(OUTDIR))
print(f"  {already} already extracted | {len(work)} to process")

if not work:
    print("Nothing to do.")
    sys.exit(0)

ok = err = 0
# Claude Vision calls are sequential per project so use fewer workers to
# avoid hammering the Anthropic API; heuristic mode can use full concurrency.
workers = 4 if USE_CLAUDE else WORKERS
with ThreadPoolExecutor(max_workers=workers) as pool:
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
