#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
# add --init (needs LRM_DB_URL in .env) to create tables; or paste lrm/init/create_lrm_tables.sql in the Supabase SQL Editor once
$PYTHON lrm/upload/upload.py "$@"
