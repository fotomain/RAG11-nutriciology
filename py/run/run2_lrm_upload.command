#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
# First time only: paste ../../sql/create_lrm_tables.sql into the Supabase SQL Editor and run it.
# 1) upload lrm_source_table/lrm_page_table, 2) chunk + embed every lrm_page_table row into lrm_child_chunk_table.
# --source-key KEY / --language LANG restrict chunking to one book/language; omit both to (re)chunk everything.
$PYTHON lrm/eda3_load/upload.py "$@" || exit 1
$PYTHON lrm/eda2_transform/build_chunks.py "$@"
