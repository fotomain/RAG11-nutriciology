#!/bin/zsh
# Sequential: 1 normalize -> 2 upload -> 3 API (background) -> 4 frontend (foreground)
cd "$(dirname "$0")" || exit 2
./run1_lrm_eda.command || exit 1
./run2_lrm_upload.command "$@" || exit 1
./run3_lrm_fastapi.command &
API=$!; trap "kill $API 2>/dev/null" EXIT
./run4_lrm_frontend.command
