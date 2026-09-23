"""Per-source section detection: split a source PDF into parent sections (chapters, articles,
sutras...) before chunking.

Most books are handled by config alone -- an entry in sources.py that a generic strategy in
strategies.py runs (outline slicing, or a hand-transcribed TOC). Only books no strategy fits have
code, in custom/<slug>.py. A PDF with no entry at all goes to generic_fallback.py (outline ->
font-size headings -> fixed page windows).

    process_source(source_key, filename, pdf_path, pages) -> (sections, structure, used_fallback)
    SKIPPED_FILENAMES   {filename: reason} -- filter these out before processing
    KNOWN_SOURCE_EDA_META {filename: {"slug", "expected_pages", "structure"}}
    read_pages(pdf_path) -- native text layer, the usual `pages` argument
    set_cache_dir(path)  -- where OCR / whole-book scans are cached (default: next to the PDF)

Each section: title, level, start_page, end_page (0-based, inclusive), text, block_type (tags).

Modules:
    sources          -- SOURCES: the per-source config table (+ EDA notes)
    strategies       -- extract_outline(), extract_fixed_toc(): run a config entry
    common           -- outline reading, boundary rules, page text / OCR, JSON cache
    generic_fallback -- extract_sections_with_strategy() for unknown PDFs
    custom/          -- nutrition_for_nurses, advanced_nutrition_human_metabolism,
                        medical_nutrition_disease_vdocpub, yoga_sutra_angot
"""
from __future__ import annotations

import importlib
import unicodedata
from pathlib import Path

from .common import read_pages, set_cache_dir
from .generic_fallback import extract_sections_with_strategy as _generic_extract
from .sources import SOURCES
from .strategies import STRATEGIES

__all__ = ["SOURCES", "SKIPPED_FILENAMES", "KNOWN_SOURCE_EDA_META", "slug_for", "process_source",
           "read_pages", "set_cache_dir"]


def _nfc(name: str) -> str:
    # macOS / Drive often hand back NFD names ("e" + combining accent) for a file spelled NFC here
    return unicodedata.normalize("NFC", name)


_BY_FILENAME = {_nfc(cfg["file"]): slug for slug, cfg in SOURCES.items()}

SKIPPED_FILENAMES = {_nfc(c["file"]): c["reason"] for c in SOURCES.values() if c["strategy"] == "skip"}

KNOWN_SOURCE_EDA_META = {
    _nfc(c["file"]): {"slug": slug, "expected_pages": c.get("pages"), "structure": c.get("structure")}
    for slug, c in SOURCES.items() if c["strategy"] != "skip"
}


def slug_for(filename: str) -> str | None:
    return _BY_FILENAME.get(_nfc(filename))


def process_source(source_key: str, filename: str, pdf_path, pages: list[str]) -> tuple[list[dict], str, bool]:
    """Dispatch to the filename's SOURCES entry, else the generic fallback.
    Returns (sections, structure_label, used_fallback)."""
    pdf_path = Path(pdf_path)
    slug = slug_for(filename)
    if slug is None:
        sections, strategy = _generic_extract(source_key, pdf_path, pages)
        return sections, strategy, True

    cfg = SOURCES[slug]
    kind = cfg["strategy"]
    if kind == "skip":
        raise ValueError(f"{filename} is marked skip: {cfg['reason']}")
    if kind == "custom":
        module = importlib.import_module(f".custom.{slug}", __name__)
        sections = module.extract_sections(source_key, pdf_path, pages)
    else:
        sections = STRATEGIES[kind](source_key, pdf_path, pages, cfg)
    return sections, cfg["structure"], False
