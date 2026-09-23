"""
Source: Advanced_Nutrition_and_Human_Metabolism.pdf (181 pages).

This is NOT the textbook itself. pdfinfo shows "Creator: BOOKEY" /
"Producer: jsPDF 2.5.2", and the front matter literally says "Written by
Bookey", "Check more about Advanced Nutrition and Human Metabolism
Summary", "Listen ... Audiobook" -- this is a Bookey-style condensed
chapter-by-chapter SUMMARY of Sareen S. Gropper's "Advanced Nutrition and
Human Metabolism, Fourth Edition", not the full text. No native PDF
outline (qpdf --json dump of the outline tree: zero /Outlines entries).

Structure found by inspecting the extracted page text (pdftotext -layout),
four zones back to back, each separated by a blank page:
  pages   0-6   front matter (title/about/"Summary Content List" TOC)
  pages   7-76  14 chapter summaries, one per chapter -- see below
  pages  77-101 "Best Quotes ... with Page Numbers", grouped by chapter
  pages 102-166 "... Questions" (Q&A), grouped by chapter
  pages 167-180 "... Quiz and Test", grouped by chapter

Chapter summaries (pages 7-76):
- A "Summary Content List" block (pages 5-6, 0-based) is the book's own
  table of contents: 14 entries shaped "Chapter N : Ch N: <title>". Parsed
  the same way nutrition_for_nurses trusts its printed TOC over a heuristic heading
  regex, rather than hardcoding titles.
- Each chapter's summary body starts at a "Chapter N Summary" heading.
  Two chapters (3 and 5) have this heading appear TWICE in a row: once as
  a short divider matching the TOC-style title, then again right before
  the real narrative (chapter 5's has a compact "Section/Content" recap
  table sandwiched in between -- itself legitimate chapter content, not
  boilerplate to strip). Using the FIRST occurrence per chapter number as
  the section start, running to the next chapter's first occurrence,
  handles both the single- and double-heading chapters correctly.
- Chapter 14 has no "Chapter 15" heading to stop at, so without an
  explicit stop point it would swallow the ~104 pages of back matter that
  follow it as if they were still chapter 14's summary -- capped instead
  at the page before the first back-matter zone starts (see below).
- A handful of chapters (verified: 6 of 14) have a "Critical Thinking"
  callout box ("Key Point:" / "Critical Interpretation:") -- tagged as
  block_type "critical_thinking", same pattern as nutrition_for_nurses's Safety Alert /
  Clinical Tip callouts.

Back matter (pages 77-180): each of the three zones (Quotes / Q&A / Quiz)
is meant to be per-chapter, but several chapters are missing an entry
outright (only 9/14 have a Q&A block, only 6/14 have a Quiz block) and the
"Chapter N | Ch N: <title>| Q&A" headings wrap across lines unpredictably
-- splitting these further by chapter is fragile and would silently lose
whichever chapters don't match. Each zone is kept as ONE parent section
instead (its content is still fully reachable -- child-chunking below
splits every section into ~300-500 token pieces regardless of parent
granularity), tagged block_type "quotes" / "qa" / "quiz".
"""
import re
from pathlib import Path


CONTENT_LIST_MARKER = "Summary Content List"
CHAPTER_HEADING_RE = re.compile(r"Chapter\s+(\d+)\s+Summary", re.IGNORECASE)
CONTENT_LIST_ENTRY_RE = re.compile(r"Chapter\s+(\d+)\s*:\s*")

CALLOUT_PATTERNS = {
    "critical_thinking": re.compile(
        r"Critical Thinking|Key Point:|Critical Interpretation:", re.IGNORECASE
    ),
}

# (zone tag, marker pattern, section title) for each back-matter zone, in
# the order they appear in the document. Each marker is a phrase that
# occurs exactly once, on that zone's first (divider) page.
BACK_MATTER_ZONES = [
    ("quotes", re.compile(r"Best Quotes from Advanced Nutrition", re.IGNORECASE),
     "Best Quotes (by chapter, with page numbers)"),
    ("qa", re.compile(r"Advanced Nutrition and Human\s+Metabolism Questions", re.IGNORECASE),
     "Chapter Q&A"),
    ("quiz", re.compile(r"Advanced Nutrition and Human\s+Metabolism Quiz and Test", re.IGNORECASE),
     "Chapter Quiz and Test"),
]


def _find_content_list_range(pages: list[str], source_key: str) -> tuple[int, int]:
    """Locate the "Summary Content List" page range: starts on the page
    containing that marker, ends right before the first page whose text
    matches CHAPTER_HEADING_RE (i.e. where Chapter 1's actual summary
    begins)."""
    start = None
    for i, p in enumerate(pages):
        if CONTENT_LIST_MARKER in p:
            start = i
            break
    if start is None:
        raise ValueError(
            f"{source_key}: could not find a '{CONTENT_LIST_MARKER}' page to anchor chapter titles"
        )

    end = start
    while end < len(pages) and not CHAPTER_HEADING_RE.search(pages[end]):
        end += 1
    if end >= len(pages):
        raise ValueError(
            f"{source_key}: found '{CONTENT_LIST_MARKER}' but no 'Chapter N Summary' heading after it"
        )
    return start, end


def _parse_chapter_titles(pages: list[str], source_key: str) -> dict[int, str]:
    start, end = _find_content_list_range(pages, source_key)
    block = "\n".join(pages[start:end])
    # Splitting on "Chapter N :" with a capturing group interleaves the
    # chapter-number matches with the raw (possibly line-wrapped) title
    # text between them; parts[0] is the "Summary Content List" preamble.
    parts = CONTENT_LIST_ENTRY_RE.split(block)
    titles: dict[int, str] = {}
    for i in range(1, len(parts) - 1, 2):
        num = int(parts[i])
        raw_title = parts[i + 1]
        titles[num] = " ".join(raw_title.split())
    return titles


def _find_back_matter_zones(pages: list[str]) -> list[tuple[str, int, str]]:
    """Return [(zone_tag, start_page, title), ...] for each back-matter
    zone found, in page order."""
    found = []
    for tag, pat, title in BACK_MATTER_ZONES:
        for i, p in enumerate(pages):
            if pat.search(p):
                found.append((tag, i, title))
                break
    found.sort(key=lambda t: t[1])
    return found


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    chapter_titles = _parse_chapter_titles(pages, source_key)

    first_page_for_chapter: dict[int, int] = {}
    for pno, text in enumerate(pages):
        for m in CHAPTER_HEADING_RE.finditer(text):
            num = int(m.group(1))
            if num not in first_page_for_chapter:
                first_page_for_chapter[num] = pno

    chapter_numbers = sorted(first_page_for_chapter)
    if not chapter_numbers:
        raise ValueError(f"{source_key}: no 'Chapter N Summary' headings found")

    back_matter = _find_back_matter_zones(pages)
    # The last chapter has no "next chapter" heading to stop at -- bound it
    # at the first back-matter zone instead of running to the end of the
    # document (see module docstring).
    summary_zone_end = back_matter[0][1] - 1 if back_matter else len(pages) - 1

    sections = []
    for i, num in enumerate(chapter_numbers):
        start_page = first_page_for_chapter[num]
        if i + 1 < len(chapter_numbers):
            end_page = first_page_for_chapter[chapter_numbers[i + 1]] - 1
        else:
            end_page = summary_zone_end
        end_page = max(start_page, end_page)
        body = "\n\n".join(pages[start_page:end_page + 1])
        blocks = [name for name, pat in CALLOUT_PATTERNS.items() if pat.search(body)]
        title = chapter_titles.get(num, f"Chapter {num}")

        sections.append({
            "title": title,
            "level": 1,
            "start_page": start_page,
            "end_page": end_page,
            "text": body.strip(),
            "block_type": blocks,
        })

    for i, (tag, start_page, title) in enumerate(back_matter):
        end_page = back_matter[i + 1][1] - 1 if i + 1 < len(back_matter) else len(pages) - 1
        end_page = max(start_page, end_page)
        body = "\n\n".join(pages[start_page:end_page + 1]).strip()
        if not body:
            continue
        sections.append({
            "title": title,
            "level": 1,
            "start_page": start_page,
            "end_page": end_page,
            "text": body,
            "block_type": [tag],
        })

    print(f"[{source_key}] {len(chapter_numbers)} chapter-summary sections "
          f"(chapters {chapter_numbers[0]}-{chapter_numbers[-1]} of {len(chapter_titles)} listed) "
          f"+ {len(back_matter)} back-matter section(s): {[t for t, _, _ in back_matter]}")
    n_with_callout = sum(1 for s in sections if "critical_thinking" in s["block_type"])
    print(f"[{source_key}] {n_with_callout} chapter(s) flagged with a Critical Thinking callout")
    return sections
