# `reusable_code/` — shared building blocks for the LRM11 notebooks

This package pulls the pieces that were being copy-pasted (and slowly
drifting) between `../ipynb/stage2_ask_examples1.ipynb` and the new
`../ipynb/stage2_ask_examples2_rerank.ipynb` into one place, so every Q&A notebook in
this repo can `import reusable_code` instead of re-defining the same
`require_env` / `_retry` / `ask_question` in its own cells.

## Modules

| File | What's in it |
| --- | --- |
| `env.py` | `require_env`, `optional_env`, `optional_env_bool` — read `.env` with clear errors |
| `config.py` | RAG technique feature flags read from `.env` at import time: `USE_HYBRID_SEARCH`, `USE_PARENT_CHUNK_EXPANSION`, `USE_MULTI_QUERY_QUESTION_SPLITTING`, `USE_HYPOTHETICAL_DOCUMENT_EMBEDDING` (each `True` if unset) — these are `ask_question()`'s defaults for the matching keyword. Also `USE_REASONING`/`REASONING_MODEL`/`REASONING_MAX_STEPS`/`REASONING_MAX_THINKING_TOKENS`/`REASONING_SELF_CHECK` for `reasoning/` (see below; `USE_REASONING` defaults to `False`) |
| `clients.py` | `init_clients()` / `get_clients()` — one Supabase + Voyage + Anthropic client per kernel, plus the model-id constants (`EMBEDDING_MODEL`, `RERANK_MODEL`, `GENERATION_MODEL`) |
| `retry.py` | `with_retry()` — the exponential-backoff wrapper every notebook already had a copy of |
| `ask/retrieval.py` | `embed_query`, `retrieve_chunks`, `page_numbers_for_chunk` |
| `ask/rerunk_code.py` | Reranking + manual overrides: **`rerank_chunks`**, `update_rank_value` |
| `eda/transform/hybrid_search.py` | Dense + keyword search, fused: **`retrieve_chunks_keyword`**, **`reciprocal_rank_fusion`**, **`hybrid_search`** |
| `ask/deduplication.py` | Order-preserving "rows that share a key collapse into one" dedup shared by `reciprocal_rank_fusion` and `expand_to_parent_chunks`: `group_by_key`, `first_occurrence_map` |
| `eda/transform/hypothetical_document_embedding.py` | HyDE retrieval: **`generate_hypothetical_document`**, `embed_hypothetical_document`, **`retrieve_chunks_hyde`** |
| `eda/transform/multi_query_question_splitting.py` | Multi-query / question splitting: **`split_into_subquestions`**, **`retrieve_chunks_multi_query`** |
| `eda/transform/parent_chunk_expansion.py` | Small-to-big context expansion: **`expand_to_parent_chunks`**, `build_expanded_context_block`, `page_numbers_for_expanded_chunk` |
| `ask/generation.py` | `build_context_block`, `extract_short_answer`, `grounding_words`, **`ask_question`** (now with `use_hybrid`, `use_hyde`, `use_multi_query`, `use_rerank`, `expand_to_parents`, plus `filter_owner` to search a single source, `system_prompt` to replace the nutrition prompt, `retrieval_query` to search with different text than the question shown to the model, and `answer_language` to force the answer's language; returns `chunks`/`context_block` alongside the answer, for a caller that needs to re-check or re-display exactly what Claude was shown) |
| `reasoning/` | Multi-step reasoning on top of `ask_question()`: **`ask_with_reasoning`** — draft, self-check the draft's claims against its own retrieved excerpts (extended thinking), retrieve again with a refined query and redraft if unsupported, up to `REASONING_MAX_STEPS` times. Off by default (`USE_REASONING`); see `reasoning/orchestrator.py` |
| `ask/devanagari.py` | `romanize_devanagari`, `contains_devanagari` — Devanagari to IAST, so a question typed in Devanagari can match IAST-transliterated chunks (used by `stage2_ask_examples7_ys.ipynb`) |
| `ask/language.py` | Speaking language: `prepare_question()` (one Claude call: detect language, translate, rewrite jokes/slang/emoji into a clean search query in the corpus language; falls back to the original question), `answer_language_directive()`, `language_name()` |
| `ask/display.py` | Notebook Question/Answer cards: `show_qa()`, `show_summary()`, `answer_html()`, `format_pages()` |
| `ys/` | Everything behind the Yoga-Sūtra notebooks: `YogaSutraQA(speaking_language)` (`ask()`, `ask_all()`, `compare_retrieval()`), `find_book()` / `readiness_message()`, `YS_SYSTEM_PROMPT` |
| `eda/` | Everything behind the ingestion pipeline (`py/lrm/eda1_extract`/`eda2_transform`/`eda3_load` are thin CLI wrappers over this, the same shape as `reasoning/ask.py`): `recognize.py` (OCR engine: `recognise_pdf`, `refine_all`, `link_book`, `set_stage_dir`), `translate.py` (`translate_source`), `download.py` (`download_sources`), `chunks.py` (`chunk_and_embed`), `load/upload.py` (`sync_to_supabase`, two-way disk↔Supabase sync), `schema.py`/`languages.py` (the OCR schema/prompt and per-language metadata), `providers/` (`google.py`/`aws.py`, the `OCR_PROVIDER_NAME` backends) |
| `git_sync.py` | `save_to_github` — wraps `save_to_github.command` |

## Using it from a notebook

```python
# near the top of the notebook, after your %pip install cell
from reusable_code import init_clients, ask_question, retrieve_chunks, rerank_chunks, update_rank_value

clients = init_clients()  # reads .env once; cached for the rest of the kernel

# ask_question() runs the full pipeline by default -- hybrid search, HyDE-vs-
# multi-query retrieval, and parent-chunk expansion are all on unless config.py
# reads a False for them from .env (see "Feature flags" below). use_rerank is
# the one technique that isn't .env-configurable -- it stays opt-in (default
# False) on every call.
result = ask_question("Is vitamin C a water-soluble vitamin?")

# every technique can still be forced on/off per call regardless of .env, by
# passing the keyword explicitly -- this is how stage2_ask_examples2..6
# isolate one technique at a time for a worked example:
result = ask_question(
    "How does soluble fiber's effect on LDL cholesterol differ from insoluble fiber's?",
    use_multi_query=True, use_hybrid=True, use_rerank=True, expand_to_parents=True,
    use_hyde=False,  # ignored anyway once use_multi_query/use_hybrid win, but explicit for clarity
)
```

### Feature flags (`config.py` / `.env`)

Four of the five retrieval techniques `ask_question()` composes are toggled
by a `USE_*` flag in `.env` (see `.env.sample`) -- each defaults to `True`
if left unset, so a fresh checkout demonstrates the full pipeline with no
setup:

| `.env` variable | `ask_question()` keyword | `False` falls back to |
| --- | --- | --- |
| `USE_HYBRID_SEARCH` | `use_hybrid` | plain vector search |
| `USE_HYPOTHETICAL_DOCUMENT_EMBEDDING` | `use_hyde` | search embeds the bare question |
| `USE_MULTI_QUERY_QUESTION_SPLITTING` | `use_multi_query` | the question is searched as-is, not split |
| `USE_PARENT_CHUNK_EXPANSION` | `expand_to_parents` | child chunks only, no expansion |

`use_rerank` isn't in this table -- it has no `.env` flag and always
defaults to plain `False`. Flip any of the four in `.env` and rerun a cell
to see that technique's simplest variant, with no code changes; an
explicit keyword on a given `ask_question()` call always overrides
whatever `.env` says, for just that call.

## Speaking language (`SPEAKING_LANGUAGE` / `language.py`)

`SPEAKING_LANGUAGE` in `.env` (default `EN`) is the language every answer is written in, whatever language or
script the question uses. Two steps make it smooth (used by `stage2_ask_examples7_ys.ipynb` and
`stage2_ask_examples8_nutriciology.ipynb`, each with a `speaking_language = "EN"` variable):

1. `prepare_question(question, language=..., corpus_hint=...)` -- one small Claude call *before* retrieval detects the
   question's language, translates it, and rewrites it as a neutral keyword-rich **search query** in the corpus's language.
   Retrieval uses that query (`ask_question(retrieval_query=...)`); the answering model sees the original question plus its
   translation (`PreparedQuestion.llm_question`). If the call fails the original question is used, never lost.
2. `ask_question(answer_language="EN")` -- appends an explicit language directive to the system prompt **and** repeats the
   rule at the end of the user turn (a model tends to mirror the question's language otherwise).

## Yoga-Sūtra notebooks (`ys/`)

`stage2_ask_examples7_ys.ipynb` and `stage2_ask_examples7_ys_RU.ipynb` contain only the questions and the answers:

```python
from reusable_code.ys import YogaSutraQA
ys = YogaSutraQA(speaking_language="EN")   # connects, finds the book, warns if the sutra text isn't loaded
answers = ys.ask_all(QUESTIONS)            # understand -> retrieve (this book only) -> answer -> cards + table
```

Your own system prompt: `YogaSutraQA(speaking_language="RU", system_prompt=MY_PROMPT)` (blank or `None` keeps the
built-in `YS_SYSTEM_PROMPT`), or for a single run `ys.ask_all(QUESTIONS, system_prompt=...)`. Do not write the answer
language into it (`answer_language` appends that); keep the `Short answer: Yes|No` protocol if you want the Yes/No
badge. `stage2_ask_examples7_ys_RU.ipynb` has the full prompt in an editable cell.

Everything else lives in the package: `book.py` (find the book, readiness check), `prompts.py` (system prompt, corpus
hint), `qa.py` (`YogaSutraQA`). Card labels follow `speaking_language` (`display.UI`: English and Russian so far; add
a dict entry for another language).

## Stage 3.1 page window (`--start`/`--end` / `MAX_NUMBER_OF_PAGES_TO_USE`)

`py/lrm/eda1_extract/recognize.py` (see its docstring) caps how many pages of a PDF it recognises: `--start`/`--end`
on the command line select an explicit page range, and when `--end` is omitted it falls back to
`MAX_NUMBER_OF_PAGES_TO_USE` from `.env` (unset = `100`, a fast smoke test; `NONE` = the whole book). Handy for
iterating against just the pages that matter without re-recognising the whole book. Already-recognised pages are
skipped unless `--force` is passed.

## What "rerank" adds, in one paragraph

`retrieve_chunks()` finds the top-K chunks by *embedding* similarity —
fast, but the query and each chunk were embedded completely independently,
so it's a rough proxy. `rerank_chunks()` takes a wider candidate pool from
`retrieve_chunks()` and re-scores each `(question, chunk)` pair *jointly*
with Voyage's cross-encoder reranker (`rerank-2`), which is slower per-pair
but far more precise, then keeps only the best few. `ask_question(...,
use_rerank=True)` wires this together: over-fetch a pool, rerank it down,
generate from the reranked top chunks instead of the raw vector-search
order. See `../ipynb/stage2_ask_examples2_rerank.ipynb` for three worked nutrition
examples.

## What "hybrid search" adds, in one paragraph

`retrieve_chunks()` only compares meaning — it's great at "roughly the
same topic" but can bury the one chunk that has the exact
number/terminology a question needs (e.g. "0.8 g/kg RDA") under chunks
that are merely thematically similar. `retrieve_chunks_keyword()` runs a
Postgres full-text search instead — it matches actual words/numbers, so it
finds that exact chunk instantly, because it's matching text, not meaning.
`hybrid_search()` runs *both* over a wide candidate pool and merges the two
rankings with **Reciprocal Rank Fusion** (`reciprocal_rank_fusion()`):
each chunk's combined score is `sum over methods of 1 / (k + rank)`, so a
chunk that scores well on *either* method still surfaces, and one both
methods agree on rises to the top — without ever needing to compare cosine
distance and `ts_rank_cd` on the same scale. `ask_question(...,
use_hybrid=True)` wires this in as a drop-in replacement for plain vector
search, and composes with `use_rerank=True` (hybrid picks the candidate
pool, rerank re-scores it). See `../ipynb/stage2_ask_examples3_hybrid_search.ipynb`
for worked nutrition examples, and
`../documentation/HOW_IT_WORKS_Hybrid_Search.html` for the full write-up
of why this matters.

Unlike reranking, hybrid search **does** need one additive, idempotent
schema change — re-run `sql/create_lrm_tables.sql` to pick up:
- `lrm_child_chunk_table.chunk_tsv` — a generated `tsvector` column over
  `rowJSON->>'text'` (the same source `chunk_text` reads from — a generated
  column can't reference another generated column, so `chunk_tsv` reads
  `rowJSON` directly rather than `chunk_text`), the keyword-search
  counterpart to the `embedding` column.
- `idx_lrm_child_chunk_table_tsv_gin` — a GIN index on `chunk_tsv`, the
  keyword-search counterpart to the HNSW `embedding` index.
- `match_lrm_chunks_keyword(query_text, match_count, filter_owner)`
  — the RPC `retrieve_chunks_keyword()` calls, mirroring
  `match_lrm_chunks()`'s shape exactly (same 5 identity columns
  plus one score column, `text_rank` instead of `cosine_distance`).

Every statement in that migration is `create table/index/function if not
exists`, `alter table ... add column if not exists`, or `create or replace
function`, so re-running it against a database that already has ingested
data is safe — existing rows just pick up a computed `chunk_tsv` value for
free from their already-populated `rowJSON`, no re-embedding or
re-ingestion required.

## What "HyDE" (hypothetical document embeddings) adds, in one paragraph

A question and a textbook answer are written in different "shapes" of
English — questions are short and interrogative, real chunks are long,
declarative, technical prose — so embedding the bare question sometimes
lands closer to a chunk that's merely thematically similar than to the one
that actually answers it. `generate_hypothetical_document()` asks Claude to
draft a short hypothetical textbook-style paragraph that *would* answer the
question (it doesn't need to be correct — only to plausibly use the same
vocabulary real chunks do), `embed_hypothetical_document()` embeds that
paragraph with `input_type='document'` (matching how the real chunks were
embedded, not `'query'`), and `retrieve_chunks_hyde()` searches with that
embedding instead of the question's — via the *same*
`match_lrm_chunks` RPC plain `retrieve_chunks()` already uses, so
**zero** schema change is needed. `ask_question(..., use_hyde=True)` wires
this in as a drop-in replacement for plain vector search (ignored if
`use_hybrid=True` is also set — hybrid's dense half already embeds the raw
question). See
`../ipynb/stage2_ask_examples5_hypothetical_document_embedding.ipynb` for worked
nutrition examples, and
`../documentation/HOW_IT_WORKS_Hypothetical_Document_Embedding.html` for
the full write-up.

## What "multi-query / question splitting" adds, in one paragraph

One search query can only point in one "direction" in embedding space. A
question like *"How does soluble fiber's effect on LDL cholesterol differ
from insoluble fiber's effect?"* is secretly **two** independent
information needs glued together — (a) soluble fiber's effect, (b)
insoluble fiber's effect — and embedding the whole thing at once produces a
blurry average of both topics that can under-match either one.
`split_into_subquestions()` asks Claude whether a question bundles more
than one independent need and, if so, rewrites it as that many
self-contained sub-questions (an already-atomic question comes back
unchanged, as a single-element list — no extra searches for the common
case); `retrieve_chunks_multi_query()` then runs the same retrieval
function once per sub-question over a wide pool and fuses every resulting
ranked list with the *same* **Reciprocal Rank Fusion**
`hybrid_search.reciprocal_rank_fusion()` already uses for dense + keyword
search — reused here to merge "one method, run once per sub-question"
instead of "two methods, run once." `ask_question(..., use_multi_query=True)`
wires this in as a drop-in replacement for plain vector search: it takes
priority over `use_hybrid` as the *top-level* retrieval mode, but composes
with it (each sub-question is itself searched with `hybrid_search()` when
`use_hybrid=True`), and with reranking and parent-chunk expansion; it
ignores `use_hyde` (multi-query needs a single-question retrieval function
per sub-question — the same reasoning `use_hybrid` already uses to ignore
HyDE). See `../ipynb/stage2_ask_examples6_multi_query_question_splitting.ipynb`
for worked nutrition examples, and
`../documentation/HOW_IT_WORKS_Multi_Query_Question_Splitting.html` for the
full write-up.

Like reranking and HyDE, this needs **zero** schema change — it's a pure
query-time Python step that adds one extra Claude call (to split the
question) before calling the exact same retrieval RPCs
`retrieve_chunks()`/`hybrid_search()` already use, once per sub-question.

## What "parent-chunk expansion" adds, in one paragraph

A child chunk is deliberately small (~300–500 tokens) so it matches a
question *precisely* — but a small chunk sometimes doesn't carry enough
surrounding context to answer the question *fully*. Example: "How does
soluble fiber's effect on LDL cholesterol differ from insoluble fiber's?"
might retrieve, as its best-reranked chunk, two sentences about soluble
fiber alone — a great match for half the question, but silent on insoluble
fiber. Every child chunk's `rowParentGUID` already points at a bigger
parent chunk from Stage 1.1 (the full section it was carved out of, which
usually discusses both sides of a comparison together).
`expand_to_parent_chunks()` swaps each winning child chunk's text for its
parent's before generation — deduping when several winning chunks share one
parent, so the parent is only sent once — and `ask_question(...,
expand_to_parents=True)` wires this in as the last, optional step: hybrid
and/or rerank pick the candidates, then expansion swaps in the surrounding
context right before Claude sees it. See
`../ipynb/stage2_ask_examples4_parent_chunk_expansion.ipynb` for worked nutrition
examples, and
`../documentation/HOW_IT_WORKS_Parent_Chunk_Expansion.html` for the full
write-up.

Like reranking, this needs **zero** schema change — `lrm_page_table`
and the `rowParentGUID` foreign key from child to parent already exist
(`sql/create_lrm_tables.sql`); `expand_to_parent_chunks()` just reads them
via `retrieval.read_page_row()`. The only thing to watch is
size: a parent chunk is a whole book *section*, not token-budgeted the way
a child chunk is, so `expand_to_parent_chunks(..., max_parent_chars=...)`
truncates an unusually long one (default 6000 chars, `None` to disable).

## `update_rank_value` — manual overrides, no schema change required

`update_rank_value(chunks, row_guid, new_value, ...)` lets a person
override one chunk's relevance score by hand and re-sorts the in-memory
list accordingly (a manual score beats a rerank score beats a raw cosine
distance). **By default this touches nothing in Supabase** — it only
returns a new Python list for the rest of your notebook session. Pass
`persist=True` to also write the override into that row's real `rowJSON`
in `lrm_child_chunk_table` (see below for why that needs no migration).

## Do the tables need to change for any of this? Short answer: no.

Every one of `rowGUID` / `rowOwnerGUID` / `rowParentGUID` / `orderInList` /
**`rowJSON`** already exists on all three tables (`sql/create_lrm_tables.sql`),
and `rowJSON` is a schemaless `jsonb` column by design — it's the "full
payload, verbatim from a JSON file" column the whole project already
treats as the source of truth. Reranking is a pure query-time function
over `rowJSON->>'text'` (the chunk text Voyage already has to embed), so:

- **Basic reranking (`rerank_chunks`, `ask_question(use_rerank=True)`)**
  needs **zero** table/column changes. It reads the same rows
  `retrieve_chunks()` already returns and adds two keys
  (`rerank_score`, `retrieval_rank`) to the *in-memory* Python dict only —
  those are query-time diagnostics, never written back to the database.
- **HyDE (`retrieve_chunks_hyde`, `ask_question(use_hyde=True)`)** also
  needs **zero** table/column changes — it calls the exact same
  `match_lrm_chunks` RPC plain `retrieve_chunks()` already uses;
  the only difference is *which text* gets embedded before that call
  (a Claude-drafted hypothetical paragraph instead of the bare question).
- **Multi-query / question splitting (`retrieve_chunks_multi_query`,
  `ask_question(use_multi_query=True)`)** also needs **zero** table/column
  changes — it calls whatever single-question retrieval function you give
  it (`retrieve_chunks()` or `hybrid_search()`) once per sub-question,
  against the exact same RPCs those already use, and merges the results
  entirely in Python via `reciprocal_rank_fusion()`.
- **Parent-chunk expansion (`expand_to_parent_chunks`,
  `ask_question(expand_to_parents=True)`)** also needs **zero** table/column
  changes — `lrm_page_table` and the child table's
  `rowParentGUID` foreign key already exist. It only reads an existing
  parent row (`retrieval.read_page_row()`) and swaps it into the
  *in-memory* row dict; nothing is written back to Supabase.
- **`update_rank_value(..., persist=False)`** (the default) is the same
  story: purely in-memory, nothing in Supabase changes.
- **`update_rank_value(..., persist=True)`** *does* write to Supabase, but
  only as an ordinary `UPDATE ... SET "rowJSON" = <merged jsonb>` on the
  one affected child row — merging `manual_rank_score` (and
  `manual_rank_reason`, if given) into that row's existing `rowJSON`
  value. No `ALTER TABLE`, no new column, no new RPC function.

### If you ever *do* want a first-class stored column (optional)

You don't need this for anything above to work, but if later you want
cheap SQL-side filtering/sorting on manual overrides (e.g. "show me every
chunk a human has corrected") without unpacking `rowJSON` every time, add
a generated column the same way `sql/create_lrm_tables.sql` already does
for `source_key` / `chunk_text` / `token_count`:

```sql
alter table public.lrm_child_chunk_table
  add column if not exists manual_rank_score double precision
  generated always as (("rowJSON"->>'manual_rank_score')::double precision) stored;

create index if not exists idx_lrm_child_chunk_table_manual_rank
  on public.lrm_child_chunk_table (manual_rank_score)
  where manual_rank_score is not null;
```

This is additive and safe to run at any time (existing rows with no
`manual_rank_score` key just get `null`); it changes nothing about how
`update_rank_value()` is called from Python.
