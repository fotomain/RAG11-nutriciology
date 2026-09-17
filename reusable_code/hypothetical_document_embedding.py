"""Hypothetical Document Embeddings (HyDE) for ``rag11_chunks_child_table``
-- another retrieval-method module living alongside ``hybrid_search.py`` and
``parent_chunk_expansion.py`` instead of being folded into
``retrieval.py``/``generation.py`` themselves.

The problem this solves: a question and a textbook answer are written in
different "shapes" of English. Questions are short and interrogative
("Does drinking coffee before exercise dehydrate you enough to hurt
performance?"); the real chunks in this table are long, declarative,
technical prose ("Caffeine has a mild diuretic effect, but studies show
that moderate pre-exercise caffeine intake does not cause clinically
significant dehydration..."). Voyage's asymmetric embeddings narrow that
gap (that's what ``input_type='query'`` vs. ``input_type='document'`` is
for -- see ``retrieval.embed_query()``), but they can't fully erase it: a
short question and a long technical paragraph about the same fact still
land at different points in embedding space, and sometimes a chunk that's
merely *thematically* similar to the bare question ends up closer than the
one that actually answers it.

HyDE's fix: don't embed the question at all. First ask Claude to write a
short hypothetical textbook-style paragraph that *would* answer the
question -- it doesn't need to be correct, it only needs to plausibly use
the same vocabulary and register real chunks use ("diuretic effect",
"habituated users") -- then embed *that* paragraph and search with it
instead. Think of it like: instead of asking a librarian "where's the fiber
book?", you hand them a page that looks like the page you want and say
"find me more like this."

    - ``generate_hypothetical_document()`` -- asks Claude (via
      ``HYDE_SYSTEM_PROMPT``) to draft that short hypothetical paragraph
      for one question. Nothing here is ever shown to a user as an answer;
      it exists purely as a retrieval probe.
    - ``embed_hypothetical_document()`` -- embeds that paragraph with
      ``input_type='document'`` (not ``'query'`` -- a HyDE paragraph is
      document-shaped text, so it should be encoded on the same asymmetric
      side Voyage used for the real child chunks in Stage 1.2, the same way
      ``embed_query()`` uses ``input_type='query'`` for a real question).
    - ``retrieve_chunks_hyde()`` -- composes the two steps above and then
      calls the *same* ``match_rag11_child_chunks`` RPC
      ``retrieval.retrieve_chunks()`` already uses -- HyDE only changes
      *what text gets embedded* before that call, not the retrieval
      mechanism itself, so it needs zero schema or migration change.

See ``stage2_ask_examples5_hypothetical_document_embedding.ipynb`` for
worked nutrition examples,
``documentation/HOW_IT_WORKS_Hypothetical_Document_Embedding.html`` for the
full write-up, and ``reusable_code/README.md`` for the one-paragraph
summary.
"""
from typing import List, Optional, Tuple, Union

from .clients import Clients, EMBEDDING_MODEL, GENERATION_MODEL, get_clients
from .retrieval import NUM_CONTEXT_CHUNKS
from .retry import with_retry

# A HyDE paragraph is a retrieval probe, not a displayed answer -- it only
# needs to be a few sentences of plausible textbook prose, so this is
# deliberately much smaller than generation.MAX_ANSWER_TOKENS (800).
HYDE_MAX_TOKENS = 200

HYDE_SYSTEM_PROMPT = """You are drafting a short passage for a nutrition \
science textbook. Given a question, write one short paragraph (3-5 \
sentences) in the same dense, technical, declarative style an actual \
textbook section would use to answer it -- confident academic prose, with \
plausible domain terminology, mechanisms, and figures, not a conversational \
reply to the question and not a list of caveats.

Do not address the reader, do not say "the answer is" or "according to", \
and do not hedge about what you don't know -- write as if this paragraph \
were lifted directly out of a nutrition textbook's body text. It does not \
need to be perfectly accurate; it only needs to *read* like the kind of \
passage that would actually contain the answer, since it exists solely to \
be embedded and used as a retrieval probe, not shown to anyone as a final \
answer."""


def generate_hypothetical_document(
    question: str,
    *,
    model: str = GENERATION_MODEL,
    max_tokens: int = HYDE_MAX_TOKENS,
    clients: Optional[Clients] = None,
) -> str:
    """Ask Claude to draft a short hypothetical textbook-style paragraph
    that would answer ``question`` -- see this module's docstring for why
    ("questions and answers are written in different shapes of English").

    The returned text is a retrieval probe only -- it is never shown to a
    user as an answer, and it is not guaranteed to be factually correct
    (that's ``generation.ask_question()``'s job, grounded in the real
    retrieved excerpts). Use ``retrieve_chunks_hyde()`` to go straight from
    a question to retrieved chunks; call this directly only when you want
    the hypothetical paragraph itself (e.g. to print/inspect it, as
    ``stage2_ask_examples5_hypothetical_document_embedding.ipynb`` does).
    """
    clients = clients or get_clients()
    resp = with_retry(
        lambda: clients.anthropic.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=HYDE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


def embed_hypothetical_document(
    text: str, *, model: str = EMBEDDING_MODEL, clients: Optional[Clients] = None
) -> list:
    """Embed a HyDE-generated paragraph with ``input_type='document'`` --
    the counterpart to ``retrieval.embed_query()``'s ``input_type='query'``.
    Voyage's asymmetric embeddings encode the query side and document side
    differently for best retrieval quality; a hypothetical paragraph is
    document-shaped text (that's the whole point of generating it), so it
    should be embedded the same way the real child chunks were in Stage
    1.2, not the way a bare question would be."""
    clients = clients or get_clients()
    resp = with_retry(clients.voyage.embed, texts=[text], model=model, input_type="document")
    return resp.embeddings[0]


def retrieve_chunks_hyde(
    question: str,
    match_count: int = NUM_CONTEXT_CHUNKS,
    *,
    filter_owner: Optional[str] = None,
    hyde_model: str = GENERATION_MODEL,
    hyde_max_tokens: int = HYDE_MAX_TOKENS,
    return_hypothetical_document: bool = False,
    clients: Optional[Clients] = None,
) -> Union[list, Tuple[list, str]]:
    """``retrieval.retrieve_chunks()``'s HyDE counterpart: instead of
    embedding ``question`` directly, first draft a hypothetical answer
    paragraph (``generate_hypothetical_document()``), embed *that*
    (``embed_hypothetical_document()``), and search with it instead --
    then return the ``match_count`` best-matching child rows for the
    resulting embedding, ordered by cosine distance ascending (closest
    first), via the *same* ``match_rag11_child_chunks`` RPC
    ``retrieve_chunks()`` calls (see ``sql/create_sql_tables.sql``). HyDE
    only changes what text gets embedded before that call -- it needs no
    schema change, unlike ``hybrid_search.py``'s keyword half.

    ``filter_owner`` restricts retrieval to one source's
    ``rag11_data_sources.rowGUID``; leave it ``None`` to search across
    every ingested source.

    Returns just the row list by default; pass
    ``return_hypothetical_document=True`` to also get back the paragraph
    that was generated and embedded (for display or debugging -- e.g. to
    show a stakeholder *why* a given chunk was retrieved), as
    ``(rows, hypothetical_document)``.
    """
    clients = clients or get_clients()
    hypothetical_document = generate_hypothetical_document(
        question, model=hyde_model, max_tokens=hyde_max_tokens, clients=clients
    )
    hyde_embedding = embed_hypothetical_document(hypothetical_document, clients=clients)
    params = {"query_embedding": hyde_embedding, "match_count": match_count}
    if filter_owner is not None:
        params["filter_owner"] = filter_owner
    resp = with_retry(lambda: clients.supabase.rpc("match_rag11_child_chunks", params).execute())
    rows = resp.data
    if return_hypothetical_document:
        return rows, hypothetical_document
    return rows
