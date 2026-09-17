"""Retrieval + reranking helpers shared by every RAG11 Q&A notebook.

Pipeline shape (see ``stage2_ask_examples2_rerank.ipynb`` for a worked, runnable
example against real nutrition questions):

    1. ``embed_query()``       -- turn a question into a Voyage 'query' embedding
    2. ``retrieve_chunks()``   -- fast, approximate: cosine-similarity top-K
                                  via the ``match_rag11_child_chunks`` RPC
    3. ``rerank_chunks()``     -- optional, slow + precise: Voyage's
                                  cross-encoder reranker re-scores
                                  (question, chunk) pairs jointly and
                                  reorders them
    4. ``update_rank_value()`` -- optional, manual: a person overrides one
                                  chunk's score by hand, entirely
                                  client-side, no schema change required

Steps 1-2 alone are what every earlier stage2 notebook already did. Step 3
is the new "rerank functionality"; step 4 is a manual escape hatch on top
of either.
"""
import re
from typing import Optional

from .clients import Clients, EMBEDDING_MODEL, RERANK_MODEL, get_clients
from .retry import with_retry

MIN_CONTEXT_CHUNKS = 3  # the LLM is always shown at least this many retrieved chunks
NUM_CONTEXT_CHUNKS = 5  # default number of chunks a plain (non-reranked) call returns

# When use_rerank=True, we deliberately over-fetch a wider candidate pool
# via cheap vector search *before* handing it to the expensive reranker --
# this is the "cast a wide net cheaply, then pick precisely" pattern: fetch
# max(final_n * RERANK_POOL_MULTIPLIER, RERANK_MIN_POOL) raw candidates,
# then rerank_chunks() narrows that pool down to final_n.
RERANK_POOL_MULTIPLIER = 4
RERANK_MIN_POOL = 15

_PAGE_RANGE_RE = re.compile(r"Pages (\d+)-(\d+)")


def embed_query(text: str, *, model: str = EMBEDDING_MODEL, clients: Optional[Clients] = None) -> list:
    """Embed a question with ``input_type='query'`` -- Voyage's asymmetric
    embeddings expect the query side and the document side (used when the
    child chunks themselves were embedded in Stage 1.2) to be encoded
    differently for best retrieval quality."""
    clients = clients or get_clients()
    resp = with_retry(clients.voyage.embed, texts=[text], model=model, input_type="query")
    return resp.embeddings[0]


def retrieve_chunks(
    question: str,
    match_count: int = NUM_CONTEXT_CHUNKS,
    *,
    filter_owner: Optional[str] = None,
    clients: Optional[Clients] = None,
) -> list:
    """Return the ``match_count`` best-matching child rows for ``question``,
    ordered by cosine distance ascending (closest first), via the
    ``match_rag11_child_chunks`` RPC from ``sql/create_sql_tables.sql``.

    ``filter_owner`` restricts retrieval to one source's
    ``rag11_data_sources.rowGUID`` (the RPC's own ``filter_owner``
    parameter); leave it ``None`` to search across every ingested source.
    """
    clients = clients or get_clients()
    query_embedding = embed_query(question, clients=clients)
    params = {"query_embedding": query_embedding, "match_count": match_count}
    if filter_owner is not None:
        params["filter_owner"] = filter_owner
    resp = with_retry(lambda: clients.supabase.rpc("match_rag11_child_chunks", params).execute())
    return resp.data


def page_numbers_for_chunk(row: dict) -> list:
    """Parse the inclusive page range out of a child row's contextual
    header, e.g. ``'[Source: foo.pdf | Section: Bar | Pages 12-14]'`` ->
    ``[12, 13, 14]``. Every child chunk carries this header (see
    ``contextual_header()`` in ``stage1_1_extract_and_chunk.ipynb``), so
    this needs no extra DB lookup against the parent row."""
    text = row.get("rowJSON", {}).get("text", "")
    match = _PAGE_RANGE_RE.search(text)
    if not match:
        return []
    start_page, end_page = int(match.group(1)), int(match.group(2))
    return list(range(start_page, end_page + 1))


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

    Why this exists: ``retrieve_chunks()`` already gives you a cheap top-K
    by *embedding distance* -- fast, but only a rough proxy, because a
    query and a chunk are embedded completely independently of each other.
    A reranker instead looks at the question and one candidate chunk
    *together* and scores how well that specific chunk actually answers
    that specific question, which is slower (it can't be precomputed the
    way an embedding can) but far more precise. The standard pattern --
    used here -- is: cast a wide, cheap net with ``retrieve_chunks()``,
    then use this to pick the truly best few out of that pool.

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
    RPC, or migration -- ``rag11_chunks_child_table.rowJSON`` is already a
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
            lambda: clients.supabase.table("rag11_chunks_child_table")
            .select("rowJSON")
            .eq("rowGUID", row_guid)
            .single()
            .execute()
        )
        merged_json = {**current.data["rowJSON"], **manual_json_patch}
        with_retry(
            lambda: clients.supabase.table("rag11_chunks_child_table")
            .update({"rowJSON": merged_json})
            .eq("rowGUID", row_guid)
            .execute()
        )

    return updated
