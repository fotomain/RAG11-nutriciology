-- =========================================================================
-- RAG11 Nutrition RAG — Sources/Parent/Child Schema Migration
-- Run once in the Supabase Dashboard -> SQL Editor before Stage 1.2
-- ingestion. Creates all three tables, the vector index, and the RPC
-- functions.
--
-- Schema shape follows the project brief exactly, and is the SAME 5-column
-- pattern on all three tables:
--   rowGUID        unique id for this row
--   rowOwnerGUID   the row's ultimate owner -- see below
--   rowParentGUID  hierarchical link (child -> its immediate parent's rowGUID)
--   orderInList    position within the owning list
--   rowJSON        the full payload, verbatim from a JSON file stage1_1/1_2
--                  wrote to disk
--
-- A few columns are pulled out of rowJSON as `generated always as` columns
-- so common filters/joins don't need a jsonb operator on every query, while
-- rowJSON itself stays the single source of truth (nothing is duplicated by
-- hand, so it can never drift from the JSON files on disk).
--
-- Hierarchy and what rowOwnerGUID/rowParentGUID mean at each level:
--   rag11_data_sources        -- one row per source PDF (the root of its
--                                 own tree). rowParentGUID is always null
--                                 here (nothing sits above a source), and
--                                 rowOwnerGUID == rowGUID (a source owns
--                                 itself) -- see stage1_1's build_source_row().
--   rag11_chunks_parent_table -- one row per section. rowOwnerGUID is the
--                                 owning source's rag11_data_sources
--                                 rowGUID (a real FK now, not the old plain
--                                 'source1'/'source2' text). rowParentGUID
--                                 is null (nothing above a parent chunk
--                                 except the source itself, tracked via
--                                 rowOwnerGUID).
--   rag11_chunks_child_table  -- one row per embeddable chunk. rowOwnerGUID
--                                 is the same source rowGUID, inherited
--                                 down the tree; rowParentGUID is its
--                                 parent chunk's rowGUID.
--
-- Ingestion mapping (Stage 1.1/1.2 notebooks), matching the RAG10 pattern:
--   rag11_data_sources.rowGUID        = uuid5(namespace, "source:" + drive_file_id)
--   rag11_chunks_parent_table.rowGUID = uuid5(namespace, "parent:" + parent_id)
--   rag11_chunks_child_table.rowGUID  = uuid5(namespace, "child:" + child_id)
--   rowParentGUID (child rows only)   = uuid5(namespace, "parent:" + child["parent_id"])
--   orderInList                       = the trailing N / M in parent_chunk-N.json /
--                                        chunk-M, or a source's position in the
--                                        Drive folder listing
--   rowOwnerGUID (parent/child rows)  = the owning source's rag11_data_sources
--                                        rowGUID, read from each chunk file's
--                                        `source_row_guid` field
-- Deterministic uuid5 ids make re-running ingestion an idempotent upsert.
-- =========================================================================

-- 1. Enable pgvector -------------------------------------------------------
create extension if not exists vector with schema extensions;

-- 2. Sources table: one row per source PDF ---------------------------------
create table if not exists public.rag11_data_sources (
    "rowGUID"       uuid primary key default gen_random_uuid(),
    "rowOwnerGUID"  uuid not null,   -- always == "rowGUID" (a source owns itself)
    "rowParentGUID" uuid,            -- always null -- a source has no parent
    "orderInList"   int not null,    -- position in the Drive folder listing
    "rowJSON"       jsonb not null,  -- full eda_output/sources/source_row-N.json payload

    -- generated helper columns, pulled out of rowJSON for cheap filtering
    source_key    text generated always as ("rowJSON"->>'source_key') stored,
    filename      text generated always as ("rowJSON"->>'filename') stored,
    drive_file_id text generated always as ("rowJSON"->>'drive_file_id') stored,
    structure     text generated always as ("rowJSON"->>'structure') stored,

    created_at timestamptz not null default timezone('utc', now()),

    -- Encodes "a source is its own tree's root/owner" at the DB level, not
    -- just by convention in the notebooks.
    constraint rag11_data_sources_self_owned check ("rowOwnerGUID" = "rowGUID"),
    constraint rag11_data_sources_no_parent check ("rowParentGUID" is null)
);

create unique index if not exists uq_rag11_sources_order
    on public.rag11_data_sources ("orderInList");

create unique index if not exists uq_rag11_sources_source_key
    on public.rag11_data_sources (source_key);

-- 3. Parent table: one row per section/parent chunk ------------------------
create table if not exists public.rag11_chunks_parent_table (
    "rowGUID"       uuid primary key default gen_random_uuid(),
    "rowOwnerGUID"  uuid not null references public.rag11_data_sources("rowGUID") on delete cascade,
    "rowParentGUID" uuid,                        -- reserved for a future higher-level grouping; null for top-level sections
    "orderInList"   int not null,                -- position of this parent within its source
    "rowJSON"       jsonb not null,              -- full parent_chunk-N.json payload

    -- generated helper columns, pulled out of rowJSON for cheap filtering
    source     text generated always as ("rowJSON"->>'source') stored,
    source_key text generated always as ("rowJSON"->>'source_key') stored,
    title      text generated always as ("rowJSON"->>'title') stored,
    start_page int  generated always as (("rowJSON"->>'start_page')::int) stored,
    end_page   int  generated always as (("rowJSON"->>'end_page')::int) stored,

    created_at timestamptz not null default timezone('utc', now())
);

-- If this table already exists from an earlier run of this script with a
-- *text* rowOwnerGUID ('source1' etc.), migrate it here. This only
-- succeeds on an EMPTY table (there's nothing non-uuid left to cast) --
-- run sql/delete_chunks_data.sql Option A first if it isn't, since this
-- project is still at the POC/dev stage per the permissive policies below.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'rag11_chunks_parent_table'
          and column_name = 'rowOwnerGUID' and data_type = 'text'
    ) then
        alter table public.rag11_chunks_parent_table
            alter column "rowOwnerGUID" type uuid using "rowOwnerGUID"::uuid;
        alter table public.rag11_chunks_parent_table
            add constraint rag11_chunks_parent_owner_fkey
            foreign key ("rowOwnerGUID") references public.rag11_data_sources("rowGUID") on delete cascade;
    end if;
end $$;

create unique index if not exists uq_rag11_parent_owner_order
    on public.rag11_chunks_parent_table ("rowOwnerGUID", "orderInList");

create index if not exists idx_rag11_parent_owner
    on public.rag11_chunks_parent_table ("rowOwnerGUID");

-- 4. Child table: one row per embeddable chunk + its embedding -------------
-- Voyage voyage-3 embeddings are 1024-dimensional; adjust the vector(...)
-- width below (and in both RPCs) if you pick a different Voyage model.
create table if not exists public.rag11_chunks_child_table (
    "rowGUID"       uuid primary key default gen_random_uuid(),
    "rowOwnerGUID"  uuid not null references public.rag11_data_sources("rowGUID") on delete cascade,
    "rowParentGUID" uuid not null references public.rag11_chunks_parent_table("rowGUID") on delete cascade,
    "orderInList"   int not null,                -- position of this child within its parent
    "rowJSON"       jsonb not null,              -- full child_chunk-parentN-chunkM.json payload

    source_key  text generated always as ("rowJSON"->>'source_key') stored,
    chunk_text  text generated always as ("rowJSON"->>'text') stored,
    token_count int  generated always as (("rowJSON"->>'token_count')::int) stored,

    embedding   extensions.vector(1024),         -- filled in by the embedding step (Stage 1.2, part 2)

    -- Postgres full-text search vector over the chunk text, for
    -- keyword/lexical retrieval -- the counterpart to `embedding` for
    -- dense/semantic retrieval. Generated (not populated in Python) so
    -- it's always in sync with rowJSON, exactly like every other generated
    -- column on this table. Built straight from "rowJSON"->>'text' rather
    -- than from chunk_text -- Postgres generated columns cannot reference
    -- another generated column (42P17), even though chunk_text computes
    -- the exact same value. Used by match_rag11_child_chunks_keyword()
    -- below and combined with dense vector search via Reciprocal Rank
    -- Fusion in reusable_code/hybrid_search.py (see hybrid_search()).
    chunk_tsv   tsvector generated always as (to_tsvector('english', coalesce("rowJSON"->>'text', ''))) stored,

    created_at  timestamptz not null default timezone('utc', now())
);

-- Same guarded migration as the parent table above, for pre-existing
-- deployments with a *text* rowOwnerGUID.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'rag11_chunks_child_table'
          and column_name = 'rowOwnerGUID' and data_type = 'text'
    ) then
        alter table public.rag11_chunks_child_table
            alter column "rowOwnerGUID" type uuid using "rowOwnerGUID"::uuid;
        alter table public.rag11_chunks_child_table
            add constraint rag11_chunks_child_owner_fkey
            foreign key ("rowOwnerGUID") references public.rag11_data_sources("rowGUID") on delete cascade;
    end if;
end $$;

-- "create table if not exists" above is a no-op against an
-- already-existing table, so a database that had this table before
-- chunk_tsv was added would never pick up the new column that way --
-- add it explicitly, idempotently. Existing rows compute chunk_tsv for
-- free from their already-populated rowJSON; no re-ingestion needed.
alter table public.rag11_chunks_child_table
    add column if not exists chunk_tsv tsvector
    generated always as (to_tsvector('english', coalesce("rowJSON"->>'text', ''))) stored;

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

-- GIN index for fast full-text (keyword) search over chunk_tsv -- the
-- lexical-retrieval counterpart to the HNSW index above.
create index if not exists idx_rag11_child_chunk_tsv_gin
    on public.rag11_chunks_child_table
    using gin (chunk_tsv);

-- 5. Stored procedure: vector search over child chunks ---------------------
-- Drop every prior overload by its exact signature first. "create or
-- replace" only replaces an EXACT signature match, so an earlier version of
-- this script that used a different filter_owner type (e.g. text, before it
-- was changed to uuid) leaves its old overload sitting in the database
-- forever. PostgREST then can't pick between them for an RPC call that
-- omits filter_owner (relying on the default) -- APIError PGRST203 "Could
-- not choose the best candidate function". Re-running this file is meant
-- to be idempotent, so we explicitly clear known-stale overloads here.
drop function if exists public.match_rag11_child_chunks(extensions.vector, int, text);
drop function if exists public.match_rag11_child_chunks(extensions.vector, int);

create or replace function public.match_rag11_child_chunks(
    query_embedding extensions.vector(1024),
    match_count     int  default 8,
    filter_owner    uuid default null   -- a rag11_data_sources.rowGUID
)
returns table (
    "rowGUID"       uuid,
    "rowParentGUID" uuid,
    "rowOwnerGUID"  uuid,
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

-- 5b. Stored procedure: keyword (full-text) search over child chunks ------
-- The lexical counterpart to match_rag11_child_chunks() above -- ranks by
-- Postgres full-text relevance (ts_rank_cd over chunk_tsv) instead of
-- embedding distance, so exact terms/numbers a dense embedding can blur
-- past (e.g. "0.8 g/kg") are found directly. Combined with the dense RPC
-- via Reciprocal Rank Fusion in reusable_code/retrieval.py::hybrid_search().
-- websearch_to_tsquery() accepts plain search-engine-style input (quoted
-- phrases, "-" to exclude, "OR") rather than requiring tsquery syntax.
drop function if exists public.match_rag11_child_chunks_keyword(text, int, uuid);

create or replace function public.match_rag11_child_chunks_keyword(
    query_text   text,
    match_count  int  default 8,
    filter_owner uuid default null   -- a rag11_data_sources.rowGUID
)
returns table (
    "rowGUID"       uuid,
    "rowParentGUID" uuid,
    "rowOwnerGUID"  uuid,
    "orderInList"   int,
    "rowJSON"       jsonb,
    text_rank       float
)
language sql stable
as $$
    select
        c."rowGUID",
        c."rowParentGUID",
        c."rowOwnerGUID",
        c."orderInList",
        c."rowJSON",
        ts_rank_cd(c.chunk_tsv, websearch_to_tsquery('english', query_text)) as text_rank
    from public.rag11_chunks_child_table c
    where c.chunk_tsv @@ websearch_to_tsquery('english', query_text)
      and (filter_owner is null or c."rowOwnerGUID" = filter_owner)
    order by text_rank desc
    limit least(match_count, 50);
$$;

-- 6. Stored procedure: fetch one parent's full row by rowGUID --------------
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

-- 7. Full permissions on all three tables (POC / development only) --------
-- Wide open for a POC, matching the RAG10 pattern. Before production,
-- replace the "allow all" policies below with narrower ones (e.g.
-- read-only for anon, writes restricted to service_role).
grant usage on schema public to anon, authenticated, service_role;

grant select, insert, update, delete
    on public.rag11_data_sources
    to anon, authenticated, service_role;

grant select, insert, update, delete
    on public.rag11_chunks_parent_table
    to anon, authenticated, service_role;

grant select, insert, update, delete
    on public.rag11_chunks_child_table
    to anon, authenticated, service_role;

alter table public.rag11_data_sources       enable row level security;
alter table public.rag11_chunks_parent_table enable row level security;
alter table public.rag11_chunks_child_table  enable row level security;

drop policy if exists "allow all - rag11 sources" on public.rag11_data_sources;
create policy "allow all - rag11 sources"
    on public.rag11_data_sources
    for all
    to anon, authenticated, service_role
    using (true)
    with check (true);

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
    extensions.vector, int, uuid
) to anon, authenticated, service_role;

grant execute on function public.match_rag11_child_chunks_keyword(
    text, int, uuid
) to anon, authenticated, service_role;

grant execute on function public.get_rag11_parent(uuid)
    to anon, authenticated, service_role;
