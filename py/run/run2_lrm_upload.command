#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
# First time only: paste ../../sql/create_lrm_tables.sql into the Supabase SQL Editor and run it.
$PYTHON lrm/eda3_load/upload.py "$@"
