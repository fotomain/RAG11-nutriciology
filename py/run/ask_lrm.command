#!/bin/zsh
cd "$(dirname "$0")/.." || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
# Ask a question against an uploaded LRM source from the terminal.
# Usage: ./ask_lrm.command "question" [--source-key KEY] [--language LANG] [--reasoning|--no-reasoning]
$PYTHON lrm/reasoning/ask.py "$@"
