#!/bin/zsh
# =========================================================================
# RAG11 Nutrition — Save & Push Workspace to GitHub
# Target Remote: https://github.com/fotomain/RAG11-nutriciology.git
# =========================================================================

set -e

# Change directory to the folder where this script is located
cd "$(dirname "$0")"

REMOTE_URL="https://github.com/fotomain/RAG11-nutriciology.git"
DEFAULT_BRANCH="main"

echo "========================================================"
echo "  RAG11 -> GitHub Sync Utility"
echo "  Directory : $(pwd)"
echo "  Remote URL: ${REMOTE_URL}"
echo "========================================================"

# 1. Initialize Git repository if not present
if [ ! -d ".git" ]; then
    echo "[1/5] Initializing new Git repository..."
    git init
else
    echo "[1/5] Git repository already initialized."
fi

# 2. Configure Remote Origin
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$CURRENT_REMOTE" ]; then
    echo "[2/5] Adding origin remote: ${REMOTE_URL}"
    git remote add origin "$REMOTE_URL"
elif [ "$CURRENT_REMOTE" != "$REMOTE_URL" ]; then
    echo "[2/5] Updating origin remote to: ${REMOTE_URL}"
    git remote set-url origin "$REMOTE_URL"
else
    echo "[2/5] Origin remote already set to: ${REMOTE_URL}"
fi

# 3. Ensure branch is main
git branch -M "$DEFAULT_BRANCH" 2>/dev/null || true

# 4. Stage all tracked/unignored files
echo "[3/5] Staging files (respecting .gitignore)..."
git add -A

# Check if there are changes to commit
if git diff --staged --quiet; then
    echo "[4/5] No new changes to commit."
else
    COMMIT_MSG="${1:-Update RAG11 nutriciology pipeline: $(date '+%Y-%m-%d %H:%M:%S')}"
    echo "[4/5] Committing changes with message:"
    echo "      \"${COMMIT_MSG}\""
    git commit -m "$COMMIT_MSG"
fi

# 5. Push to GitHub
echo "[5/5] Pushing to origin ${DEFAULT_BRANCH}..."
git push -u origin "$DEFAULT_BRANCH"

echo ""
echo "========================================================"
echo "  Successfully synchronized with GitHub!"
echo "  https://github.com/fotomain/RAG11-nutriciology"
echo "========================================================"

# Keep window open if double-clicked from macOS Finder
if [ -t 0 ]; then
    echo ""
    read -k 1 -s "?Press any key to close this window..."
    echo ""
fi
