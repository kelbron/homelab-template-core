#!/bin/sh
# githooks/pre-commit.d/05-enforce-workspace-boundaries
# Ensures transient staging manifests or flat-files do not pollute the repo index.

set -eu

# Create a secure, ephemeral staged file tracker
STAGED_LIST=$(mktemp)

# POSIX-compliant cleanup sequence:
# 1. Force explicit exits on standard interruption signals so the EXIT signal fires.
trap 'exit 1' INT TERM HUP

# 2. Bind the actual cleanup command strictly to the EXIT signal.
trap 'rm -f "$STAGED_LIST"' EXIT

git diff --cached --name-only --diff-filter=ACM > "$STAGED_LIST"

if [ ! -s "$STAGED_LIST" ]; then
    rm -f "$STAGED_LIST"
    echo "✅ No staged files to audit."
    exit 0
fi

FAILED=0

# Safely read line-by-line, preserving spaces in file paths
# Safely processes the last line even if it lacks a trailing newline
while read -r FILE || [ -n "$FILE" ]; do
    [ -z "$FILE" ] && continue

    # Rule 2: Enforce K8s subfolder encapsulation (ADR 002)
    case "$FILE" in
        *.yaml|*.yml)
            case "$FILE" in
                .github/workflows/*) continue ;;
            esac

            # Block root-level manifest leaks
            if [ "$(dirname "$FILE")" = "." ]; then
                echo "❌ ERROR: Manifest file leaked in repository root: '$FILE'"
                FAILED=1
                continue
            fi

            # Enforce folder structures strictly using directory names
            DIR_NAME=$(dirname "$FILE")
            case "$DIR_NAME" in
                manifests)
                    echo "❌ ERROR: Prohibited flat-file manifest detected: '$FILE'"
                    echo "   ADR 002 mandates that all manifests sit inside dedicated subfolders."
                    FAILED=1
                    ;;
                manifests/base)
                    echo "❌ ERROR: Prohibited flat-file manifest inside base/: '$FILE'"
                    echo "   ADR 002 mandates that all manifests sit inside dedicated subfolders."
                    FAILED=1
                    ;;
                manifests/apps)
                    echo "❌ ERROR: Prohibited flat-file manifest inside apps/: '$FILE'"
                    echo "   ADR 002 mandates that all manifests sit inside dedicated subfolders."
                    FAILED=1
                    ;;
            esac
            ;;
    esac
done < "$STAGED_LIST"

if [ "$FAILED" -eq 1 ]; then
    echo "🛑 Boundary Audit Failed! Please resolve the errors above before committing."
    exit 1
fi

echo "✅ All staged files comply with repository boundary standards."
exit 0
