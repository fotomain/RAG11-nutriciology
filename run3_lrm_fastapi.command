#!/bin/zsh
cd "$(dirname "$0")" || exit 2
[ -f .venv/bin/activate ] && source .venv/bin/activate
PYTHON=${PYTHON:-python3}
$PYTHON -m uvicorn stage8_fastapi.main:app --port 8000
