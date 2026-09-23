#!/usr/bin/env python3
"""LRM stage 3.1b: recognised source-language pages -> other languages, layout preserved (adapted from YS1's ys_translate.py).

Per target language and page: translate every block with Gemini (one call per page), render a one-page PDF that reproduces
the source layout, read exact word boxes back from that PDF's text layer, render the PNG. Block ids and chunk numbers are
identical in every language.

    python lrm/eda1_extract/translate.py --source-key book --pdf input/fr/book.pdf --from fr --lang en ru [--start 1 --end 100]

Output per language: output/<lang>/<source_key>/{json,pages,pdf,cache}/
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz  # pymupdf
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recognize as fr  # noqa: E402  paths, DPI, fold(), env loading

ROOT = fr.ROOT
STAGE = fr.STAGE  # input/ and output/ live in the extraction stage folder
LANG_FILE = STAGE / "languages.json"
TERMS_FILE = STAGE / "input" / "terms.txt"  # optional: terms kept untranslated, one per line
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
PROMPT_VERSION = "v1"
DEVA = re.compile(r"[ऀ-ॿ‌‍][ऀ-ॿ‌‍ ]*")
MARKUP = re.compile(r"\[\[(.+?)\]\]|<sup>(.+?)</sup>", re.S)

CSS = """
@font-face {font-family: YSSerif; src: url("Times New Roman.ttf");}
@font-face {font-family: YSSerif; font-style: italic; src: url("Times New Roman Italic.ttf");}
@font-face {font-family: YSSerif; font-weight: bold; src: url("Times New Roman Bold.ttf");}
@font-face {font-family: YSDeva; src: url("DevanagariMT.ttc");}
body {font-family: YSSerif; margin: 0; padding: 0;}
"""

SCHEMA = {
    "type": "object",
    "properties": {"translations": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"]}}},
    "required": ["translations"],
}

PROMPT = """You translate a scholarly book (with commentary and notes), written in {source}, into {target}.
The input JSON has the page number, optional `previous_context` (end of the previous page: for continuity only, do NOT
translate it) and `blocks` (id, type, sutra_ref, section_path, parent_id, text). Return exactly one translation per block id.

Rules:
- Translate each block as one complete unit, faithfully and idiomatically, in a scholarly register. A sutra is one holistic unit.
- Text inside [[ ... ]] is Sanskrit or Latin: copy it EXACTLY and keep it inside the [[ ]] markers at the natural position
  in the sentence. Never translate, transliterate or alter it.
- Keep <sup>...</sup> markers exactly as they are (note call numbers), directly after the word they follow.
- Proper names, authors' surnames, titles of works and bibliographic references stay in their original form; only adapt
  punctuation to the target language.
- Keep these specialised terms untranslated: {terms}
- Keep numbers, sutra numbering and abbreviations of source references. Do not add notes, merge, split or omit anything.
{style}"""


def languages() -> dict:
    return json.loads(LANG_FILE.read_text(encoding="utf-8"))


def load_terms() -> str:
    if not TERMS_FILE.exists():
        return "(none provided)"
    t = [l.strip() for l in TERMS_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    return ", ".join(t) or "(none provided)"


class Paths:
    def __init__(self, lang: str):
        self.lang = lang
        base = fr.out_dir(lang, fr.KEY)
        self.pdf_dir = base / "pdf"
        self.merged = base / f"{fr.KEY}_{lang}.pdf"
        self.json = base / "json"
        self.img = base / "pages"
        self.cache = base / "cache"
        for d in (self.pdf_dir, self.json, self.img, self.cache):
            d.mkdir(parents=True, exist_ok=True)


# ---------- source text preparation ----------

def dehyphenate(words: list[dict]) -> list[dict]:
    """Join words split by an end-of-line hyphen (next word starts on the next line, lowercase)."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        t = w["text"]
        if t.endswith("-") and len(t) > 1 and i + 1 < len(words):
            n = words[i + 1]
            if n["bbox"]["y"] > w["bbox"]["y"] + w["bbox"]["h"] * 0.5 and n["text"][:1].islower():
                out.append({**w, "text": t[:-1] + n["text"]})
                i += 2
                continue
        out.append(w)
        i += 1
    return out


def mark_source(block: dict) -> str:
    """Block text with Sanskrit/Latin runs in [[..]] and superscript markers in <sup>..</sup>."""
    parts, group = [], []

    def flush():
        if group:
            parts.append("[[" + " ".join(group) + "]]")
            group.clear()

    for w in dehyphenate(block["words"]):
        if w["lang"] in ("sa", "la"):
            group.append(w["text"])
            continue
        flush()
        parts.append(f"<sup>{w['text']}</sup>" if w["style"] == "sup" else w["text"])
    flush()
    return " ".join(parts).replace("\u00ad", "")


def is_unit(b: dict) -> bool:
    return bool(b.get("lrm") and b["lrm"].get("is_translation_unit") and b["words"])


# ---------- translation ----------

@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=5, max=60), reraise=True)
def call_model(client, model: str, prompt: str, payload: dict) -> dict:
    resp = client.models.generate_content(
        model=model,
        contents=[prompt, json.dumps(payload, ensure_ascii=False)],
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA,
                                           temperature=0.2, max_output_tokens=65000))
    return json.loads(resp.text)


def qa_check(src: str, out: str) -> dict:
    count = lambda pat, s: len(re.findall(pat, s))
    ratio = round(len(out) / max(len(re.sub(r"\[\[|\]\]|</?sup>", "", src)), 1), 2)
    return {"marks_ok": count(r"\[\[", src) == count(r"\[\[", out) and count(r"\]\]", src) == count(r"\]\]", out),
            "sup_ok": count(r"<sup>", src) == count(r"<sup>", out), "len_ratio": ratio}


def translate_page(client, model: str, lang: str, fr_page: dict, prev_ctx: str, terms: str) -> dict:
    cfg = languages()[lang]
    units = [b for b in fr_page["blocks"] if is_unit(b)]
    src = {b["id"]: mark_source(b) for b in units}
    prompt = PROMPT.format(source=languages()[fr.LANG]["prompt_name"], target=cfg["prompt_name"], terms=terms, style=cfg.get("style", ""))
    got: dict[str, str] = {}
    for _ in range(2):  # second round only for blocks the model skipped
        todo = [b for b in units if b["id"] not in got]
        if not todo:
            break
        payload = {"page": fr_page["page"], "previous_context": prev_ctx, "blocks": [
            {"id": b["id"], "type": b["type"], "sutra_ref": b["sutra_ref"], "section_path": b["section_path"],
             "parent_id": b["parent_block_id"], "text": src[b["id"]]} for b in todo]}
        for t in call_model(client, model, prompt, payload).get("translations", []):
            if t.get("id") in src and t.get("text", "").strip():
                got[t["id"]] = t["text"].strip()
    missing = [i for i in src if i not in got]
    return {"lang": lang, "page": fr_page["page"], "model": model, "prompt_version": PROMPT_VERSION,
            "texts": got, "source_marked": src, "missing": missing,
            "qa": {i: qa_check(src[i], got[i]) for i in got}}


# ---------- layout / PDF ----------

def to_html(text: str) -> str:
    text = text.replace("\u00ad", "")  # soft hyphens from the source would leak into extracted words
    def seg(s: str) -> str:
        return DEVA.sub(lambda m: f'<span style="font-family:YSDeva">{m.group(0)}</span>', html.escape(s, quote=False))

    out, pos = [], 0
    for m in MARKUP.finditer(text):
        out.append(seg(text[pos:m.start()]))
        out.append(f"<i>{seg(m.group(1))}</i>" if m.group(1) is not None else f"<sup>{seg(m.group(2))}</sup>")
        pos = m.end()
    out.append(seg(text[pos:]))
    return "".join(out)


def font_metrics(b: dict, H: float) -> tuple[float, float]:
    """(font size pt, line height pt) estimated from the French words of the block."""
    hs = [w["bbox"]["h"] * H for w in b["words"] if w["style"] not in ("sup", "sub") and w["bbox"]["h"] > 0]
    size = (statistics.median(hs) if hs else 10.0) * 0.86
    ys = sorted({round((w["bbox"]["y"] + w["bbox"]["h"] / 2) * H, 1) for w in b["words"] if w["style"] != "sup"})
    lines = []
    for y in ys:
        if not lines or y - lines[-1] > size * 0.6:
            lines.append(y)
    gaps = [b2 - a for a, b2 in zip(lines, lines[1:]) if b2 - a < size * 3]
    return size, (statistics.median(gaps) if gaps else size * 1.25)


def block_rect(b: dict, blocks: list[dict], W: float, H: float, grow: bool) -> fitz.Rect:
    bb = b["bbox"]
    x0, y0, x1, y1 = bb["x"] * W, bb["y"] * H, (bb["x"] + bb["w"]) * W, (bb["y"] + bb["h"]) * H
    if grow:  # translations may be longer: allow growth down to the next block below
        below = [o["bbox"]["y"] for o in blocks if o is not b and o["bbox"] and o["bbox"]["y"] * H > y0 + (y1 - y0) * 0.5
                 and o["bbox"]["x"] * W < x1 and (o["bbox"]["x"] + o["bbox"]["w"]) * W > x0]
        limit = min(below + [0.97]) * H
        y1 += max(0.0, min(limit - 2 - y1, (y1 - y0) * 0.6))
    else:  # copied furniture (page numbers, headers): a little slack so it never shrinks
        x1 += (x1 - x0) * 0.2
    return fitz.Rect(x0, y0, x1, y1)


def align_of(b: dict, W: float) -> str:
    bb = b["bbox"]
    if b["type"] in ("heading", "sutra") and abs((bb["x"] + bb["w"] / 2) - 0.5) < 0.04 and bb["w"] < 0.75:
        return "center"
    return "justify" if b["type"] in ("paragraph", "footnote", "quote", "list_item") and len(b["words"]) > 25 else "left"


def render_pdf(fr_page: dict, texts: dict[str, str], src_page: fitz.Page) -> tuple[fitz.Document, dict]:
    W, H = src_page.rect.width, src_page.rect.height
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    archive = fitz.Archive(str(FONT_DIR))
    blocks = [b for b in fr_page["blocks"] if b["words"] and b["bbox"]]
    layout: dict[str, dict] = {}
    for b in blocks:
        translated = b["id"] in texts
        rect = block_rect(b, blocks, W, H, grow=translated)
        size, lh = font_metrics(b, H)
        body = to_html(texts[b["id"]] if translated else b["text"])
        weight = "bold" if b["type"] == "heading" else "normal"
        css = f"* {{font-size:{size:.2f}pt; line-height:{lh:.2f}pt; text-align:{align_of(b, W)}; font-weight:{weight};}}"
        spare, scale = page.insert_htmlbox(rect, f"<div>{body}</div>", css=CSS + css, archive=archive)
        layout[b["id"]] = {"rect": [rect.x0, rect.y0, rect.x1, rect.y1], "font_pt": round(size, 2),
                           "scale": round(scale, 3), "fits": spare >= 0}
    return doc, layout


# ---------- PDF -> JSON ----------

def kept_lang(b: dict) -> dict[str, str]:
    return {fr.fold(w["text"]): w["lang"] for w in b["words"] if w["lang"] in ("sa", "la") and fr.fold(w["text"])}


def extract_page(fr_page: dict, texts: dict, layout: dict, pdf_page: fitz.Page, lang: str, model: str,
                 qa: dict, pdf_rel: str) -> dict:
    W, H = pdf_page.rect.width, pdf_page.rect.height
    raw = [w for w in pdf_page.get_text("words") if w[4].strip()]  # content-stream order = block order
    owner: dict[int, str] = {}
    order = [b for b in fr_page["blocks"] if b["id"] in layout]
    for i, w in enumerate(raw):
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        for b in order:
            r = fitz.Rect(layout[b["id"]]["rect"])
            if r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 1 <= cy <= r.y1 + 1:
                owner[i] = b["id"]
                break
    pix = pdf_page.get_pixmap(dpi=fr.DPI)
    blocks = []
    for b in fr_page["blocks"]:
        kept, words, parts, pos = kept_lang(b), [], [], 0
        for i, w in enumerate(raw):
            if owner.get(i) != b["id"]:
                continue
            text = w[4].replace("\u00ad", "-")  # font maps the hyphen glyph to U+00AD
            key = fr.fold(text)
            wl = "sa" if DEVA.search(text) else kept.get(key) or (lang if key and not key.isdigit() else "other")
            words.append({"id": f"{b['id']}_w{len(words) + 1:03d}", "text": text,
                          "bbox": {"x": round(w[0] / W, 4), "y": round(w[1] / H, 4),
                                   "w": round((w[2] - w[0]) / W, 4), "h": round((w[3] - w[1]) / H, 4)},
                          "lang": wl, "style": "normal", "bbox_source": "pdf_text_layer",
                          "char_start": pos, "char_end": pos + len(text)})
            parts.append(text)
            pos += len(text) + 1
        if words:
            x0 = min(w["bbox"]["x"] for w in words); y0 = min(w["bbox"]["y"] for w in words)
            x1 = max(w["bbox"]["x"] + w["bbox"]["w"] for w in words); y1 = max(w["bbox"]["y"] + w["bbox"]["h"] for w in words)
            bbox = {"x": round(x0, 4), "y": round(y0, 4), "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}
        else:
            bbox = b["bbox"]
        blocks.append({
            "id": b["id"], "local_id": b["local_id"], "type": b["type"], "reading_order": b["reading_order"],
            "bbox": bbox, "text": " ".join(parts), "words": words, "lang": lang,
            "source": {"lang": fr.LANG, "chunk_id": b["id"], "translated": b["id"] in texts},
            "sutra_ref": b["sutra_ref"], "footnote_marker": b["footnote_marker"], "section_path": b["section_path"],
            "continues_from_previous_page": b["continues_from_previous_page"],
            "continues_on_next_page": b["continues_on_next_page"], "parent_block_id": b["parent_block_id"],
            "lrm": b["lrm"], "layout": {k: v for k, v in layout.get(b["id"], {}).items() if k != "rect"},
            "qa": qa.get(b["id"], {}),
        })
    return {"schema_version": fr.SCHEMA_VERSION, "page": fr_page["page"], "lang": lang,
            "printed_page_number": fr_page["printed_page_number"], "image": f"{lang}/{fr.KEY}/pages/page_{fr_page['page']:04d}.png", "source_key": fr.KEY,
            "image_size": {"width": pix.width, "height": pix.height},
            "coordinate_system": fr_page["coordinate_system"], "source": {"lang": fr.LANG, "page": fr_page["page"]},
            "pdf": pdf_rel, "model": model, "prompt_version": PROMPT_VERSION, "blocks": blocks}


# ---------- book-level ----------

def merge_pdf(P: Paths, total: int, src_doc: fitz.Document) -> None:
    r = src_doc[0].rect
    out = fitz.open()
    for n in range(1, total + 1):
        f = P.pdf_dir / f"page_{n:04d}.pdf"
        if f.exists():
            with fitz.open(str(f)) as d:
                out.insert_pdf(d)
        else:
            out.new_page(width=r.width, height=r.height)
    out.save(str(P.merged), garbage=3, deflate=True)


def write_index(P: Paths, total: int) -> None:
    pages = []
    for f in sorted(P.json.glob("page_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        scales = [b["layout"].get("scale", 1) for b in d["blocks"] if b["layout"]]
        pages.append({"page": d["page"], "printed": d["printed_page_number"], "blocks": len(d["blocks"]),
                      "words": sum(len(b["words"]) for b in d["blocks"]), "min_scale": min(scales, default=1)})
    (P.json / "index.json").write_text(json.dumps(
        {"schema_version": fr.SCHEMA_VERSION, "lang": P.lang, "total_pages": total, "page_count": len(pages),
         "source_key": fr.KEY, "pdf": f"{P.lang}/{fr.KEY}/{P.merged.name}", "pages": pages}, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-key", required=True)
    ap.add_argument("--from", dest="src_lang", default="fr", help="language the source pages were recognised in")
    ap.add_argument("--pdf", type=Path, required=True, help="the source-language PDF (page size / fonts)")
    ap.add_argument("--lang", nargs="+", default=["en", "ru"])
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model", default=fr.DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true", help="re-translate even if cached")
    ap.add_argument("--render-only", action="store_true", help="re-layout from cached translations (no API calls)")
    args = ap.parse_args()

    langs = languages()
    for l in args.lang:
        if l == args.src_lang or l not in langs:
            sys.exit(f"Unknown target language {l!r}; configured: {[k for k in langs if k != args.src_lang]}")
    fr.configure(args.src_lang, args.source_key)
    src_doc = fitz.open(str(args.pdf))
    fr_pages = {}
    for f in sorted(fr.JSON_DIR.glob("page_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if args.start <= d["page"] <= (args.end or 10**9):
            fr_pages[d["page"]] = d
    if not fr_pages:
        sys.exit("No source pages recognised in that range (run recognize.py first).")

    client = None
    if not args.render_only:
        client = genai.Client(api_key=fr.api_key())
    terms = load_terms()

    for lang in args.lang:
        P = Paths(lang)

        def prev_context(n: int) -> str:
            p = fr.JSON_DIR / f"page_{n - 1:04d}.json"
            if not p.exists():
                return ""
            d = json.loads(p.read_text(encoding="utf-8"))
            tail = [" ".join(w["text"] for w in b["words"]) for b in d["blocks"] if is_unit(b) and b["type"] != "footnote"]
            return tail[-1][-600:] if tail else ""

        def job(n: int) -> tuple[int, dict]:
            cache = P.cache / f"page_{n:04d}.json"
            if cache.exists() and not args.force:
                return n, json.loads(cache.read_text(encoding="utf-8"))
            if args.render_only:
                raise FileNotFoundError(f"no cached translation for page {n}")
            res = translate_page(client, args.model, lang, fr_pages[n], prev_context(n), terms)
            cache.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            return n, res

        results: dict[int, dict] = {}
        with ThreadPoolExecutor(args.workers) as ex:
            futs = {ex.submit(job, n): n for n in fr_pages}
            for f in as_completed(futs):
                try:
                    n, res = f.result()
                    results[n] = res
                    print(f"[{lang}] translated page {n}: {len(res['texts'])} blocks"
                          + (f", MISSING {res['missing']}" if res["missing"] else ""))
                except Exception as exc:
                    print(f"[{lang}] FAIL page {futs[f]}: {str(exc)[:300]}", file=sys.stderr)

        for n in sorted(results):  # pymupdf is not thread-safe: render sequentially
            res, fp = results[n], fr_pages[n]
            doc, layout = render_pdf(fp, res["texts"], src_doc[n - 1])
            pdf_path = P.pdf_dir / f"page_{n:04d}.pdf"
            page_json = extract_page(fp, res["texts"], layout, doc[0], lang, res["model"], res["qa"],
                                     f"files/{lang}/pages/{pdf_path.name}")
            (P.img / f"page_{n:04d}.png").write_bytes(doc[0].get_pixmap(dpi=fr.DPI).tobytes("png"))
            doc.subset_fonts()
            doc.save(str(pdf_path), garbage=3, deflate=True)
            doc.close()
            (P.json / f"page_{n:04d}.json").write_text(json.dumps(page_json, ensure_ascii=False, indent=1), encoding="utf-8")
            bad = [i for i, l in layout.items() if not l["fits"] or l["scale"] < 0.8]
            print(f"[{lang}] page {n}: {sum(len(b['words']) for b in page_json['blocks'])} words"
                  + (f", tight layout in {bad}" if bad else ""))
        write_index(P, len(src_doc))
        merge_pdf(P, len(src_doc), src_doc)
        print(f"[{lang}] merged PDF: {P.merged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
