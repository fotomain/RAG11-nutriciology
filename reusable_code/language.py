"""Speaking-language support: questions in any language, answers in one.

Two cooperating pieces, both driven by ``SPEAKING_LANGUAGE`` (``.env``, default ``EN``):

1. ``prepare_question()`` -- a small "query understanding" step run BEFORE retrieval.
   One Claude call detects the question's language, translates it into the speaking
   language, and rewrites it into a neutral, self-contained, keyword-rich *search
   query* in the corpus's language (jokes, slang, emoji, typos and pronouns that need
   context are removed; Sanskrit is transliterated to IAST). Retrieval then searches
   with that clean query instead of the raw, possibly playful or foreign-script text,
   which is what makes "funny" or non-English questions retrieve as well as plain ones.
   The model that answers still sees the ORIGINAL question plus its translation.
2. ``answer_language_directive()`` -- an explicit instruction appended to the system
   prompt so the answer is written in the speaking language whatever language the
   question or the excerpts are in. (Pass ``answer_language=`` to ``ask_question``.)

If the understanding call fails or returns garbage, ``prepare_question()`` degrades to
the original question (plus an IAST rendering of any Devanagari), so a question is
never lost.
"""
import json
from dataclasses import dataclass
from typing import Optional

from .clients import Clients, GENERATION_MODEL, get_clients
from .config import SPEAKING_LANGUAGE
from .devanagari import contains_devanagari, romanize_devanagari
from .retry import with_retry

LANGUAGE_NAMES = {
    "EN": "English", "FR": "French", "DE": "German", "ES": "Spanish", "IT": "Italian",
    "PT": "Portuguese", "NL": "Dutch", "PL": "Polish", "RU": "Russian", "UK": "Ukrainian",
    "HI": "Hindi", "SA": "Sanskrit", "AR": "Arabic", "JA": "Japanese", "ZH": "Chinese",
    "KO": "Korean", "TR": "Turkish",
}

# Devanagari and Cyrillic cost several tokens per character, so leave generous room for the JSON reply.
UNDERSTAND_MAX_TOKENS = 1500

_UNDERSTAND_SYSTEM = """You prepare user questions for a retrieval-augmented question-answering system.

The searchable corpus: {corpus_hint}.
The speaking language of the system: {language}.

The question may be in any language or script and may contain slang, emoji, typos or a joke. Do NOT answer it. \
Return ONLY one JSON object with exactly these keys:
  "language":     the ISO 639-1 code of the language the question is written in (e.g. "en", "fr", "hi").
  "translation":  the question translated into {language}, faithful to its meaning and tone but without emoji; \
the empty string "" if the question is already written in {language}.
  "search_query": ONE neutral, self-contained, keyword-rich question for searching the corpus, written in the \
language of the corpus. Remove jokes, slang, emoji and references that need context; keep every distinct \
information need in the question; use the technical terms the corpus would use; transliterate Sanskrit to IAST.

No prose before or after the JSON."""


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.strip().upper(), code)


def answer_language_directive(code: str) -> str:
    name = language_name(code)
    return (
        f"LANGUAGE: Write the entire answer in {name}, even when the question is written in another language "
        f"and even if it asks you to reply in that language. This holds whatever language or script the question, the excerpts "
        f"or any quoted text is in. When you quote a source passage that is not in {name}, follow it with "
        f"its translation into {name} in parentheses. Keep Sanskrit terms in IAST. If you write a \"Short answer:\" line, "
        f"keep it exactly as \"Short answer: Yes\" or \"Short answer: No\", in English, so it can be parsed."
    )


@dataclass(frozen=True)
class PreparedQuestion:
    original: str
    llm_question: str      # what the answering model is shown: original (+ translation, + IAST)
    retrieval_query: str   # what every retrieval step searches with
    language: Optional[str]  # detected ISO code (upper case), None if unknown
    translation: Optional[str]  # in the speaking language, None if it equals the original
    used_llm: bool


def _parse_understanding(raw: str) -> Optional[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not str(data.get("search_query", "")).strip():
        return None
    return data


def prepare_question(
    question: str,
    *,
    language: str = SPEAKING_LANGUAGE,
    corpus_hint: str = "English-language clinical and sports nutrition textbooks",
    model: str = GENERATION_MODEL,
    use_llm: bool = True,
    clients: Optional[Clients] = None,
) -> PreparedQuestion:
    """Understand ``question`` (any language/register) for retrieval in a corpus described by
    ``corpus_hint`` and answering in ``language``. See this module's docstring."""
    iast = romanize_devanagari(question) if contains_devanagari(question) else None
    detected = translation = None
    search_query = None
    used_llm = False

    if use_llm:
        clients = clients or get_clients()
        system = _UNDERSTAND_SYSTEM.format(corpus_hint=corpus_hint, language=language_name(language))
        data = None
        for attempt in (1, 2):  # a malformed reply is rare and cheap to redo
            try:
                resp = with_retry(lambda: clients.anthropic.messages.create(
                    model=model, max_tokens=UNDERSTAND_MAX_TOKENS, system=system,
                    messages=[{"role": "user", "content": question}],
                ), max_attempts=3)
            except Exception as e:  # noqa: BLE001 -- never lose a question because preparation failed
                print(f"[warn] question understanding failed ({e}); using the question as-is")
                break
            data = _parse_understanding("".join(b.text for b in resp.content if b.type == "text"))
            if data:
                break
        else:
            print("[warn] question understanding returned no usable JSON twice; using the question as-is")
        if data:
            used_llm = True
            search_query = str(data["search_query"]).strip()
            detected = (str(data.get("language") or "").strip().upper() or None)
            t = str(data.get("translation") or "").strip()
            if t and t != question.strip():
                translation = t

    parts = [question]
    if translation and (detected or "").upper() != language.upper():
        parts.append(f"[{language_name(language)}: {translation}]")
    if iast:
        parts.append(f"[IAST: {iast}]")
    llm_question = "\n".join(parts)
    retrieval = search_query or (f"{question} {iast}" if iast else question)
    return PreparedQuestion(question, llm_question, retrieval, detected, translation, used_llm)
