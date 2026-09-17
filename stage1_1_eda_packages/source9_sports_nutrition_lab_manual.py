"""
Source: Sports-Nutrition-Laboratory-Manual-Mary-P.-Miles-Stephanie-M.G.-Wilson-
and-Morgan-L.-Chamberlin.pdf (87 pages).

Native outline, only 14 entries, all at level 1 (flat, no nesting) -- the
simplest structure of any source so far. Front matter (`Cover`, `About the
Authors`, `Table of Contents`, `List of Figures`, `List of Tables`) is
dropped as boilerplate, but `Preface` is kept: unlike most front matter
seen in other sources, it's a substantive page explaining the manual's
purpose and pedagogy, not just an administrative blurb. The 5 numbered
"Laboratory N" modules and 3 lettered appendices are the real lab-manual
content.

Boundaries use common.sections_from_outline (all 14 entries, single level)
computed against the FULL outline before dropping anything, same reasoning
as source5: this keeps a dropped title's own pages from being silently
absorbed into whichever kept section precedes it (here, the 4 consecutive
dropped front-matter entries between Preface and Laboratory 1 correctly
form their own excluded zone rather than extending Preface's page range).

Strips a running page footer/header repeated throughout ("Sports
Nutrition: Laboratory Manual" combined with a page number, in either
order depending on the page) -- pure layout noise, not content.

No reliable recurring callout-box marker was found (each lab's own
"N.1 BACKGROUND" / "N.2 OBJECTIVE" / "N.3 OVERVIEW" / "N.4 PROCEDURES"
numbering is just its internal subsection structure, not a distinct boxed
callout), so block_type is left empty.
"""
import re
from pathlib import Path

from .common import sections_from_outline

FILENAME = "Sports-Nutrition-Laboratory-Manual-Mary-P.-Miles-Stephanie-M.G.-Wilson-and-Morgan-L.-Chamberlin.pdf"
EXPECTED_PAGES = 87
STRUCTURE = "native_outline"  # flat, single-level outline; front matter filtered by title

DROP_TITLES = {"Cover", "About the Authors", "Table of Contents", "List of Figures", "List of Tables"}

_RUNNING_FOOTER_RE = re.compile(
    r"^\s*\d*\s*Sports Nutrition:\s*Laboratory Manual\s*\d*\s*$", re.IGNORECASE
)


def _clean_body(text: str) -> str:
    kept = [ln for ln in text.splitlines() if not _RUNNING_FOOTER_RE.match(ln)]
    return "\n".join(kept)


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    sections = sections_from_outline(pdf_path, source_key, min_level=1, max_level=1)

    kept = []
    n_dropped = 0
    for sec in sections:
        if sec["title"] in DROP_TITLES:
            n_dropped += 1
            continue
        sec["text"] = "\n\n".join(
            _clean_body(p) for p in pages[sec["start_page"]:sec["end_page"] + 1]
        ).strip()
        sec["block_type"] = []
        kept.append(sec)

    print(f"[{source_key}] {len(kept)} sections kept (Preface + labs + appendices), "
          f"dropped {n_dropped} front-matter entries, stripped running page footer")
    return kept
