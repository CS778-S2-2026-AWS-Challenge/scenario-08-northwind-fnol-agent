#!/bin/bash
# Automated conflict resolution script for PR #84
# Usage: bash resolve_conflicts.sh

set -e

echo "🔄 Merging origin/main into employee_frontend_LLL..."

cd "$(git rev-parse --show-toplevel)"

# Check if already in a merge
if [ -f .git/MERGE_HEAD ]; then
    echo "⚠️  Merge already in progress. Aborting and restarting..."
    git merge --abort
fi

# Fetch and merge
git fetch origin main 2>/dev/null || {
    echo "❌ Network error: Cannot fetch from origin"
    echo "💡 Try again when you have internet access"
    exit 1
}

echo "📥 Starting merge (no auto-commit)..."
git merge origin/main --no-commit --no-ff || true

# Check for conflicts
if ! git diff --name-only --diff-filter=U | grep -q .; then
    echo "✅ No conflicts detected!"
    git merge --abort
    exit 0
fi

echo ""
echo "🔧 Resolving conflicts..."
echo ""

# Define conflict files and their resolution strategy
declare -A RESOLUTION_STRATEGY

# Files to keep "ours" (our branch version)
RESOLUTION_STRATEGY["backend/services/workbench.py"]="ours"
RESOLUTION_STRATEGY["backend/api/workbench.py"]="ours"
RESOLUTION_STRATEGY["tests/test_workbench_api.py"]="ours"
RESOLUTION_STRATEGY["backend/core/auth.py"]="ours"
RESOLUTION_STRATEGY["backend/core/config.py"]="ours"
RESOLUTION_STRATEGY["backend/app.py"]="ours"

# Files to keep "theirs" (main version)
RESOLUTION_STRATEGY[".env.example"]="theirs"

# Get list of conflicted files
CONFLICTED_FILES=$(git diff --name-only --diff-filter=U)

echo "Found conflicted files:"
echo "$CONFLICTED_FILES" | nl

echo ""

# Resolve each file
for FILE in $CONFLICTED_FILES; do
    if [ -z "${RESOLUTION_STRATEGY[$FILE]}" ]; then
        STRATEGY="manual"
    else
        STRATEGY="${RESOLUTION_STRATEGY[$FILE]}"
    fi

    case "$STRATEGY" in
        ours)
            echo "✅ $FILE → Keeping OURS (current branch)"
            git checkout --ours "$FILE"
            git add "$FILE"
            ;;
        theirs)
            echo "✅ $FILE → Keeping THEIRS (main branch)"
            git checkout --theirs "$FILE"
            git add "$FILE"
            ;;
        manual)
            echo "⚠️  $FILE → NEEDS MANUAL REVIEW"
            echo "   Run: git diff $FILE"
            echo "   Then: vim $FILE"
            echo "   Then: git add $FILE"
            ;;
    esac
done

echo ""
echo "📊 Conflict resolution status:"
git diff --name-only --diff-filter=U | wc -l | xargs echo "Remaining unresolved conflicts:"

REMAINING=$(git diff --name-only --diff-filter=U)
if [ -n "$REMAINING" ]; then
    echo ""
    echo "⚠️  These files need manual resolution:"
    echo "$REMAINING" | sed 's/^/  - /'
    echo ""
    echo "💡 For each file, edit it, then run: git add <file>"
    exit 1
else
    echo ""
    echo "✅ All conflicts resolved automatically!"
    echo ""
    echo "Next steps:"
    echo "  1. Review changes: git log --oneline -5"
    echo "  2. Run syntax check: python3 -m py_compile backend/services/workbench.py backend/api/workbench.py"
    echo "  3. Complete merge: git commit"
    echo "  4. Push: git push origin employee_frontend_LLL"
fi
