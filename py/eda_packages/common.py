"""
Shared helpers used by more than one source's extraction algorithm.
"""
import signal
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber  # table extraction only -- see extract_page_range_tables()


class _PageTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise _PageTimeout()


def extract_page_range_tables(
    pdf_path: Path, start_page: int, end_page: int, per_page_timeout: int = 15
) -> list[str]:
    """
    Extract every table pdfplumber finds on pages [start_page, end_page]
    (0-based, inclusive) as a compact markdown-table string, one entry per
    detected table. Used for reference/encyclopedia-style sources whose
    nutrient/data tables shouldn't be flattened into prose child chunks
    (see source15/source16's docstrings) -- pdfplumber's own table-grid
    detection is far more reliable on real-world PDFs than trying to
    reconstruct row/column structure from fitz's plain extracted text.

    pdfplumber's underlying layout analysis (pdfminer) can pathologically
    hang on a small minority of real pages -- confirmed directly against
    this project's own PDFs, where a single page's extract_text() alone
    never returned. Each page therefore gets a hard wall-clock budget via
    SIGALRM (Unix only, fine for this project's macOS/Linux targets): a
    page that blows its budget is skipped with a warning instead of
    hanging the whole notebook run. Every other page's tables still come
    through normally -- one slow page is not worth losing the run over.

    Only imported here, not in every module, so sources that never call
    this don't need to think about it. Returns [] on pages with no
    detectable table (most pages -- this is the common case, not an error).
    """
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages[start_page:end_page + 1], start=start_page):
            old_handler = signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(per_page_timeout)
            try:
                tables = page.extract_tables()
            except Exception as e:
                # pdfminer's own object-stream parsing frequently catches a
                # broad Exception internally and re-raises a DIFFERENT
                # wrapped exception (confirmed directly: the SIGALRM-raised
                # _PageTimeout below came back out as a pdfplumber
                # PdfminerException instead), so this can't reliably
                # isinstance()-check for _PageTimeout specifically. Treat
                # ANY exception while this page's alarm is armed as "skip
                # this one page" -- a malformed/slow page is not worth
                # losing the whole run over, and every other page is
                # unaffected.
                print(f"  [extract_page_range_tables] page {page_no} failed or "
                      f"exceeded {per_page_timeout}s ({type(e).__name__}), "
                      "skipped")
                continue
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            for table in tables:
                rows = [[(cell or "").strip() for cell in row] for row in table]
                rows = [r for r in rows if any(r)]
                if len(rows) < 2:
                    continue  # a single-row "table" is just noise, not data
                header, *body = rows
                width = len(header)
                lines = [
                    "| " + " | ".join(header) + " |",
                    "| " + " | ".join(["---"] * width) + " |",
                ]
                for r in body:
                    r = (r + [""] * width)[:width]
                    lines.append("| " + " | ".join(r) + " |")
                out.append("\n".join(lines))
    return out


def sections_from_outline(
    pdf_path: Path, source_key: str, min_level: int = 1, max_level: int = 1
) -> list[dict]:
    """
    Build sections from a PDF's own outline/bookmark tree.

    Each returned dict has title/level/start_page/end_page (0-based,
    end-inclusive) -- the caller fills in "text" itself from its own
    `pages` list, since some sources need per-page cleanup (attribution
    stripping, H5P-gap flagging, ...) before joining pages into a section
    body, and others don't.
    """
    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
        n_pages = doc.page_count

    entries = [(lvl, title, page - 1) for lvl, title, page in toc if min_level <= lvl <= max_level]

    sections = []
    for i, (lvl, title, start) in enumerate(entries):
        end = entries[i + 1][2] - 1 if i + 1 < len(entries) else n_pages - 1
        end = max(end, start)
        sections.append({"title": title.strip(), "level": lvl, "start_page": start, "end_page": end})

    print(f"[{source_key}] {len(sections)} sections from outline (levels {min_level}-{max_level})")
    return sections
