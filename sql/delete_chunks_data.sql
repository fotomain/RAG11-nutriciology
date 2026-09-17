-- =========================================================================
-- RAG11 Nutrition RAG — Delete/reset chunk (and source) data
-- Run in the Supabase Dashboard -> SQL Editor.
--
-- Use this before re-running stage1_2_eda_load_chunks.ipynb whenever
-- stage1_1's section-detection logic changes: the number of sections per
-- source can shrink, and an upsert only overwrites rows whose id it
-- re-generates -- rows for sections that no longer exist are never touched
-- by an upsert, so they'd otherwise be left behind as stale orphans.
-- Deleting a parent row cascades to its child rows via the foreign key (on
-- delete cascade), and deleting a source row cascades to all its parent
-- (and therefore child) rows the same way -- so deleting from the topmost
-- table involved is enough in every option below.
--
-- This is also the "empty the tables first" step
-- sql/create_sql_tables.sql's rowOwnerGUID text->uuid migration guard asks
-- for, if you're upgrading a pre-rag11_data_sources deployment that already
-- has rows in it.
-- =========================================================================

-- ---------------------------------------------------------------------
-- Option A — full reset (sources + parents + children). Recommended
-- whenever the Drive folder's file set or any source's section counts
-- changed, so there is nothing worth keeping selectively.
-- ---------------------------------------------------------------------
truncate table
    public.rag11_data_sources,
    public.rag11_chunks_parent_table,
    public.rag11_chunks_child_table
    restart identity cascade;


-- ---------------------------------------------------------------------
-- Option B — delete just one source (and its parent/child rows via
-- cascade), e.g. after re-tuning only that source's section detection and
-- wanting to leave the others alone. Uncomment and run one at a time as
-- needed. Filters on `source_key` (a column generated from rowJSON), which
-- stays human-readable now that rowOwnerGUID itself is a uuid.
-- ---------------------------------------------------------------------
-- delete from public.rag11_data_sources where source_key = 'source1';
-- delete from public.rag11_data_sources where source_key = 'source2';
-- delete from public.rag11_data_sources where source_key = 'source3';


-- ---------------------------------------------------------------------
-- Sanity check — run after either option to confirm the tables are in
-- the state you expect before re-running stage1_2_eda_load_chunks.ipynb.
-- ---------------------------------------------------------------------
select source_key, "rowGUID" as source_row_guid
from public.rag11_data_sources
order by source_key;

select source_key, count(*) as parent_rows
from public.rag11_chunks_parent_table
group by source_key
order by source_key;

select source_key, count(*) as child_rows
from public.rag11_chunks_child_table
group by source_key
order by source_key;
