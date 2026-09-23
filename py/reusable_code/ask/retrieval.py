"""Retrieval helpers shared by every LRM11 Q&A notebook.

Pipeline shape (see ``stage2_ask_examples2_rerank.ipynb`` and
``stage2_ask_examples3_hybrid_search.ipynb`` for worked, runnable examples
against real LRM book questions):

    1. ``embed_query()``       -- turn a question into a Voyage 'query' embedding
    2. ``retrieve_chunks()``   -- fast, approximate: cosine-similarity top-K
                                  via the ``match_lrm_chunks`` RPC
                                  (dense/semantic retrieval)
    2b. ``hybrid_search.hybrid_search()`` -- optional, complementary: fuses
                                  this with Postgres full-text (keyword)
                                  search via Reciprocal Rank Fusion -- see
                                  ``hybrid_search.py``, the module this
                                  functionality lives in
    3. ``rerunk_code.rerank_chunks()`` -- optional, slow + precise: Voyage's
                                  cross-encoder reranker re-scores
                                  (question, chunk) pairs jointly and
                                  reorders them -- can run on top of either
                                  2 or 2b's output; see ``rerunk_code.py``,
                                  the module this functionality lives in
    4. ``rerunk_code.update_rank_value()`` -- optional, manual: a person
                                  overrides one chunk's score by hand,
                                  entirely client-side, no schema change
                                  required

Steps 1-2 alone are what every earlier stage2 notebook already did. Step 2b
is the "hybrid search" functionality (in ``hybrid_search.py``); steps 3-4
are the reranking functionality (in ``rerunk_code.py``).
"""
from typing import Optional

from ..clients import Clients, EMBEDDING_MODEL, get_clients
from ..retry import with_retry

MIN_CONTEXT_CHUNKS = 3  # the LLM is always shown at least this many retrieved chunks
NUM_CONTEXT_CHUNKS = 5  # default number of chunks a plain (non-reranked) call returns


def embed_query(text: str, *, model: str = EMBEDDING_MODEL, clients: Optional[Clients] = None) -> list:
    """Embed a question with ``input_type='query'`` -- Voyage's asymmetric
    embeddings expect the query side and the document side (used when
    ``lrm_child_chunk_table`` rows themselves were embedded) to be encoded
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
    ``match_lrm_chunks`` RPC from ``sql/create_lrm_tables.sql``.

    ``filter_owner`` restricts retrieval to one source's
    ``lrm_source_table.rowGUID`` (the RPC's own ``filter_owner``
    parameter); leave it ``None`` to search across every ingested source.
    """
    clients = clients or get_clients()
    query_embedding = embed_query(question, clients=clients)
    params = {"query_embedding": query_embedding, "match_count": match_count}
    if filter_owner is not None:
        params["filter_owner"] = filter_owner
    resp = with_retry(lambda: clients.supabase.rpc("match_lrm_chunks", params).execute())
    return resp.data


def page_numbers_for_chunk(row: dict) -> list:
    """The one page an ``lrm_child_chunk_table`` row belongs to, as a single-element
    list (kept as a list, not an int, so callers that expect "the page
    range a chunk covers" -- e.g. citation formatting shared with
    ``page_numbers_for_expanded_chunk()`` -- don't need a special case).
    A chunk never spans more than one page, and ``page_number`` is already a plain column on
    ``rowJSON`` (see ``sql/create_lrm_tables.sql``), so no text parsing or
    extra DB lookup is needed."""
    page_number = row.get("rowJSON", {}).get("page_number")
    return [page_number] if page_number is not None else []


def read_page_row(row_guid: str, *, clients: Optional[Clients] = None) -> Optional[dict]:
    """Fetch one ``lrm_page_table`` row by its ``rowGUID``, or ``None`` if it
    doesn't exist. Plain REST call, same shape as ``get_lrm_page()`` (the
    RPC in ``sql/create_lrm_tables.sql``) -- used by
    ``parent_chunk_expansion.expand_to_parent_chunks()`` to fetch the full
    page a matched chunk came from."""
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.supabase.table("lrm_page_table").select("*").eq("rowGUID", row_guid).execute()
    )
    return resp.data[0] if resp.data else None

