"""Retrieval helpers shared by every RAG11 Q&A notebook.

Pipeline shape (see ``stage2_ask_examples2_rerank.ipynb`` and
``stage2_ask_examples3_hybrid_search.ipynb`` for worked, runnable examples
against real nutrition questions):

    1. ``embed_query()``       -- turn a question into a Voyage 'query' embedding
    2. ``retrieve_chunks()``   -- fast, approximate: cosine-similarity top-K
                                  via the ``match_rag11_child_chunks`` RPC
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
import re
from typing import Optional

from .clients import Clients, EMBEDDING_MODEL, get_clients
from .retry import with_retry

MIN_CONTEXT_CHUNKS = 3  # the LLM is always shown at least this many retrieved chunks
NUM_CONTEXT_CHUNKS = 5  # default number of chunks a plain (non-reranked) call returns

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
    ``contextual_header()`` in ``stage1_1_eda_extract_and_chunk.ipynb``), so
    this needs no extra DB lookup against the parent row."""
    text = row.get("rowJSON", {}).get("text", "")
    match = _PAGE_RANGE_RE.search(text)
    if not match:
        return []
    start_page, end_page = int(match.group(1)), int(match.group(2))
    return list(range(start_page, end_page + 1))

