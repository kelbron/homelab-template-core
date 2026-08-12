#!/usr/bin/env bash
# scripts/workstation/audit-shellcheck.sh
# Deterministically audits only the working tree version of changed shell scripts on disk.
# Prevents checking clean unmodified files while catching active staged/unstaged errors on disk.
# Fulfills ADR_011 (Directory Anchoring) and ADR_013 (Secrets Sovereignty).

set -euo pipefail

# ADR 011 Rule 5: Directory Anchoring (Script is 2 levels deep)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Enforce clean environment fallback locales
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

if ! command -v shellcheck &> /dev/null; then
    echo "⚠️  [ShellCheck Audit] 'shellcheck' is not installed!"
    echo "   To enable syntax checks, run: sudo apt install shellcheck"
    exit 0
fi

echo "🔍 Auditing changed and staged Shell scripts on disk..."

failed=0
# Loop through files with any changes (staged or unstaged) compared to HEAD
while IFS= read -r file; do
    [ -z "$file" ] && continue
    
    # Check if the file physically exists in the working directory
    if [ -f "${REPO_ROOT}/${file}" ]; then
        first_line=$(head -n 1 "${REPO_ROOT}/${file}" || true)
        if [[ "$file" =~ \.sh$ ]] || [[ "$first_line" =~ ^#\!.*sh ]]; then
            echo "   -> Scanning working tree: $file"
            if ! shellcheck "${REPO_ROOT}/${file}"; then
                echo "❌ ShellCheck failed on working version of: $file"
                failed=1
            fi
        fi
    fi
done < <(git -C "$REPO_ROOT" diff HEAD --name-only --diff-filter=ACMR 2>/dev/null || true)

if [ "$failed" -ne 0 ]; then
    echo "❌ [Audit Gate] ShellCheck validation failed! Fix disk errors before committing."
    exit 1
fi

echo "✅ ShellCheck audit completed successfully!"
exit 0
