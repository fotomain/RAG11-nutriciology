"""
Source: The_Nutrition_Society_Textbook.pdf ("Introduction to Human
Nutrition (The Nutrition Society Textbook)")

BROKEN DOWNLOAD -- this is not a real PDF. The file living under this name
in the Drive folder is actually a 569KB saved HTML page (title:
"Introduction to Human Nutrition (The Nutrition Society Textbook) - Anna's
Archive") -- someone saved a shadow-library book-info page instead of the
book itself. There is no PDF structure, outline, or extractable text to
build a section-detection algorithm against, and this pipeline does not
fetch copyrighted books from shadow-library sites, so there's nothing
legitimate to substitute either.

Marked SKIPPED via SKIP_REASON below instead of getting a real
extract_sections(): stage1_1_eda_packages/__init__.py collects every
module's SKIP_REASON into SKIPPED_FILENAMES, and the notebook's Drive-
listing cell filters those filenames out entirely before SOURCES is built.
So this file is never downloaded/paged/chunked and never occupies a
source-slot number -- it's as if it weren't in the folder at all, until
fixed.

To un-skip: replace the Drive file with an actual PDF of the book, delete
SKIP_REASON below, and add the real FILENAME/EXPECTED_PAGES/STRUCTURE/
extract_sections() (same contract as every other sourceN module, see
stage1_1_eda_packages/__init__.py's docstring) -- it'll then need to move
from _SKIPPED_MODULES to _MODULES in __init__.py too.
"""

FILENAME = "The_Nutrition_Society_Textbook.pdf"
SKIP_REASON = (
    "Drive file is a saved Anna's Archive HTML page (~569KB), not a real "
    "PDF -- no textbook content to parse. Needs an actual PDF re-uploaded "
    "to Drive before this can be processed."
)
