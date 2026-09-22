#!/bin/zsh
cd "$(dirname "$0")" || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
$PYTHON stage3_1_lrm_data/download.py && $PYTHON stage3_1_lrm_data/run_all.py "$@"
