"""Hybrid (dense + keyword) search for ``lrm_child_chunk_table`` -- the
retrieval-method counterpart to ``retrieval.py``'s plain vector search (see
``retrieval.retrieve_chunks``), living in its own module the same way
row-level CRUD for the parent/child chunk tables lives in
``crud_chunks_parent.py``/``crud_chunks_child.py`` instead of being folded
into ``retrieval.py`` itself.

Two independent search methods over the same table, then one merge step:

    - ``retrieve_chunks_keyword()`` -- Postgres full-text (lexical) search
      via the ``match_lrm_chunks_keyword`` RPC from
      ``sql/create_lrm_tables.sql``. The counterpart to
      ``retrieval.retrieve_chunks()``'s dense/semantic search.
    - ``reciprocal_rank_fusion()`` -- a small, generic function that merges
      any number of already-ranked lists of rows into one combined ranking.
      Doesn't know anything about dense vs. keyword search specifically.
    - ``hybrid_search()`` -- runs ``retrieval.retrieve_chunks()`` and
      ``retrieve_chunks_keyword()`` over a wide candidate pool and fuses
      them with ``reciprocal_rank_fusion()``. What
      ``generation.ask_question(..., use_hybrid=True)`` calls.

See ``stage2_ask_examples3_hybrid_search.ipynb`` for worked nutrition
examples, ``documentation/HOW_IT_WORKS_Hybrid_Search.html`` for the full
write-up (including why this catches cases plain vector search misses), and
``reusable_code/README.md`` for the one additive SQL migration this needs.
"""
import re
import string
from typing import Dict, List, Optional

from .clients import Clients, get_clients
from .deduplication import first_occurrence_map
from .retrieval import NUM_CONTEXT_CHUNKS, retrieve_chunks
from .retry import with_retry

# Same "cast a wide net cheaply" idea rerunk_code.py's RERANK_POOL_MULTIPLIER/
# RERANK_MIN_POOL use for rerank_chunks(), but for the two hybrid_search()
# inputs: each of the dense and keyword searches over-fetches
# max(final_n * HYBRID_POOL_MULTIPLIER, HYBRID_MIN_POOL) candidates *before*
# Reciprocal Rank Fusion narrows the merged list down to final_n, so a chunk
# that only one method ranks highly still gets a chance to be seen by both.
HYBRID_POOL_MULTIPLIER = 4
HYBRID_MIN_POOL = 15

# Reciprocal Rank Fusion's damping constant -- the value from the original
# Cormack et al. (2009) RRF paper, and the conventional default. Larger k
# flattens the score curve (rank 1 vs. rank 10 matter less relative to each
# other); smaller k makes a top rank in any one list dominate more.
RRF_K = 60


def _as_or_query(question: str) -> str:
    """Turn a natural-language question into a Postgres
    ``websearch_to_tsquery``-flavored string that ORs its words together
    instead of requiring all of them.

    ``websearch_to_tsquery`` (what ``match_lrm_chunks_keyword``
    calls) treats unquoted words as an implicit AND -- fine for a
    2-3-word keyword search, but against a full question ("How many grams
    of protein per kilogram of body weight does the RDA recommend for an
    average adult?") it almost always means *no* chunk contains literally
    every one of those ~10 words, so the search returns zero rows. Joining
    the question's words with the literal ``OR`` keyword (which
    ``websearch_to_tsquery`` recognizes -- case-sensitively -- as its
    alternation operator) instead asks for *any* of them, and
    ``ts_rank_cd`` naturally ranks a chunk matching more/rarer terms
    higher, which is the keyword-search behavior actually wanted here.
    Stopwords need no special handling -- Postgres' ``english`` search
    configuration already drops them from both sides (query and indexed
    text) during tokenization, so ORing one in is a no-op, not noise.

    Only whitespace-separated tokens are touched (leading/trailing
    punctuation stripped so e.g. a trailing "?" doesn't become its own
    token); a token's *internal* characters are left alone, so numeric/unit
    terms like ``"0.8"`` or ``"g/kg"`` survive intact.
    """
    tokens = [tok.strip(string.punctuation) for tok in re.split(r"\s+", question.strip())]
    tokens = [tok for tok in tokens if tok]
    return " OR ".join(tokens) if tokens else question


def retrieve_chunks_keyword(
    question: str,
    match_count: int = NUM_CONTEXT_CHUNKS,
    *,
    filter_owner: Optional[str] = None,
    clients: Optional[Clients] = None,
) -> list:
    """Return the ``match_count`` best-matching child rows for ``question``
    by Postgres full-text (keyword/lexical) search, ordered by
    ``ts_rank_cd`` descending (best match first), via the
    ``match_lrm_chunks_keyword`` RPC from
    ``sql/create_lrm_tables.sql``.

    This is ``retrieval.retrieve_chunks()``'s lexical counterpart: it
    matches actual words/numbers in the text (via each chunk's generated
    ``chunk_tsv`` column) rather than embedding-space similarity, so it
    reliably finds a chunk containing an exact term or figure (e.g.
    "0.8 g/kg", "RDA") even when that chunk isn't the closest embedding to
    the question overall. Used on its own it's a plain keyword search;
    combined with ``retrieve_chunks()`` via ``hybrid_search()`` it's the
    "keyword" half of hybrid search.

    ``question`` is passed through ``_as_or_query()`` before being sent as
    the RPC's ``query_text`` -- its words are OR'd together rather than
    sent as-is, so a full natural-language question matches a chunk
    containing *any* of its significant words (ranked by how many/how
    well, via ``ts_rank_cd``) instead of requiring literally all of them,
    which a real question almost never has a chunk that satisfies.

    Rows whose OR'd terms don't match ``question`` at all (Postgres ``@@``
    returns no rows -- only possible if every word was a stopword) are
    simply absent from the result -- unlike vector search, which always
    returns your ``match_count`` nearest neighbors regardless of how
    distant they are.

    ``filter_owner`` restricts retrieval to one source's
    ``lrm_source_table.rowGUID``; leave it ``None`` to search across
    every ingested source.
    """
    clients = clients or get_clients()
    params = {"query_text": _as_or_query(question), "match_count": match_count}
    if filter_owner is not None:
        params["filter_owner"] = filter_owner
    resp = with_retry(
        lambda: clients.supabase.rpc("match_lrm_chunks_keyword", params).execute()
    )
    return resp.data


def reciprocal_rank_fusion(
    ranked_lists: Dict[str, List[dict]],
    *,
    k: int = RRF_K,
    key: str = "rowGUID",
) -> list:
    """Merge several already-ranked lists of rows (each best-first, e.g.
    ``{"dense": retrieve_chunks(q), "keyword": retrieve_chunks_keyword(q)}``)
    into one combined ranking via Reciprocal Rank Fusion:

        rrf_score(row) = sum over lists L containing row of  1 / (k + rank_L(row))

    ``rank_L(row)`` is that row's 1-based position within list ``L``; a row
    missing from a list simply contributes nothing for it -- so a chunk
    that ranks well on just *one* method still surfaces, while one that
    ranks well on *multiple* methods (the case RRF is designed to reward)
    rises further, without either method's raw score scale (cosine
    distance vs. ``ts_rank_cd``) ever needing to be compared directly.

    Each row in the returned list is a **shallow copy** of its first
    occurrence across ``ranked_lists`` (via ``deduplication.
    first_occurrence_map()`` -- the same "first occurrence wins" dedup
    ``parent_chunk_expansion.expand_to_parent_chunks()`` uses for chunks
    sharing a parent), plus one new ``"<name>_rank"`` key per input list
    (``None`` if that method didn't return this row at all) and the
    combined ``"rrf_score"``. Returned rows are sorted by ``rrf_score``
    descending (most cross-method agreement / highest combined rank first).
    """
    # deduplication-step: a row that appears in more than one ranked list
    # (e.g. both "dense" and "keyword") keeps just one representative copy,
    # whichever list saw it first.
    rows_by_key = first_occurrence_map(
        (row for ranked in ranked_lists.values() for row in ranked), key=key
    )

    scores: Dict[object, float] = {}
    per_list_rank: Dict[str, Dict[object, int]] = {name: {} for name in ranked_lists}

    for name, ranked in ranked_lists.items():
        for rank, row in enumerate(ranked, start=1):
            row_key = row[key]
            per_list_rank[name][row_key] = rank
            scores[row_key] = scores.get(row_key, 0.0) + 1.0 / (k + rank)

    fused = []
    for row_key, score in scores.items():
        row_copy = dict(rows_by_key[row_key])
        row_copy["rrf_score"] = score
        for name in ranked_lists:
            row_copy[f"{name}_rank"] = per_list_rank[name].get(row_key)
        fused.append(row_copy)

    fused.sort(key=lambda r: r["rrf_score"], reverse=True)
    return fused


def hybrid_search(
    question: str,
    match_count: int = NUM_CONTEXT_CHUNKS,
    *,
    dense_pool: Optional[int] = None,
    keyword_pool: Optional[int] = None,
    rrf_k: int = RRF_K,
    filter_owner: Optional[str] = None,
    clients: Optional[Clients] = None,
) -> list:
    """Dense (vector) + keyword (full-text) search, merged via Reciprocal
    Rank Fusion -- the "biggest bang for the buck" retrieval upgrade over
    plain ``retrieve_chunks()``: pure embeddings are great at "roughly the
    same topic" but can bury a chunk that contains the exact
    number/terminology the question needs (e.g. "0.8 g/kg RDA") under
    chunks that are merely thematically similar; a keyword search finds
    that exact chunk instantly, because it's matching text, not meaning.
    Running both and fusing the rankings catches whichever case applies,
    without having to guess in advance which method a given question needs.

    Think of it like: dense search = "find me something in the same
    neighborhood," keyword search = "find me the exact house number."

    Like ``rerunk_code.rerank_chunks()``'s over-fetch pattern, each underlying
    search is deliberately given a wider pool than ``match_count`` --
    ``max(match_count * HYBRID_POOL_MULTIPLIER, HYBRID_MIN_POOL)`` by
    default for each of ``dense_pool``/``keyword_pool`` -- *before*
    ``reciprocal_rank_fusion()`` narrows the merged list down to
    ``match_count``, so a chunk only one method would have surfaced in a
    narrower top-K still gets counted.

    Each returned row carries ``"dense_rank"``, ``"keyword_rank"`` (either
    may be ``None``, if that method didn't return the row at all) and
    ``"rrf_score"`` -- see ``reciprocal_rank_fusion()`` for exactly what
    they mean. These are query-time diagnostics only, same as
    ``rerunk_code.rerank_chunks()``'s ``rerank_score``/``retrieval_rank`` --
    nothing is written back to Supabase.
    """
    clients = clients or get_clients()
    pool = max(match_count * HYBRID_POOL_MULTIPLIER, HYBRID_MIN_POOL)
    # retrieval-step (dense half): the same embedding search retrieve_chunks()
    # always does, over a wider pool than match_count so fusion has room to work.
    dense_rows = retrieve_chunks(
        question, match_count=dense_pool or pool, filter_owner=filter_owner, clients=clients
    )
    # retrieval-step (keyword half): Postgres full-text search, over the same
    # kind of wide pool.
    keyword_rows = retrieve_chunks_keyword(
        question, match_count=keyword_pool or pool, filter_owner=filter_owner, clients=clients
    )
    # fusion-step: merge both ranked pools into one via Reciprocal Rank
    # Fusion (reciprocal_rank_fusion() does its own dedup-step internally --
    # see deduplication.py -- for rows both methods returned).
    fused = reciprocal_rank_fusion({"dense": dense_rows, "keyword": keyword_rows}, k=rrf_k)
    return fused[:match_count]
