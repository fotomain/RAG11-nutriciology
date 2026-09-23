"""SOURCES: one entry per known source PDF, keyed by a stable slug (never by a slot number).

Common keys:
    file        exact filename (matched Unicode-normalised, see __init__.py)
    pages       expected page count from manual EDA
    structure   short label for the detection approach (reported alongside the sections)
    strategy    "outline" | "fixed_toc" (strategies.py), "custom" (custom/<slug>.py exposes
                extract_sections(source_key, pdf_path, pages)), or "skip"
    notes       why this book is parsed this way -- keep it: it's the EDA record

outline:    levels, ends ("next" | "level"), keep [(level|None, regex)], drop [regex], single_page
fixed_toc:  toc [(title, pdf_page_1based, keep)], text ("pages" | "ocr")
skip:       reason
cleanup (outline / fixed_toc): strip_chars, strip_text [regex], strip_lines [regex, fullmatched
            per stripped line], collapse_spaces, callouts {tag: regex}, flag (regex; pages reported)

Title regexes are FULLMATCHED against the whitespace-collapsed title, so a plain title string is
an exact match; add (?i) for case-insensitive. Adding a source: inspect the PDF (fitz get_toc() /
pdftotext -layout), add an entry here; write custom/<slug>.py only if no strategy fits.
"""

# Level-aware "N Title" chapter pattern shared by several textbooks.
_NUMBERED = r"\d+\s+\S.*"

SOURCES: dict[str, dict] = {
    "human_nutrition_text": dict(
        file="human-nutrition-text.pdf", pages=1208, structure="native_outline",
        strategy="outline", levels=(2, 2),
        drop=[r".*Food Science and Human Nutrition Program.*"],
        notes="Level 1 is just chapters/front matter; the real ~133 sections are level 2. Half of "
              "the level-2 entries are an attribution bookmark repeated after every real title on "
              "the same page -- dropped.",
    ),
    "nutrition_for_nurses": dict(
        file="Nutrition_for_Nurses-WEB_260913_200839.pdf", pages=513, structure="printed_toc",
        strategy="custom",
        notes="No outline; numbered-heading regexes hit table rows/citations. Parses the book's own "
              "printed TOC instead. See custom/nutrition_for_nurses.py.",
    ),
    "nutrition_science_everyday_application": dict(
        file="Nutrition-Science-and-Everyday-Application-1773787282.pdf", pages=649,
        structure="native_outline", strategy="outline", levels=(1, 2),
        strip_text=[r"(?im)^\s*(Adapted from|Image credit|CC BY[- ]?\w*)\b.*$"],
        flag=r"(?i)\[?interactive (element|widget|activity)\]?",
        notes="91 outline entries (17 Units + 74 chapters) taken as one flat page-ordered list: a "
              "Unit's own section is just its divider page(s). Attribution lines stripped; pages "
              "that lost an H5P interactive widget in the PDF export are flagged (content gaps).",
    ),
    "advanced_nutrition_human_metabolism": dict(
        file="Advanced_Nutrition_and_Human_Metabolism.pdf", pages=181,
        structure="regex_chapter_summary", strategy="custom",
        notes="Not the textbook: a Bookey condensed summary with no outline. See "
              "custom/advanced_nutrition_human_metabolism.py.",
    ),
    "nancy_clark_food_guide_new_runners": dict(
        file="Clark N. - Nancy Clark's Food Guide for New Runners. Getting It Right from the Start - 2009.pdf",
        pages=161, structure="native_outline", strategy="outline", levels=(1, 2),
        drop=["Contents", "Acknowledgements", "Dedication", "Index", r"(?i)Section\s+[IVXLC]+\.\s+.*"],
        strip_lines=[r"(?i)nancy\s+1-78|\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}:\d{2}\s*Uhr|Seite\s+\d+"],
        notes="16 chapters (level 2) under 4 'Section I.' Part dividers that share their first "
              "chapter's start page (would be bogus 1-page duplicates -- dropped). Boilerplate front/"
              "back matter dropped, substantive Foreword/Afterword/Resources kept. Strips a German "
              "print-shop job line repeated on every page ('nancy 1-78', date, 'HH:MM Uhr', 'Seite N').",
    ),
    "intuitive_eating": dict(
        file="Intuitive_Eating_A_Revolutionary_Program_that_Works.pdf", pages=240,
        structure="native_outline", strategy="outline", levels=(1, 2),
        drop=["Acknowledgments"], strip_chars="\uf051\uf033\u2002", collapse_spaces=True,
        notes="Teen workbook edition: level 1 chapters + level 2 'activity N' entries, no page "
              "collisions, taken flat. Two Private Use Area glyphs (U+F051 heading separator, "
              "U+F033 checkbox) render as tofu and are stripped, with the en spaces around them.",
    ),
    "krauses_food_nutrition_care_process": dict(
        file="Krauses_Food_and_the_Nutrition_Care_Process.pdf", pages=1159,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(2, _NUMBERED), (1, r"(?i)APPENDIX\s+\d+.*")],
        callouts={"clinical_insight": r"(?m)^CLINICAL INSIGHT$", "new_directions": r"(?m)^NEW DIRECTIONS$",
                  "case_study": r"(?m)^CASE STUDY$", "focus_on": r"(?m)^FOCUS ON$"},
        notes="2538 outline entries across 7 levels. Keeps 44 level-2 numbered chapters + 53 level-1 "
              "appendices; level-aware ends so chapters aren't cut at their first sub-heading (also "
              "fixes chapter 42 being nested under the wrong Part). Callout boxes named in the "
              "preface are tagged.",
    ),
    "medical_nutrition_disease_case_based": dict(
        file="Medical_Nutrition_and_Disease_A_Case_Based_Approach.pdf", pages=402,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(3, _NUMBERED), (3, r"(?i)Appendix\s+[A-Z]"), (2, "Review Questions"), (2, "Review Answers")],
        strip_chars="\u00a0\ue0a1\uf6da", collapse_spaces=True,
        notes="176 entries / 4 levels (root bookmark is 'The Nurse Practitioner's Guide to "
              "Nutrition'). Keeps level-3 chapters and lettered appendices plus the CE quiz and "
              "answer key; drops front matter, dividers, Index, CE admin forms. Strips NBSP and two "
              "rare PUA glyphs (U+E0A1 bullet, U+F6DA lost (R)). Same book as "
              "medical_nutrition_disease_vdocpub, different conversion.",
    ),
    "sports_nutrition_lab_manual": dict(
        file="Sports-Nutrition-Laboratory-Manual-Mary-P.-Miles-Stephanie-M.G.-Wilson-and-Morgan-L.-Chamberlin.pdf",
        pages=87, structure="native_outline", strategy="outline", levels=(1, 1),
        drop=["Cover", "About the Authors", "Table of Contents", "List of Figures", "List of Tables"],
        strip_lines=[r"(?i)\d*\s*Sports Nutrition:\s*Laboratory Manual\s*\d*"],
        notes="Flat 14-entry outline. Front matter dropped but Preface kept (substantive). 5 labs + "
              "3 appendices. Running footer stripped.",
    ),
    "nancy_clark_sports_nutrition_guidebook": dict(
        file="_OceanofPDF.com_Nancy_Clarks_Sports_Nutrition_Guidebook_-_Nancy_Clark.pdf", pages=537,
        structure="ocr_hardcoded_toc", strategy="fixed_toc", text="ocr",
        toc=[
            ("Preface", 8, True),
            ("Acknowledgments", 10, False),
            ("Part I divider", 12, False),
            ("Building a High-Energy Eating Plan", 14, True),
            ("Eating to Stay Healthy for the Long Run", 46, True),
            ("Breakfast: The Key to a Successful Sports Diet", 72, True),
            ("Lunch and Dinner: At Home, on the Run, and on the Road", 90, True),
            ("Between Meals: Snacking for Health and Sustained Energy", 110, True),
            ("Carbohydrate: Simplifying a Complex Topic", 122, True),
            ("Protein: Building and Repairing Muscles", 150, True),
            ("Fluids: Replacing Sweat Losses to Maintain Performance", 172, True),
            ("Part II divider", 192, False),
            ("Fueling Before Exercise", 194, True),
            ("Fueling During and After Exercise", 212, True),
            ("Supplements, Performance Enhancers, and Engineered Sports Foods", 230, True),
            ("Nutrition and Active Women", 250, True),
            ("Athlete-Specific Nutrition Advice", 264, True),
            ("Part III divider", 284, False),
            ("Assessing Your Body: Fat, Fit, or Fine?", 286, True),
            ("Gaining Weight the Healthy Way", 306, True),
            ("Losing Weight Without Starving", 322, True),
            ("Dieting Gone Awry: Eating Disorders and Food Obsessions", 346, True),
            ("Part IV divider", 368, False),
            ("Breads and Breakfasts", 370, True),
            ("Pasta, Rice, and Potatoes", 386, True),
            ("Vegetables and Salads", 404, True),
            ("Chicken and Turkey", 414, True),
            ("Fish and Seafood", 430, True),
            ("Beef and Pork", 440, True),
            ("Beans and Tofu", 448, True),
            ("Beverages and Smoothies", 464, True),
            ("Snacks and Desserts", 474, True),
            ("Appendix A: For More Information", 490, True),
            ("Appendix B: Selected References", 508, True),
            ("Index", 526, False),
            ("About the Author", 536, True),
        ],
        notes="Fully scanned: no text layer, no outline, so pages are OCR'd (Tesseract, cached). "
              "Chapter openers are white-on-black and often vanish under OCR, so boundaries come from "
              "the printed TOC transcribed by hand: PDF page = printed arabic page + 11 (roman + 1 "
              "for Preface/Acknowledgments), verified at 16 checkpoints across the book.",
    ),
    "peak_marc_bubbs": dict(
        file="_OceanofPDF.com_Peak_-_Marc_Bubbs.pdf", pages=398,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(2, r"Chapter\s+\d+:.*"), (1, "Introduction: The Revolution in Performance"),
              (1, "Conclusion"), (1, "About the Author")],
        single_page=["About the Author"],
        notes="calibre ebook, 111 entries / 3 levels. 12 chapters + Introduction/Conclusion/About "
              "the Author; drops front matter, Part dividers (1 page + epigraph) and 40 pages of "
              "Notes. About the Author is capped at 1 page: the ~8 unbookmarked pages after it are "
              "publisher ads.",
    ),
    "medical_nutrition_disease_vdocpub": dict(
        file="vdoc.pub_medical-nutrition-and-disease-a-case-based-approach.pdf", pages=607,
        structure="native_outline_pattern_filtered_appendix_page_split", strategy="custom",
        notes="Rich 548-entry outline plus two special cases (combined Review Answers, appendices "
              "split per page). See custom/medical_nutrition_disease_vdocpub.py.",
    ),
    "motivational_interviewing": dict(
        file="vdoc.pub_motivational-interviewing-in-nutrition-and-fitness.pdf", pages=290,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(2, r"\d+\.\s+\S.*"), (1, r"(?i)Appendix\s+\d+.*"), (1, "Introduction")],
        notes="33 entries / 2 levels. Keeps Introduction, 15 level-2 chapters ('N. Title') and 2 "
              "appendices; drops front matter, 5 Part dividers, References, Index.",
    ),
    "nutrition_therapy_pathophysiology": dict(
        file="vdoc.pub_nutrition-therapy-and-pathophysiology-2nd-edition.pdf", pages=1080,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(2, _NUMBERED), (2, r"(?i)Appendix\s+[A-Z].*"), (1, r"(?i)glossary")],
        notes="289 entries / 3 levels. Keeps 26 level-2 chapters, appendices A-O and the Glossary; "
              "drops front matter, PART/APPENDIXES dividers, Index.",
    ),
    "nutrition_society_textbook": dict(
        file="The_Nutrition_Society_Textbook.pdf", strategy="skip",
        reason="Drive file is a saved Anna's Archive HTML page (~569KB), not a real PDF -- no textbook "
               "content to parse. Needs an actual PDF re-uploaded before this can be processed.",
    ),
    "encyclopedia_human_nutrition_caballero": dict(
        file="Encyclopedia_of_Human_Nutrition_4th_Edition_Benjamin_Caballero.pdf", pages=2602,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(2, r".*")],
        drop=["Front Cover", "Copyright", "EDITOR BIOGRAPHIES", "PREFACE", "INDEX", "AUTHOR INDEX",
              r"ENCYCLOPEDIA OF HUMAN NUTRITION.*", r"CONTENTS OF VOLUME.*", r"CONTRIBUTORS TO VOLUME.*"],
        collapse_spaces=True,
        notes="4 volumes in one PDF, 5286 entries / 3 levels. Keeps the 245 level-2 articles; level "
              "3 sub-headings stay inside their article.",
    ),
    "encyclopedia_of_foods_mayo_clinic": dict(
        file="_OceanofPDF.com_Encyclopedia_of_foods_-_Mayo_Clinic.pdf", pages=529,
        structure="native_outline_pattern_filtered", strategy="outline", ends="level",
        keep=[(2, r".*"), (1, "Glossary"), (1, "Appendix")],
        drop=["Encyclopedia of Foods", "Copyright Page", "Table of Contents",
              "Part I: A Guide to Healthy Nutrition", "Part II: Encyclopedia of Foods", "Reading List", "Index"],
        notes="71 entries / 3 levels. Keeps 5 Part I chapters, 8 Part II food groups, Glossary and "
              "Appendix.",
    ),
    "yoga_sutra_angot": dict(
        file="Yogasutra.janvier. 2020.pdf, éd. 2021.pdf", pages=941,
        structure="custom_sutra_markers_notices", strategy="custom",
        notes="French, no outline, one section per sutra found from in-text markers. See "
              "custom/yoga_sutra_angot.py.",
    ),
}
