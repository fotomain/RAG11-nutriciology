-- =========================================================================
-- LRM — Language Reading Model: page-image book viewer + retrieval schema
-- Run once in the Supabase Dashboard -> SQL Editor (or via
-- py/run/run2_lrm_upload.command --init, which pastes this in for you).
--
-- Same 5-column rowGUID/rowOwnerGUID/rowParentGUID/orderInList/rowJSON
-- pattern used everywhere in this repo (see sql/create_sql_tables.sql for
-- the RAG11 nutrition-RAG tables -- LRM's tables are entirely separate;
-- nothing here is read by or written to a rag11_* table, and vice versa).
--
-- Hierarchy:
--   lrm_language_table -- reference table of supported language codes,
--       self-owned like lrm_source_table (rowOwnerGUID == rowGUID). Every
--       lrm_source_table.language, lrm_page_table.language, and
--       lrm_child_chunk_table.language value must exist here first (its `code`
--       generated column, which carries a unique constraint every such FK
--       references) -- add a language by inserting one row, no code
--       changes required.
--   lrm_source_table -- one row per (book, language) pair. rowParentGUID
--       is always null (nothing sits above a source) and rowOwnerGUID ==
--       rowGUID (a source owns itself), exactly like rag11_data_sources.
--   lrm_page_table -- one row per recognised/translated page. rowOwnerGUID
--       and rowParentGUID both point at the owning source (pages sit
--       directly under their source, one level, no separate "parent
--       chunk" concept -- a page IS the natural parent-sized unit here).
--   lrm_child_chunk_table -- one row per embeddable chunk of page text (usually
--       one chunk per page; only split further if a page's text exceeds
--       the embedding model's practical token budget). rowOwnerGUID is the
--       source; rowParentGUID is the owning lrm_page_table row. This is
--       the table that makes LRM retrievable the way RAG11 already is --
--       see match_lrm_chunks()/match_lrm_chunks_keyword() below, and
--       py/reusable_code/hybrid_search.py etc. for the retrieval layer
--       that calls them.
--
-- Multi-language by design: `language` is a free-text FK into
-- lrm_language_table, not a fixed enum/CHECK constraint -- adding a 4th
-- (5th, 6th, ...) language beyond the initial fr/en/ru never requires a
-- schema migration, only an insert into lrm_language_table plus running
-- the pipeline for the new language.
--
-- Section 8 below adds a separate, self-describing data dictionary
-- (lrm_definition_table, lrm_definition_attribute_table, lrm_entities_relations_table)
-- grounded in the IFLA Library Reference Model (LRM, the bibliographic
-- standard -- unrelated to "LRM" = Language Reading Model, this project's
-- own name). It documents the four tables above without restructuring
-- them; see section 8's own header comment for the full explanation.
-- =========================================================================

-- 1. Enable pgvector (idempotent; already run by sql/create_sql_tables.sql
--    if you have both schemas, but this file must also work standalone) --
create extension if not exists vector with schema extensions;

-- 2. Languages: reference table, same 5-column pattern as every other table --
create table if not exists public.lrm_language_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid,
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,   -- {code, name, native_name, prompt_name, translation_style, is_source_capable}

    code        text generated always as ("rowJSON"->>'code') stored,        -- e.g. 'fr', 'en', 'ru', 'hi'
    name        text generated always as ("rowJSON"->>'name') stored,        -- display name, e.g. 'English'
    native_name text generated always as ("rowJSON"->>'native_name') stored, -- e.g. 'Русский'

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_language_table_self_owned check ("rowOwnerGUID" = "rowGUID"),  -- a language owns itself
    constraint lrm_language_table_code_key unique (code)  -- every `language` FK elsewhere targets this
);

insert into public.lrm_language_table ("rowGUID", "rowOwnerGUID", "orderInList", "rowJSON")
select id, id, ord, jsonb_build_object(
    'code', code, 'name', name, 'native_name', native_name,
    'prompt_name', prompt_name, 'translation_style', translation_style, 'is_source_capable', true)
from (
    select gen_random_uuid() as id, * from (values
        ('fr', 'Français', 'Français', 'French', null::text, 1),
        ('en', 'English', 'English', 'American English (US)',
            '- Use American English spelling and punctuation, with curly quotation marks " ".', 2),
        ('ru', 'Русский', 'Русский', 'Russian',
            '- Write in a natural, literary scholarly Russian. Use «…» quotation marks and the em dash — per Russian typography. Do not transliterate the Sanskrit or Latin kept in [[ ]]; leave it in the source form.', 3)
    ) as t(code, name, native_name, prompt_name, translation_style, ord)
) s
on conflict (code) do nothing;

-- 3. Sources: one row per (book, language) -----------------------------
create table if not exists public.lrm_source_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid,
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,

    source_key text generated always as ("rowJSON"->>'source_key') stored,
    language   text generated always as ("rowJSON"->>'language') stored,
    title      text generated always as ("rowJSON"->>'title') stored,

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_source_table_self_owned  check ("rowOwnerGUID" = "rowGUID"),   -- a source owns itself
    constraint lrm_source_table_no_parent   check ("rowParentGUID" is null),      -- a source has no parent
    constraint lrm_source_table_language_fkey foreign key (language) references public.lrm_language_table(code)
);

create unique index if not exists uq_lrm_source_table_key_lang on public.lrm_source_table (source_key, language);

-- 4. Pages: one row per recognised/translated page ----------------------
create table if not exists public.lrm_page_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid,
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,   -- blocks/words/bboxes/text, see py/lrm/data/recognize.py

    source_key  text generated always as ("rowJSON"->>'source_key') stored,
    language    text generated always as ("rowJSON"->>'language') stored,
    page_number int  generated always as (("rowJSON"->>'page_number')::int) stored,

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_page_table_owner_fkey    foreign key ("rowOwnerGUID")  references public.lrm_source_table("rowGUID") on delete cascade,
    constraint lrm_page_table_parent_fkey   foreign key ("rowParentGUID") references public.lrm_source_table("rowGUID") on delete cascade,
    constraint lrm_page_table_language_fkey foreign key (language) references public.lrm_language_table(code)
);

create unique index if not exists uq_lrm_page_table_key_lang_page
    on public.lrm_page_table (source_key, language, page_number);

-- 4b. Source structure: table of contents (chapters/sections) within a source --
-- Bridges lrm_source_table and lrm_page_table: a lightweight, nestable ToC
-- so the frontend viewer can jump to "Book II" instead of only paging one at
-- a time. RAG11's parent-chunks had titled sections; LRM pages don't, so this
-- fills that gap without changing lrm_page_table itself. Not auto-populated
-- yet -- rows are written by a future structure-detection step, same "table
-- exists, ready when you are" posture as lrm_entities_relations_table.
create table if not exists public.lrm_source_structure_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid,             -- nesting: a section's rowParentGUID is its chapter's rowGUID; null = top level
    "orderInList"   int  not null,    -- position among siblings at the same level
    "rowJSON"       jsonb not null,   -- {source_key, language, title, level, kind, start_page, end_page}

    source_key text generated always as ("rowJSON"->>'source_key') stored,
    language   text generated always as ("rowJSON"->>'language') stored,
    title      text generated always as ("rowJSON"->>'title') stored,
    level      int  generated always as (("rowJSON"->>'level')::int) stored,        -- 1 = top (book/part), 2 = chapter, 3 = section, ...
    start_page int  generated always as (("rowJSON"->>'start_page')::int) stored,
    end_page   int  generated always as (("rowJSON"->>'end_page')::int) stored,

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_source_structure_table_owner_fkey    foreign key ("rowOwnerGUID")  references public.lrm_source_table("rowGUID") on delete cascade,
    constraint lrm_source_structure_table_parent_fkey   foreign key ("rowParentGUID") references public.lrm_source_structure_table("rowGUID") on delete cascade,
    constraint lrm_source_structure_table_language_fkey foreign key (language) references public.lrm_language_table(code)
);

create unique index if not exists uq_lrm_source_structure_table_owner_order
    on public.lrm_source_structure_table ("rowOwnerGUID", "orderInList");
create index if not exists idx_lrm_source_structure_table_owner on public.lrm_source_structure_table ("rowOwnerGUID");
create index if not exists idx_lrm_source_structure_table_parent on public.lrm_source_structure_table ("rowParentGUID");
create index if not exists idx_lrm_source_structure_table_pages on public.lrm_source_structure_table (start_page, end_page);

-- 5. Chunks: one row per embeddable chunk of page text -------------------
-- Voyage voyage-3 embeddings are 1024-dimensional, same model/dimension as
-- RAG11's rag11_chunks_child_table -- adjust vector(...) below (and in
-- both RPCs) together if you ever change embedding models.
create table if not exists public.lrm_child_chunk_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid not null,   -- unlike lrm_page_table's, always set: a chunk always has a page
    "orderInList"   int  not null,   -- chunk position within its page (0 for the common one-chunk-per-page case)
    "rowJSON"       jsonb not null,  -- {source_key, language, page_number, text, char_start, char_end, block_ids}

    source_key  text generated always as ("rowJSON"->>'source_key') stored,
    language    text generated always as ("rowJSON"->>'language') stored,
    page_number int  generated always as (("rowJSON"->>'page_number')::int) stored,
    chunk_text  text generated always as ("rowJSON"->>'text') stored,

    embedding   extensions.vector(1024),   -- filled in by the embedding step

    -- keyword/lexical retrieval counterpart to `embedding`, exactly like
    -- rag11_chunks_child_table.chunk_tsv -- used by
    -- match_lrm_chunks_keyword() below.
    chunk_tsv   tsvector generated always as (to_tsvector('english', coalesce("rowJSON"->>'text', ''))) stored,

    created_at  timestamptz not null default timezone('utc', now()),

    constraint lrm_child_chunk_table_owner_fkey    foreign key ("rowOwnerGUID")  references public.lrm_source_table("rowGUID") on delete cascade,
    constraint lrm_child_chunk_table_parent_fkey   foreign key ("rowParentGUID") references public.lrm_page_table("rowGUID") on delete cascade,
    constraint lrm_child_chunk_table_language_fkey foreign key (language) references public.lrm_language_table(code)
);

create unique index if not exists uq_lrm_child_chunk_table_key_lang_page_order
    on public.lrm_child_chunk_table (source_key, language, page_number, "orderInList");

create index if not exists idx_lrm_child_chunk_table_owner on public.lrm_child_chunk_table ("rowOwnerGUID");
create index if not exists idx_lrm_child_chunk_table_parent on public.lrm_child_chunk_table ("rowParentGUID");

create index if not exists idx_lrm_child_chunk_table_embedding_hnsw
    on public.lrm_child_chunk_table
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

create index if not exists idx_lrm_child_chunk_table_tsv_gin
    on public.lrm_child_chunk_table
    using gin (chunk_tsv);

-- 6. Stored procedure: vector search over LRM chunks ----------------------
drop function if exists public.match_lrm_chunks(extensions.vector, int, uuid, text);

create or replace function public.match_lrm_chunks(
    query_embedding  extensions.vector(1024),
    match_count      int  default 8,
    filter_owner     uuid default null,  -- a lrm_source_table.rowGUID
    filter_language  text default null   -- a lrm_language_table.code
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
    from public.lrm_child_chunk_table c
    where c.embedding is not null
      and (filter_owner is null or c."rowOwnerGUID" = filter_owner)
      and (filter_language is null or c.language = filter_language)
    order by c.embedding <=> query_embedding asc
    limit least(match_count, 50);
$$;

-- 6b. Stored procedure: keyword (full-text) search over LRM chunks -------
drop function if exists public.match_lrm_chunks_keyword(text, int, uuid, text);

create or replace function public.match_lrm_chunks_keyword(
    query_text       text,
    match_count      int  default 8,
    filter_owner     uuid default null,
    filter_language  text default null
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
    from public.lrm_child_chunk_table c
    where c.chunk_tsv @@ websearch_to_tsquery('english', query_text)
      and (filter_owner is null or c."rowOwnerGUID" = filter_owner)
      and (filter_language is null or c.language = filter_language)
    order by text_rank desc
    limit least(match_count, 50);
$$;

-- 7. Stored procedure: fetch one page's full row by rowGUID ---------------
-- Lets the retrieval layer expand a matched chunk back to its full page
-- (blocks/words/bboxes) without a second hand-built REST query -- exactly
-- like get_rag11_parent() does for RAG11.
create or replace function public.get_lrm_page(
    p_row_guid uuid
)
returns public.lrm_page_table
language sql stable
as $$
    select * from public.lrm_page_table where "rowGUID" = p_row_guid;
$$;

-- =========================================================================
-- 8. Data dictionary: IFLA LRM-grounded model registry ---------------------
-- A self-describing metadata layer, not new content tables. It documents
-- lrm_source_table/lrm_page_table/lrm_child_chunk_table/lrm_language_table in
-- terms of the IFLA Library Reference Model (LRM, the 2017 bibliographic
-- conceptual model from IFLA -- unrelated to "LRM" = Language Reading
-- Model, this project's own name) instead of restructuring them into
-- separate Work/Expression/Manifestation/Item tables, which this
-- single-book system does not yet need. Nothing above reads or writes
-- these three tables; they exist purely as governance/documentation and a
-- landing place for future standards-mapping and entity associations.
--
--   lrm_definition_table -- what kinds of things exist in this model
--       (IFLA LRM's 11 entities, plus our own internal concepts: source,
--       page, chunk, language). One row per concept, not per instance.
--       Same 5-column pattern as every content table: rowParentGUID is a
--       self-referential taxonomy link (e.g. 'person' -> 'agent'), and
--       rowOwnerGUID == rowGUID (a definition owns itself, like a source).
--   lrm_definition_attribute_table  -- the data dictionary: what attributes each
--       definition has, its data type, whether required/repeatable, and
--       (when implemented) which real column carries it. A row with
--       maps_to_column = null is a documented-but-not-yet-built attribute
--       (e.g. Manifestation.carrier_type) -- extending the model is one
--       insert here, same "add a row, not a migration" pattern
--       lrm_language_table already uses for languages. rowOwnerGUID
--       points at the owning lrm_definition_table row.
--   lrm_entities_relations_table   -- typed edges between two concepts, of two
--       kinds (relation_kind): 'external_mapping' (our attribute <->
--       an external standard's element, e.g. Dublin Core) and
--       'association' (a real many-to-many link between entity instances
--       that are peers, not parent/child -- e.g. a Work and its Agent).
--       Polymorphic by design (source_type/target_type can name any
--       definition or table), so it cannot carry a strict foreign key to
--       either side; source_ref/target_ref are free-text identifiers
--       (a code, a rowGUID as text, or a label) instead.
-- =========================================================================

create table if not exists public.lrm_definition_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null,
    "rowParentGUID" uuid,             -- self-referential taxonomy, e.g. 'person' row -> 'agent' row; null = top-level
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,   -- {code, label, is_ifla_lrm, ifla_lrm_entity, maps_to_table, definition}

    code            text generated always as ("rowJSON"->>'code') stored,             -- e.g. 'work', 'expression', 'source'
    label           text generated always as ("rowJSON"->>'label') stored,            -- e.g. 'Expression'
    is_ifla_lrm     boolean generated always as (coalesce(("rowJSON"->>'is_ifla_lrm')::boolean, false)) stored,

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_definition_table_self_owned check ("rowOwnerGUID" = "rowGUID"),  -- a definition owns itself
    constraint lrm_definition_table_parent_fkey foreign key ("rowParentGUID") references public.lrm_definition_table("rowGUID"),
    constraint lrm_definition_table_code_key unique (code)  -- every entity_code lookup and FK targets this
);

insert into public.lrm_definition_table ("rowGUID", "rowOwnerGUID", "orderInList", "rowJSON")
select id, id, ord, jsonb_build_object(
    'code', code, 'label', label, 'is_ifla_lrm', is_ifla_lrm,
    'ifla_lrm_entity', ifla_lrm_entity, 'maps_to_table', maps_to_table, 'definition', definition)
from (
    select gen_random_uuid() as id, * from (values
        ('res', 'Res', true, 'LRM-E1 Res', null::text,
            'The most generic IFLA LRM entity: anything that can be talked about or referred to, the root every other entity specialises.', 1),
        ('work', 'Work', true, 'LRM-E2 Work', null,
            'The distinct intellectual or artistic content of a creation -- the abstract idea, independent of how it is worded, translated, or published.', 2),
        ('expression', 'Expression', true, 'LRM-E3 Expression', 'lrm_source_table',
            'A specific intellectual or artistic realisation of a Work -- e.g. a particular text or translation. lrm_source_table (one row per book+language) is our closest current implementation, though it also carries some Manifestation-level detail (e.g. page_count) since Work/Expression/Manifestation are not yet split into separate tables.', 3),
        ('manifestation', 'Manifestation', true, 'LRM-E4 Manifestation', null,
            'The physical or digital embodiment of an Expression -- e.g. a specific edition, printing, or PDF. Not yet a separate table in this schema; see lrm_definition_attribute_table for its planned attributes.', 4),
        ('item', 'Item', true, 'LRM-E5 Item', null,
            'A single exemplar of a Manifestation -- one specific physical or digital copy. Not tracked separately; this system has no notion of "which copy".', 5),
        ('agent', 'Agent', true, 'LRM-E6 Agent', null,
            'An entity capable of deliberate action, of being granted rights, and of being held accountable -- e.g. an author, translator, or publisher. Not yet a table; see lrm_entities_relations_table for the illustrative association pattern.', 6),
        ('person', 'Person', true, 'LRM-E7 Person', null,
            'An individual human being.', 7),
        ('collective_agent', 'Collective Agent', true, 'LRM-E8 Collective Agent', null,
            'A gathering or organisation of agents acting as a unit -- e.g. a publisher or corporate body.', 8),
        ('nomen', 'Nomen', true, 'LRM-E9 Nomen', null,
            'An association between an entity and a name, identifier, or code by which it is known.', 9),
        ('place', 'Place', true, 'LRM-E10 Place', null,
            'A location, of any extent, used to situate an entity (e.g. a place of publication).', 10),
        ('time_span', 'Time-span', true, 'LRM-E11 Time-span', null,
            'A temporal extent with a beginning, an end, and a duration -- e.g. a publication year.', 11),
        ('source', 'Source', false, null, 'lrm_source_table',
            'LRM11-internal: one row per (book, language) -- see the "expression" row above for how this maps to IFLA LRM.', 12),
        ('page', 'Page', false, null, 'lrm_page_table',
            'LRM11-internal: one recognised/translated page. No IFLA LRM equivalent -- purely an artifact of the OCR pipeline.', 13),
        ('chunk', 'Chunk', false, null, 'lrm_child_chunk_table',
            'LRM11-internal: one embeddable slice of a page''s text. No IFLA LRM equivalent.', 14),
        ('language', 'Language', false, null, 'lrm_language_table',
            'LRM11-internal reference concept: a supported language code. Loosely corresponds to IFLA LRM''s "has language" attribute of Expression.', 15),
        ('source_structure', 'Source structure', false, null, 'lrm_source_structure_table',
            'LRM11-internal: a table-of-contents entry (chapter/section) within a source. No IFLA LRM equivalent.', 16)
    ) as t(code, label, is_ifla_lrm, ifla_lrm_entity, maps_to_table, definition, ord)
) s
on conflict (code) do nothing;

-- Taxonomy: Person and Collective Agent are sub-types of Agent (IFLA LRM's own hierarchy).
-- A separate UPDATE, not inline in the insert above, so the seed data needs no hardcoded UUIDs.
update public.lrm_definition_table
set "rowParentGUID" = (select "rowGUID" from public.lrm_definition_table where code = 'agent')
where code in ('person', 'collective_agent') and "rowParentGUID" is null;

create table if not exists public.lrm_definition_attribute_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid not null references public.lrm_definition_table("rowGUID") on delete cascade,
    "rowParentGUID" uuid,             -- reserved, unused today -- kept for pattern consistency
    "orderInList"   int  not null,
    "rowJSON"       jsonb not null,   -- {code, attribute_name, label, data_type, is_required, is_repeatable, maps_to_column, ifla_lrm_attribute, description}

    code           text generated always as ("rowJSON"->>'code') stored,             -- e.g. 'expression.language'
    attribute_name text generated always as ("rowJSON"->>'attribute_name') stored,
    data_type      text generated always as ("rowJSON"->>'data_type') stored,        -- 'text' | 'int' | 'boolean' | 'jsonb' | 'uuid' | 'vector' | 'timestamptz'

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_definition_attribute_table_code_key unique (code),
    constraint lrm_definition_attribute_table_owner_attr_key unique ("rowOwnerGUID", attribute_name)
);

insert into public.lrm_definition_attribute_table ("rowGUID", "rowOwnerGUID", "orderInList", "rowJSON")
select gen_random_uuid(), d."rowGUID", v.ord, jsonb_build_object(
    'code', v.entity_code || '.' || v.attribute_name, 'attribute_name', v.attribute_name, 'label', v.label,
    'data_type', v.data_type, 'is_required', v.is_required, 'is_repeatable', v.is_repeatable,
    'maps_to_column', v.maps_to_column, 'ifla_lrm_attribute', v.ifla_lrm_attribute, 'description', v.description)
from (values
    ('expression', 'language', 'Language', 'text', true, false, 'language', 'has language',
        'The language of this expression; FK into lrm_language_table.', 1),
    ('expression', 'title', 'Title', 'text', true, false, 'title', 'has title',
        'Display title, generated from rowJSON.', 2),
    ('expression', 'source_key', 'Source key', 'text', true, false, 'source_key', null,
        'LRM11-internal identifier slug, not an IFLA LRM attribute.', 3),
    ('manifestation', 'carrier_type', 'Carrier type', 'text', false, false, null, 'has carrier type',
        'e.g. "online resource". Documented for future use; no manifestation table exists yet.', 1),
    ('manifestation', 'extent', 'Extent', 'text', false, true, null, 'has extent',
        'e.g. page count / physical description. Currently approximated by lrm_source_table.rowJSON.page_count.', 2),
    ('work', 'has_form', 'Has form', 'text', false, true, null, 'has form of work',
        'e.g. "text", "treatise". Documented for future use.', 1),
    ('agent', 'name', 'Name', 'text', true, false, null, 'has name (via Nomen)',
        'Documented for future use; agents are currently only referenced as free-text labels in lrm_entities_relations_table associations.', 1),
    ('page', 'page_number', 'Page number', 'int', true, false, 'page_number', null, '1-based page number.', 1),
    ('page', 'blocks', 'Blocks', 'jsonb', true, true, 'rowJSON->blocks', null,
        'Word/block-level OCR content with bounding boxes.', 2),
    ('chunk', 'chunk_text', 'Chunk text', 'text', true, false, 'chunk_text', null, 'The embedded text.', 1),
    ('chunk', 'embedding', 'Embedding', 'vector', true, false, 'embedding', null, 'Voyage voyage-3 vector(1024).', 2),
    ('language', 'code', 'Code', 'text', true, false, 'code', null, 'e.g. ''fr'', ''en'', ''ru''.', 1),
    ('language', 'name', 'Name', 'text', true, false, 'name', null, 'Display name.', 2)
) as v(entity_code, attribute_name, label, data_type, is_required, is_repeatable, maps_to_column, ifla_lrm_attribute, description, ord)
join public.lrm_definition_table d on d.code = v.entity_code
on conflict (code) do nothing;

create index if not exists idx_lrm_definition_attribute_table_owner on public.lrm_definition_attribute_table ("rowOwnerGUID");

create table if not exists public.lrm_entities_relations_table (
    "rowGUID"       uuid primary key,
    "rowOwnerGUID"  uuid,             -- nullable: schema-level mapping rows have no owning content row
    "rowParentGUID" uuid,             -- reserved, unused today -- kept for pattern consistency with every other table
    "orderInList"   int not null default 0,
    "rowJSON"       jsonb not null,   -- {relation_kind, source_type, source_ref, predicate, target_type, target_ref, external_standard, external_uri, notes}

    relation_kind text generated always as ("rowJSON"->>'relation_kind') stored,  -- 'external_mapping' | 'association'
    source_type   text generated always as ("rowJSON"->>'source_type') stored,
    source_ref    text generated always as ("rowJSON"->>'source_ref') stored,
    predicate     text generated always as ("rowJSON"->>'predicate') stored,      -- e.g. 'equivalentTo', 'hasAgent', 'hasSubject'
    target_type   text generated always as ("rowJSON"->>'target_type') stored,
    target_ref    text generated always as ("rowJSON"->>'target_ref') stored,

    created_at timestamptz not null default timezone('utc', now()),

    constraint lrm_entities_relations_table_kind_check check (relation_kind in ('external_mapping', 'association'))
);

create index if not exists idx_lrm_entities_relations_table_kind on public.lrm_entities_relations_table (relation_kind);
create index if not exists idx_lrm_entities_relations_table_source on public.lrm_entities_relations_table (source_type, source_ref);
create index if not exists idx_lrm_entities_relations_table_target on public.lrm_entities_relations_table (target_type, target_ref);

-- Illustrative seed rows -- two schema-level Dublin Core mappings, and one instance-level
-- association using the real Yoga-Sutra source (safe to delete; nothing depends on these).
insert into public.lrm_entities_relations_table ("rowGUID", "orderInList", "rowJSON") values
    ('a1e1c1d1-0001-4a11-8a11-000000000001', 0, jsonb_build_object(
        'relation_kind', 'external_mapping', 'source_type', 'expression', 'source_ref', 'language',
        'predicate', 'equivalentTo', 'target_type', 'dublin_core', 'target_ref', 'dc:language',
        'external_standard', 'Dublin Core', 'external_uri', 'http://purl.org/dc/elements/1.1/language')),
    ('a1e1c1d1-0001-4a11-8a11-000000000002', 1, jsonb_build_object(
        'relation_kind', 'external_mapping', 'source_type', 'expression', 'source_ref', 'title',
        'predicate', 'equivalentTo', 'target_type', 'dublin_core', 'target_ref', 'dc:title',
        'external_standard', 'Dublin Core', 'external_uri', 'http://purl.org/dc/elements/1.1/title')),
    ('a1e1c1d1-0001-4a11-8a11-000000000003', 2, jsonb_build_object(
        'relation_kind', 'association', 'source_type', 'lrm_source_table', 'source_ref', 'yogasutra_janvier_2020_pdf_d_2021',
        'predicate', 'hasAgent', 'target_type', 'agent', 'target_ref', 'Patañjali (attributed author)',
        'notes', 'Illustrative: no lrm_agent_table yet, so target_ref is a free-text label rather than a rowGUID.'))
on conflict ("rowGUID") do nothing;

-- 9. Full permissions on all tables (POC / development only) -------------
-- Wide open for a POC, matching sql/create_sql_tables.sql's convention.
-- Before production, replace with narrower policies (e.g. read-only for
-- anon, writes restricted to service_role).
grant usage on schema public to anon, authenticated, service_role;

grant select, insert, update, delete on public.lrm_language_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_source_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_page_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_source_structure_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_child_chunk_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_definition_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_definition_attribute_table to anon, authenticated, service_role;
grant select, insert, update, delete on public.lrm_entities_relations_table to anon, authenticated, service_role;

alter table public.lrm_language_table            enable row level security;
alter table public.lrm_source_table              enable row level security;
alter table public.lrm_page_table                enable row level security;
alter table public.lrm_source_structure_table    enable row level security;
alter table public.lrm_child_chunk_table         enable row level security;
alter table public.lrm_definition_table          enable row level security;
alter table public.lrm_definition_attribute_table enable row level security;
alter table public.lrm_entities_relations_table  enable row level security;

drop policy if exists "allow all - lrm languages" on public.lrm_language_table;
create policy "allow all - lrm languages" on public.lrm_language_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm sources" on public.lrm_source_table;
create policy "allow all - lrm sources" on public.lrm_source_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm pages" on public.lrm_page_table;
create policy "allow all - lrm pages" on public.lrm_page_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm chunks" on public.lrm_child_chunk_table;
create policy "allow all - lrm chunks" on public.lrm_child_chunk_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm source structure" on public.lrm_source_structure_table;
create policy "allow all - lrm source structure" on public.lrm_source_structure_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm definitions" on public.lrm_definition_table;
create policy "allow all - lrm definitions" on public.lrm_definition_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm attributes" on public.lrm_definition_attribute_table;
create policy "allow all - lrm attributes" on public.lrm_definition_attribute_table
    for all to anon, authenticated, service_role using (true) with check (true);

drop policy if exists "allow all - lrm relations" on public.lrm_entities_relations_table;
create policy "allow all - lrm relations" on public.lrm_entities_relations_table
    for all to anon, authenticated, service_role using (true) with check (true);

grant execute on function public.match_lrm_chunks(extensions.vector, int, uuid, text)
    to anon, authenticated, service_role;
grant execute on function public.match_lrm_chunks_keyword(text, int, uuid, text)
    to anon, authenticated, service_role;
grant execute on function public.get_lrm_page(uuid)
    to anon, authenticated, service_role;
