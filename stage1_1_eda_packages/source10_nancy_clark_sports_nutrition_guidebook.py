"""
Source: _OceanofPDF.com_Nancy_Clarks_Sports_Nutrition_Guidebook_-_Nancy_Clark.pdf
(Nancy Clark's Sports Nutrition Guidebook, 6th ed., Human Kinetics, 537
pages, "Google Books PDF Converter" scan).

FULLY SCANNED, ZERO EMBEDDED TEXT -- unlike every other source registered so
far, this PDF has no text layer at all: `pdffonts` reports no fonts, and
every page is a JBIG2/JPEG scanned image (confirmed with `pdfimages -list`
and by running `pdftotext` -- it returns 537 completely empty pages). fitz's
`page.get_text("text")` (what the notebook's `extract_pages()` cell relies
on for every other source) also returns "" for all 537 pages, and there's
no native outline either (`fitz.get_toc()` / `pypdf`'s `.outline` are both
empty). None of the previous strategies -- outline slicing, TOC-regex over
real extracted text -- have anything to work with here.

WHAT THIS MODULE DOES INSTEAD: it OCRs the book itself. `_ocr_all_pages()`
below rasterizes each page with fitz (`page.get_pixmap()`, already a
dependency -- no extra system tool needed for rendering) and runs Tesseract
over the image via `pytesseract` (added to requirements.txt; the Tesseract
OCR *engine* itself is a separate system install, e.g. `brew install
tesseract` on macOS / `apt install tesseract-ocr` on Linux -- pytesseract is
just a thin Python wrapper around that binary and does nothing without it).
Results are cached to
`stage1_eda_output/<source_key>/_ocr_pages_cache.json` (a sibling of the
notebook's own `_cache_pages.json`, same idea) so the expensive part -- OCR
of ~530 image pages -- only ever runs once; expect several minutes the
first time, then near-instant.

WHY THE SECTION BOUNDARIES ARE A HARDCODED TABLE, NOT A RUNTIME REGEX: the
obvious approach -- OCR every page, then regex-search the OCR text for
"CHAPTER N" headings -- turned out to be unreliable in testing. Several
chapter-opener headings in this book are printed as white text on a solid
black rectangle (a design choice), and Tesseract silently drops that text
under ordinary binarization instead of misreading it -- so the heading a
regex would be searching for sometimes just isn't in the OCR output for an
otherwise perfectly OCR'able page. Hunting for a heading that may or may not
survive OCR, per page, per run, is a worse foundation than using information
that's already exact: the book's own printed table of contents (pdf pages
5-6), which lists every chapter/appendix with its PRINTED page number.

_TOC below is that table of contents, transcribed by hand from the OCR'd
contents pages (not parsed by a runtime regex -- the OCR text has enough
noise, mid-title line wraps, and stray punctuation from stylized numerals
that a general parser would be fragile and no more trustworthy than reading
it once and hardcoding it, the same way e.g. source1's attribution bookmark
or source5/8/9's DROP_TITLES sets are hand-identified constants specific to
one book), with each entry's PRINTED page number already converted to its
actual PDF page number using a fixed, independently-verified offset:

    PDF page = printed arabic page number + 11      (Part I divider onward)
    PDF page = printed roman-numeral page number + 1 (Preface, Acknowledgments)

Both offsets were verified directly against the real scanned page images
(not just trusted from the TOC) at 16 independent checkpoints spread across
the whole book -- every kept chapter/appendix opener, the Part divider
pages, the Index, and About the Author, from printed page 1 all the way to
printed page 525 out of ~526 -- and held exactly everywhere, including a
dedicated check that the four one-line "PART N" divider pages (which have no
chapter content of their own) sit exactly 2 pages before their first child
chapter (divider, then a blank verso, then the chapter) at all 4 occurrences.

Kept: Preface (substantive -- explains the book's purpose, not an
administrative blurb, same call as source5/9's Foreword/Preface), all 26
numbered chapters, both appendices, About the Author. Dropped:
Acknowledgments (boilerplate), the 4 "PART N" divider pages (no standalone
content), and the Index (an alphabetical locator, not prose). Boundaries are
computed against the FULL table (including dropped entries) before
filtering -- same "don't let a dropped entry's pages bleed into whichever
kept section precedes it" reasoning as source5/9 -- which is exactly what
correctly excludes each Part divider + its blank verso from the end of the
previous chapter. Note: because the very last entry (About the Author) is
followed by nothing, its kept range runs through the book's final page,
which turns out to be a one-page "find more resources" publisher blurb
after the actual author bio -- a small, unavoidable tail no different in
kind from similar back-matter slack accepted in other sources.
"""
import io
import json
from pathlib import Path

FILENAME = "_OceanofPDF.com_Nancy_Clarks_Sports_Nutrition_Guidebook_-_Nancy_Clark.pdf"
EXPECTED_PAGES = 537
STRUCTURE = "ocr_hardcoded_toc"  # no text layer at all; OCR'd, boundaries from a hand-transcribed + offset-verified printed TOC

# (title, pdf_page_1indexed, keep) -- see module docstring for how the PDF
# page numbers were derived and verified. Order matches the book's own
# table of contents / physical page order.
_TOC = [
    ("Preface", 8, True),
    ("Acknowledgments", 10, False),                                    # boilerplate
    ("Part I divider", 12, False),                                     # no standalone content
    ("Building a High-Energy Eating Plan", 14, True),
    ("Eating to Stay Healthy for the Long Run", 46, True),
    ("Breakfast: The Key to a Successful Sports Diet", 72, True),
    ("Lunch and Dinner: At Home, on the Run, and on the Road", 90, True),
    ("Between Meals: Snacking for Health and Sustained Energy", 110, True),
    ("Carbohydrate: Simplifying a Complex Topic", 122, True),
    ("Protein: Building and Repairing Muscles", 150, True),
    ("Fluids: Replacing Sweat Losses to Maintain Performance", 172, True),
    ("Part II divider", 192, False),
    ("Fueling Before Exercise", 194, True),
    ("Fueling During and After Exercise", 212, True),
    ("Supplements, Performance Enhancers, and Engineered Sports Foods", 230, True),
    ("Nutrition and Active Women", 250, True),
    ("Athlete-Specific Nutrition Advice", 264, True),
    ("Part III divider", 284, False),
    ("Assessing Your Body: Fat, Fit, or Fine?", 286, True),
    ("Gaining Weight the Healthy Way", 306, True),
    ("Losing Weight Without Starving", 322, True),
    ("Dieting Gone Awry: Eating Disorders and Food Obsessions", 346, True),
    ("Part IV divider", 368, False),
    ("Breads and Breakfasts", 370, True),
    ("Pasta, Rice, and Potatoes", 386, True),
    ("Vegetables and Salads", 404, True),
    ("Chicken and Turkey", 414, True),
    ("Fish and Seafood", 430, True),
    ("Beef and Pork", 440, True),
    ("Beans and Tofu", 448, True),
    ("Beverages and Smoothies", 464, True),
    ("Snacks and Desserts", 474, True),
    ("Appendix A: For More Information", 490, True),
    ("Appendix B: Selected References", 508, True),
    ("Index", 526, False),                                             # locator, not prose
    ("About the Author", 536, True),
]


def _compute_boundaries(n_pages: int) -> list[dict]:
    """0-indexed [start_page, end_page] for every _TOC entry, computed
    against the FULL (unfiltered) table so a dropped entry's pages are
    correctly excluded from the kept entry before it, not absorbed into it.
    """
    out = []
    for i, (title, pdf_page_1idx, keep) in enumerate(_TOC):
        start = pdf_page_1idx - 1
        if i + 1 < len(_TOC):
            end = _TOC[i + 1][1] - 1 - 1
        else:
            end = n_pages - 1
        out.append({"title": title, "start_page": start, "end_page": end, "keep": keep})
    return out


def _ocr_all_pages(source_key: str, pdf_path: Path, n_pages: int) -> list[str]:
    """OCR every page of a text-less scanned PDF via fitz rasterization +
    Tesseract, caching the result so this only ever runs once per source.
    """
    import fitz  # PyMuPDF -- already a pipeline dependency, used here just to rasterize
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            f"[{source_key}] this source has no text layer at all and needs OCR, which "
            "needs `pytesseract` and `Pillow` (pip install pytesseract pillow -- see "
            "requirements.txt) AND the Tesseract OCR engine itself installed system-side "
            "(pytesseract is just a wrapper around that binary): `brew install tesseract` "
            "on macOS, `apt install tesseract-ocr` on Linux."
        ) from e

    cache_path = pdf_path.parents[2] / "stage1_eda_output" / source_key / "_ocr_pages_cache.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if len(cached) == n_pages:
            print(f"[{source_key}] using cached OCR text for all {n_pages} pages -> {cache_path}")
            return cached
        print(f"[{source_key}] OCR cache page count mismatch ({len(cached)} != {n_pages}), re-OCRing")

    print(f"[{source_key}] this PDF has no text layer (a scanned book, confirmed by manual "
          f"EDA) -- OCRing all {n_pages} pages now. One-time cost, cached afterward; this "
          "can take several minutes depending on your machine.")
    ocr_pages = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_pages.append(pytesseract.image_to_string(img, config="--psm 6"))
            if (i + 1) % 50 == 0 or (i + 1) == n_pages:
                print(f"[{source_key}] OCR progress: {i + 1}/{n_pages} pages")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(ocr_pages, ensure_ascii=False), encoding="utf-8")
    print(f"[{source_key}] OCR complete, cached -> {cache_path}")
    return ocr_pages


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    # `pages` (fitz's native text extraction, done by the notebook before
    # calling us) is 537 empty strings for this source -- there's no text
    # layer for it to find -- so it's intentionally ignored here in favor
    # of this module's own OCR pass.
    import fitz
    with fitz.open(pdf_path) as doc:
        n_pages = doc.page_count

    ocr_pages = _ocr_all_pages(source_key, pdf_path, n_pages)
    boundaries = _compute_boundaries(n_pages)

    kept = []
    n_dropped = 0
    for b in boundaries:
        if not b["keep"]:
            n_dropped += 1
            continue
        text = "\n\n".join(
            ocr_pages[p] for p in range(b["start_page"], b["end_page"] + 1)
        ).strip()
        kept.append({
            "title": b["title"],
            "level": 1,
            "start_page": b["start_page"],
            "end_page": b["end_page"],
            "text": text,
            "block_type": [],
        })

    print(f"[{source_key}] {len(kept)} sections kept (Preface + 26 chapters + 2 appendices "
          f"+ About the Author) from OCR'd, hand-verified TOC page mapping, dropped "
          f"{n_dropped} entries (Acknowledgments + 4 Part dividers + Index)")
    return kept
