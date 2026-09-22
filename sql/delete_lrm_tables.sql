-- =========================================================================
-- LRM — Full teardown
-- Run in the Supabase Dashboard -> SQL Editor, or via
-- py/run/run2_lrm_upload.command --reset (which also re-runs
-- create_lrm_tables.sql right after, via --init).
--
-- Drops everything sql/create_lrm_tables.sql creates: lrm_child_chunk_table,
-- lrm_source_structure_table, lrm_page_table, lrm_source_table,
-- lrm_language_table, and the IFLA LRM-grounded data dictionary
-- (lrm_entities_relations_table, lrm_definition_attribute_table, lrm_definition_table) --
-- their indexes, RLS policies, and foreign keys go with them -- and all
-- three RPC functions. This is DESTRUCTIVE and unrecoverable.
--
-- `cascade` on each drop also removes HNSW/unique/foreign-key dependents
-- automatically, so the order below (chunks -> structure -> pages ->
-- sources -> languages, then relations -> attributes -> definitions) is
-- for readability, not correctness.
-- =========================================================================

drop function if exists public.match_lrm_chunks(extensions.vector, int, uuid, text);
drop function if exists public.match_lrm_chunks_keyword(text, int, uuid, text);
drop function if exists public.get_lrm_page(uuid);

drop table if exists public.lrm_child_chunk_table cascade;
drop table if exists public.lrm_source_structure_table cascade;
drop table if exists public.lrm_page_table cascade;
drop table if exists public.lrm_source_table cascade;
drop table if exists public.lrm_language_table cascade;

drop table if exists public.lrm_entities_relations_table cascade;
drop table if exists public.lrm_definition_attribute_table cascade;
drop table if exists public.lrm_definition_table cascade;

-- Not dropped: the `vector` extension itself -- other tables/projects in
-- the same Supabase database (including the RAG11 schema) may depend on
-- it. Uncomment only if you're sure nothing else uses it:
-- drop extension if exists vector;

-- ---------------------------------------------------------------------
-- Sanity check — should return zero rows once the drop above succeeded.
-- ---------------------------------------------------------------------
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
      'lrm_language_table', 'lrm_source_table', 'lrm_page_table', 'lrm_source_structure_table',
      'lrm_child_chunk_table', 'lrm_definition_table', 'lrm_definition_attribute_table', 'lrm_entities_relations_table'
  );
