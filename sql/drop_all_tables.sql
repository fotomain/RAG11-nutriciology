-- =========================================================================
-- RAG11 Nutrition RAG — Full teardown
-- Run in the Supabase Dashboard -> SQL Editor.
--
-- Drops everything sql/create_sql_tables.sql creates: all three tables
-- (rag11_data_sources, rag11_chunks_parent_table, rag11_chunks_child_table
-- -- their indexes, RLS policies, and foreign keys go with them), and both
-- RPC functions. Nothing is left behind to `create table if not exists`
-- around next time, so re-running create_sql_tables.sql afterwards is a
-- completely clean rebuild rather than the guarded text->uuid migration
-- path (that migration only matters when the tables already exist).
--
-- This is DESTRUCTIVE and unrecoverable -- unlike delete_chunks_data.sql
-- (which empties the tables but keeps the schema), this removes the tables
-- themselves. Use delete_chunks_data.sql instead if you just want to clear
-- rows before a fresh stage1_2_eda_load_chunks.ipynb run.
--
-- `cascade` on each drop also removes the HNSW/unique/foreign-key
-- dependents automatically, so the order below (child -> parent -> sources)
-- is for readability, not correctness.
-- =========================================================================

drop function if exists public.match_rag11_child_chunks(extensions.vector, int, uuid);
drop function if exists public.get_rag11_parent(uuid);

drop table if exists public.rag11_chunks_child_table cascade;
drop table if exists public.rag11_chunks_parent_table cascade;
drop table if exists public.rag11_data_sources cascade;

-- Not dropped: the `vector` extension itself (sql/create_sql_tables.sql's
-- step 1) -- other tables/projects in the same Supabase database may
-- depend on it. Uncomment if you're sure nothing else uses it:
-- drop extension if exists vector;

-- ---------------------------------------------------------------------
-- Sanity check — should return zero rows once the drop above succeeded.
-- ---------------------------------------------------------------------
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
      'rag11_data_sources',
      'rag11_chunks_parent_table',
      'rag11_chunks_child_table'
  );
