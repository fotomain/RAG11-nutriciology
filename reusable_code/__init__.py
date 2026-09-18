"""RAG11 Nutrition -- shared, importable building blocks for every
notebook in this repo (Stage 1.2 onward): client construction, retrieval,
hybrid (dense + keyword) search, hypothetical document embeddings (HyDE),
reranking, parent-chunk expansion, generation, and the git-sync helper.

Usage from any notebook, right after its own ``%pip install`` cell::

    from reusable_code import init_clients, ask_question

    clients = init_clients()
    result = ask_question("Is vitamin C a water-soluble vitamin?")

``ask_question()`` runs hybrid search, HyDE-vs-multi-query retrieval, and
parent-chunk expansion by default -- each is controlled by a
USE_HYBRID_SEARCH / USE_HYPOTHETICAL_DOCUMENT_EMBEDDING /
USE_MULTI_QUERY_QUESTION_SPLITTING / USE_PARENT_CHUNK_EXPANSION flag in
.env (see config.py), all ``True`` if left unset. Set any of them to
``False`` in .env to fall back to that technique's simplest variant with
no code changes, or override per call with an explicit keyword (e.g.
``use_hybrid=False``) regardless of what .env says.

See ``reusable_code/README.md`` for the full guide (including exactly how
-- and whether -- you need to touch the Supabase tables),
``stage2_ask_examples3_hybrid_search.ipynb`` for a worked example of the
hybrid-search functions specifically,
``stage2_ask_examples2_rerank.ipynb`` for a worked example of the reranking
functions, ``stage2_ask_examples4_parent_chunk_expansion.ipynb`` for a
worked example of parent-chunk expansion, and
``stage2_ask_examples5_hypothetical_document_embedding.ipynb`` for a worked
example of HyDE.
"""
from .clients import (
    Clients,
    EMBEDDING_MODEL,
    GENERATION_MODEL,
    RERANK_MODEL,
    get_clients,
    init_clients,
)
from .config import (
    USE_HYBRID_SEARCH,
    USE_HYPOTHETICAL_DOCUMENT_EMBEDDING,
    USE_MULTI_QUERY_QUESTION_SPLITTING,
    USE_PARENT_CHUNK_EXPANSION,
)
from .crud_chunks_child import (
    CHILD_TABLE,
    create_child_payload,
    create_child_row,
    create_child_rows,
    delete_child_row,
    delete_child_rows_by_owner,
    delete_child_rows_by_parent,
    read_all_child_rows,
    read_child_row,
    read_child_rows_by_owner,
    read_child_rows_by_parent,
    update_child_embedding,
    update_child_rowjson,
)
from .crud_chunks_parent import (
    PARENT_TABLE,
    RAG11_UUID_NAMESPACE,
    create_parent_payload,
    create_parent_row,
    create_parent_rows,
    delete_parent_row,
    delete_parent_rows_by_owner,
    deterministic_uuid,
    read_all_parent_rows,
    read_parent_row,
    read_parent_rows_by_owner,
    update_parent_rowjson,
)
from .deduplication import (
    first_occurrence_map,
    group_by_key,
)
from .generation import (
    MAX_ANSWER_TOKENS,
    SYSTEM_PROMPT,
    ask_question,
    build_context_block,
    extract_short_answer,
    grounding_words,
)
from .git_sync import save_to_github
from .hybrid_search import (
    HYBRID_MIN_POOL,
    HYBRID_POOL_MULTIPLIER,
    RRF_K,
    hybrid_search,
    reciprocal_rank_fusion,
    retrieve_chunks_keyword,
)
from .hypothetical_document_embedding import (
    HYDE_MAX_TOKENS,
    HYDE_SYSTEM_PROMPT,
    embed_hypothetical_document,
    generate_hypothetical_document,
    retrieve_chunks_hyde,
)
from .multi_query_question_splitting import (
    MAX_SUBQUESTIONS,
    MULTI_QUERY_MAX_TOKENS,
    MULTI_QUERY_MIN_POOL,
    MULTI_QUERY_POOL_MULTIPLIER,
    MULTI_QUERY_SYSTEM_PROMPT,
    retrieve_chunks_multi_query,
    split_into_subquestions,
)
from .parent_chunk_expansion import (
    DEFAULT_MAX_PARENT_CHARS,
    build_expanded_context_block,
    expand_to_parent_chunks,
    page_numbers_for_expanded_chunk,
)
from .rerunk_code import (
    RERANK_MIN_POOL,
    RERANK_POOL_MULTIPLIER,
    rerank_chunks,
    update_rank_value,
)
from .retrieval import (
    MIN_CONTEXT_CHUNKS,
    NUM_CONTEXT_CHUNKS,
    embed_query,
    page_numbers_for_chunk,
    retrieve_chunks,
)
from .retry import with_retry

__all__ = [
    "Clients",
    "init_clients",
    "get_clients",
    "EMBEDDING_MODEL",
    "RERANK_MODEL",
    "GENERATION_MODEL",
    "USE_HYBRID_SEARCH",
    "USE_PARENT_CHUNK_EXPANSION",
    "USE_MULTI_QUERY_QUESTION_SPLITTING",
    "USE_HYPOTHETICAL_DOCUMENT_EMBEDDING",
    "with_retry",
    "MIN_CONTEXT_CHUNKS",
    "NUM_CONTEXT_CHUNKS",
    "RERANK_POOL_MULTIPLIER",
    "RERANK_MIN_POOL",
    "HYBRID_POOL_MULTIPLIER",
    "HYBRID_MIN_POOL",
    "RRF_K",
    "embed_query",
    "retrieve_chunks",
    "retrieve_chunks_keyword",
    "reciprocal_rank_fusion",
    "hybrid_search",
    "HYDE_MAX_TOKENS",
    "HYDE_SYSTEM_PROMPT",
    "generate_hypothetical_document",
    "embed_hypothetical_document",
    "retrieve_chunks_hyde",
    "MAX_SUBQUESTIONS",
    "MULTI_QUERY_MAX_TOKENS",
    "MULTI_QUERY_POOL_MULTIPLIER",
    "MULTI_QUERY_MIN_POOL",
    "MULTI_QUERY_SYSTEM_PROMPT",
    "split_into_subquestions",
    "retrieve_chunks_multi_query",
    "DEFAULT_MAX_PARENT_CHARS",
    "expand_to_parent_chunks",
    "build_expanded_context_block",
    "page_numbers_for_expanded_chunk",
    "page_numbers_for_chunk",
    "rerank_chunks",
    "update_rank_value",
    "SYSTEM_PROMPT",
    "MAX_ANSWER_TOKENS",
    "build_context_block",
    "extract_short_answer",
    "grounding_words",
    "ask_question",
    "save_to_github",
    "PARENT_TABLE",
    "RAG11_UUID_NAMESPACE",
    "deterministic_uuid",
    "create_parent_payload",
    "create_parent_rows",
    "create_parent_row",
    "read_parent_row",
    "read_parent_rows_by_owner",
    "read_all_parent_rows",
    "update_parent_rowjson",
    "delete_parent_row",
    "delete_parent_rows_by_owner",
    "CHILD_TABLE",
    "create_child_payload",
    "create_child_rows",
    "create_child_row",
    "read_child_row",
    "read_child_rows_by_parent",
    "read_child_rows_by_owner",
    "read_all_child_rows",
    "update_child_rowjson",
    "update_child_embedding",
    "delete_child_row",
    "delete_child_rows_by_parent",
    "delete_child_rows_by_owner",
    "group_by_key",
    "first_occurrence_map",
]
