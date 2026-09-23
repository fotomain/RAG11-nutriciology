"""RAG technique feature flags, read once from .env at import time.

Each flag controls whether ``ask_question()`` (generation.py) defaults to
the advanced retrieval technique or the simplest version of the code path
it replaces. All four default to ``True`` when unset in .env, so a fresh
checkout demonstrates the full pipeline out of the box; flip any of them
to ``False`` in .env to fall back to that technique's simplest variant
without touching code:

    USE_HYBRID_SEARCH=False                    -> plain vector search
    USE_PARENT_CHUNK_EXPANSION=False           -> child chunks only, no expansion
    USE_MULTI_QUERY_QUESTION_SPLITTING=False   -> the question is searched as-is
    USE_HYPOTHETICAL_DOCUMENT_EMBEDDING=False  -> search embeds the bare question

These are defaults only -- any explicit ``use_hybrid=``/``expand_to_parents=``/
etc. keyword passed to ``ask_question()`` still overrides them, which is how
stage2_ask_examples2..6 demonstrate each technique in isolation regardless
of what .env is set to.
"""
from .env import optional_env, optional_env_bool, optional_env_int

USE_HYBRID_SEARCH = optional_env_bool("USE_HYBRID_SEARCH", True)
USE_PARENT_CHUNK_EXPANSION = optional_env_bool("USE_PARENT_CHUNK_EXPANSION", True)
USE_MULTI_QUERY_QUESTION_SPLITTING = optional_env_bool("USE_MULTI_QUERY_QUESTION_SPLITTING", True)
USE_HYPOTHETICAL_DOCUMENT_EMBEDDING = optional_env_bool("USE_HYPOTHETICAL_DOCUMENT_EMBEDDING", True)

# Language every answer is written in, whatever language/script the question uses
# (ISO 639-1 code, e.g. EN, FR, DE, HI). See language.py.
SPEAKING_LANGUAGE = (optional_env("SPEAKING_LANGUAGE", "EN") or "EN").upper()

# reasoning/ (multi-step plan -> retrieve -> draft -> self-check-against-citations -> revise,
# on top of plain ask_question()). Off by default: slower and more expensive than a single
# ask_question() call, so it's opt-in rather than the default path like the four flags above.
USE_REASONING = optional_env_bool("USE_REASONING", False)
REASONING_MODEL = optional_env("REASONING_MODEL", "claude-sonnet-5") or "claude-sonnet-5"
REASONING_MAX_STEPS = optional_env_int("REASONING_MAX_STEPS", 4, minimum=1)
REASONING_MAX_THINKING_TOKENS = optional_env_int("REASONING_MAX_THINKING_TOKENS", 4000, minimum=1024)
REASONING_SELF_CHECK = optional_env_bool("REASONING_SELF_CHECK", True)
