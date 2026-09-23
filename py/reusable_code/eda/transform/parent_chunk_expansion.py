"""Page expansion ("small-to-big") for ``lrm_child_chunk_table`` results -- the
retrieval-stage counterpart to ``hybrid_search.py`` and
``rerunk_code.py``'s ``rerank_chunks()``, living in its own module the same
way those do, instead of being folded into ``retrieval.py``/``generation.py``
themselves.

The problem this solves: a chunk can be just a fragment of a page (see
``sql/create_lrm_tables.sql``'s note on when a page splits into more than
one chunk), so it sometimes doesn't carry enough surrounding context --
the rest of the page -- to answer a question fully.

Every chunk's ``rowParentGUID`` (a real foreign key into ``lrm_page_table`` --
see ``sql/create_lrm_tables.sql``) points at the full page it was carved
out of, blocks/words/bboxes and all.

The fix, and what this module does: after retrieval (plain, hybrid, and/or
reranked -- ``expand_to_parent_chunks()`` doesn't care which one produced
its input), swap each winning chunk's text for its page's full text before
building the context block Claude sees.

    - ``expand_to_parent_chunks()`` -- the swap itself: groups input chunks
      by ``rowParentGUID`` via ``deduplication.group_by_key()`` (the same
      "first occurrence wins" dedup ``hybrid_search.reciprocal_rank_fusion()``
      uses) so several winning chunks from the same page collapse into one
      fetch (via ``retrieval.read_page_row()``) and one row, and keeps each
      surviving row's original ranking metadata (``rerank_score`` /
      ``rrf_score`` / ``cosine_distance`` / ``dense_rank`` / ... --
      whatever the input already carried) so it still sorts and prints the
      same way downstream.
    - ``build_expanded_context_block()`` --
      ``generation.build_context_block()``'s counterpart for expanded rows:
      same numbered-excerpt shape Claude already expects, plus (for
      human/debugging visibility only) the page's title and how many
      originally-matched chunks it's standing in for.
    - ``page_numbers_for_expanded_chunk()`` --
      ``retrieval.page_numbers_for_chunk()``'s counterpart, kept as its own
      function so call sites read symmetrically with
      ``build_expanded_context_block()``.

No schema or migration change is needed -- ``lrm_page_table`` and its
``rowParentGUID`` foreign key already exist (``sql/create_lrm_tables.sql``).
"""
from typing import List, Optional

from ...clients import Clients, get_clients
from ...ask.deduplication import group_by_key
from ...ask.retrieval import page_numbers_for_chunk, read_page_row

# A whole page's text can run much longer than a single chunk (a page that
# split into several chunks is, by definition, over the chunking token
# budget). Truncating keeps one expanded page from silently eating the
# whole context-window budget build_context_block()/ask_question() have to
# share across every excerpt. ~1500 tokens (English prose runs roughly 4
# chars/token).
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
          ``sql/create_lrm_tables.sql`` -- but the input chunk is kept
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

    # deduplication-step: collapse child chunks that share a rowParentGUID
    # into one group each, so their parent is fetched/sent only once.
    groups = group_by_key(chunks, key="rowParentGUID")

    expanded = []
    for parent_guid, matched_children in groups.items():
        parent_row = read_page_row(parent_guid, clients=clients)

        expanded_row = dict(matched_children[0])
        expanded_row["matched_children"] = matched_children
        if parent_row is None:
            expanded_row["expanded_from_parent"] = False
        else:
            expanded_row["rowJSON"] = dict(parent_row["rowJSON"])
            expanded_row["rowJSON"]["text"] = _truncate(parent_row["rowJSON"]["text"], max_parent_chars)
            expanded_row["parent_row_guid"] = parent_row["rowGUID"]
            expanded_row["expanded_from_parent"] = True

        expanded.append(expanded_row)

    return expanded


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
    """The page(s) a (possibly page-expanded) row belongs to.

    An expanded row's ``rowJSON`` is a full ``lrm_page_table`` row's JSON, which
    carries the same ``page_number`` field a plain chunk's ``rowJSON``
    does (``upload.py`` stamps it onto every page before upserting -- see
    ``sql/create_lrm_tables.sql``'s generated column of the same name), so
    this needs no special parent-shaped case: it's just
    ``retrieval.page_numbers_for_chunk()``, kept as its own function so
    call sites read symmetrically with ``build_expanded_context_block()``.
    """
    return page_numbers_for_chunk(row)
