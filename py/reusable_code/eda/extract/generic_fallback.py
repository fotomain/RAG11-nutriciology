"""
Generic fallback section detection for any PDF that has no SOURCES entry
(sources.py), so a new file in the sources folder still gets sections.

Strategies, tried in order (the first that yields a usable result wins):

1. ``generic_outline``       -- the PDF's own bookmarks (shallowest level
                                 that gives at least MIN_HEADINGS entries).
2. ``generic_font_headings`` -- no usable outline: find lines set noticeably
                                 larger than the body text (>= HEADING_SIZE_RATIO x
                                 the most common font size), merge wrapped
                                 title lines, drop running headers and
                                 non-heading noise. Costs one pass over every
                                 page's font info, so the result is cached
                                 (common.cached_json, _cache_headings.json).
3. ``generic_page_windows``  -- last resort: fixed WINDOW_PAGES-page sections.

Whatever strategy is used, a section longer than MAX_SECTION_PAGES pages is
split into consecutive parts so no single parent chunk grows unmanageably.

This is deliberately less precise than a hand-tuned module (no running
header/footer stripping, no callout-box tags). If a book matters, add a
SOURCES entry for it (see sources.py) -- it takes precedence.
"""
import re
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

from .common import cached_json, sections_from_outline

MIN_HEADINGS = 5
HEADING_SIZE_RATIO = 1.4
MAX_TITLE_CHARS = 100
RUNNING_HEADER_PAGE_FRACTION = 0.03
MAX_SECTION_PAGES = 40
WINDOW_PAGES = 10

_LETTERS_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _outline_sections(pdf_path: Path, source_key: str) -> list[dict]:
    for max_level in (1, 2, 3):
        sections = sections_from_outline(pdf_path, source_key, min_level=1, max_level=max_level)
        if len(sections) >= MIN_HEADINGS:
            return sections
    return []


def _looks_like_heading(text: str) -> bool:
    if not text or len(text) > MAX_TITLE_CHARS:
        return False
    if len(_LETTERS_RE.findall(text)) < 3:
        return False
    first = text[0]
    return first.isupper() or first.isdigit()


def _scan_font_headings(pdf_path: Path) -> tuple[int, list[tuple[int, str]]]:
    size_chars: Counter = Counter()
    lines: list[tuple[int, float, str]] = []
    with fitz.open(pdf_path) as doc:
        n_pages = doc.page_count
        for page_no, page in enumerate(doc):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).replace("\x00", "").strip()
                    if not text or not line["spans"]:
                        continue
                    size = round(max(s["size"] for s in line["spans"]), 1)
                    size_chars[size] += len(text)
                    lines.append((page_no, size, text))
    if not size_chars:
        return n_pages, []

    cutoff = size_chars.most_common(1)[0][0] * HEADING_SIZE_RATIO

    # Merge adjacent large lines of the same size on one page (wrapped titles).
    merged: list[tuple[int, str]] = []
    prev = None  # (page, size) of the previous *large* line
    for page_no, size, text in lines:
        if size < cutoff:
            prev = None
            continue
        if prev == (page_no, size) and merged:
            merged[-1] = (page_no, f"{merged[-1][1]} {text}")
        else:
            merged.append((page_no, text))
        prev = (page_no, size)

    # A title repeated on many pages is a running header, not a heading.
    pages_per_title: dict[str, set] = {}
    for page_no, title in merged:
        pages_per_title.setdefault(title, set()).add(page_no)
    max_repeats = max(3, int(n_pages * RUNNING_HEADER_PAGE_FRACTION))

    headings: list[tuple[int, str]] = []
    for page_no, title in merged:
        if len(pages_per_title[title]) > max_repeats or not _looks_like_heading(title):
            continue
        if headings and headings[-1][0] == page_no:
            if headings[-1][1].count(" / ") < 1:  # keep at most two titles per page
                headings[-1] = (page_no, f"{headings[-1][1]} / {title}")
            continue
        if headings and headings[-1][1] == title:
            continue
        headings.append((page_no, title))
    return n_pages, headings


def _font_heading_sections(pdf_path: Path, source_key: str) -> list[dict]:
    n_pages, headings = cached_json(pdf_path, source_key, "_cache_headings.json",
                                    lambda: _scan_font_headings(pdf_path))
    headings = [tuple(h) for h in headings]

    if not (MIN_HEADINGS <= len(headings) <= n_pages):
        return []
    if headings[0][0] > 0:
        headings = [(0, "Front matter")] + headings
    sections = []
    for i, (start, title) in enumerate(headings):
        end = headings[i + 1][0] - 1 if i + 1 < len(headings) else n_pages - 1
        sections.append({"title": title, "level": 1, "start_page": start, "end_page": max(end, start)})
    return sections


def _window_sections(n_pages: int) -> list[dict]:
    return [
        {"title": f"Pages {s + 1}-{min(s + WINDOW_PAGES, n_pages)}", "level": 1,
         "start_page": s, "end_page": min(s + WINDOW_PAGES, n_pages) - 1}
        for s in range(0, n_pages, WINDOW_PAGES)
    ]


def _split_oversized(sections: list[dict]) -> list[dict]:
    out = []
    for sec in sections:
        span = sec["end_page"] - sec["start_page"] + 1
        if span <= MAX_SECTION_PAGES:
            out.append(sec)
            continue
        n_parts = -(-span // MAX_SECTION_PAGES)
        for part in range(n_parts):
            start = sec["start_page"] + part * MAX_SECTION_PAGES
            end = min(start + MAX_SECTION_PAGES - 1, sec["end_page"])
            out.append({**sec, "title": f"{sec['title']} (part {part + 1}/{n_parts})",
                        "start_page": start, "end_page": end})
    return out


def extract_sections_with_strategy(source_key: str, pdf_path: Path, pages: list[str]) -> tuple[list[dict], str]:
    """Return (sections, strategy_label); every section has title/level/start_page/
    end_page (0-based, inclusive)/text/block_type, like a dedicated module's output."""
    pdf_path = Path(pdf_path)
    sections = _outline_sections(pdf_path, source_key)
    strategy = "generic_outline"
    if not sections:
        sections = _font_heading_sections(pdf_path, source_key)
        strategy = "generic_font_headings"
    if not sections:
        sections = _window_sections(len(pages))
        strategy = "generic_page_windows"

    sections = _split_oversized(sections)
    for sec in sections:
        sec["text"] = "\n\n".join(pages[sec["start_page"]: sec["end_page"] + 1]).strip()
        sec["block_type"] = []
    print(f"[{source_key}] generic fallback ({strategy}): {len(sections)} section(s) -- "
          "consider adding a SOURCES entry (sources.py) for better boundaries")
    return sections, strategy


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    return extract_sections_with_strategy(source_key, pdf_path, pages)[0]
