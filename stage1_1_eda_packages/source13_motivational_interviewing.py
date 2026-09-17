"""
Source: vdoc.pub_motivational-interviewing-in-nutrition-and-fitness.pdf (290 pages).

Motivational Interviewing in Nutrition and Fitness (Dawn Clifford, Denise Phelan).
Native outline: 33 entries across 2 levels:
  level 1: front matter (Cover, Title, Copyright, Contents, etc.), Introduction,
           5 Part dividers ("Part I. Motivational Interviewing Basics", etc.),
           2 lettered/numbered appendices ("Appendix 1. Making Referrals",
           "Appendix 2. Additional Resources"), References, and Index.
  level 2: 15 numbered chapters ("N. Title") nested under the 5 Part dividers.

Kept content:
  - Level 1 "Introduction"
  - Level 2 chapters 1 through 15 ("N. <title>")
  - Level 1 Appendices 1 and 2 ("Appendix N. <title>")

Dropped content:
  - Front matter (Cover, Half Title, Series Page, Title Page, Copyright,
    About the Authors, Series Editors’ Note, Contents)
  - Part dividers (Part I through Part V)
  - Back matter (References, Index)

Boundaries use level-aware compute_end: a section ends before the next entry
with level <= its own level, preventing chapters from spilling into part dividers.
"""
import re
from pathlib import Path

FILENAME = "vdoc.pub_motivational-interviewing-in-nutrition-and-fitness.pdf"
EXPECTED_PAGES = 290
STRUCTURE = "native_outline_pattern_filtered"

CHAPTER_RE = re.compile(r"^\d+\.\s+\S")
APPENDIX_RE = re.compile(r"^Appendix\s+\d+", re.IGNORECASE)


def _is_keep(lvl: int, title: str) -> bool:
    if lvl == 2 and CHAPTER_RE.match(title):
        return True
    if lvl == 1 and (APPENDIX_RE.match(title) or title == "Introduction"):
        return True
    return False


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)
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
    n_appendices = 0
    n_other = 0

    for i, (lvl, title, start) in enumerate(full_entries):
        if not _is_keep(lvl, title):
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
        if CHAPTER_RE.match(title):
            n_chapters += 1
        elif APPENDIX_RE.match(title):
            n_appendices += 1
        else:
            n_other += 1

    print(f"[{source_key}] {n_chapters} chapters + {n_appendices} appendices + "
          f"{n_other} introductory section(s) kept ({n_dropped} front-matter/part-divider/index entries dropped)")
    return sections
