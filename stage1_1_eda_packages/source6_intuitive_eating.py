"""
Source: Intuitive_Eating_A_Revolutionary_Program_that_Works.pdf (240 pages).

Native outline, 95 entries across 2 levels: 12 at level 1 ("introduction",
10 "chapter N: <title>" dividers, and a trailing "Acknowledgments"), 83 at
level 2 ("activity N ... : for you to know", one or more per chapter -- this
is a teen workbook edition of Intuitive Eating, and each numbered "activity"
is a guided exercise with its own "for you to know" / "for you to do"
subsections). Unlike source1, the two levels don't collide on the same
page here -- there's real chapter-intro narrative before a chapter's first
*bookmarked* activity starts (oddly, "activity 1" of each chapter is never
itself bookmarked, only "activity 2" onward; its content is simply part of
the parent chapter's own page range, same as source3's Unit-divider
pattern) -- so both levels are taken together as one flat, page-ordered
sequence via common.sections_from_outline(min_level=1, max_level=2), same
approach as source3.

"Acknowledgments" (the last entry) is dropped post-hoc as pure boilerplate
with no prose content worth retrieving -- safe to drop after the fact here
(unlike source5's mid-document drops) since it's the final entry and removing
it can't steal pages from any section that follows it.

The book's embedded font uses two Private Use Area glyphs as decorative
bullet/checkbox icons -- U+F051 (371 occurrences: used both as a "activity N
[glyph] Title" heading separator that's repeated as a running header on
every page of that activity, and inline in the front-matter contents list)
and the much rarer U+F033 (2 occurrences: a checkbox icon in a worksheet
table). Neither has a real glyph in standard fonts (renders as a blank box/
tofu character), so both are stripped from section text and outline titles
before use, and the "en space" (U+2002) used to pad around them in outline
titles is collapsed to a normal space.
"""
import re
from pathlib import Path

from .common import sections_from_outline

FILENAME = "Intuitive_Eating_A_Revolutionary_Program_that_Works.pdf"
EXPECTED_PAGES = 240
STRUCTURE = "native_outline"  # chapters + activities, levels 1-2 combined; decorative PUA glyphs stripped

DROP_TITLES = {"Acknowledgments"}  # pure boilerplate, no prose content

_DECORATIVE_GLYPH_RE = re.compile("[]")
_EN_SPACE_RE = re.compile(" ")


def _clean_title(title: str) -> str:
    t = _EN_SPACE_RE.sub(" ", _DECORATIVE_GLYPH_RE.sub(" ", title))
    return " ".join(t.split())


def _clean_body(text: str) -> str:
    # Collapse only horizontal whitespace left behind by a stripped glyph --
    # never touch newlines, so paragraph/line structure survives.
    cleaned = _EN_SPACE_RE.sub(" ", _DECORATIVE_GLYPH_RE.sub(" ", text))
    return re.sub(r"[ \t]+", " ", cleaned)


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    sections = sections_from_outline(pdf_path, source_key, min_level=1, max_level=2)

    kept = []
    n_dropped = 0
    for sec in sections:
        sec["title"] = _clean_title(sec["title"])
        if sec["title"] in DROP_TITLES:
            n_dropped += 1
            continue
        sec["text"] = "\n\n".join(
            _clean_body(p) for p in pages[sec["start_page"]:sec["end_page"] + 1]
        ).strip()
        sec["block_type"] = []
        kept.append(sec)

    print(f"[{source_key}] {len(kept)} sections from outline (levels 1-2), "
          f"dropped {n_dropped} boilerplate entry/entries, cleaned decorative PUA glyphs")
    return kept
