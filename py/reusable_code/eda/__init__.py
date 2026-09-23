"""LRM11 -- EDA pipeline logic: recognise (OCR), translate, chunk+embed, upload, download.

The actual work behind py/lrm/eda1_extract (recognise + translate), eda2_transform (chunk+embed)
and eda3_load (upload to Supabase) lives here, the same "thin CLI wrapper calling into
reusable_code" shape as py/lrm/reasoning/ask.py -> reusable_code.reasoning. Each submodule below
is used by exactly one py/lrm/eda*/*.py script; see that script's docstring for the CLI.

Modules:
    languages   -- LANGS: display name / OCR prompt name / translate.py style notes, per language
    schema      -- BLOCK_TYPES, SCHEMA, PROMPT: the page-recognition JSON schema + vision prompt
    providers/  -- google.py, aws.py: OCR_PROVIDER_NAME backends recognize.py dispatches to
    recognize   -- page recognition engine: set_stage_dir(), configure(), recognise_pdf(), refine_all(), link_book()
    translate   -- layout-preserving translation engine: set_stage_dir() (via recognize), translate_source()
    download    -- download_sources(): pull source PDFs from LRM_SOURCES_FOLDER (Google Drive)
    chunks      -- chunk_and_embed(): lrm_page_table -> lrm_child_chunk_table
    load/       -- upload.py: sync_to_supabase(): lrm/eda1_extract/output -> lrm_source_table/lrm_page_table
    extract/    -- process_source(): per-source section detection (SOURCES config + custom/ outliers)
    transform/  -- retrieval transforms: hybrid search, HyDE, multi-query splitting, parent expansion
"""
