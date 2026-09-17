# `reusable_code/` — shared building blocks for the RAG11 notebooks

This package pulls the pieces that were being copy-pasted (and slowly
drifting) between `../stage2_ask_examples1.ipynb` and the new
`../stage2_ask_examples2_rerank.ipynb` into one place, so every Q&A notebook in
this repo can `import reusable_code` instead of re-defining the same
`require_env` / `_retry` / `ask_question` in its own cells.

## Modules

| File | What's in it |
| --- | --- |
| `env.py` | `require_env`, `optional_env` — read `.env` with clear errors |
| `clients.py` | `init_clients()` / `get_clients()` — one Supabase + Voyage + Anthropic client per kernel, plus the model-id constants (`EMBEDDING_MODEL`, `RERANK_MODEL`, `GENERATION_MODEL`) |
| `retry.py` | `with_retry()` — the exponential-backoff wrapper every notebook already had a copy of |
| `retrieval.py` | `embed_query`, `retrieve_chunks`, `page_numbers_for_chunk`, **`rerank_chunks`**, **`update_rank_value`** |
| `generation.py` | `build_context_block`, `extract_short_answer`, `grounding_words`, **`ask_question`** (now with `use_rerank`) |
| `git_sync.py` | `save_to_github` — wraps `save_to_github.command` |

## Using it from a notebook

```python
# near the top of the notebook, after your %pip install cell
from reusable_code import init_clients, ask_question, retrieve_chunks, rerank_chunks, update_rank_value

clients = init_clients()  # reads .env once; cached for the rest of the kernel

# unchanged behavior -- exactly what stage2 always did
result = ask_question("Is vitamin C a water-soluble vitamin?")

# new: rerank pass on top of retrieval (use_rerank is optional, default False)
result = ask_question("Is vitamin C a water-soluble vitamin?", use_rerank=True)
```

Every function also accepts an explicit `clients=` argument instead of
relying on the cached one from `init_clients()` — that's what makes them
independently unit-testable (see `test_reusable_code.py` at the repo root,
which exercises all of this with fully faked clients and no network
access) and reusable across notebooks that might each want their own
client instance.

## What "rerank" adds, in one paragraph

`retrieve_chunks()` finds the top-K chunks by *embedding* similarity —
fast, but the query and each chunk were embedded completely independently,
so it's a rough proxy. `rerank_chunks()` takes a wider candidate pool from
`retrieve_chunks()` and re-scores each `(question, chunk)` pair *jointly*
with Voyage's cross-encoder reranker (`rerank-2`), which is slower per-pair
but far more precise, then keeps only the best few. `ask_question(...,
use_rerank=True)` wires this together: over-fetch a pool, rerank it down,
generate from the reranked top chunks instead of the raw vector-search
order. See `../stage2_ask_examples2_rerank.ipynb` for three worked nutrition
examples.

## `update_rank_value` — manual overrides, no schema change required

`update_rank_value(chunks, row_guid, new_value, ...)` lets a person
override one chunk's relevance score by hand and re-sorts the in-memory
list accordingly (a manual score beats a rerank score beats a raw cosine
distance). **By default this touches nothing in Supabase** — it only
returns a new Python list for the rest of your notebook session. Pass
`persist=True` to also write the override into that row's real `rowJSON`
in `rag11_chunks_child_table` (see below for why that needs no migration).

## Do the tables need to change for any of this? Short answer: no.

Every one of `rowGUID` / `rowOwnerGUID` / `rowParentGUID` / `orderInList` /
**`rowJSON`** already exists on all three tables (`sql/create_sql_tables.sql`),
and `rowJSON` is a schemaless `jsonb` column by design — it's the "full
payload, verbatim from a JSON file" column the whole project already
treats as the source of truth. Reranking is a pure query-time function
over `rowJSON->>'text'` (the chunk text Voyage already has to embed), so:

- **Basic reranking (`rerank_chunks`, `ask_question(use_rerank=True)`)**
  needs **zero** table/column changes. It reads the same rows
  `retrieve_chunks()` already returns and adds two keys
  (`rerank_score`, `retrieval_rank`) to the *in-memory* Python dict only —
  those are query-time diagnostics, never written back to the database.
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
a generated column the same way `sql/create_sql_tables.sql` already does
for `source_key` / `chunk_text` / `token_count`:

```sql
alter table public.rag11_chunks_child_table
  add column if not exists manual_rank_score double precision
  generated always as (("rowJSON"->>'manual_rank_score')::double precision) stored;

create index if not exists idx_rag11_child_manual_rank
  on public.rag11_chunks_child_table (manual_rank_score)
  where manual_rank_score is not null;
```

This is additive and safe to run at any time (existing rows with no
`manual_rank_score` key just get `null`); it changes nothing about how
`update_rank_value()` is called from Python.
