"""Reranking + manual rank overrides for ``lrm_child_chunk_table`` --
the retrieval-method counterpart to ``hybrid_search.py``, living in its own
module the same way hybrid search lives in ``hybrid_search.py`` instead of
being folded into ``retrieval.py`` itself.

Two functions, both operating on an already-retrieved list of rows (from
``retrieval.retrieve_chunks()`` and/or ``hybrid_search.hybrid_search()``):

    - ``rerank_chunks()`` -- Voyage's cross-encoder reranker re-scores
      (question, chunk) pairs jointly and reorders them. What
      ``generation.ask_question(..., use_rerank=True)`` calls.
    - ``update_rank_value()`` -- a person manually overrides one chunk's
      relevance score, entirely client-side by default.

See ``stage2_ask_examples2_rerank.ipynb`` for worked nutrition examples and
``reusable_code/README.md`` for the "what rerank adds" write-up.
"""
from typing import Optional

from .clients import Clients, RERANK_MODEL, get_clients
from .retry import with_retry

# Same "cast a wide net cheaply" idea hybrid_search.py's HYBRID_POOL_MULTIPLIER/
# HYBRID_MIN_POOL use for hybrid_search(): over-fetch
# max(final_n * RERANK_POOL_MULTIPLIER, RERANK_MIN_POOL) raw candidates via
# retrieve_chunks() *before* rerank_chunks() narrows that pool down to final_n.
RERANK_POOL_MULTIPLIER = 4
RERANK_MIN_POOL = 15


def rerank_chunks(
    question: str,
    chunks: list,
    top_n: Optional[int] = None,
    *,
    model: str = RERANK_MODEL,
    clients: Optional[Clients] = None,
) -> list:
    """Re-score ``chunks`` against ``question`` with Voyage's cross-encoder
    reranker and return them reordered by actual relevance, most relevant
    first.

    Why this exists: ``retrieval.retrieve_chunks()`` already gives you a
    cheap top-K by *embedding distance* -- fast, but only a rough proxy,
    because a query and a chunk are embedded completely independently of
    each other. A reranker instead looks at the question and one candidate
    chunk *together* and scores how well that specific chunk actually
    answers that specific question, which is slower (it can't be
    precomputed the way an embedding can) but far more precise. The
    standard pattern -- used here -- is: cast a wide, cheap net with
    ``retrieve_chunks()``, then use this to pick the truly best few out of
    that pool.

    Each returned row is a **shallow copy** of its input row (the objects
    you passed in are never mutated) with two new top-level keys. These
    are query-time diagnostics only -- they are NOT written into rowJSON
    and do NOT require any table/column change, since they only exist for
    the life of this Python list:
        - ``"rerank_score"``:   Voyage's relevance score for (question, chunk)
        - ``"retrieval_rank"``: this chunk's 1-based position *before*
                                 reranking (i.e. its index in the `chunks`
                                 list you passed in)

    ``top_n`` defaults to ``len(chunks)`` (everything, just reordered);
    pass a smaller number to also cut the list down -- e.g. rerank 20
    candidates from a wide ``retrieve_chunks()`` call down to the best 5.
    """
    if not chunks:
        return []
    clients = clients or get_clients()
    documents = [row["rowJSON"]["text"] for row in chunks]
    n = top_n if top_n is not None else len(chunks)
    # rerank-step: Voyage's cross-encoder scores (question, chunk) jointly,
    # unlike the independent embeddings retrieve_chunks()/hybrid_search()
    # ranked by -- the actual re-scoring this whole module exists to do.
    resp = with_retry(
        clients.voyage.rerank,
        query=question,
        documents=documents,
        model=model,
        top_k=min(n, len(documents)),
    )
    reranked = []
    for result in resp.results:
        row_copy = dict(chunks[result.index])
        row_copy["rerank_score"] = result.relevance_score
        row_copy["retrieval_rank"] = result.index + 1
        reranked.append(row_copy)
    return reranked


def update_rank_value(
    chunks: list,
    row_guid: str,
    new_value: float,
    *,
    reason: Optional[str] = None,
    resort: bool = True,
    persist: bool = False,
    clients: Optional[Clients] = None,
) -> list:
    """Let a person manually override one retrieved/reranked chunk's
    relevance score.

    By default this is **entirely client-side and in-memory**: it does not
    require, and does not create, any stored server-side ranking column,
    RPC, or migration -- ``lrm_child_chunk_table.rowJSON`` is already a
    schemaless ``jsonb`` column, so nothing about the tables needs to
    change for this function to work at all. It just sets
    ``"manual_rank_score"`` (and, if given, ``"manual_rank_reason"``) on a
    copy of the matching row and, by default, re-sorts the list so the
    override actually takes effect on what a caller sees next (e.g. what
    ``build_context_block()``/``ask_question()`` send to the LLM).

    Sort precedence once at least one row carries a manual override:
    ``manual_rank_score`` (if set) beats ``rerank_score`` (if set) beats
    the raw ``cosine_distance`` retrieve_chunks() returned -- i.e. a human
    correction always wins over the automatic ranking it's correcting.

    Args:
        chunks: the list previously returned by retrieve_chunks() and/or
            rerank_chunks() -- NOT mutated; a new list is returned.
        row_guid: the ``rowGUID`` of the chunk to override (must already be
            present in ``chunks`` -- this reorders what you retrieved, it
            does not fetch a new chunk by id).
        new_value: the relevance score to force for that chunk. Use a
            value on the same scale as whatever score you're overriding
            (e.g. match rerank_score's roughly-0..1 range if the list also
            has reranked rows) so the resort behaves sensibly.
        reason: optional free-text note, stored alongside the override
            (and persisted with it, if ``persist=True``) so it's clear
            later *why* a human stepped in.
        resort: if True (default), re-sort the returned list by the
            precedence above. Set False to keep the original order and
            just annotate the one row.
        persist: if True, also write the override into that row's real
            ``rowJSON`` in Supabase -- an ordinary ``UPDATE`` that merges
            ``manual_rank_score``/``manual_rank_reason`` into the existing
            jsonb value (no ``ALTER TABLE`` needed). Requires a
            ``clients.supabase`` built with a key that has UPDATE rights
            (the service_role key -- see ``init_clients()``'s docstring).
            Off by default, per the "must work without stored server-side
            factors if possible" requirement -- turn it on only if you
            want the override to survive past this notebook run.
        clients: only needed when ``persist=True`` (to reach Supabase);
            defaults to ``get_clients()``.

    Returns:
        A new list of shallow-copied row dicts with the override applied
        (and, if resort=True, reordered).
    """
    updated = []
    found = False
    manual_json_patch = None
    for row in chunks:
        row_copy = dict(row)
        if row_copy.get("rowGUID") == row_guid:
            row_copy["manual_rank_score"] = new_value
            if reason is not None:
                row_copy["manual_rank_reason"] = reason
            found = True
            manual_json_patch = {"manual_rank_score": new_value}
            if reason is not None:
                manual_json_patch["manual_rank_reason"] = reason
        updated.append(row_copy)

    if not found:
        raise ValueError(
            f"No chunk with rowGUID={row_guid!r} in the given list -- "
            f"update_rank_value() only reorders what you already retrieved, "
            f"it doesn't fetch a chunk by id."
        )

    if resort:

        def sort_key(row):
            if "manual_rank_score" in row:
                return -row["manual_rank_score"]
            if "rerank_score" in row:
                return -row["rerank_score"]
            return row.get("cosine_distance", 0.0)

        updated.sort(key=sort_key)

    if persist:
        clients = clients or get_clients()
        # rowJSON has no fixed schema, so merging a new key into it is an
        # ordinary UPDATE, not a migration. Two round trips (read the
        # current rowJSON, write the merged copy back) because supabase-py's
        # REST update() takes a full replacement value for a jsonb column,
        # not a partial `||` merge expression the way raw SQL could.
        current = with_retry(
            lambda: clients.supabase.table("lrm_child_chunk_table")
            .select("rowJSON")
            .eq("rowGUID", row_guid)
            .single()
            .execute()
        )
        merged_json = {**current.data["rowJSON"], **manual_json_patch}
        with_retry(
            lambda: clients.supabase.table("lrm_child_chunk_table")
            .update({"rowJSON": merged_json})
            .eq("rowGUID", row_guid)
            .execute()
        )

    return updated
