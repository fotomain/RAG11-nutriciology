"""LRM stage 3.1 step 0 engine: download every PDF of LRM_SOURCES_FOLDER (Google Drive, from
.env) into a stage's input/<lang>/. The language (fr/en/ru) is detected from the PDF's text.
Already-present files are skipped.

Thin CLI wrapper: py/lrm/eda1_extract/download.py (calls download_sources() below).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import fitz
import gdown

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


def download_sources(input_dir: Path) -> list[Path]:
    """Download every PDF from LRM_SOURCES_FOLDER (.env) into input_dir/<lang>/, skipping files
    already present there. Returns the newly downloaded destination paths."""
    url = os.getenv("LRM_SOURCES_FOLDER", "")
    m = re.search(r"folders/([\w-]+)", url) or re.fullmatch(r"([\w-]+)", url)
    if not m:
        raise SystemExit("Set LRM_SOURCES_FOLDER in .env (a Google Drive folder link)")
    tmp = input_dir / "_download"
    files = gdown.download_folder(id=m.group(1), output=str(tmp), quiet=True, use_cookies=False) or []
    downloaded = []
    for f in map(Path, files):
        if f.suffix.lower() != ".pdf":
            continue
        dest = input_dir / detect(f) / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            f.unlink()
        else:
            f.rename(dest)
            downloaded.append(dest)
    return downloaded
