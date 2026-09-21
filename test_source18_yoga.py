"""Tests for stage1_1_eda_packages/source18_yoga_sutra_angot.py.
Unit tests run offline; the integration test needs the real PDF in stage1_eda_input/ and is skipped otherwise.
Run: .venv/bin/python test_source18_yoga.py"""
import glob
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, ".")
from stage1_1_eda_packages import FILENAME_PROCESSORS, KNOWN_SOURCE_EDA_META, process_source  # noqa: E402
from stage1_1_eda_packages import source18_yoga_sutra_angot as y  # noqa: E402

failures = []


def check(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        failures.append(name)


# glyph normalisation
check("iast: yogænu‡æsanam", y._to_iast("Atha yogænu‡æsanam") == "Atha yogānuśāsanam")
check("iast: retroflex/vocalic/anusvara", y._to_iast("KÒiptaµ mº∂haµ v®tti") == "Kṣiptaṃ mūḍhaṃ vṛtti")
check("iast: Greek mu untouched", "µ" in y._to_iast("τῶi µὲν"))

# cleaning drops page-number lines and garbled marker lines
cleaned = y._clean("\n\n- 244 \nAtha yogænu‡æsanam /I.1/\nAT yoganuxasnm` ; 1 ;\n\n\n\ntexte")
check("clean: page number + garbled marker dropped", "- 244" not in cleaned and "; 1 ;" not in cleaned and "yogānuśāsanam" in cleaned)

# marker acceptance: garbled 43 appears before roman 42 -> 42 must still be found
cands = [(0, 0, n) for n in range(1, 42)] + [(1, 0, 43), (1, 5, 42), (1, 9, 43), (1, 12, 44)]
got = [c[2] for c in y._accept_markers(cands, 51)]
check("markers: 42 recovered, 43 taken once", got == list(range(1, 45)))
check("markers: stray far-off number ignored", [c[2] for c in y._accept_markers([(0, 0, 1), (0, 1, 30), (0, 2, 2)], 51)] == [1, 2])
check("markers: respects expected max", [c[2] for c in y._accept_markers([(0, i, i + 1) for i in range(6)], 3)] == [1, 2, 3])

# slicing mid-page
pages = ["aaaXXXbbb", "ccc", "dddYYYeee"]
check("slice: same page", y._slice(pages, (0, 3), (0, 6)) == "XXX")
check("slice: across pages", y._slice(pages, (0, 3), (2, 3)) == "XXXbbb\n\nccc\n\nddd")

# registry tolerates NFD/NFC file names (macOS hands back NFD)
nfd = unicodedata.normalize("NFD", y.FILENAME)
check("registry: NFD name resolves to the dedicated module", nfd in FILENAME_PROCESSORS and KNOWN_SOURCE_EDA_META.get(nfd)["expected_pages"] == 941)

# integration (real PDF)
matches = glob.glob("stage1_eda_input/*/Yogasutra*.pdf")
if not matches:
    print("[SKIP] integration test: PDF not present")
else:
    pdf = Path(matches[0])
    import fitz
    with fitz.open(pdf) as doc:
        pages = [p.get_text("text").replace("\x00", "") for p in doc]
    secs, strat, used_fallback = process_source(pdf.parent.name, pdf.name, pdf, pages)
    sut = [s for s in secs if "sutra" in s["block_type"]]
    check("integration: dedicated module used (not fallback)", not used_fallback and strat == y.STRUCTURE)
    check("integration: 195 sutras", len(sut) == 195)
    check("integration: I.1 title", sut[0]["title"] == "Yoga-Sūtra I.1 (Samādhipāda) — Atha yogānuśāsanam")
    check("integration: last sutra is IV.34", sut[-1]["title"].startswith("Yoga-Sūtra IV.34"))
    check("integration: intro A-F present", sum(1 for s in secs if "introduction" in s["block_type"]) >= 6)
    check("integration: notices present", sum(1 for s in secs if "notice" in s["block_type"]) >= 30)
    check("integration: no index/bibliography sections", not any("Index" in s["title"] or "Études" in s["title"] for s in secs))
    check("integration: no section left empty", all(s["text"] for s in secs))

print("\nAll checks passed." if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
