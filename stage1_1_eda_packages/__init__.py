"""
Per-source section-detection algorithms for stage1_1_extract_and_chunk.ipynb.

Each sibling module handles exactly one source PDF, matched by its exact
FILENAME (not by its source1/2/.../sourceN slot -- that slot depends on the
Drive folder's own listing order and on new files being added, see
stage1_1_extract_and_chunk.ipynb's config cell). Every normal module
exports:

    FILENAME        -- exact filename as it appears in the Drive folder
    EXPECTED_PAGES  -- page count from manual EDA, or None if unknown
    STRUCTURE       -- short label describing the detection strategy
    extract_sections(source_key, pdf_path, pages) -> list[dict]
                       the actual algorithm. Each returned dict has
                       title/level/start_page/end_page/text, and optionally
                       block_type (a list of callout-box tags found in it).

To add a new source: drop the PDF in GOOGLE_DRIVE_SOURCES_FOLDER, inspect
it (pdfinfo/qpdf --json for an outline, pdftotext -layout for the raw
text) the way every module's docstring here documents, write a new
sourceN_<slug>.py module with those four names, import it below, and add
it to _MODULES. The notebook's "Assemble sections" cell will then dispatch
to it automatically by filename -- nothing else needs to change.

A file that turns out NOT to be usable at all (e.g. a broken download that
isn't really a PDF) gets a module too, but a minimal one exporting just
FILENAME and SKIP_REASON (a short string explaining why) instead of the
four names above -- see source10_nutrition_society_textbook.py. Such
modules go in _SKIPPED_MODULES, not _MODULES. SKIPPED_FILENAMES (built
below) is read by the notebook's Drive-listing cell to filter those
filenames out entirely before SOURCES is built, so a known-broken file
never occupies a source-slot number or gets downloaded/paged/chunked.
"""
from . import source1_human_nutrition_text as _source1
from . import source2_nutrition_for_nurses as _source2
from . import source3_nutrition_science_everyday_application as _source3
from . import source4_advanced_nutrition_human_metabolism as _source4
from . import source5_nancy_clark_food_guide_new_runners as _source5
from . import source6_intuitive_eating as _source6
from . import source7_krauses_food_nutrition_care_process as _source7
from . import source8_medical_nutrition_disease_case_based as _source8
from . import source9_sports_nutrition_lab_manual as _source9
from . import source10_nancy_clark_sports_nutrition_guidebook as _source10
from . import source11_peak_marc_bubbs as _source11
from . import source12_medical_nutrition_disease_vdocpub as _source12
from . import source13_motivational_interviewing as _source13
from . import source14_nutrition_therapy_pathophysiology as _source14
from . import source16_encyclopedia_human_nutrition_caballero as _source16
from . import source17_encyclopedia_of_foods_mayo_clinic as _source17
from . import source10_nutrition_society_textbook as _source_nst_skip

_MODULES = [
    _source1, _source2, _source3, _source4, _source5, _source6, _source7,
    _source8, _source9, _source10, _source11, _source12, _source13, _source14,
    _source16, _source17,
]

_SKIPPED_MODULES = [_source_nst_skip]

FILENAME_PROCESSORS = {m.FILENAME: m.extract_sections for m in _MODULES}

KNOWN_SOURCE_EDA_META = {
    m.FILENAME: {"expected_pages": m.EXPECTED_PAGES, "structure": m.STRUCTURE}
    for m in _MODULES
}

SKIPPED_FILENAMES = {m.FILENAME: m.SKIP_REASON for m in _SKIPPED_MODULES}
