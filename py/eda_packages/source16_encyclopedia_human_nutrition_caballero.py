"""
Source: Encyclopedia_of_Human_Nutrition_4th_Edition_Benjamin_Caballero.pdf (2602 pages).

Encyclopedia of Human Nutrition, 4th Edition (Editor-in-Chief: Benjamin Caballero).
Massive multi-volume reference work spanning 4 volumes in a single 2602-page PDF.
Native outline has 5286 entries across 3 levels:
  level 1: 4 volume bookmark root entries ("9780323908160v1_WEB" through "v4_WEB").
  level 2: 279 total entries:
           - Front matter per volume (Front Cover, Copyright, Contents, Contributors,
             Editor Biographies, Preface)
           - 245 substantive encyclopedia articles alphabetically arranged ("Aluminum",
             "Amino acids: Chemistry and classification", ... "Supplementation: Developing countries")
           - Back matter at the end of Volume 4 (INDEX, AUTHOR INDEX).
  level 3: Thousands of internal sub-headings within individual articles.

Kept content:
  - 245 Level 2 encyclopedia articles.

Dropped content:
  - Level 1 volume dividers
  - Level 2 front-matter boilerplate (Front Cover, Copyright, CONTENTS OF VOLUME N,
    CONTRIBUTORS TO VOLUME N, EDITOR BIOGRAPHIES, PREFACE)
  - Level 2 back-matter indices (INDEX, AUTHOR INDEX)
  - Level 3 subheadings (preserved within the parent article text)

Boundaries use level-aware compute_end: an article ends before the next entry
whose level <= 2, ensuring clean article-to-article boundaries without fragmenting
internal level-3 subheadings or spilling across volume boundaries.
"""
import re
from pathlib import Path

FILENAME = "Encyclopedia_of_Human_Nutrition_4th_Edition_Benjamin_Caballero.pdf"
EXPECTED_PAGES = 2602
STRUCTURE = "native_outline_pattern_filtered"

_DROP_TITLES_EXACT = {
    "Front Cover",
    "Copyright",
    "EDITOR BIOGRAPHIES",
    "PREFACE",
    "INDEX",
    "AUTHOR INDEX",
}


def _clean_title(title: str) -> str:
    return " ".join(title.strip().split())


def _clean_body(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def _is_keep(lvl: int, title: str) -> bool:
    if lvl != 2:
        return False
    t = title.strip()
    if t in _DROP_TITLES_EXACT:
        return False
    if t.startswith("ENCYCLOPEDIA OF HUMAN NUTRITION"):
        return False
    if t.startswith("CONTENTS OF VOLUME"):
        return False
    if t.startswith("CONTRIBUTORS TO VOLUME"):
        return False
    return True


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)
        n_pages = doc.page_count

    full_entries = sorted(
        ((lvl, _clean_title(title), page - 1) for lvl, title, page in toc),
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
    n_articles = 0

    for i, (lvl, title, start) in enumerate(full_entries):
        if not _is_keep(lvl, title):
            if lvl <= 2:
                n_dropped += 1
            continue
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
        n_articles += 1

    print(f"[{source_key}] {n_articles} encyclopedia articles kept "
          f"({n_dropped} front-matter/volume-divider/index entries dropped)")
    return sections
