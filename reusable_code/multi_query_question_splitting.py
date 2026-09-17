"""Multi-query / question splitting for ``rag11_chunks_child_table`` --
another retrieval-method module living alongside ``hybrid_search.py``,
``hypothetical_document_embedding.py``, and ``parent_chunk_expansion.py``
instead of being folded into ``retrieval.py``/``generation.py`` themselves.

The problem this solves: one search query can only point in one "direction"
in embedding space. A question that's secretly *two* questions glued
together confuses a single vector (or keyword) search.

Example: "How does soluble fiber's effect on LDL cholesterol differ from
insoluble fiber's effect?" is really two independent information needs --
(a) "What does soluble fiber do to LDL cholesterol?" and (b) "What does
insoluble fiber do to LDL cholesterol?" -- glued together with "differ
from". A single embedding of the whole question ends up as a blurry
average of both topics, which can under-match either one (or bury one of
them below the retrieval cutoff while the other dominates).

The fix, and what this module does: ask Claude to split the question into
its independent sub-questions, run the *same* underlying single-question
retrieval function (``retrieval.retrieve_chunks()`` by default -- but
``hybrid_search.hybrid_search()`` works exactly as well, since both share
the same ``(question, match_count, filter_owner, clients)`` shape) once per
sub-question over a wide pool, then fuse all of the resulting ranked lists
into one combined ranking with the *same* Reciprocal Rank Fusion
``hybrid_search.py`` already uses to merge dense + keyword search --
``reciprocal_rank_fusion()`` doesn't know or care whether its inputs came
from different *search methods* (hybrid search's case) or the same method
run on different *sub-questions* (this module's case). Now chunks about
both fiber types are guaranteed a chance to surface, instead of hoping one
combined search happens to catch both.

    - ``split_into_subquestions()`` -- asks Claude (via
      ``MULTI_QUERY_SYSTEM_PROMPT``) whether ``question`` bundles more than
      one independent information need, and if so, splits it into up to
      ``max_subquestions`` self-contained sub-questions. A question that's
      already a single, atomic ask comes back unchanged as a length-1 list
      -- this function always returns *something* to retrieve on, even if
      Claude declines to split.
    - ``retrieve_chunks_multi_query()`` -- composes the above with
      ``retrieve_fn`` (default ``retrieval.retrieve_chunks``) and
      ``hybrid_search.reciprocal_rank_fusion()``: split the question, run
      ``retrieve_fn`` once per sub-question over a wide pool, fuse every
      resulting ranked list into one. What
      ``generation.ask_question(..., use_multi_query=True)`` calls.

See ``stage2_ask_examples6_multi_query_question_splitting.ipynb`` for
worked nutrition examples,
``documentation/HOW_IT_WORKS_Multi_Query_Question_Splitting.html`` for the
full write-up, and ``reusable_code/README.md`` for the one-paragraph
summary. No schema or migration change is needed -- this only adds one
extra Claude call (to split the question) before calling the exact same
retrieval RPCs ``retrieve_chunks()``/``hybrid_search()`` already use.
"""
import re
from typing import Callable, List, Optional, Tuple, Union

from .clients import Clients, GENERATION_MODEL, get_clients
from .hybrid_search import RRF_K, reciprocal_rank_fusion
from .retrieval import NUM_CONTEXT_CHUNKS, retrieve_chunks
from .retry import with_retry

# A sub-question is a retrieval probe, not a displayed answer -- a handful
# of short lines is all this ever needs, deliberately much smaller than
# generation.MAX_ANSWER_TOKENS (800). Mirrors
# hypothetical_document_embedding.HYDE_MAX_TOKENS's reasoning.
MULTI_QUERY_MAX_TOKENS = 300

# Cap on how many sub-questions one call will split into -- keeps a
# pathological "and" chain (or a prompt-injected question) from fanning out
# into an unbounded number of retrieval calls. Four independent questions
# glued into one is already an unusual amount of splitting to need.
MAX_SUBQUESTIONS = 4

# Same "cast a wide net cheaply" idea hybrid_search.py's HYBRID_POOL_MULTIPLIER/
# HYBRID_MIN_POOL and rerunk_code.py's RERANK_POOL_MULTIPLIER/RERANK_MIN_POOL
# use: each sub-question's retrieve_fn call over-fetches
# max(match_count * MULTI_QUERY_POOL_MULTIPLIER, MULTI_QUERY_MIN_POOL)
# candidates *before* reciprocal_rank_fusion() narrows the merged list down
# to match_count, so a chunk only one sub-question's search would have
# surfaced in a narrower top-K still gets counted.
MULTI_QUERY_POOL_MULTIPLIER = 4
MULTI_QUERY_MIN_POOL = 15

MULTI_QUERY_SYSTEM_PROMPT = """You split nutrition questions into their \
independent parts for a document-retrieval system.

Read the question. If it bundles two or more genuinely independent \
information needs -- e.g. it asks for a comparison ("how does X differ \
from Y"), asks about several distinct nutrients/conditions/populations in \
one sentence, or is really two questions joined by "and"/"or"/a comma -- \
rewrite it as that many separate, self-contained sub-questions, one per \
line, each prefixed with "SUBQ: ". Each sub-question must stand on its own \
(replace pronouns like "it"/"the other one" with the actual subject) so it \
can be searched for on its own, without the rest of the original question.

If the question is already a single, atomic ask -- even if it's long or \
detailed -- do NOT split it. Reply with exactly one line: "SUBQ: " \
followed by the original question, unchanged.

Output ONLY the "SUBQ: " lines. No preamble, no numbering, no explanation, \
no blank lines between them."""

_SUBQ_LINE_RE = re.compile(r"^\s*SUBQ:\s*(.+?)\s*$", re.IGNORECASE)


def split_into_subquestions(
    question: str,
    *,
    model: str = GENERATION_MODEL,
    max_tokens: int = MULTI_QUERY_MAX_TOKENS,
    max_subquestions: int = MAX_SUBQUESTIONS,
    clients: Optional[Clients] = None,
) -> List[str]:
    """Ask Claude whether ``question`` bundles more than one independent
    information need and, if so, split it into up to ``max_subquestions``
    self-contained sub-questions -- see this module's docstring for the
    soluble/insoluble fiber example.

    Always returns a non-empty list: a question Claude judges already
    atomic comes back as ``[question]`` (its own text, per
    ``MULTI_QUERY_SYSTEM_PROMPT``'s instruction to echo it unchanged rather
    than paraphrase it); if the response can't be parsed at all (empty
    reply, no ``"SUBQ: "`` lines), this falls back to ``[question]`` too --
    a parsing failure should never leave the caller with nothing to
    retrieve on. Output beyond ``max_subquestions`` lines is truncated.

    This is a retrieval-planning step only -- the returned strings are used
    to drive extra searches, never shown to a user as answers.
    """
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.anthropic.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=MULTI_QUERY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
    )
    raw = "".join(block.text for block in resp.content if block.type == "text").strip()

    subquestions = []
    for line in raw.splitlines():
        match = _SUBQ_LINE_RE.match(line)
        if match:
            subquestions.append(match.group(1).strip())
    subquestions = subquestions[:max_subquestions]

    return subquestions or [question]


def retrieve_chunks_multi_query(
    question: str,
    match_count: int = NUM_CONTEXT_CHUNKS,
    *,
    retrieve_fn: Callable[..., list] = retrieve_chunks,
    per_query_pool: Optional[int] = None,
    rrf_k: int = RRF_K,
    max_subquestions: int = MAX_SUBQUESTIONS,
    split_model: str = GENERATION_MODEL,
    filter_owner: Optional[str] = None,
    return_subquestions: bool = False,
    clients: Optional[Clients] = None,
) -> Union[list, Tuple[list, List[str]]]:
    """Split ``question`` into its independent sub-questions
    (``split_into_subquestions()``), run ``retrieve_fn`` once per
    sub-question over a wide pool, and fuse every resulting ranked list
    into one combined ranking via
    ``hybrid_search.reciprocal_rank_fusion()`` -- the same merge function
    ``hybrid_search()`` uses for dense + keyword search, reused here to
    merge "the same search, run once per sub-question" instead.

    ``retrieve_fn`` defaults to ``retrieval.retrieve_chunks`` (plain dense
    search) but anything sharing its ``(question, match_count, *,
    filter_owner, clients)`` shape works -- e.g. pass
    ``hybrid_search.hybrid_search`` to run dense + keyword search *per
    sub-question*, then fuse across sub-questions on top of that.

    Each sub-question's call over-fetches
    ``per_query_pool or max(match_count * MULTI_QUERY_POOL_MULTIPLIER,
    MULTI_QUERY_MIN_POOL)`` candidates before fusion narrows the merged
    list down to ``match_count`` -- the same over-fetch-then-narrow pattern
    every other retrieval module here uses.

    A question Claude doesn't split (``split_into_subquestions()`` returns
    a single-element list) still goes through ``reciprocal_rank_fusion()``
    with one input list -- harmless (the fused order matches ``retrieve_fn``'s
    own order, just with an ``"rrf_score"``/``"sub1_rank"`` key attached),
    and keeps this function's return shape uniform regardless of whether a
    split actually happened.

    Each returned row carries ``"sub1_rank"``, ``"sub2_rank"``, ... (one
    per sub-question that ran, ``None`` if that sub-question's search
    didn't return the row at all) and ``"rrf_score"`` -- see
    ``reciprocal_rank_fusion()`` for exactly what they mean. Query-time
    diagnostics only, same as every other module here; nothing is written
    back to Supabase.

    Returns just the row list by default; pass ``return_subquestions=True``
    to also get back the sub-question list that was searched (for
    display/debugging -- e.g. to show a stakeholder *why* a given chunk was
    retrieved), as ``(rows, subquestions)``.
    """
    clients = clients or get_clients()
    subquestions = split_into_subquestions(
        question, model=split_model, max_subquestions=max_subquestions, clients=clients
    )
    pool = per_query_pool or max(match_count * MULTI_QUERY_POOL_MULTIPLIER, MULTI_QUERY_MIN_POOL)

    ranked_lists = {}
    for i, sub_question in enumerate(subquestions, start=1):
        ranked_lists[f"sub{i}"] = retrieve_fn(
            sub_question, match_count=pool, filter_owner=filter_owner, clients=clients
        )

    fused = reciprocal_rank_fusion(ranked_lists, k=rrf_k)
    rows = fused[:match_count]

    if return_subquestions:
        return rows, subquestions
    return rows
