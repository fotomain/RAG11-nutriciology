#!/usr/bin/env python3
"""LRM stage 3.1a: scholarly PDF -> static per-page JSON (page -> block -> word bbox) + page PNGs
via an LLM vision call. Thin wrapper -- all the actual logic (build_page, refine_page, link_book,
the OCR-provider dispatch) is reusable_code.eda.recognize; this script only parses args and points
it at this stage's input/output directories.

    python lrm/eda1_extract/recognize.py --pdf input/fr/book.pdf --lang fr [--start 1 --end 100]

The page limit defaults to MAX_NUMBER_OF_PAGES_TO_USE from .env (a number, or NONE for the whole book).
OCR_PROVIDER_NAME in .env selects the vision backend: ocr_with_google (default) or ocr_with_aws.
See reusable_code.eda.recognize for output paths and the full docstring.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

STAGE = Path(__file__).resolve().parent  # py/lrm/eda1_extract/ (input/, output/)
ROOT = STAGE.parent.parent  # py/
sys.path.insert(0, str(ROOT))

from reusable_code.eda import recognize as rc  # noqa: E402

rc.set_stage_dir(STAGE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--lang", required=True, choices=list(rc.LANGS))
    ap.add_argument("--start", type=int, help="default: START_PAGE_NUMBER from .env, else 1")
    ap.add_argument("--end", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model", default=rc.DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true", help="redo pages that already exist")
    ap.add_argument("--refine-only", action="store_true", help="re-snap boxes of existing pages (no API calls)")
    ap.add_argument("--link-only", action="store_true", help="only rebuild LRM links + index")
    args = ap.parse_args()

    rc.SRC_PDF = args.pdf
    rc.configure(args.lang, rc.slug(args.pdf.stem))
    rc.JSON_DIR.mkdir(parents=True, exist_ok=True)
    rc.IMG_DIR.mkdir(parents=True, exist_ok=True)

    if args.link_only:
        print("linked pages:", rc.link_book())
        return 0
    if args.refine_only:
        rc.refine_all(args.pdf)
        return 0

    failed = rc.recognise_pdf(args.pdf, start=args.start, end=args.end, workers=args.workers,
                              model=args.model, force=args.force)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
