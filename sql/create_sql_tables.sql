-- =========================================================================
-- RAG11 Nutrition RAG — Parent/Child Schema Migration
-- Run once in the Supabase Dashboard -> SQL Editor before Stage 1.2
-- ingestion. Creates both tables, the vector index, and the RPC functions.
--
-- Schema shape follows the project brief exactly:
--   rowGUID        unique id for this row
--   rowOwnerGUID   source identifier ('source1' / 'source2' / 'source3')
--   rowParentGUID  hierarchical link (child -> its parent's rowGUID)
--   orderInList    position within the owning list
--   rowJSON        the full chunk payload, verbatim from
--                  stage1_eda_output/<source>/parent_chunk-N.json or
--                  child_chunk-parentN-chunkM.json
--
-- A few columns are pulled out of rowJSON as `generated always as` columns
-- so common filters/joins don't need a jsonb operator on every query, while
-- rowJSON itself stays the single source of truth (nothing is duplicated by
-- hand, so it can never drift from the JSON files on disk).
--
-- Ingestion mapping (Stage 1.2 notebook), matching the RAG10 pattern:
--   rowGUID       = uuid5(namespace, parent_id)   or  uuid5(namespace, child_id)
--   rowParentGUID = uuid5(namespace, child["parent_id"])   (child rows only)
--   orderInList   = the trailing N / M in parent_chunk-N.json / chunk-M
--   rowOwnerGUID  = the source key folder name ('source1', 'source2', 'source3')
-- Deterministic uuid5 ids make re-running ingestion an idempotent upsert.
-- =========================================================================

-- 1. Enable pgvector -------------------------------------------------------
create extension if not exists vector with schema extensions;

-- 2. Parent table: one row per section/parent chunk -----------------------
create table if not exists public.rag11_chunks_parent_table (
    "rowGUID"       uuid primary key default gen_random_uuid(),
    "rowOwnerGUID"  text not null,               -- 'source1' / 'source2' / 'source3'
    "rowParentGUID" uuid,                        -- reserved for a future higher-level grouping; null for top-level sections
    "orderInList"   int not null,                -- position of this parent within its source
    "rowJSON"       jsonb not null,              -- full parent_chunk-N.json payload

    -- generated helper columns, pulled out of rowJSON for cheap filtering
    source     text generated always as ("rowJSON"->>'source') stored,
    title      text generated always as ("rowJSON"->>'title') stored,
    start_page int  generated always as (("rowJSON"->>'start_page')::int) stored,
    end_page   int  generated always as (("rowJSON"->>'end_page')::int) stored,

    created_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists uq_rag11_parent_owner_order
    on public.rag11_chunks_parent_table ("rowOwnerGUID", "orderInList");

create index if not exists idx_rag11_parent_owner
    on public.rag11_chunks_parent_table ("rowOwnerGUID");

-- 3. Child table: one row per embeddable chunk + its embedding -------------
-- Voyage voyage-3 embeddings are 1024-dimensional; adjust the vector(...)
-- width below (and in both RPCs) if you pick a different Voyage model.
create table if not exists public.rag11_chunks_child_table (
    "rowGUID"       uuid primary key default gen_random_uuid(),
    "rowOwnerGUID"  text not null,               -- denormalized source identifier
    "rowParentGUID" uuid not null references public.rag11_chunks_parent_table("rowGUID") on delete cascade,
    "orderInList"   int not null,                -- position of this child within its parent
    "rowJSON"       jsonb not null,              -- full child_chunk-parentN-chunkM.json payload

    chunk_text  text generated always as ("rowJSON"->>'text') stored,
    token_count int  generated always as (("rowJSON"->>'token_count')::int) stored,

    embedding   extensions.vector(1024),         -- filled in by the embedding step (Stage 1.2, part 2)

    created_at  timestamptz not null default timezone('utc', now())
);

create unique index if not exists uq_rag11_child_parent_order
    on public.rag11_chunks_child_table ("rowParentGUID", "orderInList");

create index if not exists idx_rag11_child_owner
    on public.rag11_chunks_child_table ("rowOwnerGUID");

create index if not exists idx_rag11_child_parent
    on public.rag11_chunks_child_table ("rowParentGUID");

-- HNSW cosine-similarity index for fast approximate nearest-neighbor search
create index if not exists idx_rag11_child_embedding_hnsw
    on public.rag11_chunks_child_table
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

-- 4. Stored procedure: vector search over child chunks ---------------------
create or replace function public.match_rag11_child_chunks(
    query_embedding extensions.vector(1024),
    match_count     int  default 8,
    filter_owner    text default null
)
returns table (
    "rowGUID"       uuid,
    "rowParentGUID" uuid,
    "rowOwnerGUID"  text,
    "orderInList"   int,
    "rowJSON"       jsonb,
    cosine_distance float
)
language sql stable
as $$
    select
        c."rowGUID",
        c."rowParentGUID",
        c."rowOwnerGUID",
        c."orderInList",
        c."rowJSON",
        (c.embedding <=> query_embedding) as cosine_distance
    from public.rag11_chunks_child_table c
    where c.embedding is not null
      and (filter_owner is null or c."rowOwnerGUID" = filter_owner)
    order by c.embedding <=> query_embedding asc
    limit least(match_count, 50);
$$;

-- 5. Stored procedure: fetch one parent's full row by rowGUID --------------
-- Convenience RPC so the retrieval layer can expand a matched child back to
-- its full parent section without hand-building a second REST query.
create or replace function public.get_rag11_parent(
    p_row_guid uuid
)
returns public.rag11_chunks_parent_table
language sql stable
as $$
    select * from public.rag11_chunks_parent_table where "rowGUID" = p_row_guid;
$$;

-- 6. Full permissions on both tables (POC / development only) --------------
-- Wide open for a POC, matching the RAG10 pattern. Before production,
-- replace the "allow all" policies below with narrower ones (e.g.
-- read-only for anon, writes restricted to service_role).
grant usage on schema public to anon, authenticated, service_role;

grant select, insert, update, delete
    on public.rag11_chunks_parent_table
    to anon, authenticated, service_role;

grant select, insert, update, delete
    on public.rag11_chunks_child_table
    to anon, authenticated, service_role;

alter table public.rag11_chunks_parent_table enable row level security;
alter table public.rag11_chunks_child_table  enable row level security;

drop policy if exists "allow all - rag11 parent" on public.rag11_chunks_parent_table;
create policy "allow all - rag11 parent"
    on public.rag11_chunks_parent_table
    for all
    to anon, authenticated, service_role
    using (true)
    with check (true);

drop policy if exists "allow all - rag11 child" on public.rag11_chunks_child_table;
create policy "allow all - rag11 child"
    on public.rag11_chunks_child_table
    for all
    to anon, authenticated, service_role
    using (true)
    with check (true);

grant execute on function public.match_rag11_child_chunks(
    extensions.vector, int, text
) to anon, authenticated, service_role;

grant execute on function public.get_rag11_parent(uuid)
    to anon, authenticated, service_role;
