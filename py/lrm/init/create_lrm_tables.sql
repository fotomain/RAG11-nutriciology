-- LRM tables (same 5-column rowGUID/rowJSON pattern as RAG11). Run in Supabase SQL Editor,
-- or via run2_lrm_upload.command if LRM_DB_URL is set.
create table if not exists public.lrm_sources (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid,
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,
    source_key text generated always as ("rowJSON"->>'source_key') stored,
    language   text generated always as ("rowJSON"->>'language') stored,
    title      text generated always as ("rowJSON"->>'title') stored,
    created_at timestamptz not null default timezone('utc', now()),
    unique (source_key, language)
);

create table if not exists public.lrm_pages (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null references public.lrm_sources("rowGUID") on delete cascade,
    "rowParentGUID" uuid references public.lrm_sources("rowGUID") on delete cascade,
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,
    source_key  text generated always as ("rowJSON"->>'source_key') stored,
    language    text generated always as ("rowJSON"->>'language') stored,
    page_number int  generated always as (("rowJSON"->>'page_number')::int) stored,
    created_at timestamptz not null default timezone('utc', now()),
    unique (source_key, language, page_number)
);
create index if not exists ix_lrm_pages_lookup on public.lrm_pages (source_key, language, page_number);
