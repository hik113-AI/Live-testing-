"""
extract_brochures.py — downloads brochure PDFs from hims.kpkt.gov.my,
picks the best embedded JPEG using CLIP (zero-shot ML, no API key needed),
compresses to ≤90KB, and saves to b/{id}.jpg.

Runs automatically 4x daily via GitHub Actions for new projects.
Pass --reextract to reprocess all existing images (e.g. after algorithm updates).

How the image selection works:
  CLIP (openai/clip-vit-base-patch32) is a free open-source vision model that
  scores images against text descriptions. Each candidate JPEG is scored against
  "an exterior photo or render of a residential building" — the highest-scoring
  image wins. Falls back to aspect-ratio + edge-density heuristics if
  transformers/torch are not installed.
"""
import json, os, io, time, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    print("Pillow not installed — run: pip3 install Pillow")
    sys.exit(1)

# ── CLIP setup (optional — graceful fallback to heuristics if missing) ────

USE_ML = False
_clip_model = None
_clip_processor = None

try:
    from transformers import CLIPProcessor, CLIPModel
    import torch

    print("Loading CLIP model (openai/clip-vit-base-patch32) …")
    _clip_model     = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    _clip_model.eval()
    USE_ML = True
    print("  CLIP ready.")
except Exception as e:
    print(f"  CLIP not available ({e}) — using heuristic fallback.")

# Text descriptions CLIP scores each image against.
# Index 0 is what we want; higher probability = better pick.
_PROMPTS = [
    "an exterior photo or architectural render of a residential building or house",
    "a marketing brochure flyer with price text bullet points and coloured boxes",
    "a floor plan blueprint showing room layouts and dimensions",
    "a location map or site plan aerial view",
]

OUTDIR         = "b"
MAX_W          = 900
QUALITY        = 68
MAX_SIZE       = 90_000
WORKERS        = 8 if USE_ML else 12   # fewer workers when doing ML inference
DELAY          = 0.15
MIN_JPEG_BYTES = 40_000
MAX_CANDIDATES = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    "Referer":    "https://teduh.kpkt.gov.my/",
}

os.makedirs(OUTDIR, exist_ok=True)
REEXTRACT = "--reextract" in sys.argv


# ── CLIP scorer ────────────────────────────────────────────────────────────

def _clip_score_property(jpeg_bytes: bytes) -> float:
    """Return the probability that this image is a property exterior photo/render."""
    import torch
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    inputs = _clip_processor(
        text=_PROMPTS, images=img, return_tensors="pt", padding=True
    )
    with torch.no_grad():
        outputs = _clip_model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)[0]
    return probs[0].item()  # probability for prompt index 0


# ── heuristic scorer (fallback) ────────────────────────────────────────────

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


# ── JPEG extraction from raw PDF bytes ────────────────────────────────────

def extract_cover_jpeg(data: bytes) -> bytes | None:
    """Scan PDF bytes for embedded JPEGs, return the one that looks most
    like a property exterior photo."""
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

    if USE_ML:
        return max(candidates, key=_clip_score_property)

    return max(
        enumerate(candidates),
        key=lambda t: _heuristic_score(t[1], t[0], len(candidates)),
    )[1]


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

mode = "CLIP ML" if USE_ML else "heuristic (install transformers + torch for ML)"
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
