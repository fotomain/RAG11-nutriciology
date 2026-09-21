"""
Source: "Yogasutra.janvier. 2020.pdf, éd. 2021.pdf" -- Michel Angot, "Yoga. La
parole sur le silence: le Yoga-Sutra, le Yoga-Bhasya" (941 pages, French, 3rd
edition 2021). Text layer present, NO outline, so boundaries are found from
the page text itself.

Layout of the book (0-based page indexes in the constants below):
  - cover / plan / abbreviations                              -> dropped
  - prefaces                                                  -> 1 section
  - Introduction A-F (essays)                                 -> 1 section each
  - "Presentation materielle du texte"                        -> 1 section
  - the text: 4 padas x 195 sutras, each sutra followed by the
    Bhasya and Angot's notes                                  -> ONE SECTION PER SUTRA
    (title "Yoga-Sutra II.30 (Sadhanapada) -- Ahimsa-...")
  - Appendix 1 "Notices" (glossary essays, size-18 headings)  -> 1 section per notice
  - sutra indexes, word index, bibliography, table of contents -> dropped (pure lookup
    tables; embedding them would only add noise)

Sutra boundaries. Each sutra starts with a line of Sanskrit in a legacy font
that extracts as garbage ending in "; N ;", followed by a bold transliteration
line ending in "/I.N/". Either marker works; combining both (see
_accept_markers) finds all 195 sutras. Sections start MID-PAGE at the marker,
so two short sutras on one page do not duplicate each other's text.

Glyph normalisation. The transliteration uses a legacy font whose characters
extract as e.g. "yogænu‡æsanam". _to_iast() maps the unambiguous ones to
standard IAST ("yogānuśāsanam") so a user typing "ahimsa" or
"anushasana" style queries has something to match. Garbled Devanagari lines
and the running page-number lines ("- 244") are dropped.

Boundaries need a whole-book pass (text + font sizes for the notices), so they
are computed once and cached in
stage1_eda_output/<source_key>/_cache_yoga_layout.json (keyed by PDF name+size).
Section TEXT still comes from the `pages` argument, so
MAX_NUMBER_OF_PAGES_TO_USE keeps working (later pages simply yield empty text).

Known limitation: a sutra whose marker cannot be recognised is absorbed into
the preceding sutra's section (nothing is lost, it just isn't its own parent).
"""
import json
import re
from pathlib import Path

import fitz  # PyMuPDF

FILENAME = "Yogasutra.janvier. 2020.pdf, éd. 2021.pdf"
EXPECTED_PAGES = 941
STRUCTURE = "custom_sutra_markers_notices"  # per-sutra sections + intro essays + notices

PREFACE_PAGES = (2, 5)  # 0-based [start, end): pages 3-5
INTRO_SEARCH = (12, 240)
TEXT_SEARCH = (243, 752)
NOTICES_SEARCH = (740, 760)
INDEX_SEARCH = (880, 895)
PADAS = [  # (heading word, roman numeral, expected number of sutras)
    ("Samædhi", "I", 51),
    ("Sædhana", "II", 55),
    ("Vibhºti", "III", 55),
    ("Kaivalya", "IV", 34),
]
PADA_LABEL = {"I": "Samādhipāda", "II": "Sādhanapāda", "III": "Vibhūtipāda", "IV": "Kaivalyapāda"}
INTRO_TITLES = [  # (letter, line regex, canonical title)
    ("A", r"^A\.\s*Le Yoga-S", "A. Le Yoga-Sūtra et la tradition du yoga"),
    ("B", r"^B\.\s*Comment lire", "B. Comment lire le Yoga-Sūtra ?"),
    ("C", r"^C\.\s*La raison", "C. La raison d'être du Yoga-Sūtra"),
    ("D", r"^D\.\s*M[ée]ditation", "D. Méditation, contemplation et oraison"),
    ("E", r"^E\.\s*Le r[ée]alisme", "E. Le réalisme du Yoga-Sūtra confronté à Śaṅkara et Thomas d'Aquin"),
    ("F", r"^F\.\s*L.esp[ée]rance", "F. L'espérance dans la libération brahmanique et le salut chrétien"),
]
NOTICE_HEADING_MIN_SIZE = 16.0
MAX_SECTION_PAGES = 25

_GARBLED_MARK_RE = re.compile(r"^.*;\s*(\d{1,2})\s*;\s*$")
_ROMAN_MARK_RE = re.compile(r"/\s*(I{1,3}|IV)\s*\.\s*(\d{1,2})\s*/\s*$")
_ROMAN_REF_TAIL_RE = re.compile(r"\s*/\s*(?:I{1,3}|IV)\s*\.\s*\d{1,2}\s*/.*$")
_PAGE_NUM_LINE_RE = re.compile(r"^\s*-\s*\d+\s*$")

_IAST = str.maketrans({
    "æ": "ā", "Æ": "Ā", "Ò": "ṣ", "†": "ṭ", "‡": "ś", "◊": "ṇ", "Ì": "ḥ", "º": "ū",
    "Ú": "ī", "Ÿ": "Ī", "®": "ṛ", "©": "ṅ", "Ω": "Ś", "∂": "ḍ",
})
_MU_AFTER_LATIN_RE = re.compile("(?<=[A-Za-zĀ-ſḀ-ỿ])µ")


def _to_iast(text: str) -> str:
    return _MU_AFTER_LATIN_RE.sub("ṃ", text.translate(_IAST))


def _clean(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if _PAGE_NUM_LINE_RE.match(line) or (len(line) < 160 and _GARBLED_MARK_RE.match(line.strip())):
            continue
        kept.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", _to_iast("\n".join(kept))).strip()


def _accept_markers(cands: list, expected_max: int) -> list:
    """cands: (page, offset, number) in reading order. Keep an increasing run 1..N; tolerate a
    gap of up to 3 only when the skipped number does not show up in the next few candidates."""
    accepted, last = [], 0
    for i, cand in enumerate(cands):
        n = cand[2]
        if n == last + 1:
            ok = True
        elif last + 1 < n <= last + 4:
            ok = not any(x[2] == last + 1 for x in cands[i + 1: i + 7])
        else:
            ok = False
        if ok and n <= expected_max:
            accepted.append(cand)
            last = n
    return accepted


def _find_line(pages: list, pattern: str, page_range: tuple):
    rx = re.compile(pattern)
    for pi in range(page_range[0], min(page_range[1], len(pages))):
        offset = 0
        for line in pages[pi].splitlines(True):
            if rx.search(line.strip()):
                return (pi, offset)
            offset += len(line)
    return None


def _translit_title(raw_pages: list, page: int, offset: int) -> str:
    """First transliteration line (the one ending in /I.N/) at or after the marker."""
    seen = 0
    for pi in range(page, min(page + 2, len(raw_pages))):
        text = raw_pages[pi][offset:] if pi == page else raw_pages[pi]
        for line in text.splitlines():
            s = line.strip()
            if _ROMAN_MARK_RE.search(s) and not _GARBLED_MARK_RE.match(s):
                title = _ROMAN_REF_TAIL_RE.sub("", s).strip(" –-")
                if title:
                    return _to_iast(title)[:90]
            seen += 1
            if seen > 8:
                return ""
    return ""


def _scan_notice_headings(pdf_path: Path, raw_pages: list, start: tuple, end: tuple) -> list:
    """[(page, offset, title)] for size>=16 lines between the two anchors (wrapped lines merged)."""
    found = []
    prev_page = None
    with fitz.open(pdf_path) as doc:
        for pi in range(start[0], end[0] + 1):
            for block in doc[pi].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).replace("\x00", "").strip()
                    if not text or not line["spans"]:
                        continue
                    if round(max(s["size"] for s in line["spans"]), 1) < NOTICE_HEADING_MIN_SIZE or len(text) < 3:
                        prev_page = None
                        continue
                    if prev_page == pi and found:
                        found[-1][2] += " " + text
                        continue
                    offset = raw_pages[pi].find(text)
                    found.append([pi, max(offset, 0), text])
                    prev_page = pi
            prev_page = None
    return [(p, o, t) for p, o, t in found if (p, o) > start and (p, o) < end and t.strip().lower() != "notices"]


def _compute_layout(pdf_path: Path) -> dict:
    with fitz.open(pdf_path) as doc:
        raw = [page.get_text("text").replace("\x00", "") for page in doc]
    n = len(raw)

    pada_anchor = []
    for word, numeral, expected in PADAS:
        anchor = _find_line(raw, rf"^{word}pæda$", TEXT_SEARCH)
        if anchor is None:
            raise RuntimeError(f"source18: could not find the '{word}pæda' heading; layout changed?")
        pada_anchor.append(anchor)
    appendix = _find_line(raw, r"^Appendice 1$", NOTICES_SEARCH) or _find_line(raw, r"^Notices$", NOTICES_SEARCH)
    notices = _find_line(raw, r"^Notices$", NOTICES_SEARCH)
    index = _find_line(raw, r"^Index des sºtra", INDEX_SEARCH) or (min(888, n - 1), 0)
    if appendix is None or notices is None:
        raise RuntimeError("source18: could not find the 'Notices' appendix; layout changed?")

    sutras = []  # [numeral, number, page, offset, title]
    bounds = pada_anchor + [appendix]
    for k, (word, numeral, expected) in enumerate(PADAS):
        lo, hi = bounds[k], bounds[k + 1]
        cands = []
        for pi in range(lo[0], hi[0] + 1):
            offset = 0
            for line in raw[pi].splitlines(True):
                pos, s = (pi, offset), line.strip()
                offset += len(line)
                if not (lo <= pos < hi):
                    continue
                m = _GARBLED_MARK_RE.match(s)
                if m and len(s) < 160:
                    cands.append((pi, pos[1], int(m.group(1))))
                    continue
                m = _ROMAN_MARK_RE.search(s)
                if m and m.group(1) == numeral and len(s) < 200:
                    cands.append((pi, pos[1], int(m.group(2))))
        for pi, off, num in _accept_markers(cands, expected):
            sutras.append([numeral, num, pi, off, _translit_title(raw, pi, off)])

    intro = []
    prev = (INTRO_SEARCH[0], 0)
    for letter, rx, title in INTRO_TITLES:
        anchor = _find_line(raw, rx, (prev[0], INTRO_SEARCH[1]))
        if anchor:
            intro.append([letter, title, anchor[0], anchor[1]])
            prev = anchor
    intro_start = _find_line(raw, r"^(INTRODUCTION|Introduction)$", (INTRO_SEARCH[0], INTRO_SEARCH[0] + 3))
    materielle = _find_line(raw, r"^Présentation matérielle du texte", (INTRO_SEARCH[1] - 60, TEXT_SEARCH[0] + 1))

    return {
        "n_pages": n,
        "pada": pada_anchor, "appendix": appendix, "notices": notices, "index": index,
        "intro_start": intro_start, "intro": intro, "materielle": materielle,
        "sutras": sutras,
        "notice_headings": _scan_notice_headings(pdf_path, raw, notices, index),
    }


def _layout(pdf_path: Path, source_key: str) -> dict:
    cache_dir = Path(pdf_path).parents[2] / "stage1_eda_output" / source_key
    cache = cache_dir / "_cache_yoga_layout.json"
    fingerprint = [Path(pdf_path).name, Path(pdf_path).stat().st_size]
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("pdf") == fingerprint:
            return data["layout"]
    layout = _compute_layout(Path(pdf_path))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"pdf": fingerprint, "layout": layout}, ensure_ascii=False), encoding="utf-8")
    return layout


def _slice(pages: list, start: tuple, end: tuple) -> str:
    (p0, o0), (p1, o1) = start, end
    if p0 == p1:
        return pages[p0][o0:o1]
    parts = [pages[p0][o0:]] + pages[p0 + 1:p1] + [pages[p1][:o1]]
    return "\n\n".join(parts)


def _section(title: str, level: int, start: tuple, end: tuple, pages: list, block_type: list) -> dict:
    last_page = end[0] - 1 if end[1] == 0 and end[0] > start[0] else end[0]
    return {
        "title": title, "level": level, "start_page": start[0], "end_page": max(last_page, start[0]),
        "text": _clean(_slice(pages, start, end)), "block_type": block_type,
    }


def _split_long(sec: dict, pages: list, start: tuple, end: tuple) -> list:
    span = sec["end_page"] - sec["start_page"] + 1
    if span <= MAX_SECTION_PAGES:
        return [sec]
    n_parts = -(-span // MAX_SECTION_PAGES)
    size = -(-span // n_parts)  # even parts, no tiny tail
    out = []
    for k in range(n_parts):
        s = start if k == 0 else (start[0] + k * size, 0)
        e = end if k == n_parts - 1 else (start[0] + (k + 1) * size, 0)
        out.append(_section(f"{sec['title']} (part {k + 1}/{n_parts})", sec["level"], s, e, pages, sec["block_type"]))
    return out


def extract_sections(source_key: str, pdf_path: Path, pages: list[str]) -> list[dict]:
    lay = _layout(pdf_path, source_key)
    tup = lambda a: (a[0], a[1])  # noqa: E731 -- json turns tuples into lists
    sections = []

    def add(title, level, start, end, block_type):
        sec = _section(title, level, start, end, pages, block_type)
        sections.extend(_split_long(sec, pages, start, end))

    add("Préfaces (2012, 2021)", 1, (PREFACE_PAGES[0], 0), (PREFACE_PAGES[1], 0), [])

    intro = lay["intro"]
    first_intro = tup(lay["intro_start"]) if lay["intro_start"] else (INTRO_SEARCH[0], 0)
    ends = [tup(lay["materielle"]) if lay["materielle"] else tup(lay["pada"][0])]
    if intro:
        for i, (letter, title, pi, off) in enumerate(intro):
            start = first_intro if i == 0 else (pi, off)
            end = (intro[i + 1][2], intro[i + 1][3]) if i + 1 < len(intro) else ends[0]
            add(f"Introduction — {title}", 1, start, end, ["introduction"])
    else:
        add("Introduction", 1, first_intro, ends[0], ["introduction"])
    if lay["materielle"]:
        add("Présentation matérielle du texte", 1, tup(lay["materielle"]), tup(lay["pada"][0]), [])

    sutras = lay["sutras"]
    pada_end = [tup(a) for a in lay["pada"][1:]] + [tup(lay["appendix"])]
    pada_idx = {numeral: i for i, (_, numeral, _) in enumerate(PADAS)}
    for i, (numeral, num, pi, off, translit) in enumerate(sutras):
        if i + 1 < len(sutras) and sutras[i + 1][0] == numeral:
            end = (sutras[i + 1][2], sutras[i + 1][3])
        else:
            end = pada_end[pada_idx[numeral]]
        title = f"Yoga-Sūtra {numeral}.{num} ({PADA_LABEL[numeral]})" + (f" — {translit}" if translit else "")
        add(title, 2, (pi, off), end, ["sutra"])

    notices, index = tup(lay["notices"]), tup(lay["index"])
    heads = [(p, o, _to_iast(t).strip(" .")) for p, o, t in lay["notice_headings"]]
    starts = [notices] + [(p, o) for p, o, _ in heads]
    titles = ["Notices (Appendice 1) — présentation"] + [f"Notice — {t}" for _, _, t in heads]
    for i, start in enumerate(starts):
        add(titles[i], 1, start, starts[i + 1] if i + 1 < len(starts) else index, ["notice"])

    sections = [s for s in sections if s["text"]]  # empty past MAX_NUMBER_OF_PAGES_TO_USE
    n_sutra = sum(1 for s in sections if "sutra" in s["block_type"])
    print(f"[{source_key}] {len(sections)} sections ({n_sutra} sutras, {len(heads)} notices)")
    return sections
