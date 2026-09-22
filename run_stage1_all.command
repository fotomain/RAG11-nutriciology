#!/bin/zsh
# =========================================================================
# RAG11 Nutrition -- run the FULL stage 1 pipeline in one go:
#   1.1 extract & chunk  ->  1.2 embed & load into Supabase  ->  1.9 verify
#
# Double-click it in Finder, or from a terminal:
#   ./run_stage1_all.command                    # everything
#   ./run_stage1_all.command --only 1.9         # just verify
#   ./run_stage1_all.command --from 1.2         # load + verify (reuse chunks on disk)
#   ./run_stage1_all.command --prune-orphans    # also delete Supabase rows with no local file
#
# Settings live in .env (see .env.sample), e.g. MAX_NUMBER_OF_PAGES_TO_USE=NONE for a full run, or
# START_PAGE_NUMBER=303 + MAX_NUMBER_OF_PAGES_TO_USE=10 to extract just pages 303-312 of each PDF.
# Every stage is idempotent and resumable, so if something fails: fix it and run again.
# Exit code: 0 = PASS, 1 = ran but verification found issues, 2 = a stage crashed.
# =========================================================================

cd "$(dirname "$0")" || exit 2

if [ ! -f .env ]; then
    echo "No .env file found. Create it first:  cp .env.sample .env   (then fill in your keys)"
    [[ -t 0 && -z "$NON_INTERACTIVE" ]] && read -k 1 "?Press any key to close..."
    exit 2
fi

# Use the project's virtualenv if there is one.
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi
PYTHON=${PYTHON:-python3}

# Avoid "[Errno 35] Resource temporarily unavailable" (low macOS open-file limit) during the upserts.
ulimit -n 10240 2>/dev/null || ulimit -n 4096 2>/dev/null || true

export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false

echo "RAG11 stage 1 pipeline  --  $(date '+%Y-%m-%d %H:%M:%S')"
"$PYTHON" -m reusable_code.stage1 "$@"
STATUS=$?

echo
case $STATUS in
    0) echo "Stage 1 finished: PASS" ;;
    1) echo "Stage 1 finished, but verification found issues (see stage 1.9 above)." ;;
    *) echo "Stage 1 stopped with an error (exit code $STATUS)." ;;
esac

# Keep the window open when double-clicked.
[[ -t 0 && -z "$NON_INTERACTIVE" ]] && read -k 1 "?Press any key to close..."
exit $STATUS
