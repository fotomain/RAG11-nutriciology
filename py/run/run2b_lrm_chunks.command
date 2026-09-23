#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
# Run after run2_lrm_upload.command: chunks + embeds every lrm_page_table row into lrm_child_chunk_table.
# --source-key KEY / --language LANG restrict to one book/language; omit both to (re)chunk everything.
$PYTHON lrm/eda2_transform/build_chunks.py "$@"
