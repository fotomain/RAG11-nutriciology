#!/usr/bin/env python3
"""LRM stage 3.1b: recognised source-language pages -> other languages, layout preserved. Thin
wrapper -- all the actual logic (per-page translation, PDF layout, PDF->JSON extraction) is
reusable_code.eda.translate; this script only parses args and points it at this stage's
input/output directories.

    python lrm/eda1_extract/translate.py --source-key book --pdf input/fr/book.pdf --from fr --lang en ru [--start 1 --end 100]

Output per language: lrm/eda1_extract/output/<lang>/<source_key>/{json,pages,pdf,cache}/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

STAGE = Path(__file__).resolve().parent  # py/lrm/eda1_extract/ (input/, output/)
ROOT = STAGE.parent.parent  # py/
sys.path.insert(0, str(ROOT))

from reusable_code.eda import recognize as rc  # noqa: E402
from reusable_code.eda import translate as tr  # noqa: E402

rc.set_stage_dir(STAGE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-key", required=True)
    ap.add_argument("--from", dest="src_lang", default="fr", help="language the source pages were recognised in")
    ap.add_argument("--pdf", type=Path, required=True, help="the source-language PDF (page size / fonts)")
    ap.add_argument("--lang", nargs="+", default=["en", "ru"])
    ap.add_argument("--start", type=int, help="default: START_PAGE_NUMBER from .env, else 1")
    ap.add_argument("--end", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model", default=rc.DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true", help="re-translate even if cached")
    ap.add_argument("--render-only", action="store_true", help="re-layout from cached translations (no API calls)")
    args = ap.parse_args()

    failed = tr.translate_source(args.pdf, args.source_key, args.src_lang, args.lang, start=args.start, end=args.end,
                                 workers=args.workers, model=args.model, force=args.force, render_only=args.render_only)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
