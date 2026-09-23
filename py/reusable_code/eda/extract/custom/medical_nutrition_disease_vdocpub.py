"""
Source: vdoc.pub_medical-nutrition-and-disease-a-case-based-approach.pdf
(607 pages) -- a different PDF conversion of the SAME book as medical_nutrition_disease_case_based
(Medical_Nutrition_and_Disease_A_Case_Based_Approach.pdf, Wiley, 5th ed.,
ed. Lisa Hark/Darwin Deen/Gail Morrison), this time from Adobe InDesign CS4
via iText (vs. medical_nutrition_disease_case_based's converter), with a much richer native outline: 548
entries across 4 levels (vs. medical_nutrition_disease_case_based's 176 across 4 levels, heavily
flattened by its own converter) -- effectively the publisher's real
chapter/section/case hierarchy, preserved rather than collapsed.

  level 1: front matter (Cover, Title page, Copyright page, Contents, List
           of Contributors), "Preface", 4 "Part N: <title>" dividers,
           "Appendices", "Review Questions", "Review Answers", "Index",
           2 CE-credit administrative entries (a registration form and an
           answer-bubble-sheet), "EULA".
  level 2: the 13 "N: <title>" chapter entries (nested under their Part
           divider), plus, nested under "Review Questions"/"Review
           Answers", 13 "Chapter N <title>" entries each (26 total) -- and,
           nested under the CE answer-bubble-sheet, 13 bare "Chapter N"
           entries (no title text at all) that are NOT real content, just
           scoring-grid labels on a fill-in-the-bubble form.
  level 3-4: ~478 entries -- per-chapter subsections named "Case N ...",
           "Case Questions", "Answers to Questions: Case N", chapter/case
           references, etc. -- real internal chapter structure, not
           standalone sections.

Kept: the 13 numbered chapters (level 2, "N: title"); the 13 real Review
Questions entries individually (level 2, "Chapter N <title>" -- the
non-content bare "Chapter N" entries under the CE answer-bubble-sheet are
excluded by requiring text *after* the chapter number, see
_REVIEW_ENTRY_RE); "Preface" (level 1 -- confirmed substantive,
edition-specific content, not boilerplate, same check-the-actual-page call
as nancy_clark_food_guide_new_runners / sports_nutrition_lab_manual's Foreword/Preface); and "Appendices" (level 1) --
special-cased, see below.

SPECIAL CASE -- "Review Answers": its 13 "Chapter N <title>" child
bookmarks (same title pattern as the real Review Questions entries) turn
out to collide on shared pages -- the answer key is terse enough that
Wiley's layout crams several chapters' answers onto one physical page
(e.g. chapters 1-4's answer-key bookmarks all point at the very same
page), so treating them as 13 independent sections would duplicate that
page's text across multiple "sections" with no reliable way to split the
run-on answer lines back apart per chapter. Kept as ONE combined "Review
Answers" section spanning the whole divider's page range instead -- the
same call medical_nutrition_disease_case_based made for this same book's answer key.

Dropped: Cover/Title page/Copyright page/Contents/List of Contributors
(pure boilerplate), the 4 Part dividers (confirmed zero standalone content
-- e.g. "Part I" is a single title page, the next page is blank, and the
first chapter starts on the page after that), the "Review Questions"
level-1 parent entry itself (divider-only -- its own page IS its first
child chapter's page; its 13 children are kept individually, see above),
Index, the CE registration form, the CE answer-bubble-sheet ("Answer
Sheet: Medical Nutrition & Disease 5th Edition" and its 13 bare "Chapter
N" children -- confirmed by direct page inspection to be a blank
multiple-choice bubble grid, not real content), and EULA.

SPECIAL CASE -- "Appendices": unlike medical_nutrition_disease_case_based (whose PDF converter gave
each of the 16 lettered food-source appendices its own outline bookmark),
this converter bookmarks the whole 18-page "Appendices" run as one flat
level-1 entry with no children at all. Direct inspection showed a
completely regular one-appendix-per-page layout (page 1 of the run is a
title/listing of all 16 appendix titles, page 2 is blank, then pages 3-18
are Appendix A through P in order, each opening with the exact line
"Appendix <letter> <title>."), so rather than keeping it as one 18-page
blob, _split_appendices() detects each "Appendix <letter> ..." page
heading directly -- a page-level regex scan within the outline-computed
[start, end] range, not a hardcoded absolute page offset, so it stays
correct if front-matter pagination ever shifts -- and emits 16 separate
one-page sections, dropping the intro/listing page and the blank page
before Appendix A (neither has any content worth keeping on its own).

Boundaries otherwise use the same level-aware rule as the level-aware outline sources (sources.py, ends="level") -- a
kept entry's end is the start of the next entry whose level is <= its own
level, minus one -- computed against the *full* outline (all 548 entries,
before filtering) so a dropped entry's pages are never silently absorbed
into whichever kept section precedes it (the nancy_clark_food_guide_new_runners / sports_nutrition_lab_manual bug).

No reliable recurring callout-box marker was found beyond plain section
headers ("OBJECTIVES", "REVIEW QUESTIONS") -- the same conclusion medical_nutrition_disease_case_based
reached for this same book under a different converter -- so block_type is
left empty.
"""
import re
from pathlib import Path

from ..common import level_aware_ends, page_text, read_outline, section

_CHAPTER_RE = re.compile(r"^\d+:\s")
# Real Review Questions/Review Answers entries only -- requires text after
# the chapter number, which excludes the bare "Chapter N" CE-answer-sheet
# labels (see module docstring).
_REVIEW_ENTRY_RE = re.compile(r"^Chapter\s+\d+\s+\S")
_APPENDIX_PAGE_RE = re.compile(r"^Appendix\s+([A-P])\s+(.+?)\.\s*$", re.MULTILINE)

_LEVEL1_KEEP_TITLES = {"Preface"}
_LEVEL1_SPLIT_TITLES = {"Appendices"}  # handled specially, not by the generic keep path
_LEVEL1_COALESCE_TITLES = {"Review Answers"}  # handled specially, see module docstring


def _is_keep(lvl: int, title: str) -> bool:
    if lvl == 2 and (_CHAPTER_RE.match(title) or _REVIEW_ENTRY_RE.match(title)):
        return True
    if lvl == 1 and title in _LEVEL1_KEEP_TITLES:
        return True
    return False


def _split_appendices(pages: list[str], start: int, end: int) -> list[dict]:
    hits = []
    for pno in range(start, end + 1):
        m = _APPENDIX_PAGE_RE.search(pages[pno])
        if m:
            hits.append((pno, m.group(1), m.group(2).strip()))
    out = []
    for i, (pno, letter, desc) in enumerate(hits):
        sec_end = hits[i + 1][0] - 1 if i + 1 < len(hits) else end
        out.append(section(f"Appendix {letter}: {desc}", 2, pno, sec_end, page_text(pages, pno, sec_end)))
    return out


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    outline, n_pages = read_outline(pdf_path)
    full_entries = sorted(((lvl, title.strip(), start) for lvl, title, start in outline), key=lambda e: e[2])
    ends = level_aware_ends(full_entries, n_pages)

    # "Review Answers"' own child bookmarks collide on shared pages (see
    # module docstring), so pre-compute its page range once and fold every
    # "Chapter N ..." entry that falls inside it into a single combined
    # section, rather than treating them as independent sections.
    review_answers_range = None
    for i, (lvl, title, start) in enumerate(full_entries):
        if lvl == 1 and title in _LEVEL1_COALESCE_TITLES:
            review_answers_range = (start, ends[i])
            break

    def _in_review_answers(start: int) -> bool:
        return review_answers_range is not None and review_answers_range[0] <= start <= review_answers_range[1]

    sections = []
    n_dropped = 0
    n_chapters = 0
    n_review_q = 0
    n_appendix = 0
    n_preface = 0
    for i, (lvl, title, start) in enumerate(full_entries):
        if lvl == 1 and title in _LEVEL1_SPLIT_TITLES:
            end = ends[i]
            appendix_sections = _split_appendices(pages, start, end)
            sections.extend(appendix_sections)
            n_appendix += len(appendix_sections)
            continue
        if lvl == 1 and title in _LEVEL1_COALESCE_TITLES:
            start_r, end_r = review_answers_range
            sections.append(section(title, lvl, start_r, end_r, page_text(pages, start_r, end_r)))
            continue
        if lvl == 2 and _REVIEW_ENTRY_RE.match(title) and _in_review_answers(start):
            # an individual Review Answers child bookmark -- already folded
            # into the combined section above
            n_dropped += 1
            continue
        if not _is_keep(lvl, title):
            n_dropped += 1
            continue
        end = ends[i]
        sections.append(section(title, lvl, start, end, page_text(pages, start, end)))
        if _CHAPTER_RE.match(title):
            n_chapters += 1
        elif _REVIEW_ENTRY_RE.match(title):
            n_review_q += 1
        else:
            n_preface += 1

    print(f"[{source_key}] {n_chapters} chapters + {n_review_q} Review Questions "
          f"entries + 1 combined Review Answers + {n_appendix} split appendices + "
          f"{n_preface} Preface -- {n_dropped} front-matter/Part-divider/Index/"
          "CE-form/coalesced entries dropped")
    return sections
