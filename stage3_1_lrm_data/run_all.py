#!/usr/bin/env python3
"""LRM stage 3.1 driver: for every PDF in input/<lang>/, recognise it (Gemini, word boxes), then translate it into the
languages that have no PDF of their own for that source key. Idempotent: existing pages are skipped.

    python stage3_1_lrm_data/run_all.py [--start N --end M] [--force]
The page limit comes from MAX_NUMBER_OF_PAGES_TO_USE in .env (default 100, NONE = whole book)."""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import recognize as rc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    span = [x for k, v in (("--start", a.start), ("--end", a.end)) for x in (k, str(v)) if v is not None]
    if a.force:
        span.append("--force")

    langs = list(rc.LANGS)
    sources: dict[str, dict[str, Path]] = {}
    for lang in langs:
        for pdf in sorted((HERE / "input" / lang).glob("*.pdf")):
            sources.setdefault(rc.slug(pdf.stem), {})[lang] = pdf
    if not sources:
        print("No PDFs in stage3_1_lrm_data/input/<lang>/ (fr, en, ru). Put the downloaded Drive files there.")
        return 1

    for key, pdfs in sources.items():
        for lang, pdf in pdfs.items():
            print(f"== recognise {key} [{lang}]")
            if subprocess.call([sys.executable, str(HERE / "recognize.py"), "--pdf", str(pdf), "--lang", lang, *span]):
                return 2
        src_lang = next(l for l in langs if l in pdfs)
        missing = [l for l in langs if l not in pdfs]
        if missing:
            print(f"== translate {key} {src_lang} -> {missing}")
            if subprocess.call([sys.executable, str(HERE / "translate.py"), "--source-key", key, "--pdf", str(pdfs[src_lang]),
                                "--from", src_lang, "--lang", *missing, *span]):
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
