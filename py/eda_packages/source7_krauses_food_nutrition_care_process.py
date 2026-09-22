"""
Source: Krauses_Food_and_the_Nutrition_Care_Process.pdf (1159 pages, 14th ed.).

Native outline, but at a completely different scale than sources 1/3/5/6:
2538 entries across 7 levels. Structure (by level-1/level-2 inspection):

  pages    0-21   front matter (cover, copyright, dedication, contributors,
                   foreword, preface + its level-2 subentries, acknowledgments,
                   table of contents)
  pages   22-951   6 "Part" dividers (level 1, roman numerals I-VI) each
                   containing several numbered chapters (level 2, "N Title",
                   44 total, 1-44)
  pages  952-1109  53 numbered appendices (level 1, "APPENDIX N Title"),
                   several of which have their own level-2 subsections
                   (measurement tables, References, ...)
  pages 1110-1158  INDEX (level 1, with a level-2 A-Z entry per letter) +
                   inside back cover

Only the 44 chapters and 53 appendices are real retrievable content --
everything else (front matter, Part dividers, the index) is dropped by a
title pattern:
    level 2 AND title starts with "<digits> "        -> keep as a chapter
    level 1 AND title starts with "APPENDIX <digits>" -> keep as an appendix
Anything else (front matter, Part headers, index letters, ...) is dropped.

The tricky part is BOUNDARIES, because this outline nests 7 levels deep
(figures/subheadings inside a chapter add up to hundreds of level 3-7
entries) -- naively using "next entry in the full outline" as a section's
end (the approach that works for sources 1/3/5/6, which are at most 2
levels deep) would truncate every chapter/appendix down to just its first
internal subheading. The fix: a kept entry's end is the start of the next
entry *whose level is <= its own level* (skipping any deeper descendant
entries, which are internal content, not new sections) - 1. This also
transparently repairs a real inconsistency in the source PDF's outline tree
(chapter 42 is nested as the last child of Part V even though its own page
number puts it after Part VI's divider page) since the algorithm only
looks at page order and level, never tree parentage.

Also tags well-documented recurring callout boxes (named in the book's own
preface): CLINICAL INSIGHT, NEW DIRECTIONS, CASE STUDY, FOCUS ON -- each
appears as a standalone all-caps line right before its own boxed content.
"""
import re
from pathlib import Path

FILENAME = "Krauses_Food_and_the_Nutrition_Care_Process.pdf"
EXPECTED_PAGES = 1159
STRUCTURE = "native_outline_pattern_filtered"  # numbered chapters + APPENDIX headers, level-aware boundaries

CHAPTER_RE = re.compile(r"^\d+\s+\S")
APPENDIX_RE = re.compile(r"^APPENDIX\s+\d+", re.IGNORECASE)

CALLOUT_PATTERNS = {
    "clinical_insight": re.compile(r"^CLINICAL INSIGHT$", re.MULTILINE),
    "new_directions": re.compile(r"^NEW DIRECTIONS$", re.MULTILINE),
    "case_study": re.compile(r"^CASE STUDY$", re.MULTILINE),
    "focus_on": re.compile(r"^FOCUS ON$", re.MULTILINE),
}


def _is_keep(lvl: int, title: str) -> bool:
    if lvl == 2 and CHAPTER_RE.match(title):
        return True
    if lvl == 1 and APPENDIX_RE.match(title):
        return True
    return False


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz  # PyMuPDF -- only needed here for the raw outline

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
        n_pages = doc.page_count

    # Sort by start page (not outline-tree order): this book's tree has at
    # least one real inconsistency (see module docstring) where a chapter's
    # page number doesn't match its tree position, and computing boundaries
    # by scanning in page order is what actually matters.
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
    n_appendices = 0
    for i, (lvl, title, start) in enumerate(full_entries):
        if not _is_keep(lvl, title):
            n_dropped += 1
            continue
        end = max(compute_end(i), start)
        body = "\n\n".join(pages[start:end + 1]).strip()
        blocks = sorted(name for name, pat in CALLOUT_PATTERNS.items() if pat.search(body))
        sections.append({
            "title": title,
            "level": lvl,
            "start_page": start,
            "end_page": end,
            "text": body,
            "block_type": blocks,
        })
        if lvl == 2:
            n_chapters += 1
        else:
            n_appendices += 1

    n_with_callout = sum(1 for s in sections if s["block_type"])
    print(f"[{source_key}] {n_chapters} chapters + {n_appendices} appendices kept "
          f"({n_dropped} front-matter/part-divider/index entries dropped), "
          f"{n_with_callout} section(s) flagged with a callout box")
    return sections
