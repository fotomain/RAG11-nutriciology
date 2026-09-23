"""Config-driven section extraction: the two strategies most sources need, parameterised by their
entry in sources.py (see that module's docstring for every key).

    outline    -- slice the PDF's own bookmarks; keep/drop entries by (level, title regex)
    fixed_toc  -- a hand-transcribed [(title, pdf_page_1based, keep)] table (scans with no text
                  layer and no outline), text from native pages or OCR

Boundaries are always computed over the FULL candidate list before keep/drop filtering, so a
dropped entry's pages (an Index, a Part divider) are excluded rather than silently absorbed into
whichever kept section precedes it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .common import (callouts, clean_title, level_aware_ends, next_entry_ends, ocr_pages, page_text,
                     read_outline, section)


def _page_cleaner(cfg: dict) -> Callable[[str], str] | None:
    """Per-page cleanup from cfg: strip_chars (-> space), strip_text (regex subs), strip_lines
    (drop lines whose stripped text fullmatches), collapse_spaces (runs of space/tab -> one)."""
    strip_chars = cfg.get("strip_chars", "")
    strip_text = [re.compile(p) for p in cfg.get("strip_text", [])]
    strip_lines = [re.compile(p) for p in cfg.get("strip_lines", [])]
    collapse = cfg.get("collapse_spaces", False)
    if not (strip_chars or strip_text or strip_lines or collapse):
        return None

    def clean(text: str) -> str:
        for ch in strip_chars:
            text = text.replace(ch, " ")
        for pat in strip_text:
            text = pat.sub("", text)
        if strip_lines:
            text = "\n".join(ln for ln in text.splitlines()
                             if not any(p.fullmatch(ln.strip()) for p in strip_lines))
        if collapse:
            text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    return clean


def _finish(source_key: str, sections: list[dict], cfg: dict, pages: list[str], n_dropped: int) -> list[dict]:
    """Tag callouts, report flagged pages, print a one-line summary."""
    patterns = {name: re.compile(p) for name, p in cfg.get("callouts", {}).items()}
    if patterns:
        for sec in sections:
            sec["block_type"] = callouts(sec["text"], patterns)
    if cfg.get("flag"):
        flag = re.compile(cfg["flag"])
        hits = sorted({p for sec in sections for p in range(sec["start_page"], sec["end_page"] + 1)
                       if p < len(pages) and flag.search(pages[p])})
        print(f"[{source_key}] {len(hits)} page(s) match flag {cfg['flag']!r}: {hits[:10]}{'...' if len(hits) > 10 else ''}")
    n_tagged = sum(1 for s in sections if s["block_type"])
    print(f"[{source_key}] {len(sections)} sections kept, {n_dropped} entries dropped"
          + (f", {n_tagged} with a callout" if patterns else ""))
    if not sections:
        raise ValueError(f"{source_key}: no sections left after filtering -- check its sources.py entry")
    return sections


def extract_outline(source_key: str, pdf_path: Path, pages: list[str], cfg: dict) -> list[dict]:
    """cfg keys: levels (min, max) -- only these outline levels are candidates (default all);
    ends "next" (default: next candidate's start - 1) or "level" (next candidate with level <= own,
    for deep outlines; candidates sorted by page); keep [(level|None, title_regex)] -- if given, a
    candidate must match one; drop [title_regex] -- checked first; single_page [titles] -- capped
    to their first page. All title regexes are fullmatched against the cleaned title."""
    outline, n_pages = read_outline(pdf_path)
    strip_chars = cfg.get("strip_chars", "")
    entries = [(lvl, clean_title(t, strip_chars), start) for lvl, t, start in outline]
    lo, hi = cfg.get("levels", (1, 99))
    entries = [e for e in entries if lo <= e[0] <= hi]

    if cfg.get("ends", "next") == "level":
        entries.sort(key=lambda e: e[2])  # page order: some outlines nest a chapter under the wrong Part
        ends = level_aware_ends(entries, n_pages)
    else:
        ends = next_entry_ends([e[2] for e in entries], n_pages)

    keep = [(lvl, re.compile(p)) for lvl, p in cfg.get("keep", [])]
    drop = [re.compile(p) for p in cfg.get("drop", [])]
    single_page = set(cfg.get("single_page", []))
    clean = _page_cleaner(cfg)

    sections, n_dropped = [], 0
    for (lvl, title, start), end in zip(entries, ends):
        if any(p.fullmatch(title) for p in drop) or (
                keep and not any((kl is None or kl == lvl) and p.fullmatch(title) for kl, p in keep)):
            n_dropped += 1
            continue
        if title in single_page:
            end = start
        sections.append(section(title, lvl, start, end, page_text(pages, start, end, clean)))
    return _finish(source_key, sections, cfg, pages, n_dropped)


def extract_fixed_toc(source_key: str, pdf_path: Path, pages: list[str], cfg: dict) -> list[dict]:
    """cfg keys: toc [(title, pdf_page_1based, keep)] in page order; text "pages" (default) or
    "ocr" (ignore the native text layer and OCR the PDF, cached)."""
    toc = cfg["toc"]
    if cfg.get("text") == "ocr":
        pages = ocr_pages(pdf_path, source_key)
    starts = [p - 1 for _, p, _ in toc]
    ends = next_entry_ends(starts, len(pages))
    clean = _page_cleaner(cfg)
    sections, n_dropped = [], 0
    for (title, _, keep), start, end in zip(toc, starts, ends):
        if not keep:
            n_dropped += 1
            continue
        sections.append(section(title, 1, start, end, page_text(pages, start, end, clean)))
    return _finish(source_key, sections, cfg, pages, n_dropped)


STRATEGIES = {"outline": extract_outline, "fixed_toc": extract_fixed_toc}
