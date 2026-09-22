#!/bin/zsh
cd "$(dirname "$0")" || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
# add --init (needs LRM_DB_URL in .env) to create tables; or paste stage3_2_lrm_init/create_lrm_tables.sql in the Supabase SQL Editor once
$PYTHON stage3_3_lrm_upload/upload.py "$@"
