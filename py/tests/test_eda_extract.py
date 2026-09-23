"""Offline tests for reusable_code.eda.extract -- builds tiny synthetic PDFs with pymupdf, no real
source books needed. Run: .venv/bin/python tests/test_eda_extract.py

Covers the SOURCES registry's integrity, both config strategies (outline with next-entry and
level-aware boundaries, fixed_toc), page cleanup options, process_source() dispatch (NFD filenames,
skip, generic fallback) and the per-PDF JSON cache.
"""
import importlib
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, ".")

import fitz  # noqa: E402

from reusable_code.eda import extract as ex  # noqa: E402
from reusable_code.eda.extract import common, strategies  # noqa: E402

FAILURES = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


TMP = Path(tempfile.mkdtemp())
ex.set_cache_dir(TMP / "cache")


def make_pdf(name, page_texts, toc=()):
    """One page per text; toc = [(level, title, page_1based), ...]."""
    doc = fitz.open()
    for text in page_texts:
        doc.new_page().insert_text((72, 72), text)
    if toc:
        doc.set_toc([list(e) for e in toc])
    path = TMP / name
    doc.save(path)
    doc.close()
    return path


# ---------- SOURCES registry integrity ----------

files = [c["file"] for c in ex.SOURCES.values()]
check("every SOURCES entry has a unique filename", len(files) == len(set(files)))
check("every strategy is known",
      all(c["strategy"] in {"outline", "fixed_toc", "custom", "skip"} for c in ex.SOURCES.values()))
bad_regex = []
for slug, c in ex.SOURCES.items():
    pats = ([p for _, p in c.get("keep", [])] + c.get("drop", []) + c.get("strip_text", [])
            + c.get("strip_lines", []) + list(c.get("callouts", {}).values()) + ([c["flag"]] if c.get("flag") else []))
    for p in pats:
        try:
            re.compile(p)
        except re.error:
            bad_regex.append((slug, p))
check("every SOURCES regex compiles", not bad_regex)
customs = [s for s, c in ex.SOURCES.items() if c["strategy"] == "custom"]
check("every custom source has custom/<slug>.py with extract_sections()",
      all(callable(getattr(importlib.import_module(f"reusable_code.eda.extract.custom.{s}"), "extract_sections", None))
          for s in customs))
check("non-skip, non-custom entries carry pages/structure/notes",
      all(c.get("pages") and c.get("structure") and c.get("notes")
          for c in ex.SOURCES.values() if c["strategy"] in {"outline", "fixed_toc"}))
check("skipped files are listed in SKIPPED_FILENAMES, not in KNOWN_SOURCE_EDA_META",
      "The_Nutrition_Society_Textbook.pdf" in ex.SKIPPED_FILENAMES
      and "The_Nutrition_Society_Textbook.pdf" not in ex.KNOWN_SOURCE_EDA_META)


# ---------- boundary rules ----------

check("next_entry_ends: each entry runs to the next start - 1, last to the end",
      common.next_entry_ends([0, 3, 3, 7], 10) == [2, 3, 6, 9])
entries = [(1, "Part I", 0), (2, "1 Intro", 1), (3, "sub", 2), (2, "2 Next", 4), (1, "Index", 6)]
check("level_aware_ends: deeper entries don't cut a chapter, a same-level/shallower one does",
      common.level_aware_ends(entries, 8) == [5, 3, 3, 5, 7])


# ---------- outline strategy, next-entry ends + drop + cleanup ----------

pdf = make_pdf("shallow.pdf", [
    "Contents page",
    "Chapter one body\nRunning Footer 12",
    "more chapter one\uf051",
    "Index a b c",
    "Afterword text",
], toc=[(1, "Contents", 1), (1, "Chapter\uf051 One", 2), (1, "Index", 4), (1, "Afterword", 5)])
cfg = dict(strategy="outline", levels=(1, 1), drop=["Contents", "Index"], strip_chars="\uf051",
           strip_lines=[r"Running Footer \d+"], collapse_spaces=True, structure="t")
secs = strategies.extract_outline("t", pdf, common.read_pages(pdf), cfg)
check("outline: dropped entries are not emitted", [s["title"] for s in secs] == ["Chapter One", "Afterword"])
check("outline: a dropped Index is not absorbed into the chapter before it",
      (secs[0]["start_page"], secs[0]["end_page"]) == (1, 2))
check("outline: strip_lines removes the running footer", "Running Footer" not in secs[0]["text"])
check("outline: strip_chars removes PUA glyphs from titles and text",
      "\uf051" not in secs[0]["title"] and "\uf051" not in secs[0]["text"])


# ---------- outline strategy, level-aware ends + keep + single_page + callouts ----------

pdf = make_pdf("deep.pdf", [
    "Part I divider",
    "1 Energy body\nCLINICAL INSIGHT\nbox",
    "subheading page",
    "2 Protein body",
    "About the author bio",
    "publisher ads",
], toc=[(1, "Part I", 1), (2, "1 Energy", 2), (3, "Sub heading", 3), (2, "2 Protein", 4),
        (1, "About the Author", 5)])
cfg = dict(strategy="outline", ends="level", keep=[(2, r"\d+\s+\S.*"), (1, "About the Author")],
           single_page=["About the Author"], callouts={"clinical_insight": r"(?m)^CLINICAL INSIGHT$"},
           structure="t")
secs = strategies.extract_outline("t", pdf, common.read_pages(pdf), cfg)
check("level-aware: keep filters by (level, title regex)",
      [s["title"] for s in secs] == ["1 Energy", "2 Protein", "About the Author"])
check("level-aware: a chapter spans its level-3 sub-heading", (secs[0]["start_page"], secs[0]["end_page"]) == (1, 2))
check("level-aware: single_page caps the last entry to one page", secs[2]["end_page"] == secs[2]["start_page"] == 4)
check("callouts are tagged per section",
      secs[0]["block_type"] == ["clinical_insight"] and secs[1]["block_type"] == [])

try:
    strategies.extract_outline("t", pdf, common.read_pages(pdf), dict(keep=[(9, ".*")]))
    raised = False
except ValueError:
    raised = True
check("outline: an entry that keeps nothing raises instead of silently returning []", raised)


# ---------- fixed_toc strategy ----------

pdf = make_pdf("scan.pdf", ["cover", "preface", "part divider", "ch1 a", "ch1 b", "index"])
cfg = dict(strategy="fixed_toc", toc=[("Preface", 2, True), ("Part I", 3, False), ("Chapter 1", 4, True),
                                      ("Index", 6, False)], structure="t")
secs = strategies.extract_fixed_toc("t", pdf, common.read_pages(pdf), cfg)
check("fixed_toc: kept entries only, 1-based pdf pages -> 0-based ranges",
      [(s["title"], s["start_page"], s["end_page"]) for s in secs] == [("Preface", 1, 1), ("Chapter 1", 3, 4)])


# ---------- process_source dispatch ----------

real_name = ex.SOURCES["human_nutrition_text"]["file"]
pdf = make_pdf("hn.pdf", ["ch", "a1", "x", "a2"],
               toc=[(1, "Chapter", 1), (2, "Section A", 2), (2, "Food Science and Human Nutrition Program", 2),
                    (2, "Section B", 4)])
secs, structure, fallback = ex.process_source("s1", real_name, pdf, common.read_pages(pdf))
check("process_source: a known filename runs its SOURCES entry",
      not fallback and structure == "native_outline" and [s["title"] for s in secs] == ["Section A", "Section B"])

yoga = ex.SOURCES["yoga_sutra_angot"]["file"]
check("slug_for matches an NFD-spelled filename", ex.slug_for(unicodedata.normalize("NFD", yoga)) == "yoga_sutra_angot")

try:
    ex.process_source("x", "The_Nutrition_Society_Textbook.pdf", pdf, [])
    raised = False
except ValueError:
    raised = True
check("process_source: a skipped file raises", raised)

pdf = make_pdf("unknown.pdf", [f"page {i}" for i in range(12)])
secs, structure, fallback = ex.process_source("u", "unknown.pdf", pdf, common.read_pages(pdf))
check("process_source: an unknown file goes to the generic fallback",
      fallback and structure.startswith("generic_") and secs and secs[-1]["end_page"] == 11)


# ---------- cache ----------

calls = []
v1 = common.cached_json(pdf, "u", "_t.json", lambda: calls.append(1) or {"a": 1})
v2 = common.cached_json(pdf, "u", "_t.json", lambda: calls.append(1) or {"a": 2})
check("cached_json computes once per PDF and lands under set_cache_dir()",
      v1 == v2 == {"a": 1} and len(calls) == 1 and (TMP / "cache" / "u" / "_t.json").exists())


print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All checks passed.")
