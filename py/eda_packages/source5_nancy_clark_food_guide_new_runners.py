"""
Source: Clark N. - Nancy Clark's Food Guide for New Runners. Getting It
Right from the Start - 2009.pdf (161 pages).

Native PDF outline, 30 entries across 2 levels -- but unlike source1/source3
it can't be sliced with a single min_level/max_level range via
common.sections_from_outline, for two reasons:

1. The book groups its 16 real chapters (level 2, "Chapter N ...") under 4
   "Part" dividers (level 1, "Section I./II./III./IV. ..."). Each divider
   starts on the SAME page as its first child chapter (e.g. "Section II."
   and "Chapter 6" both start on page 56 (0-based)) -- it has zero standalone
   content of its own. Keeping both levels would emit a bogus 1-page
   "section" duplicating the first page of the chapter that follows it, so
   part-divider titles (matched by PART_DIVIDER_RE) are dropped from the
   section list; the chapter titles ("Chapter 6 ...") already carry enough
   context on their own.
2. The remaining level-1 entries are real front/back matter, but of very
   mixed value for RAG: some are pure structural boilerplate with no prose
   ("Contents", "Acknowledgements", "Dedication", "Index" -- dropped, same
   idea as source1 dropping its attribution bookmark), while others are
   genuine short-form content worth keeping ("Foreword", "Afterword",
   "Additional Resources", "Recommended Books", "Internet Resources",
   "About the Author").

Also strips a print-shop production artifact line repeated on every page
("nancy 1-78" / a DD.MM.YYYY date / "HH:MM Uhr" / "Seite N" -- German for
"o'clock"/"page", left over from the book's print job) before joining pages
into each section's text, the same way other sources strip running headers.

Not checked: this book is a consumer trade paperback with a 2-column /
sidebar layout (see the "Some Top Sports Foods" boxed list interleaved into
chapter 1's body). No consistent callout marker (like source2's "SAFETY
ALERT" or source4's "Critical Thinking:") was found in the sample checked,
so block_type is left empty here rather than guessing at one -- revisit if
a real pattern turns up once this runs against the full extracted text.
"""
import re
from pathlib import Path

FILENAME = "Clark N. - Nancy Clark's Food Guide for New Runners. Getting It Right from the Start - 2009.pdf"
EXPECTED_PAGES = 161
STRUCTURE = "native_outline"  # chapters at level 2; part-dividers dropped, front/back matter filtered by title

# Pure structural boilerplate -- no prose content worth retrieving.
DROP_TITLES = {"Contents", "Acknowledgements", "Dedication", "Index"}

# "Section I./II./III./IV. <title>" part-dividers share their start page
# with their first child chapter (see module docstring) -- drop them.
PART_DIVIDER_RE = re.compile(r"^Section\s+[IVXLC]+\.\s+", re.IGNORECASE)

# Print-shop job-ticket line repeated on every page, split across several
# short lines by page-text extraction: "nancy 1-78", a date, a time, and a
# "Seite N" (German "page N") line. Filtered line-by-line rather than as one
# block pattern, so it survives whatever exact line-splitting the extractor
# produces.
_PRINT_ARTIFACT_LINE_RE = re.compile(
    r"^(nancy\s+1-78|\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}:\d{2}\s*Uhr|Seite\s+\d+)$",
    re.IGNORECASE,
)


def _strip_print_artifacts(text: str) -> str:
    kept = [ln for ln in text.splitlines() if not _PRINT_ARTIFACT_LINE_RE.match(ln.strip())]
    return "\n".join(kept)


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz  # PyMuPDF -- only needed here for the raw outline

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
        n_pages = doc.page_count

    # Boundaries are computed against the FULL (unfiltered) outline first,
    # so a dropped entry's own pages stay excluded from the corpus instead
    # of being silently absorbed by whichever kept entry precedes it (e.g.
    # "Internet Resources" would otherwise swallow the ~9-page "Index" that
    # follows it, since "Index" is dropped and wouldn't exist as a boundary
    # on its own). Titles are classified for keep/drop only afterward.
    full_entries = [(lvl, title.strip(), page - 1) for lvl, title, page in toc]

    n_dropped_boilerplate = 0
    n_dropped_dividers = 0
    sections = []
    for i, (lvl, title, start) in enumerate(full_entries):
        end = full_entries[i + 1][2] - 1 if i + 1 < len(full_entries) else n_pages - 1
        end = max(end, start)

        if title in DROP_TITLES:
            n_dropped_boilerplate += 1
            continue
        if PART_DIVIDER_RE.match(title):
            n_dropped_dividers += 1
            continue

        body = "\n\n".join(_strip_print_artifacts(p) for p in pages[start:end + 1]).strip()
        sections.append({
            "title": title,
            "level": lvl,
            "start_page": start,
            "end_page": end,
            "text": body,
            "block_type": [],
        })

    if not sections:
        raise ValueError(f"{source_key}: no usable outline entries after filtering -- check DROP_TITLES/PART_DIVIDER_RE")

    print(f"[{source_key}] {len(sections)} sections from outline "
          f"(dropped {n_dropped_boilerplate} boilerplate + {n_dropped_dividers} part-divider entries)")
    return sections
