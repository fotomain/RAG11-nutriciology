"""
Source: Nutrition-Science-and-Everyday-Application-1773787282.pdf (649 pages).

Native outline (qpdf --json dump of the outline tree): 17 top-level entries
(Units/front matter) plus 74 second-level chapter entries nested under
them -- 91 total, exactly matching the brief's "91 entries". Treating both
levels as one flat, page-ordered sequence (as sections_from_outline already
does) means a Unit heading's own "section" is just its divider page(s)
before its first child chapter starts, so ranges don't overlap.

Also strips attribution/header blocks per page and flags pages that look
like they contained an H5P interactive widget that didn't survive the PDF
export (a content gap worth knowing about downstream).
"""
import re
from pathlib import Path

from .common import sections_from_outline

FILENAME = "Nutrition-Science-and-Everyday-Application-1773787282.pdf"
EXPECTED_PAGES = 649
STRUCTURE = "native_outline"  # 91 outline entries

ATTRIBUTION_PATTERNS = [
    re.compile(r"^\s*(Adapted from|Image credit|CC BY[- ]?\w*)\b.*$", re.IGNORECASE | re.MULTILINE),
]

H5P_GAP_PATTERN = re.compile(r"\[?interactive (element|widget|activity)\]?", re.IGNORECASE)


def _clean_page(text: str) -> tuple[str, bool]:
    """Strip attribution blocks/headers from one page; flag likely H5P gaps."""
    cleaned = text
    for pat in ATTRIBUTION_PATTERNS:
        cleaned = pat.sub("", cleaned)
    is_gap = bool(H5P_GAP_PATTERN.search(text))
    return cleaned.strip(), is_gap


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    sections = sections_from_outline(pdf_path, source_key, min_level=1, max_level=2)
    h5p_gap_pages = []
    for sec in sections:
        cleaned_pages = []
        for pno in range(sec["start_page"], sec["end_page"] + 1):
            cleaned, is_gap = _clean_page(pages[pno])
            cleaned_pages.append(cleaned)
            if is_gap:
                h5p_gap_pages.append(pno)
        sec["text"] = "\n\n".join(cleaned_pages)
    shown = h5p_gap_pages[:10]
    suffix = "..." if len(h5p_gap_pages) > 10 else ""
    print(f"[{source_key}] flagged {len(h5p_gap_pages)} page(s) as possible H5P content gaps "
          f"(brief mentions ~62): {shown}{suffix}")
    return sections
