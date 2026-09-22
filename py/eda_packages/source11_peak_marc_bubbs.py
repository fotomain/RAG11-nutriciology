"""
Source: _OceanofPDF.com_Peak_-_Marc_Bubbs.pdf ("Peak" by Dr. Marc Bubbs,
398 pages, a calibre-converted ebook -- Creator/Producer both "calibre").

Native outline, 111 entries across 3 levels, structured like a smaller,
cleaner cousin of source7/8:

  level 1: front matter ("Praise for Peak", "Title Page", "Copyright",
           "Contents"), "Introduction: The Revolution in Performance",
           4 "Part N: <title>" dividers, "Conclusion", "Notes" (endnote
           citations), "About the Author".
  level 2: the 12 "Chapter N: <title>" entries, nested under their Part
           divider.
  level 3: ~9 subsections inside each chapter (not sections in their own
           right).

Kept content, by pattern: the 12 level-2 "Chapter N:" entries, plus 3
level-1 entries kept by exact title -- "Introduction: The Revolution in
Performance" and "Conclusion" (both substantive chapter-length prose, not
administrative front/back matter) and "About the Author" (short bio).
Everything else is dropped: the 4 boilerplate front-matter entries, the 4
Part dividers (verified to have zero standalone content -- e.g. "Part One"
starts on page 23 and "Chapter 1" starts on page 24, so the divider is a
single page with just a part title and an epigraph quote), and "Notes"
(40 pages of numbered footnote citations -- bibliographic data, not
narrative prose, the same call as dropping an Index elsewhere).

Boundaries use the same level-aware rule as source7/8 -- a kept entry's end
is the start of the next entry whose level is <= its own level, minus one --
so each chapter's ~9 internal level-3 subsections don't fragment it, and a
dropped Part divider still correctly stops the previous chapter before it.

SPECIAL CASE -- "About the Author": it's the last outline entry, so the
generic rule would run its kept range all the way to the PDF's last page.
Direct inspection showed the real bio is exactly one page (388, 0-indexed);
the following ~8 pages are unrelated publisher back-matter (ads for other
Chelsea Green Publishing books), which the outline never bookmarks. Capped
explicitly to a single page rather than swallowing that back matter.

No reliable recurring callout-box marker was found (a full-text scan for
repeated ALL-CAPS lines turned up only one-off subsection headers, e.g.
"CAFFEINE", "BLUE LIGHT", "SLEEP APNEA AND RESTLESS LEGS SYNDROME" -- topic
headers, not a distinct boxed-callout label repeated across chapters like
source7's CLINICAL INSIGHT), so block_type is left empty.
"""
import re
from pathlib import Path

FILENAME = "_OceanofPDF.com_Peak_-_Marc_Bubbs.pdf"
EXPECTED_PAGES = 398
STRUCTURE = "native_outline_pattern_filtered"  # numbered chapters + Introduction/Conclusion/About the Author, level-aware boundaries

CHAPTER_RE = re.compile(r"^Chapter\s+\d+:")
LEVEL1_KEEP_TITLES = {
    "Introduction: The Revolution in Performance",
    "Conclusion",
    "About the Author",
}
# The real bio is exactly 1 page; everything after it in the PDF is
# unbookmarked publisher back-matter (see module docstring).
SINGLE_PAGE_TITLES = {"About the Author"}


def _is_keep(lvl: int, title: str) -> bool:
    if lvl == 2 and CHAPTER_RE.match(title):
        return True
    if lvl == 1 and title in LEVEL1_KEEP_TITLES:
        return True
    return False


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz  # PyMuPDF -- only needed here for the raw outline

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
        n_pages = doc.page_count

    full_entries = sorted(
        ((lvl, title.strip(), page - 1) for lvl, title, page in toc),
        key=lambda e: e[2],
    )

    def compute_end(i: int) -> int:
        lvl = full_entries[i][0]
        for j in range(i + 1, len(full_entries)):
            if full_entries[j][0] <= lvl:
                return full_entries[j][2] - 1
        return n_pages - 1

    sections = []
    n_dropped = 0
    n_chapters = 0
    n_other = 0
    for i, (lvl, title, start) in enumerate(full_entries):
        if not _is_keep(lvl, title):
            n_dropped += 1
            continue
        if title in SINGLE_PAGE_TITLES:
            end = start
        else:
            end = max(compute_end(i), start)
        body = "\n\n".join(pages[start:end + 1]).strip()
        sections.append({
            "title": title,
            "level": lvl,
            "start_page": start,
            "end_page": end,
            "text": body,
            "block_type": [],
        })
        if CHAPTER_RE.match(title):
            n_chapters += 1
        else:
            n_other += 1

    print(f"[{source_key}] {n_chapters} chapters + {n_other} other kept section(s) "
          f"(Introduction/Conclusion/About the Author) -- {n_dropped} front-matter/"
          "Part-divider/Notes entries dropped")
    return sections
