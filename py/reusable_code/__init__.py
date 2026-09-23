"""LRM11 -- shared, importable building blocks for every LRM notebook:
client construction, retrieval, hybrid (dense + keyword) search,
hypothetical document embeddings (HyDE), reranking, page expansion,
generation, and the git-sync helper.

Usage from any notebook, right after its own ``%pip install`` cell::

    from reusable_code import init_clients, ask_question

    clients = init_clients()
    result = ask_question("What does the Yoga-Sutra say about ahimsa?")

``ask_question()`` runs hybrid search, HyDE-vs-multi-query retrieval, and
page expansion by default -- each is controlled by a
USE_HYBRID_SEARCH / USE_HYPOTHETICAL_DOCUMENT_EMBEDDING /
USE_MULTI_QUERY_QUESTION_SPLITTING / USE_PARENT_CHUNK_EXPANSION flag in
.env (see config.py), all ``True`` if left unset. Set any of them to
``False`` in .env to fall back to that technique's simplest variant with
no code changes, or override per call with an explicit keyword (e.g.
``use_hybrid=False``) regardless of what .env says.

See ``reusable_code/README.md`` for the full guide (including exactly how
-- and whether -- you need to touch the Supabase tables),
``py/ipynb/stage2_ask_examples3_hybrid_search.ipynb`` for a worked example
of the hybrid-search functions specifically,
``py/ipynb/stage2_ask_examples2_rerank.ipynb`` for a worked example of the
reranking functions, ``py/ipynb/stage2_ask_examples4_parent_chunk_expansion.ipynb``
for a worked example of page expansion, and
``py/ipynb/stage2_ask_examples5_hypothetical_document_embedding.ipynb`` for
a worked example of HyDE.
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
    REASONING_MAX_STEPS,
    REASONING_MAX_THINKING_TOKENS,
    REASONING_MODEL,
    REASONING_SELF_CHECK,
    SPEAKING_LANGUAGE,
    USE_HYBRID_SEARCH,
    USE_HYPOTHETICAL_DOCUMENT_EMBEDDING,
    USE_MULTI_QUERY_QUESTION_SPLITTING,
    USE_PARENT_CHUNK_EXPANSION,
    USE_REASONING,
)
from .ask.deduplication import (
    first_occurrence_map,
    group_by_key,
)
from .ask.generation import (
    MAX_ANSWER_TOKENS,
    SYSTEM_PROMPT,
    ask_question,
    build_context_block,
    extract_short_answer,
    grounding_words,
)
from .ask.devanagari import contains_devanagari, romanize_devanagari
from .ask.display import (
    answer_html,
    format_pages,
    qa_card_html,
    show_qa,
    show_summary,
    summary_table_html,
)
from .ask.language import (
    PreparedQuestion,
    answer_language_directive,
    language_name,
    prepare_question,
)
from .git_sync import save_to_github
from .reasoning import ask_with_reasoning
from .eda.transform.hybrid_search import (
    HYBRID_MIN_POOL,
    HYBRID_POOL_MULTIPLIER,
    RRF_K,
    hybrid_search,
    reciprocal_rank_fusion,
    retrieve_chunks_keyword,
)
from .eda.transform.hypothetical_document_embedding import (
    HYDE_MAX_TOKENS,
    HYDE_SYSTEM_PROMPT,
    embed_hypothetical_document,
    generate_hypothetical_document,
    retrieve_chunks_hyde,
)
from .eda.transform.multi_query_question_splitting import (
    MAX_SUBQUESTIONS,
    MULTI_QUERY_MAX_TOKENS,
    MULTI_QUERY_MIN_POOL,
    MULTI_QUERY_POOL_MULTIPLIER,
    MULTI_QUERY_SYSTEM_PROMPT,
    retrieve_chunks_multi_query,
    split_into_subquestions,
)
from .eda.transform.parent_chunk_expansion import (
    DEFAULT_MAX_PARENT_CHARS,
    build_expanded_context_block,
    expand_to_parent_chunks,
    page_numbers_for_expanded_chunk,
)
from .ask.rerunk_code import (
    RERANK_MIN_POOL,
    RERANK_POOL_MULTIPLIER,
    rerank_chunks,
    update_rank_value,
)
from .ask.retrieval import (
    MIN_CONTEXT_CHUNKS,
    NUM_CONTEXT_CHUNKS,
    embed_query,
    page_numbers_for_chunk,
    read_page_row,
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
    "contains_devanagari",
    "romanize_devanagari",
    "SPEAKING_LANGUAGE",
    "PreparedQuestion",
    "answer_language_directive",
    "language_name",
    "prepare_question",
    "answer_html",
    "format_pages",
    "qa_card_html",
    "show_qa",
    "show_summary",
    "summary_table_html",
    "read_page_row",
    "group_by_key",
    "first_occurrence_map",
    "ask_with_reasoning",
    "USE_REASONING",
    "REASONING_MODEL",
    "REASONING_MAX_STEPS",
    "REASONING_MAX_THINKING_TOKENS",
    "REASONING_SELF_CHECK",
]
