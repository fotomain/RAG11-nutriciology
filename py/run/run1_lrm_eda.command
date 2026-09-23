#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
$PYTHON lrm/eda1_extract/download.py && $PYTHON lrm/eda1_extract/run_all.py "$@"
