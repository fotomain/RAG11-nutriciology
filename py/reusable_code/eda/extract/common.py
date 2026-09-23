"""Shared helpers for eda.extract: page text (native or OCR), outline reading, section boundaries,
section assembly, and a per-PDF JSON cache for expensive whole-book passes.

Section dict contract (what every strategy / custom module returns):
    title, level, start_page, end_page (0-based, inclusive), text, block_type (list of tags)
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Callable

import fitz  # pymupdf

# Where whole-book passes (OCR, font-heading scans, custom layouts) are cached. None -> next to
# the PDF in _eda_cache/<source_key>/. Set once via set_cache_dir() by whatever drives the run.
CACHE_DIR: Path | None = None


def set_cache_dir(path) -> None:
    global CACHE_DIR
    CACHE_DIR = Path(path) if path else None


def cache_path(pdf_path, source_key: str, name: str) -> Path:
    base = CACHE_DIR if CACHE_DIR is not None else Path(pdf_path).parent / "_eda_cache"
    return base / source_key / name


def cached_json(pdf_path, source_key: str, name: str, compute: Callable[[], object]):
    """compute() once per PDF and cache the JSON result, keyed by (filename, size) so replacing
    the PDF invalidates it."""
    path = cache_path(pdf_path, source_key, name)
    fingerprint = [Path(pdf_path).name, Path(pdf_path).stat().st_size]
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pdf") == fingerprint:
            return data["value"]
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pdf": fingerprint, "value": value}, ensure_ascii=False), encoding="utf-8")
    return value


# ---------- page text ----------

def read_pages(pdf_path) -> list[str]:
    """Native text layer, one string per page."""
    with fitz.open(pdf_path) as doc:
        return [page.get_text("text").replace("\x00", "") for page in doc]


def ocr_pages(pdf_path, source_key: str, dpi: int = 150) -> list[str]:
    """OCR every page of a scanned (text-less) PDF with Tesseract, cached. Needs `pytesseract` +
    `Pillow` and the Tesseract engine itself (`brew install tesseract` / `apt install tesseract-ocr`)."""
    def compute():
        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            raise RuntimeError(
                f"[{source_key}] this source has no text layer and needs OCR: pip install pytesseract "
                "pillow, plus the Tesseract engine (brew install tesseract / apt install tesseract-ocr)"
            ) from e
        out = []
        with fitz.open(pdf_path) as doc:
            print(f"[{source_key}] OCRing {doc.page_count} pages (one-time, cached afterwards)")
            for i, page in enumerate(doc):
                img = Image.open(io.BytesIO(page.get_pixmap(dpi=dpi).tobytes("png")))
                out.append(pytesseract.image_to_string(img, config="--psm 6"))
                if (i + 1) % 50 == 0 or i + 1 == doc.page_count:
                    print(f"[{source_key}] OCR progress: {i + 1}/{doc.page_count}")
        return out

    return cached_json(pdf_path, source_key, "_ocr_pages.json", compute)


# ---------- outline + boundaries ----------

def read_outline(pdf_path) -> tuple[list[tuple[int, str, int]], int]:
    """([(level, raw_title, start_page_0based), ...] in outline order, n_pages)."""
    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
        return [(lvl, title, page - 1) for lvl, title, page in toc], doc.page_count


def next_entry_ends(starts: list[int], n_pages: int) -> list[int]:
    """End page of each entry = the next entry's start - 1 (last one runs to the end). Right for
    shallow (1-2 level) outlines."""
    ends = [starts[i + 1] - 1 if i + 1 < len(starts) else n_pages - 1 for i in range(len(starts))]
    return [max(e, s) for s, e in zip(starts, ends)]


def level_aware_ends(entries: list[tuple[int, str, int]], n_pages: int) -> list[int]:
    """End page of each entry = start of the next entry whose level is <= its own, - 1. Deeper
    descendants are internal sub-headings, so a chapter isn't cut at its first sub-heading."""
    ends = []
    for i, (lvl, _, start) in enumerate(entries):
        end = n_pages - 1
        for j in range(i + 1, len(entries)):
            if entries[j][0] <= lvl:
                end = entries[j][2] - 1
                break
        ends.append(max(end, start))
    return ends


def sections_from_outline(pdf_path, source_key: str, min_level: int = 1, max_level: int = 1) -> list[dict]:
    """title/level/start_page/end_page for outline entries within [min_level, max_level], each
    running to the next such entry. The caller fills in text."""
    outline, n_pages = read_outline(pdf_path)
    entries = [e for e in outline if min_level <= e[0] <= max_level]
    ends = next_entry_ends([e[2] for e in entries], n_pages)
    sections = [{"title": title.strip(), "level": lvl, "start_page": start, "end_page": end}
                for (lvl, title, start), end in zip(entries, ends)]
    print(f"[{source_key}] {len(sections)} sections from outline (levels {min_level}-{max_level})")
    return sections


# ---------- section assembly ----------

def clean_title(title: str, strip_chars: str = "") -> str:
    for ch in strip_chars:
        title = title.replace(ch, " ")
    return " ".join(title.split())


def page_text(pages: list[str], start: int, end: int, clean: Callable[[str], str] | None = None) -> str:
    return "\n\n".join(clean(p) if clean else p for p in pages[start:end + 1]).strip()


def callouts(text: str, patterns: dict[str, re.Pattern]) -> list[str]:
    """Sorted names of the callout-box patterns found in text."""
    return sorted(name for name, pat in patterns.items() if pat.search(text))


def section(title: str, level: int, start: int, end: int, text: str, block_type: list | None = None) -> dict:
    return {"title": title, "level": level, "start_page": start, "end_page": end,
            "text": text, "block_type": list(block_type or [])}
