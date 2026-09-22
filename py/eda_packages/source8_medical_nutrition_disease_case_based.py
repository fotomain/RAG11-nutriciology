"""
Source: Medical_Nutrition_and_Disease_A_Case_Based_Approach.pdf (402 pages).

A Nurse Practitioner continuing-education (CE) course textbook (its own
outline root bookmark is actually titled "The Nurse Practitioner's Guide to
Nutrition" -- a subtitle/earlier-edition mismatch with the filename, not a
different book). Native outline, 176 entries across 4 levels, structured
like a smaller, shallower cousin of source7:

  level 1: just the whole-book root bookmark (1 entry) -- not useful on its
           own.
  level 2: front matter (Copyright, Contents, About the Editors,
           Contributors), 3 "Section N <title>" dividers, an "Appendices"
           divider, then "Review Questions" / "Review Answers" (the CE
           quiz + answer key -- real content), Index, and 2 CE
           administrative forms (Enrollment Form, Evaluation Form).
  level 3: 13 numbered chapters ("N Title") nested under the 3 Section
           dividers, and 20 single-letter appendices ("Appendix A".."Appendix T")
           nested under the "Appendices" divider.
  level 4: ~129 sub-headings inside individual chapters (not sections in
           their own right).

Kept content, by pattern (same idea as source7, smaller scale): level-3
numbered chapters, level-3 "Appendix <letter>" entries, and the two level-2
CE quiz entries by exact title. Everything else (root bookmark, front
matter, Section/Appendices dividers, Index, CE admin forms) is dropped.

Boundaries use the same level-aware rule as source7 -- a kept entry's end
is the start of the next entry whose level is <= its own level, minus one
-- so a chapter's ~10 internal level-4 sub-headings don't fragment it, and
a dropped "Section N" divider still correctly stops the chapter before it
(rather than being silently absorbed).

No reliable recurring callout-box marker was found in a text scan (unlike
source7's ALL-CAPS box headers) -- "Key Points"/"Patient Education" turned
up as ordinary prose and inconsistent table captions, not a clean box
pattern -- so block_type is left empty here rather than guessing at one.
Titles/bodies are cleaned of a non-breaking space (U+00A0, present in some
outline titles) and two rare PUA/font-mapping-fallback glyphs found by a
full-text scan (U+E0A1, a bullet substitute, 4 occurrences; U+F6DA, likely
a lost trademark-symbol glyph in "MNA(R)-SF", 1 occurrence).
"""
import re
from pathlib import Path

FILENAME = "Medical_Nutrition_and_Disease_A_Case_Based_Approach.pdf"
EXPECTED_PAGES = 402
STRUCTURE = "native_outline_pattern_filtered"  # numbered chapters + lettered appendices + CE quiz, level-aware boundaries

CHAPTER_RE = re.compile(r"^\d+\s+\S")
APPENDIX_LETTER_RE = re.compile(r"^Appendix\s+[A-Z]$", re.IGNORECASE)
STANDALONE_KEEP_TITLES = {"Review Questions", "Review Answers"}

_STRIP_CHARS_RE = re.compile("[ ]")


def _clean_title(title: str) -> str:
    return " ".join(_STRIP_CHARS_RE.sub(" ", title).split())


def _clean_body(text: str) -> str:
    cleaned = _STRIP_CHARS_RE.sub(" ", text)
    return re.sub(r"[ \t]+", " ", cleaned)


def _is_keep(lvl: int, title: str) -> bool:
    if lvl == 3 and (CHAPTER_RE.match(title) or APPENDIX_LETTER_RE.match(title)):
        return True
    if lvl == 2 and title in STANDALONE_KEEP_TITLES:
        return True
    return False


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz  # PyMuPDF -- only needed here for the raw outline

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
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
    n_chapters = 0
    n_appendices = 0
    n_quiz = 0
    for i, (lvl, title, start) in enumerate(full_entries):
        if not _is_keep(lvl, title):
            n_dropped += 1
            continue
        end = max(compute_end(i), start)
        body = "\n\n".join(_clean_body(p) for p in pages[start:end + 1]).strip()
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
        elif APPENDIX_LETTER_RE.match(title):
            n_appendices += 1
        else:
            n_quiz += 1

    print(f"[{source_key}] {n_chapters} chapters + {n_appendices} appendices + "
          f"{n_quiz} CE quiz section(s) kept ({n_dropped} front-matter/divider/index/"
          "admin-form entries dropped)")
    return sections
