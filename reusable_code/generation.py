"""Answer generation shared by every RAG11 Q&A notebook."""
import re
from typing import Optional

from .clients import Clients, GENERATION_MODEL, RERANK_MODEL, get_clients
from .retrieval import (
    MIN_CONTEXT_CHUNKS,
    NUM_CONTEXT_CHUNKS,
    RERANK_MIN_POOL,
    RERANK_POOL_MULTIPLIER,
    page_numbers_for_chunk,
    rerank_chunks,
    retrieve_chunks,
)
from .retry import with_retry

MAX_ANSWER_TOKENS = 800  # upper bound on how many tokens Claude's generated answer may use

SYSTEM_PROMPT = """You are a nutrition Q&A assistant. Answer strictly using \
the numbered excerpts provided in the user message -- do not rely on \
outside knowledge, and say plainly if the excerpts don't contain enough \
information to answer.

First decide whether the question has a clean Yes/No answer:
  - If it does, begin your reply with exactly this one line:
        Short answer: Yes
    or
        Short answer: No
    then a blank line, then the full explanation.
  - If the question has no clean Yes/No answer (it asks for a list, a \
description, a comparison -- a "what"/"how" question rather than an \
"is"/"does"/"can" one), skip the "Short answer" line entirely and just \
give the full explanation.

Keep the full explanation grounded in the excerpts -- refer to what they \
actually say rather than general nutrition knowledge."""


def build_context_block(chunks: list) -> str:
    """Render retrieved (and, optionally, reranked) chunks into the numbered
    excerpt block the system prompt above expects. When a chunk carries a
    ``rerank_score`` (i.e. it went through ``rerank_chunks()``), that score
    is shown in the excerpt label -- purely for human/debugging visibility
    in printed output, it plays no role in what Claude is told to do with
    the excerpts."""
    parts = []
    for i, row in enumerate(chunks, start=1):
        source_key = row["rowJSON"].get("source_key", row["rowOwnerGUID"])
        label = f"[Excerpt {i} -- {source_key}"
        if "rerank_score" in row:
            label += f" | relevance {row['rerank_score']:.2f}"
        label += "]"
        parts.append(f"{label}\n{row['rowJSON']['text']}")
    return "\n\n".join(parts)


_SHORT_ANSWER_RE = re.compile(r"^\s*Short answer:\s*(Yes|No)\s*$", re.IGNORECASE | re.MULTILINE)


def extract_short_answer(answer_text: str) -> Optional[str]:
    match = _SHORT_ANSWER_RE.search(answer_text)
    return match.group(1).capitalize() if match else None


# A compact, deliberately unsurprising English stopword list -- just enough
# to strip connective/filler words so grounding_words() below surfaces the
# actual nutrition terminology the answer and its source excerpts share.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "for", "nor", "so",
    "as", "at", "by", "in", "into", "of", "on", "onto", "to", "with", "within",
    "from", "about", "above", "after", "again", "against", "all", "am", "any",
    "are", "because", "been", "before", "being", "below", "between", "both",
    "can", "cannot", "did", "do", "does", "doesn't", "doing", "down", "during",
    "each", "few", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "however", "i",
    "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself",
    "no", "not", "now", "off", "once", "only", "other", "our", "ours",
    "ourselves", "out", "over", "own", "same", "she", "should", "some", "such",
    "than", "that", "their", "theirs", "them", "themselves", "there", "these",
    "therefore", "they", "this", "those", "through", "thus", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "whom", "why", "will", "would", "you", "your",
    "yours", "yourself", "yourselves",
}
_WORD_RE = re.compile(r"[A-Za-z']+")


def grounding_words(answer_text: str, chunks: list, top_n: int = 12) -> list:
    """Words the printed answer actually shares with its retrieved source
    excerpts -- a literal, checkable answer to "what words is this answer
    established on", rather than just trusting the system prompt's "answer
    only from the excerpts" instruction. Stopwords and 1-2 letter tokens
    are dropped; the rest are returned lowercased, deduplicated, in the
    order they first appear in the answer, capped at ``top_n``."""
    excerpt_text = " ".join(row["rowJSON"]["text"] for row in chunks)
    excerpt_words = {w.lower() for w in _WORD_RE.findall(excerpt_text) if len(w) > 2}

    seen = set()
    shared = []
    for word in _WORD_RE.findall(answer_text):
        lower = word.lower()
        if lower in _STOPWORDS or len(lower) <= 2 or lower in seen:
            continue
        if lower in excerpt_words:
            seen.add(lower)
            shared.append(lower)
        if len(shared) >= top_n:
            break
    return shared


def ask_question(
    question: str,
    match_count: int = NUM_CONTEXT_CHUNKS,
    *,
    use_rerank: bool = False,
    rerank_top_n: Optional[int] = None,
    rerank_candidate_pool: Optional[int] = None,
    rerank_model: str = RERANK_MODEL,
    generation_model: str = GENERATION_MODEL,
    clients: Optional[Clients] = None,
) -> dict:
    """Retrieve chunks for ``question``, ask Claude to answer from them
    only, and return a structured result -- including the short Yes/No
    call (if any), the array of source page numbers behind the answer, and
    the words the answer shares with those source excerpts.

    ``use_rerank`` is optional and defaults to ``False`` -- existing calls
    like ``ask_question("Is vitamin C water-soluble?")`` behave exactly as
    before. Pass ``use_rerank=True`` to add Voyage's cross-encoder rerank
    pass on top of plain vector retrieval:

        - a wider pool of raw candidates is fetched first (
          ``rerank_candidate_pool``, default
          ``max(match_count * 4, 15)``),
        - ``rerank_chunks()`` re-scores that pool against the question and
          keeps the best ``rerank_top_n`` (default ``match_count``),
        - only those reranked chunks go to Claude.

    When ``use_rerank=False``, ``match_count`` chunks are fetched directly
    by vector search, exactly like the original stage2 notebook.

    Returned dict keys (all present regardless of ``use_rerank``):
        question, short_answer, answer, chunks_used, source_pages,
        source_keys, grounding_words, used_rerank, rerank_model,
        candidates_considered
    """
    clients = clients or get_clients()
    final_n = rerank_top_n or match_count

    if use_rerank:
        pool_size = rerank_candidate_pool or max(final_n * RERANK_POOL_MULTIPLIER, RERANK_MIN_POOL)
        candidates = retrieve_chunks(question, match_count=pool_size, clients=clients)
        chunks = rerank_chunks(question, candidates, top_n=final_n, model=rerank_model, clients=clients)
    else:
        candidates = chunks = retrieve_chunks(question, match_count=final_n, clients=clients)

    if len(chunks) < MIN_CONTEXT_CHUNKS:
        print(
            f"  [warn] only {len(chunks)} chunk(s) retrieved for {question!r} "
            f"(< {MIN_CONTEXT_CHUNKS}) -- answer may be under-supported."
        )

    context_block = build_context_block(chunks)
    user_message = f"{context_block}\n\nQuestion: {question}"

    resp = with_retry(
        lambda: clients.anthropic.messages.create(
            model=generation_model,
            max_tokens=MAX_ANSWER_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    )
    answer_text = "".join(block.text for block in resp.content if block.type == "text")

    source_pages = sorted({page for row in chunks for page in page_numbers_for_chunk(row)})
    source_keys = sorted({row["rowJSON"].get("source_key", row["rowOwnerGUID"]) for row in chunks})

    return {
        "question": question,
        "short_answer": extract_short_answer(answer_text),  # "Yes" / "No" / None
        "answer": answer_text,
        "chunks_used": len(chunks),
        "source_pages": source_pages,  # array of page numbers backing this answer
        "source_keys": source_keys,
        "grounding_words": grounding_words(answer_text, chunks),  # words shared with the source excerpts
        "used_rerank": use_rerank,
        "rerank_model": rerank_model if use_rerank else None,
        "candidates_considered": len(candidates),
    }
