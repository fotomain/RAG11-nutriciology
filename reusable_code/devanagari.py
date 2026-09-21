"""Devanagari -> IAST transliteration, dependency-free.

Why: the Yoga-Sutra source (stage1_1_eda_packages/source18_yoga_sutra_angot.py)
is stored as French prose with Sanskrit in IAST ("yogaś cittavṛttinirodhaḥ").
A question typed in Devanagari ("योगश्चित्तवृत्तिनिरोधः") shares no characters with
those chunks, so neither the keyword search nor the embedding has much to
match. ``romanize_devanagari()`` rewrites every Devanagari run in a question
into IAST so it can be appended to the question for retrieval, while the
original script is kept for the reader/LLM.
"""
import re

_VOWELS = {
    "अ": "a", "आ": "ā", "इ": "i", "ई": "ī", "उ": "u", "ऊ": "ū", "ऋ": "ṛ", "ॠ": "ṝ", "ऌ": "ḷ",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_MATRAS = {
    "ा": "ā", "ि": "i", "ी": "ī", "ु": "u", "ू": "ū", "ृ": "ṛ", "ॄ": "ṝ", "े": "e", "ै": "ai",
    "ो": "o", "ौ": "au",
}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ṅ",
    "च": "c", "छ": "ch", "ज": "j", "झ": "jh", "ञ": "ñ",
    "ट": "ṭ", "ठ": "ṭh", "ड": "ḍ", "ढ": "ḍh", "ण": "ṇ",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "ś", "ष": "ṣ", "स": "s", "ह": "h", "ळ": "ḷ",
}
_SIGNS = {"ं": "ṃ", "ँ": "ṃ", "ः": "ḥ", "ऽ": "'", "ॐ": "oṃ", "।": ".", "॥": "."}
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_VIRAMA = "्"
_NUKTA = "़"

DEVANAGARI_RE = re.compile("[ऀ-ॿ]+")
_RUN_RE = re.compile(r"[ऀ-ॿ]+")


def contains_devanagari(text: str) -> bool:
    return DEVANAGARI_RE.search(text) is not None


def _romanize_run(run: str) -> str:
    out, i, n = [], 0, len(run)
    while i < n:
        ch = run[i]
        if ch in _CONSONANTS:
            base = _CONSONANTS[ch]
            j = i + 1
            while j < n and run[j] == _NUKTA:
                j += 1
            nxt = run[j] if j < n else ""
            if nxt == _VIRAMA:
                out.append(base)
                j += 1
            elif nxt in _MATRAS:
                out.append(base + _MATRAS[nxt])
                j += 1
            else:
                out.append(base + "a")
            i = j
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
            i += 1
        elif ch in _SIGNS:
            out.append(_SIGNS[ch])
            i += 1
        elif ch in _DIGITS:
            out.append(_DIGITS[ch])
            i += 1
        else:  # stray combining mark (e.g. a lone matra/nukta): drop it
            i += 1
    return "".join(out)


def romanize_devanagari(text: str) -> str:
    """Return ``text`` with every Devanagari run converted to IAST; all other
    characters (Latin, French, digits, punctuation) are left exactly as they are.

    Word-final inherent "a" is kept, as Sanskrit is written: योगः -> yogaḥ.
    """
    return _RUN_RE.sub(lambda m: _romanize_run(m.group(0)), text)
