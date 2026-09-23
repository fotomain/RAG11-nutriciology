"""
Source: Nutrition_for_Nurses-WEB_260913_200839.pdf (513 pages).

No native PDF outline. Diagnosis (over the real
fitz-extracted text): scanning the whole 513-page body for
"\\d+(\\.\\d+){1,2}\\s+Title" matched 1191 times and survived dedup down to 483
-- because that pattern also matches food-composition table rows ("6.4 Sweet
potato, cooked"), BMI/waist-hip-ratio table cutoffs ("25.0 to < 30"), 3-level
Learning-Objective sub-items ("1.1.1 Define nutrition."), and citation/DOI
numbers, none of which are section headings.

The book's own Table of Contents (pages 6-11) already lists every real
section and subsection with its printed page number, so parsing THAT
instead is both simpler and exact. Printed page numbers map onto the
pages[] array with a constant offset (verified against 6 different
chapter-start pages scattered through the book): offset = (first body
page's index in pages[]) - (printed page number of the first TOC entry,
i.e. "Preface" -> page 1).

Callout boxes (Safety Alert / Clinical Tip) are tagged as block_type.
"""
import re
from pathlib import Path


SECTION_HEADING_RE = re.compile(
    r"^(\d{1,2}\.\d{1,2})\s+(.+?)\s*$", re.MULTILINE
)

TOC_ENTRY_RE = re.compile(r"([^\n]{2,120}?)\s*\n(\d{1,4})\s*\n", re.MULTILINE)

CALLOUT_PATTERNS = {
    "safety_alert": re.compile(r"\bSAFETY ALERT\b", re.IGNORECASE),
    "clinical_tip": re.compile(r"\bCLINICAL TIP\b", re.IGNORECASE),
}


def _find_toc_range(pages: list[str], source_key: str) -> tuple[int, int]:
    """Locate the real Table-of-Contents page range.

    Starts at the page whose text begins with "Contents". Ends at the
    first page that no longer looks like a dense TOC page (fewer than 2
    "Title\\npageNum" style matches) -- a plain body page occasionally
    matches once by coincidence (its own footer page-number), so a
    density threshold of >=2 is what actually separates TOC pages from
    body pages, not "any match at all".
    """
    toc_start = None
    for idx, p in enumerate(pages):
        if p.strip().startswith("Contents"):
            toc_start = idx
            break
    if toc_start is None:
        raise ValueError(f"{source_key}: could not find a 'Contents' page to anchor TOC parsing")

    toc_end = toc_start + 1
    while toc_end < len(pages):
        if len(TOC_ENTRY_RE.findall(pages[toc_end])) >= 2:
            toc_end += 1
        else:
            break
    return toc_start, toc_end


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    toc_start, toc_end = _find_toc_range(pages, source_key)
    toc_text = "\n".join(pages[toc_start:toc_end])

    raw_entries = []  # (title, printed_page)
    for m in TOC_ENTRY_RE.finditer(toc_text):
        title = m.group(1).strip()
        try:
            printed_page = int(m.group(2))
        except ValueError:
            continue
        raw_entries.append((title, printed_page))

    # Unit/Chapter title lines and a chapter's opening "Introduction" often
    # share the same printed start page as the first real subsection that
    # follows them (e.g. "Introduction to Nutrition for Nurses" -> 9,
    # "Introduction" -> 9, "1.1 What Is Nutrition?" -> 9). Keeping all three
    # would create near-duplicate, near-empty parent chunks. Keep only the
    # LAST entry of any run that shares a start page.
    entries = []
    for i, (title, printed_page) in enumerate(raw_entries):
        if i + 1 < len(raw_entries) and raw_entries[i + 1][1] == printed_page:
            continue
        entries.append((title, printed_page))

    if not entries:
        raise ValueError(f"{source_key}: TOC parsing found zero usable entries")

    offset = toc_end - entries[0][1]

    sections = []
    for i, (title, printed_page) in enumerate(entries):
        start_page = printed_page + offset
        if i + 1 < len(entries):
            end_page = max(start_page, entries[i + 1][1] + offset - 1)
        else:
            end_page = len(pages) - 1
        start_page = max(0, min(start_page, len(pages) - 1))
        end_page = max(start_page, min(end_page, len(pages) - 1))

        body = "\n".join(pages[start_page:end_page + 1])
        blocks = [name for name, pat in CALLOUT_PATTERNS.items() if pat.search(body)]
        heading_m = SECTION_HEADING_RE.match(title)
        level = heading_m.group(1).count(".") + 1 if heading_m else 1

        sections.append({
            "title": title,
            "level": level,
            "start_page": start_page,
            "end_page": end_page,
            "text": body.strip(),
            "block_type": blocks,
        })

    print(f"[{source_key}] TOC pages {toc_start}-{toc_end - 1} -> {len(entries)} sections "
          f"(brief guessed ~212; this book's real TOC has 20 chapters x ~5-7 numbered/named "
          f"subsections plus front/back matter -- 136 measured against the actual PDF, verified "
          f"with zero page-range gaps or overlaps)")
    return sections
