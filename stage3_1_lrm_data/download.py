#!/usr/bin/env python3
"""LRM stage 3.1 step 0: download every PDF of LRM_SOURCES_FOLDER (Google Drive, from .env) into input/<lang>/.
The language (fr/en/ru) is detected from the PDF's text. Already-present files are skipped."""
import os
import re
import sys
from pathlib import Path

import fitz
import gdown
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")
FR = {"le", "la", "les", "des", "et", "est", "dans", "pour", "que", "une"}
EN = {"the", "and", "of", "to", "is", "in", "that", "for", "with", "are"}


def detect(pdf: Path) -> str:
    doc = fitz.open(str(pdf))
    text = " ".join(doc[i].get_text() for i in range(min(len(doc), 60)))
    if len(re.findall(r"[Ѐ-ӿ]", text)) > 200:
        return "ru"
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    fr, en = sum(w in FR for w in words), sum(w in EN for w in words)
    return "fr" if fr > en else "en"


def main() -> int:
    url = os.getenv("LRM_SOURCES_FOLDER", "")
    m = re.search(r"folders/([\w-]+)", url) or re.fullmatch(r"([\w-]+)", url)
    if not m:
        print("Set LRM_SOURCES_FOLDER in .env (a Google Drive folder link)")
        return 1
    tmp = HERE / "input" / "_download"
    files = gdown.download_folder(id=m.group(1), output=str(tmp), quiet=True, use_cookies=False) or []
    for f in map(Path, files):
        if f.suffix.lower() != ".pdf":
            continue
        dest = HERE / "input" / detect(f) / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            f.unlink()
        else:
            f.rename(dest)
            print("downloaded", dest.relative_to(HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
