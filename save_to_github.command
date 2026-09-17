#!/bin/zsh
# =========================================================================
# RAG11 Nutrition — Bulletproof Save & Push Workspace to GitHub
# Target Remote: https://github.com/fotomain/RAG11-nutriciology.git
# =========================================================================

set -eo pipefail

# Change directory to repo root
cd "$(dirname "$0")"
REPO_DIR="$(pwd)"

REMOTE_URL="https://github.com/fotomain/RAG11-nutriciology.git"
DEFAULT_BRANCH="main"

echo "========================================================"
echo "  RAG11 -> GitHub Robust Sync Utility"
echo "  Directory : ${REPO_DIR}"
echo "  Remote URL: ${REMOTE_URL}"
echo "========================================================"

# -------------------------------------------------------------------------
# Step 0: Auto-resolve stale locks and hung Git processes
# -------------------------------------------------------------------------
echo "[0/5] Checking repository health & clearing stale locks..."

# Terminate any hung git process specifically locking this repository
CURRENT_PID=$$
GIT_PIDS=$(pgrep -f "git " 2>/dev/null | tr '\n' ' ' || true)
if [ -n "$GIT_PIDS" ]; then
    for pid in $GIT_PIDS; do
        if [ "$pid" != "$CURRENT_PID" ]; then
            PROC_CWD=$(lsof -p "$pid" -Fn 2>/dev/null | grep "^n/" | grep "$REPO_DIR" || true)
            if [ -n "$PROC_CWD" ]; then
                echo "      Terminating hanging git process (PID: $pid)..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
    done
fi

# Safely remove all stale lock files (.git/index.lock, .git/refs/**/*.lock, etc.)
STALE_LOCKS=$(find .git -name "*.lock" 2>/dev/null || true)
if [ -n "$STALE_LOCKS" ]; then
    echo "      Removing stale lock files:"
    for lock_file in ${(f)STALE_LOCKS}; do
        echo "       - $lock_file"
        rm -f "$lock_file"
    done
fi

# -------------------------------------------------------------------------
# Step 1: Ensure Git repository initialized
# -------------------------------------------------------------------------
if [ ! -d ".git" ]; then
    echo "[1/5] Initializing Git repository..."
    git init
else
    echo "[1/5] Git repository verified."
fi

# -------------------------------------------------------------------------
# Step 2: Configure & Verify Remote Origin
# -------------------------------------------------------------------------
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$CURRENT_REMOTE" ]; then
    echo "[2/5] Adding origin remote: ${REMOTE_URL}"
    git remote add origin "$REMOTE_URL"
elif [ "$CURRENT_REMOTE" != "$REMOTE_URL" ]; then
    echo "[2/5] Updating origin remote to: ${REMOTE_URL}"
    git remote set-url origin "$REMOTE_URL"
else
    echo "[2/5] Origin remote verified: ${REMOTE_URL}"
fi

# Ensure default branch is main
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$DEFAULT_BRANCH")
if [ "$CURRENT_BRANCH" = "HEAD" ] || [ -z "$CURRENT_BRANCH" ]; then
    CURRENT_BRANCH="$DEFAULT_BRANCH"
    git checkout -B "$DEFAULT_BRANCH" 2>/dev/null || true
fi

# -------------------------------------------------------------------------
# Step 3: Stage all files (respecting .gitignore)
# -------------------------------------------------------------------------
echo "[3/5] Staging workspace files..."

STAGE_ATTEMPTS=0
while [ $STAGE_ATTEMPTS -lt 3 ]; do
    if git add -A; then
        break
    else
        STAGE_ATTEMPTS=$((STAGE_ATTEMPTS + 1))
        echo "      Staging attempt $STAGE_ATTEMPTS failed, clearing locks and retrying..."
        find .git -name "*.lock" -delete 2>/dev/null || true
        sleep 1
    fi
done

# -------------------------------------------------------------------------
# Step 4: Commit changes
# -------------------------------------------------------------------------
USER_INPUT="${1:-}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

if [ -n "$USER_INPUT" ]; then
    if [[ "$USER_INPUT" == *.ipynb ]]; then
        COMMIT_MSG="Update ${USER_INPUT}: ${TIMESTAMP}"
    else
        COMMIT_MSG="${USER_INPUT}"
    fi
else
    MODIFIED_NB=$(git diff --staged --name-only | grep '\.ipynb$' | head -n 3 | tr '\n' ' ' || true)
    if [ -n "$MODIFIED_NB" ]; then
        COMMIT_MSG="Update ${MODIFIED_NB}(${TIMESTAMP})"
    else
        COMMIT_MSG="Update RAG11 nutriciology pipeline: ${TIMESTAMP}"
    fi
fi

if git diff --staged --quiet; then
    echo "[4/5] Working tree clean, no new uncommitted changes."
else
    echo "[4/5] Committing changes: \"${COMMIT_MSG}\""
    git commit -m "$COMMIT_MSG"
fi

# -------------------------------------------------------------------------
# Step 5: Pull remote updates (rebase/merge) & Push to GitHub
# -------------------------------------------------------------------------
echo "[5/5] Synchronizing with GitHub (${CURRENT_BRANCH})..."

git fetch origin "$CURRENT_BRANCH" 2>/dev/null || true

BEHIND=$(git rev-list --count HEAD..origin/"$CURRENT_BRANCH" 2>/dev/null || echo "0")
if [ "$BEHIND" -gt 0 ]; then
    echo "      Branch is behind remote by $BEHIND commit(s). Syncing remote changes..."
    if ! git pull --rebase --autostash origin "$CURRENT_BRANCH" 2>/dev/null; then
        echo "      Rebase conflict detected, aborting rebase and performing standard merge..."
        git rebase --abort 2>/dev/null || true
        git pull --no-edit origin "$CURRENT_BRANCH" 2>/dev/null || true
    fi
fi

PUSH_SUCCESS=0
for attempt in 1 2 3; do
    echo "      Pushing to origin ${CURRENT_BRANCH} (attempt ${attempt}/3)..."
    if git push -u origin "$CURRENT_BRANCH"; then
        PUSH_SUCCESS=1
        break
    else
        echo "      Push failed. Retrying after clearing locks & remote sync..."
        find .git -name "*.lock" -delete 2>/dev/null || true
        git pull --rebase origin "$CURRENT_BRANCH" 2>/dev/null || true
        sleep 2
    fi
done

if [ $PUSH_SUCCESS -eq 1 ]; then
    echo ""
    echo "========================================================"
    echo "  Successfully synchronized with GitHub!"
    echo "  Branch    : ${CURRENT_BRANCH}"
    echo "  Commit    : $(git rev-parse --short HEAD)"
    echo "  Repository: https://github.com/fotomain/RAG11-nutriciology"
    echo "========================================================"
else
    echo ""
    echo "========================================================"
    echo "  WARNING: Push failed after 3 attempts."
    echo "  Local commits are safely preserved in git history."
    echo "========================================================"
    exit 1
fi

# Keep window open only if double-clicked from macOS Finder interactively
if [ -t 0 ] && [ -z "${NON_INTERACTIVE:-}" ]; then
    echo ""
    read -k 1 -s "?Press any key to close this window..."
    echo ""
fi
