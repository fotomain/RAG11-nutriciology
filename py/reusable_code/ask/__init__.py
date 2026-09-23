"""Question answering: retrieval, reranking, generation, question language and notebook display.

Modules:
    retrieval     -- embed_query(), retrieve_chunks(), page_numbers_for_chunk(), read_page_row()
    rerunk_code   -- rerank_chunks(), update_rank_value()
    generation    -- ask_question(), build_context_block(), extract_short_answer(), grounding_words()
    language      -- prepare_question(), answer_language_directive(), language_name()
    devanagari    -- romanize_devanagari(), contains_devanagari()
    deduplication -- group_by_key(), first_occurrence_map()
    display       -- show_qa(), show_summary(), answer_html(), format_pages()
"""
