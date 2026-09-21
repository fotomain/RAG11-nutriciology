"""Offline test for stage1_1_eda_packages.generic_fallback using tiny synthetic PDFs.
Run: .venv/bin/python test_stage1_generic_fallback.py"""
import sys
import tempfile
from pathlib import Path

import fitz

sys.path.insert(0, ".")
from stage1_1_eda_packages import process_source  # noqa: E402

failures = []


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        failures.append(name)


def make_pdf(path, pages, toc=None):
    doc = fitz.open()
    for heading, body in pages:
        page = doc.new_page()
        y = 72
        if heading:
            page.insert_text((72, y), heading, fontsize=22)
            y += 40
        for i in range(30):
            page.insert_text((72, y + i * 14), body + f" line {i}", fontsize=11)
    if toc:
        doc.set_toc(toc)
    doc.save(path)
    doc.close()


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    pdf_dir = root / "stage1_eda_input" / "source1"
    pdf_dir.mkdir(parents=True)

    # 1) headings by font size: 8 chapters, one per page, plus a lowercase-start noise line ignored
    pdf = pdf_dir / "fonts.pdf"
    make_pdf(pdf, [(f"Chapter {i}", "body text") for i in range(1, 9)])
    pages = [f"page {i} text" for i in range(8)]
    secs, strat, fb = process_source("source1", "fonts.pdf", pdf, pages)
    check("font headings: strategy", strat == "generic_font_headings" and fb)
    check("font headings: 8 sections titled Chapter N", [s["title"] for s in secs] == [f"Chapter {i}" for i in range(1, 9)])
    check("font headings: text joined from pages", secs[0]["text"] == "page 0 text")
    check("font headings: cache written", (root / "stage1_eda_output" / "source1" / "_cache_headings.json").exists())

    # 2) outline wins when present
    pdf2 = pdf_dir / "outline.pdf"
    make_pdf(pdf2, [(None, "plain")] * 12, toc=[[1, f"Part {i}", 1 + i * 2] for i in range(6)])
    secs, strat, _ = process_source("source1", "outline.pdf", pdf2, ["t"] * 12)
    check("outline: strategy + 6 sections", strat == "generic_outline" and len(secs) == 6)

    # 3) nothing to detect -> page windows, oversized sections split
    pdf3 = pdf_dir / "plain.pdf"
    make_pdf(pdf3, [(None, "plain")] * 25)
    secs, strat, _ = process_source("source1", "plain.pdf", pdf3, ["t"] * 25)
    check("windows: 3 sections of <=10 pages", strat == "generic_page_windows" and len(secs) == 3
          and secs[-1]["end_page"] == 24)

    pdf4 = pdf_dir / "big.pdf"
    make_pdf(pdf4, [(None, "plain")] * 5, toc=[[1, "Only", 1]])
    secs, strat, _ = process_source("source1", "big.pdf", pdf4, ["t"] * 5)
    check("too few outline entries -> falls through to page windows", strat == "generic_page_windows")

    # 4) known filename still uses its dedicated module (no fallback)
    from stage1_1_eda_packages import FILENAME_PROCESSORS
    check("registered modules still registered", len(FILENAME_PROCESSORS) >= 16)

print("\nAll checks passed." if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
