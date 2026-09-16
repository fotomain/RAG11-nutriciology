-- =========================================================================
-- RAG11 Nutrition RAG — Delete/reset chunk data
-- Run in the Supabase Dashboard -> SQL Editor.
--
-- Use this before re-running stage1_2_eda_load_chunks.ipynb whenever
-- stage1_1's section-detection logic changes (as it just did): the number
-- of sections per source can shrink, and an upsert only overwrites rows
-- whose id it re-generates -- rows for sections that no longer exist are
-- never touched by an upsert, so they'd otherwise be left behind as stale
-- orphans. Deleting the parent row cascades to its child rows via the
-- foreign key (on delete cascade), so deleting from the parent table alone
-- is enough in every option below.
-- =========================================================================

-- ---------------------------------------------------------------------
-- Option A — full reset (recommended right now: all three sources'
-- section counts changed, so there is nothing worth keeping selectively).
-- ---------------------------------------------------------------------
truncate table public.rag11_chunks_parent_table, public.rag11_chunks_child_table
    restart identity cascade;


-- ---------------------------------------------------------------------
-- Option B — delete just one source, e.g. after re-tuning only that
-- source's section detection and wanting to leave the other two alone.
-- Uncomment and run one at a time as needed (a plain "delete" respects
-- foreign keys/cascade the same way truncate does, just row-by-row).
-- ---------------------------------------------------------------------
-- delete from public.rag11_chunks_parent_table where "rowOwnerGUID" = 'source1';
-- delete from public.rag11_chunks_parent_table where "rowOwnerGUID" = 'source2';
-- delete from public.rag11_chunks_parent_table where "rowOwnerGUID" = 'source3';


-- ---------------------------------------------------------------------
-- Sanity check — run after either option to confirm the tables are in
-- the state you expect before re-running stage1_2_eda_load_chunks.ipynb.
-- ---------------------------------------------------------------------
select "rowOwnerGUID", count(*) as parent_rows
from public.rag11_chunks_parent_table
group by "rowOwnerGUID"
order by "rowOwnerGUID";

select "rowOwnerGUID", count(*) as child_rows
from public.rag11_chunks_child_table
group by "rowOwnerGUID"
order by "rowOwnerGUID";
