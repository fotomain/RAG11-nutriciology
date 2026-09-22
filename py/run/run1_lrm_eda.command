#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
$PYTHON lrm/data/download.py && $PYTHON lrm/data/run_all.py "$@"
