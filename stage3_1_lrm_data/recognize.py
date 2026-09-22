#!/usr/bin/env python3
"""LRM stage 3.1a: scholarly PDF -> static per-page JSON (page -> block -> word bbox) + page PNGs via an LLM vision call.
Adapted from YS1's ys_pipeline.py (word boxes are snapped to the PDF text layer when it matches).

    python stage3_1_lrm_data/recognize.py --pdf input/fr/book.pdf --lang fr [--start 1 --end 100]

The page limit defaults to MAX_NUMBER_OF_PAGES_TO_USE from .env (a number, or NONE for the whole book).
Output: output/<lang>/<source_key>/json/page_0001.json, index.json and output/<lang>/<source_key>/pages/page_0001.png
Coordinates are fractions of the page image: x, y, w, h in 0..1, origin top-left.

OCR_PROVIDER_NAME in .env selects the vision backend (same SCHEMA/PROMPT either way):
  - ocr_with_google (default): Gemini via GOOGLE_AI_API_KEY.
  - ocr_with_aws: Claude on AWS Bedrock via AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_REGION + BEDROCK_MODEL_ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz  # pymupdf
from dotenv import load_dotenv

STAGE = Path(__file__).resolve().parent  # stage3_1_lrm_data/ (input/, output/, languages.json)
ROOT = STAGE.parent  # RAG11 (.env)
load_dotenv(ROOT / ".env")
LANGS = json.loads((STAGE / "languages.json").read_text(encoding="utf-8"))

import ocr_schema
import recognize_google
import recognize_aws

PROVIDER = (os.getenv("OCR_PROVIDER_NAME") or "ocr_with_google").strip().lower()
_PROVIDERS = {"ocr_with_google": recognize_google, "ocr_with_aws": recognize_aws}
if PROVIDER not in _PROVIDERS:
    sys.exit(f"Unknown OCR_PROVIDER_NAME={PROVIDER!r} (use ocr_with_google or ocr_with_aws)")
PROVIDER_MODULE = _PROVIDERS[PROVIDER]

# set by configure(): which source PDF / language is being processed
LANG = "fr"
KEY = ""
PDF_DIR = STAGE / "input" / LANG
JSON_DIR = IMG_DIR = STAGE / "output"
DEFAULT_MODEL = PROVIDER_MODULE.DEFAULT_MODEL


def slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "source"


def out_dir(lang: str, key: str) -> Path:
    return STAGE / "output" / lang / key


def configure(lang: str, key: str) -> None:
    global LANG, KEY, JSON_DIR, IMG_DIR
    LANG, KEY = lang, key
    JSON_DIR, IMG_DIR = out_dir(lang, key) / "json", out_dir(lang, key) / "pages"


def max_pages() -> int | None:
    v = (os.getenv("MAX_NUMBER_OF_PAGES_TO_USE") or "100").strip()
    return None if v.upper() in ("NONE", "") else int(v)
DPI = 170
SCHEMA_VERSION = 1
SRC_PDF: Path | None = None

BLOCK_TYPES = ocr_schema.BLOCK_TYPES
# blocks that are page furniture: kept for the visual layer, excluded from LRM sequence
NON_LRM = {"running_header", "running_footer", "page_number"}

SCHEMA = ocr_schema.SCHEMA
PROMPT = ocr_schema.PROMPT

# translate.py always uses Gemini for translation (independent of OCR_PROVIDER_NAME), so it
# imports this module and calls fr.api_key() directly regardless of which OCR provider is active.
api_key = recognize_google.api_key


def make_client(model: str | None = None):
    """Build the vision-API client for the configured OCR_PROVIDER_NAME."""
    return PROVIDER_MODULE.make_client(model)


def clamp(v: int) -> int:
    return max(0, min(1000, int(v)))


def norm_box(box) -> dict | None:
    """[ymin,xmin,ymax,xmax] 0-1000  ->  {x,y,w,h} fractions."""
    if not isinstance(box, list) or len(box) != 4:
        return None
    y0, x0, y1, x1 = (clamp(v) for v in box)
    if y1 < y0:
        y0, y1 = y1, y0
    if x1 < x0:
        x0, x1 = x1, x0
    return {"x": round(x0 / 1000, 4), "y": round(y0 / 1000, 4),
            "w": round((x1 - x0) / 1000, 4), "h": round((y1 - y0) / 1000, 4)}


def build_page(raw: dict, page_no: int, size: tuple[int, int], model: str, src: str) -> dict:
    """Turn Gemini output into the static page document (adds ids, offsets, text)."""
    blocks = []
    for bi, rb in enumerate(raw.get("blocks", []), 1):
        bid = f"p{page_no:04d}_b{bi:03d}"
        words, parts, pos = [], [], 0
        for wi, rw in enumerate(rb.get("words", []), 1):
            text = rw.get("t", "")
            box = norm_box(rw.get("box"))
            if not text or box is None:
                continue
            start = pos
            parts.append(text)
            pos += len(text) + 1  # joined by single spaces
            words.append({"id": f"{bid}_w{wi:03d}", "text": text, "bbox": box,
                          "lang": LANG if rw.get("lang") == "src" else rw.get("lang", "other"), "style": rw.get("style", "normal"),
                          "char_start": start, "char_end": start + len(text)})
        blocks.append({
            "id": bid, "local_id": rb.get("block_id", f"b{bi}"),
            "type": rb.get("type", "other"), "reading_order": bi,
            "bbox": norm_box(rb.get("box")),
            "text": " ".join(parts), "words": words,
            "sutra_ref": rb.get("sutra_ref", ""), "footnote_marker": rb.get("footnote_marker", ""),
            "section_path": rb.get("section_path", []),
            "continues_from_previous_page": bool(rb.get("continues_from_previous_page")),
            "continues_on_next_page": bool(rb.get("continues_on_next_page")),
            "_parent_local": rb.get("parent_block_id", ""),
            # filled by link_book(); LRM stage consumes these
            "lrm": None,
            # placeholders for the future LRM stage (nothing translated in step 1)
            "translations": {"ru": None, "en_us": None},
        })
    local = {b["local_id"]: b["id"] for b in blocks}
    for b in blocks:
        parent = local.get(b.pop("_parent_local"), "")
        b["parent_block_id"] = "" if parent == b["id"] else parent
    return {
        "schema_version": SCHEMA_VERSION, "page": page_no,
        "printed_page_number": raw.get("printed_page_number", ""),
        "image": f"{LANG}/{KEY}/pages/page_{page_no:04d}.png", "lang": LANG, "source_key": KEY, "image_size": {"width": size[0], "height": size[1]},
        "coordinate_system": "fractions of page image; x,y,w,h in 0..1; origin top-left",
        "source": src, "model": model, "blocks": blocks,
    }



def fold(t: str) -> str:
    """Comparable key: strip diacritics/punctuation so true text and the corrupted text layer can be matched."""
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if c.isascii() and c.isalnum())


def _center(b: dict) -> tuple[float, float]:
    return b["x"] + b["w"] / 2, b["y"] + b["h"] / 2


def _align(gkey, gbox, pkey, pbox) -> dict[int, int]:
    """Needleman-Wunsch over reading-ordered words: fuzzy text similarity + same-line geometry."""
    from difflib import SequenceMatcher
    G, P, GAP = len(gkey), len(pkey), -0.4
    gc = [_center(b) for b in gbox]; pc = [_center(b) for b in pbox]

    def score(i: int, j: int) -> float:
        dy = abs(gc[i][1] - pc[j][1])
        if dy > 0.015:
            return -1.0
        a, b = gkey[i], pkey[j]
        sim = 0.5 if not a and not b else SequenceMatcher(None, a, b).ratio() if a and b else 0.0
        return (sim - 0.45) * 2  # x is not used: Gemini's x drifts; order + line (y) anchor the alignment

    H = [[0.0] * (P + 1) for _ in range(G + 1)]
    T = [[0] * (P + 1) for _ in range(G + 1)]  # 0 diag, 1 up (skip g), 2 left (skip p)
    for i in range(1, G + 1):
        H[i][0], T[i][0] = i * GAP, 1
    for j in range(1, P + 1):
        H[0][j], T[0][j] = j * GAP, 2
    for i in range(1, G + 1):
        Hi, Hp, Ti = H[i], H[i - 1], T[i]
        for j in range(1, P + 1):
            d = Hp[j - 1] + score(i - 1, j - 1)
            u = Hp[j] + GAP
            l = Hi[j - 1] + GAP
            if d >= u and d >= l:
                Hi[j], Ti[j] = d, 0
            elif u >= l:
                Hi[j], Ti[j] = u, 1
            else:
                Hi[j], Ti[j] = l, 2
    match: dict[int, int] = {}
    i, j = G, P
    while i > 0 or j > 0:
        t = T[i][j]
        if i > 0 and j > 0 and t == 0:
            if score(i - 1, j - 1) > 0:
                match[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif i > 0 and (t == 1 or j == 0):
            i -= 1
        else:
            j -= 1
    return match


def refine_page(page: dict, fpage: "fitz.Page") -> dict:
    """Snap Gemini's approximate word boxes to the exact geometry of the PDF text layer.

    The text layer has corrupted glyphs but exact positions. Words are aligned by (1) sequence match on folded
    text, (2) in-gap pairing (same count -> in order, else nearest centre). Words without a counterpart keep the
    Gemini box (bbox_source = "gemini"). Original Gemini boxes stay in `bbox_gemini`, so this is re-runnable.
    """
    from difflib import SequenceMatcher
    r = fpage.rect
    pw = [w for w in fpage.get_text("words", sort=True) if w[4].strip()]
    pbox = [{"x": w[0] / r.width, "y": w[1] / r.height, "w": (w[2] - w[0]) / r.width, "h": (w[3] - w[1]) / r.height}
            for w in pw]
    pkey = [fold(w[4]) for w in pw]
    gw = [w for b in page["blocks"] for w in b["words"]]
    for w in gw:
        w.setdefault("bbox_gemini", w["bbox"])
    gkey = [fold(w["text"]) for w in gw]
    gbox = [w["bbox_gemini"] for w in gw]
    match: dict[int, int] = {}
    if pw and gw:
        match = _align(gkey, gbox, pkey, pbox)
    n_snap = 0
    for i, w in enumerate(gw):
        if i in match:
            pb = pbox[match[i]]
            # sanity: the text-layer word must sit near where Gemini saw it (guards against misalignment)
            cx, cy = _center(gbox[i]); px, py = _center(pb)
            if abs(py - cy) < 0.02:
                w["bbox"] = {k: round(v, 4) for k, v in pb.items()}
                w["bbox_source"] = "pdf_text_layer"; n_snap += 1; continue
        w["bbox"] = gbox[i]; w["bbox_source"] = "gemini"
    for b in page["blocks"]:
        if b["words"]:
            x0 = min(w["bbox"]["x"] for w in b["words"]); y0 = min(w["bbox"]["y"] for w in b["words"])
            x1 = max(w["bbox"]["x"] + w["bbox"]["w"] for w in b["words"])
            y1 = max(w["bbox"]["y"] + w["bbox"]["h"] for w in b["words"])
            b["bbox"] = {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}
    page["bbox_refinement"] = {"method": "pdf_text_layer_snap", "words": len(gw), "snapped": n_snap}
    return page


def link_book() -> int:
    """Second pass over all recognised pages: global sequence, parent/child chunk numbers, prev/next.

    chunk_number_in_lrm = 1-based position of the block in the whole-book reading sequence
    (page furniture excluded). Parent/child use the same numbering.
    """
    files = sorted(JSON_DIR.glob("page_*.json"))
    pages = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    seq, order = 0, []
    number_of, by_id = {}, {}
    for pg in pages:
        for b in pg["blocks"]:
            by_id[b["id"]] = b
            if b["type"] in NON_LRM:
                continue
            seq += 1
            number_of[b["id"]] = seq
            order.append(b)
    children: dict[str, list[str]] = {}
    for b in order:
        if b["parent_block_id"] in number_of:
            children.setdefault(b["parent_block_id"], []).append(b["id"])
    prev = None
    for i, b in enumerate(order):
        pid = b["parent_block_id"] if b["parent_block_id"] in number_of else ""
        kids = children.get(b["id"], [])
        cont_from = ""
        if b["continues_from_previous_page"] and prev and prev["page_no"] == pg_of(b) - 1:
            cont_from = prev["id"]
        b["lrm"] = {
            "chunk_id": b["id"],
            "chunk_number_in_lrm": number_of[b["id"]],
            "parent_chunk_id": pid,
            "parent_chunk_number_in_lrm": number_of.get(pid),
            "child_chunk_ids": kids,
            "child_chunk_numbers_in_lrm": [number_of[k] for k in kids],
            "level": 0 if not pid else 1 + (1 if by_id[pid]["parent_block_id"] else 0),
            "prev_chunk_id": order[i - 1]["id"] if i else "",
            "next_chunk_id": order[i + 1]["id"] if i + 1 < len(order) else "",
            "continues_from_chunk_id": cont_from,
            "sutra_ref": b["sutra_ref"], "section_path": b["section_path"],
            "is_translation_unit": b["type"] in {"sutra", "paragraph", "heading", "footnote", "list_item", "quote", "caption"},
            "keep_original": {"sa": True, "la": True, "proper_names": True},
        }
        prev = {"id": b["id"], "page_no": pg_of(b)}
    for f, pg in zip(files, pages):
        for b in pg["blocks"]:
            if b["type"] in NON_LRM:
                b["lrm"] = {"chunk_id": b["id"], "chunk_number_in_lrm": None, "is_translation_unit": False}
        f.write_text(json.dumps(pg, ensure_ascii=False, indent=1), encoding="utf-8")
    total = len(fitz.open(str(SRC_PDF))) if SRC_PDF else len(pages)
    index = {"schema_version": SCHEMA_VERSION, "source_key": KEY, "lang": LANG, "total_pages": total, "page_count": len(pages), "lrm_chunk_count": seq,
             "pages": [{"page": p["page"], "printed": p["printed_page_number"],
                        "blocks": len(p["blocks"]), "words": sum(len(b["words"]) for b in p["blocks"])}
                       for p in pages]}
    (JSON_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(pages)


def pg_of(b: dict) -> int:
    return int(b["id"][1:5])


def recognise(client, model: str, png: bytes) -> dict:
    """Dispatches to recognize_google.recognise() or recognize_aws.recognise() per OCR_PROVIDER_NAME."""
    prompt = PROMPT.format(language=LANGS[LANG]["prompt_name"])
    return PROVIDER_MODULE.recognise(client, model, png, prompt, SCHEMA)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--lang", required=True, choices=list(LANGS))
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true", help="redo pages that already exist")
    ap.add_argument("--refine-only", action="store_true", help="re-snap boxes of existing pages (no API calls)")
    ap.add_argument("--link-only", action="store_true", help="only rebuild LRM links + index")
    args = ap.parse_args()

    global SRC_PDF
    SRC_PDF = args.pdf
    configure(args.lang, slug(args.pdf.stem))
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    if args.link_only:
        print("linked pages:", link_book())
        return 0

    if args.refine_only:
        doc = fitz.open(str(args.pdf))
        for f in sorted(JSON_DIR.glob("page_*.json")):
            pg = json.loads(f.read_text(encoding="utf-8"))
            refine_page(pg, doc[pg["page"] - 1])
            f.write_text(json.dumps(pg, ensure_ascii=False, indent=1), encoding="utf-8")
            print("refined page", pg["page"], pg["bbox_refinement"])
        return 0

    client = make_client(args.model)
    src = args.pdf
    doc = fitz.open(str(src))
    end = min(args.end or max_pages() or len(doc), len(doc))

    def run(n: int):
        pix = doc[n - 1].get_pixmap(dpi=DPI)
        png = pix.tobytes("png")
        (IMG_DIR / f"page_{n:04d}.png").write_bytes(png)
        page = build_page(recognise(client, args.model, png), n, (pix.width, pix.height), args.model, src.name)
        refine_page(page, doc[n - 1])
        (JSON_DIR / f"page_{n:04d}.json").write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")
        return n, len(page["blocks"]), sum(len(b["words"]) for b in page["blocks"])

    todo = [n for n in range(args.start, end + 1) if args.force or not (JSON_DIR / f"page_{n:04d}.json").exists()]
    # pymupdf documents are not thread-safe: render+API per page in a single thread pool is
    # fine only for the API part, so render sequentially first.
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(run, n): n for n in todo}
        for f in as_completed(futs):
            try:
                print("ok  page %d: %d blocks, %d words" % f.result())
            except Exception as exc:
                print("FAIL page", futs[f], str(exc)[:300], file=sys.stderr)
    print("linked pages:", link_book())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
