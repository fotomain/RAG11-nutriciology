"""
Source: _OceanofPDF.com_Encyclopedia_of_foods_-_Mayo_Clinic.pdf (529 pages).

Encyclopedia of Foods: A Guide to Healthy Nutrition (Mayo Clinic, Dole Food Company,
UCLA Center for Human Nutrition).
Native outline: 71 entries across 3 levels:
  level 1: Front matter (Title, Copyright, Table of Contents),
           Part I divider ("Part I: A Guide to Healthy Nutrition"),
           Part II divider ("Part II: Encyclopedia of Foods"),
           Glossary, Reading List, Appendix, and Index.
  level 2: Under Part I: 5 numbered chapters ("Chapter 1. Optimizing Health" ..
           "Chapter 5. Preparing Healthful Meals").
           Under Part II: 8 food group categories ("Fruits", "Vegetables", "Grains",
           "High-Protein Foods", "Dairy Foods", "Herbs & Spices", "Beverages",
           "Fats, Oils & Sweeteners").
  level 3: Subsections within individual chapters and specific food subcategories
           (e.g., Poultry, Fish, Milk, Cheese).

Kept content:
  - Level 2 chapters 1 through 5 (Part I)
  - Level 2 food group encyclopedia sections (Part II: Fruits through Fats, Oils & Sweeteners)
  - Level 1 "Glossary" and "Appendix" reference sections

Dropped content:
  - Front matter (Encyclopedia of Foods, Copyright Page, Table of Contents)
  - Part dividers (Part I, Part II)
  - Back matter (Reading List, Index)
  - Level 3 subheadings (preserved inside parent chapters/food categories)

Boundaries use level-aware compute_end: a section ends before the next entry
whose level <= its own level, ensuring chapters and food categories remain intact
without spilling into part dividers or adjacent categories.
"""
import re
from pathlib import Path

FILENAME = "_OceanofPDF.com_Encyclopedia_of_foods_-_Mayo_Clinic.pdf"
EXPECTED_PAGES = 529
STRUCTURE = "native_outline_pattern_filtered"

_DROP_TITLES_EXACT = {
    "Encyclopedia of Foods",
    "Copyright Page",
    "Table of Contents",
    "Part I: A Guide to Healthy Nutrition",
    "Part II: Encyclopedia of Foods",
    "Reading List",
    "Index",
}

_KEEP_LEVEL1 = {"Glossary", "Appendix"}


def _clean_title(title: str) -> str:
    return " ".join(title.strip().split())


def _is_keep(lvl: int, title: str) -> bool:
    t = title.strip()
    if t in _DROP_TITLES_EXACT:
        return False
    if lvl == 2:
        return True
    if lvl == 1 and t in _KEEP_LEVEL1:
        return True
    return False


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    import fitz

    with fitz.open(pdf_path) as doc:
        toc = doc.get_toc(simple=True)
        n_pages = doc.page_count

    full_entries = sorted(
        ((lvl, _clean_title(title), page - 1) for lvl, title, page in toc),
        key=lambda e: e[2],
    )

    def compute_end(i: int) -> int:
        lvl = full_entries[i][0]
        for j in range(i + 1, len(full_entries)):
            if full_entries[j][0] <= lvl:
                return full_entries[j][2] - 1
        return n_pages - 1

    sections = []
    n_dropped = 0
    n_chapters = 0
    n_food_cats = 0
    n_reference = 0

    for i, (lvl, title, start) in enumerate(full_entries):
        if not _is_keep(lvl, title):
            if lvl <= 2:
                n_dropped += 1
            continue
        end = max(compute_end(i), start)
        body = "\n\n".join(pages[start:end + 1]).strip()
        sections.append({
            "title": title,
            "level": lvl,
            "start_page": start,
            "end_page": end,
            "text": body,
            "block_type": [],
        })
        if title.startswith("Chapter"):
            n_chapters += 1
        elif title in _KEEP_LEVEL1:
            n_reference += 1
        else:
            n_food_cats += 1

    print(f"[{source_key}] {n_chapters} chapters + {n_food_cats} food categories + "
          f"{n_reference} reference section(s) kept ({n_dropped} front-matter/part-divider/index entries dropped)")
    return sections
