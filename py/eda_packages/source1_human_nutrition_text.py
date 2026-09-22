"""
Source: human-nutrition-text.pdf (1,208 pages).

Native PDF outline/bookmarks. The level-1 entries (25 of them) are just
chapters/front matter. The real ~140-150 "sections" the project brief means
are the level-2 children -- 267 of them, but exactly HALF are a repeated
attribution bookmark ("... Food Science and Human Nutrition Program ...")
injected right after every real section title at the same page. Using
level 2 and dropping that boilerplate yields 133 real sections, matching
the brief closely.
"""
from pathlib import Path

from .common import sections_from_outline

FILENAME = "human-nutrition-text.pdf"
EXPECTED_PAGES = 1208
STRUCTURE = "native_outline"  # ~140-150 sections via PDF bookmarks

ATTRIBUTION_TITLE_MARKER = "Food Science and Human Nutrition Program"


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    sections = sections_from_outline(pdf_path, source_key, min_level=2, max_level=2)
    sections = [s for s in sections if ATTRIBUTION_TITLE_MARKER not in s["title"]]
    for sec in sections:
        sec["text"] = "\n\n".join(pages[sec["start_page"]: sec["end_page"] + 1])
    print(f"[{source_key}] {len(sections)} sections after dropping attribution bookmarks "
          f"(brief expects ~140-150)")
    return sections
