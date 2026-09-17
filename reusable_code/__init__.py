"""RAG11 Nutrition -- shared, importable building blocks for every
notebook in this repo (Stage 1.2 onward): client construction, retrieval,
reranking, generation, and the git-sync helper.

Usage from any notebook, right after its own ``%pip install`` cell::

    from reusable_code import init_clients, ask_question

    clients = init_clients()
    result = ask_question("Is vitamin C a water-soluble vitamin?", use_rerank=True)

See ``reusable_code/README.md`` for the full guide (including exactly how
-- and whether -- you need to touch the Supabase tables), and
``stage2_ask_examples2_rerank.ipynb`` for a worked example of the reranking
functions specifically.
"""
from .clients import (
    Clients,
    EMBEDDING_MODEL,
    GENERATION_MODEL,
    RERANK_MODEL,
    get_clients,
    init_clients,
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
from .generation import (
    MAX_ANSWER_TOKENS,
    SYSTEM_PROMPT,
    ask_question,
    build_context_block,
    extract_short_answer,
    grounding_words,
)
from .git_sync import save_to_github
from .retrieval import (
    MIN_CONTEXT_CHUNKS,
    NUM_CONTEXT_CHUNKS,
    RERANK_MIN_POOL,
    RERANK_POOL_MULTIPLIER,
    embed_query,
    page_numbers_for_chunk,
    rerank_chunks,
    retrieve_chunks,
    update_rank_value,
)
from .retry import with_retry

__all__ = [
    "Clients",
    "init_clients",
    "get_clients",
    "EMBEDDING_MODEL",
    "RERANK_MODEL",
    "GENERATION_MODEL",
    "with_retry",
    "MIN_CONTEXT_CHUNKS",
    "NUM_CONTEXT_CHUNKS",
    "RERANK_POOL_MULTIPLIER",
    "RERANK_MIN_POOL",
    "embed_query",
    "retrieve_chunks",
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
]
