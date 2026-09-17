"""Parent-chunk expansion ("small-to-big") for ``rag11_chunks_child_table``
results -- the retrieval-stage counterpart to ``hybrid_search.py`` and
``rerunk_code.py``'s ``rerank_chunks()``, living in its own module the same
way those do, instead of being folded into ``retrieval.py``/``generation.py``
themselves.

The problem this solves: child chunks are deliberately small (~300-500
tokens, see ``stage1_1_extract_and_chunk.ipynb``) so they match a question
precisely, but a small chunk sometimes doesn't carry enough surrounding
context to answer the question fully.

Example: the question "How does soluble fiber's effect on LDL cholesterol
differ from insoluble fiber's effect?" might retrieve, as its best-reranked
child chunk, just two sentences: "Soluble fiber binds bile acids in the gut,
which forces the liver to pull more LDL cholesterol from the blood to make
more bile acids." That's a great match for half the question, but says
nothing about insoluble fiber -- the comparison Claude needs is incomplete.
Every child chunk's ``rowParentGUID`` (a real foreign key -- see
``sql/create_sql_tables.sql``) already points at a bigger parent chunk from
Stage 1.1: the full section the child chunk was carved out of, which
usually discusses both sides of a comparison like this together.

The fix, and what this module does: after retrieval (plain, hybrid, and/or
reranked -- ``expand_to_parent_chunks()`` doesn't care which one produced
its input), swap each winning child chunk's text for its parent chunk's
text before building the context block Claude sees. The small chunk finds
the needle; the parent chunk gives the whole haystack around the needle so
the comparison isn't cut off mid-thought.

    - ``expand_to_parent_chunks()`` -- the swap itself: fetches each input
      chunk's parent row (via ``crud_chunks_parent.read_parent_row()``,
      keyed off ``rowParentGUID``), dedupes when several winning child
      chunks share the same parent (a very common case for a "compare X and
      Y" question, whose best-matching child chunks often come from the
      same section), and keeps each surviving row's original ranking
      metadata (``rerank_score`` / ``rrf_score`` / ``cosine_distance`` /
      ``dense_rank`` / ... -- whatever the input already carried) so it
      still sorts and prints the same way downstream.
    - ``build_expanded_context_block()`` --
      ``generation.build_context_block()``'s counterpart for expanded rows:
      same numbered-excerpt shape Claude already expects, plus (for
      human/debugging visibility only) the parent section's title and how
      many originally-matched child chunks it's standing in for.
    - ``page_numbers_for_expanded_chunk()`` --
      ``retrieval.page_numbers_for_chunk()``'s counterpart: a parent
      chunk's ``rowJSON`` carries its own ``start_page``/``end_page``
      fields directly (``stage1_1_extract_and_chunk.ipynb``), rather than
      the ``"[... | Pages N-M]"`` header ``contextual_header()`` only
      stamps onto child chunk text, so it can't be found by that regex.

See ``stage2_ask_examples4_parent_chunk_expansion.ipynb`` for worked
nutrition examples,
``documentation/HOW_IT_WORKS_Parent_Chunk_Expansion.html`` for the full
write-up, and ``reusable_code/README.md`` for the one-paragraph summary. No
schema or migration change is needed -- ``rag11_chunks_parent_table`` and
its ``rowParentGUID`` foreign key already exist
(``sql/create_sql_tables.sql``).
"""
from typing import List, Optional

from .clients import Clients, get_clients
from .crud_chunks_parent import read_parent_row
from .retrieval import page_numbers_for_chunk

# A parent chunk is a whole book *section* (stage1_1_extract_and_chunk.ipynb
# builds parent chunks by section, not by a fixed token budget the way
# child chunks are), so a section can run to several thousand words --
# dwarfing the ~300-500 tokens a child chunk is capped at. Truncating keeps
# one expanded parent from silently eating the whole context-window budget
# build_context_block()/ask_question() have to share across every excerpt.
# ~1500 tokens (English prose runs roughly 4 chars/token).
DEFAULT_MAX_PARENT_CHARS = 6000


def _truncate(text: str, max_chars: Optional[int]) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n...[parent chunk truncated for length]"


def expand_to_parent_chunks(
    chunks: List[dict],
    *,
    max_parent_chars: Optional[int] = DEFAULT_MAX_PARENT_CHARS,
    clients: Optional[Clients] = None,
) -> List[dict]:
    """Swap each input chunk's text for its parent chunk's text ("small
    chunk finds the needle, parent chunk gives the whole haystack around
    it") -- see this module's docstring for the full fiber/LDL example.

    ``chunks`` is whatever a prior retrieval step already returned --
    ``retrieve_chunks()``, ``hybrid_search()``, and/or ``rerank_chunks()``
    output are all the same row shape, so this composes with any of them
    (or all three; put it *last*, right before ``build_context_block()``/
    ``build_expanded_context_block()``, since it needs each input row's
    ``rowParentGUID`` and doesn't itself change ranking).

    Two or more input chunks that share the same ``rowParentGUID`` (common
    for a "compare X and Y" question, whose best-matching child chunks
    often come from the same section) collapse into **one** expanded row --
    the parent is only fetched, and only sent to Claude, once. The
    surviving row is a shallow copy of the *first* (best-ranked, since
    every retrieval method here returns best-first) chunk that matched that
    parent, so whatever ranking fields it already carried
    (``rerank_score``, ``rrf_score``, ``cosine_distance``, ``dense_rank``,
    ...) are preserved -- the same "first occurrence wins" rule
    ``hybrid_search.reciprocal_rank_fusion()`` already uses when several
    ranked lists share a row.

    Each returned row also carries:
        - ``"matched_children"``: every original input row that pointed at
          this parent (length 1, usually; more when several child chunks
          from the same section matched).
        - ``"expanded_from_parent"``: ``True`` once its ``rowJSON`` (and
          therefore its ``"text"``) has been swapped for the parent's; only
          ``False`` if the parent row was somehow missing (shouldn't
          happen -- ``rowParentGUID`` is a foreign key, see
          ``sql/create_sql_tables.sql`` -- but the input chunk is kept
          as-is rather than silently dropped if it does).
        - ``"parent_row_guid"``: the parent's own ``rowGUID`` (present only
          when ``expanded_from_parent`` is ``True``).

    Order is preserved: the first time each distinct parent is seen. Input
    rows are never mutated; nothing is written back to Supabase --
    query-time only, exactly like ``rerank_chunks()``'s
    ``rerank_score``/``retrieval_rank``.

    ``max_parent_chars`` truncates an unusually long parent section (see
    this module's ``DEFAULT_MAX_PARENT_CHARS``); pass ``None`` to disable
    truncation.
    """
    if not chunks:
        return []
    clients = clients or get_clients()

    expanded_by_parent: dict = {}
    order: List[str] = []
    parent_row_cache: dict = {}

    for row in chunks:
        parent_guid = row["rowParentGUID"]
        if parent_guid in expanded_by_parent:
            expanded_by_parent[parent_guid]["matched_children"].append(row)
            continue

        if parent_guid not in parent_row_cache:
            parent_row_cache[parent_guid] = read_parent_row(parent_guid, clients=clients)
        parent_row = parent_row_cache[parent_guid]

        expanded_row = dict(row)
        expanded_row["matched_children"] = [row]
        if parent_row is None:
            expanded_row["expanded_from_parent"] = False
        else:
            expanded_row["rowJSON"] = dict(parent_row["rowJSON"])
            expanded_row["rowJSON"]["text"] = _truncate(parent_row["rowJSON"]["text"], max_parent_chars)
            expanded_row["parent_row_guid"] = parent_row["rowGUID"]
            expanded_row["expanded_from_parent"] = True

        expanded_by_parent[parent_guid] = expanded_row
        order.append(parent_guid)

    return [expanded_by_parent[guid] for guid in order]


def build_expanded_context_block(chunks: List[dict]) -> str:
    """``generation.build_context_block()``'s counterpart for rows that
    went through ``expand_to_parent_chunks()``: same numbered-excerpt shape
    Claude already expects (this can replace ``build_context_block()`` in
    the ``ask_question()`` pipeline with no other change needed), plus --
    for human/debugging visibility only, exactly like how ``rerank_score``
    is shown in ``build_context_block()`` -- the parent section's title and
    how many originally-matched child chunks it's standing in for. Behaves
    identically to ``build_context_block()`` for a row that never went
    through ``expand_to_parent_chunks()`` (no ``"title"``/
    ``"expanded_from_parent"`` to show)."""
    parts = []
    for i, row in enumerate(chunks, start=1):
        source_key = row["rowJSON"].get("source_key", row["rowOwnerGUID"])
        label = f"[Excerpt {i} -- {source_key}"
        title = row["rowJSON"].get("title")
        if title:
            label += f" | {title}"
        if row.get("expanded_from_parent"):
            n = len(row.get("matched_children", []))
            label += f" | expanded from {n} matched chunk{'s' if n != 1 else ''}"
        if "rerank_score" in row:
            label += f" | relevance {row['rerank_score']:.2f}"
        label += "]"
        parts.append(f"{label}\n{row['rowJSON']['text']}")
    return "\n\n".join(parts)


def page_numbers_for_expanded_chunk(row: dict) -> list:
    """Page range for a (possibly parent-expanded) chunk row.

    A parent chunk's ``rowJSON`` already carries its own
    ``start_page``/``end_page`` fields, set directly by
    ``stage1_1_extract_and_chunk.ipynb`` (see
    ``rag11_chunks_parent_table``'s generated columns in
    ``sql/create_sql_tables.sql``) -- unlike a child chunk, whose page range
    only exists inside its ``"[Source: ... | Pages N-M]"`` text header
    (``contextual_header()``, applied to child chunks only), which is what
    ``retrieval.page_numbers_for_chunk()`` parses instead. This tries the
    parent-shaped fields first and falls back to that regex, so it works
    whether or not ``row`` went through ``expand_to_parent_chunks()``.
    """
    row_json = row.get("rowJSON", {})
    start_page, end_page = row_json.get("start_page"), row_json.get("end_page")
    if start_page is not None and end_page is not None:
        return list(range(start_page, end_page + 1))
    return page_numbers_for_chunk(row)
