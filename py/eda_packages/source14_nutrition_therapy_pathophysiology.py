"""
Source: vdoc.pub_nutrition-therapy-and-pathophysiology-2nd-edition.pdf (1080 pages).

Nutrition Therapy and Pathophysiology 2nd Edition (Marcia Nelms, Kathryn P. Sucher,
Sara Long Roth).
Native outline: 289 entries across 3 levels:
  level 1: front matter (Cover Page, Title, Copyright, Dedication, Contents),
           4 Part dividers ("PART 1", "PART 2", "PART 3", "PART 4"),
           "APPENDIXES" divider, "GLOSSARY", and "INDEX".
  level 2: 26 numbered chapters ("N Title") nested under the 4 Part dividers,
           and 15 lettered appendices ("Appendix A—...", "Appendix O—...") nested
           under the "APPENDIXES" divider.
  level 3: hundreds of sub-headings inside chapters and individual appendices.

Kept content:
  - Level 2 chapters 1 through 26 ("N <title>")
  - Level 2 appendices A through O ("Appendix <letter>—<title>")
  - Level 1 "GLOSSARY"

Dropped content:
  - Front matter (Cover, Title, Copyright, Dedication, Brief TOC, Full TOC)
  - Part dividers (PART 1 through PART 4, APPENDIXES)
  - Back matter (INDEX)

Boundaries use level-aware compute_end: a section ends before the next entry
with level <= its own level, preventing chapters from spilling into part dividers
or adjacent chapters while preserving internal level-3 subheadings.
"""
import re
from pathlib import Path

FILENAME = "vdoc.pub_nutrition-therapy-and-pathophysiology-2nd-edition.pdf"
EXPECTED_PAGES = 1080
STRUCTURE = "native_outline_pattern_filtered"

CHAPTER_RE = re.compile(r"^\d+\s+\S")
APPENDIX_RE = re.compile(r"^Appendix\s+[A-Z]", re.IGNORECASE)


def _is_keep(lvl: int, title: str) -> bool:
    if lvl == 2 and CHAPTER_RE.match(title):
        return True
    if lvl == 2 and APPENDIX_RE.match(title):
        return True
    if lvl == 1 and title.upper() == "GLOSSARY":
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
    n_glossary = 0

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
            n_glossary += 1

    print(f"[{source_key}] {n_chapters} chapters + {n_appendices} appendices + "
          f"{n_glossary} glossary section(s) kept ({n_dropped} front-matter/part-divider/sub-heading/index entries dropped)")
    return sections
