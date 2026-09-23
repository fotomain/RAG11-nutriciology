"""Retrieval-stage transforms: hybrid search, HyDE, multi-query splitting, parent-chunk expansion.

Modules:
    hybrid_search                   -- hybrid_search(), reciprocal_rank_fusion(): dense + keyword search fused via RRF
    hypothetical_document_embedding -- retrieve_chunks_hyde(): HyDE retrieval
    multi_query_question_splitting  -- retrieve_chunks_multi_query(): split a question into sub-queries, fuse results
    parent_chunk_expansion          -- expand_to_parent_chunks(): small-to-big context expansion
"""
