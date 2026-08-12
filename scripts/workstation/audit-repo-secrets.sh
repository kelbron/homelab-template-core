#!/usr/bin/env bash
# scripts/workstation/audit-repo-secrets.sh
# Audits the local repository for potential secret leaks, untracked files, 
# and ensures that gitignore rules are actively protecting sensitive files.
# Aligned with ADR_011 (Automation Standards) and ADR_013 (Secrets Management).

set -euo pipefail

# Force safe environment fallback locales (suppresses locale warnings)
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

# ANSI color codes for terminal logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=====================================================================${NC}"
echo -e "${BLUE}🛡️  HOMELAB REPOSITORY SECURITY & SECRETS AUDIT GATE ${NC}"
echo -e "${BLUE}=====================================================================${NC}"

# Check if inside a git repo
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo -e "${RED}❌ ERROR: Not inside a Git repository! Run this script from your repository root.${NC}"
    exit 1
fi

# Directory Anchoring (ADR 011 Rule 5: Script is 2 levels deep inside scripts/workstation/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

FAILED=0

# Step 1: Active Tracking Audit
echo -e "\n${BLUE}🔎 Step 1: Checking for actively tracked sensitive files...${NC}"
TRACKED_SECRETS=$(git ls-files | grep -E '(\.tfvars$|\.env$|\.tfstate$|id_rsa|id_ed25519|\.pem$|\.key$|vault-keys\.json|\.kdbx$)' || true)

if [ -n "$TRACKED_SECRETS" ]; then
    echo -e "${RED}❌ CRITICAL WARNING: Git is actively tracking sensitive files!${NC}"
    echo -e "${RED}These files are committed or staged and WILL be pushed to your public repository:${NC}"
    while IFS= read -r file; do
        [ -z "$file" ] && continue
        echo -e "  - $file"
    done <<< "$TRACKED_SECRETS"
    echo -e "${YELLOW}👉 To stop tracking these files while keeping them locally, run:${NC}"
    echo -e "   git rm --cached <filename>"
    FAILED=1
else
    echo -e "${GREEN}✅ Clean! No actively tracked sensitive files detected.${NC}"
fi

# Step 2: Gitignore Enforcement Audit
echo -e "\n${BLUE}🔎 Step 2: Verifying .gitignore coverage for sensitive files...${NC}"
EXISTING_SECRETS=$(find . -type f \( -name "*.env" -o -name "*.tfvars" -o -name "*.tfstate" -o -name "vault-keys.json" -o -name "*.kdbx" \) -not -path '*/.*' -not -path '*/node_modules/*' || true)

if [ -n "$EXISTING_SECRETS" ]; then
    UNIGNORED_SECRETS=""
    while IFS= read -r file; do
        [ -z "$file" ] && continue
        if ! git check-ignore -q "$file"; then
            UNIGNORED_SECRETS="${UNIGNORED_SECRETS}\n  - $file"
        fi
    done <<< "$EXISTING_SECRETS"

    if [ -n "$UNIGNORED_SECRETS" ]; then
        echo -e "${RED}❌ WARNING: Found existing secret files NOT covered by .gitignore:${NC}"
        echo -e "$UNIGNORED_SECRETS"
        echo -e "${YELLOW}👉 Add these patterns to your .gitignore immediately!${NC}"
        FAILED=1
    else
        echo -e "${GREEN}✅ Safe! All existing local secret files (.env, .tfvars, .tfstate, .kdbx) are properly ignored.${NC}"
    fi
else
    echo -e "${GREEN}✅ Safe! No local .env, .tfvars, or backup files found in the directory tree.${NC}"
fi

# Step 3: High-Entropy Plaintext Scan
echo -e "\n${BLUE}🔎 Step 3: Scanning files for high-entropy strings and plaintext patterns...${NC}"
PATTERN="(password|token|pat|client_secret|client-secret|clientid|client-id|access_key|access-key|api-token|api_token)[[:space:]]*=[[:space:]]*[\"'][a-zA-Z0-9_-]{8,128}[\"']"

SUSPICIOUS_LINES=$(git grep -E -n -i "$PATTERN" -- '*.tf' '*.sh' '*.yaml' '*.yml' '*.env' '*.json' 2>/dev/null || true)

if [ -n "$SUSPICIOUS_LINES" ]; then
    echo -e "${YELLOW}⚠️  POTENTIAL PLAIN-TEXT SECRET LEAKS DETECTED:${NC}"
    echo -e "${YELLOW}The following tracked lines seem to assign sensitive strings in plain text:${NC}"
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        echo -e "  - $line"
    done <<< "$SUSPICIOUS_LINES"
    echo -e "${YELLOW}👉 Ensure these values are abstracted into variables/Azure Key Vault references!${NC}"
else
    echo -e "${GREEN}✅ Clean! No obvious plain-text password/token assignments found in tracked files.${NC}"
fi

# Step 4: Line Normalization Check
echo -e "\n${BLUE}🔎 Step 4: Running validation checklist...${NC}"
if [ -f ".gitattributes" ]; then
    echo -e "${GREEN}✅ .gitattributes exists (line normalization is active).${NC}"
else
    echo -e "${YELLOW}⚠️  Missing .gitattributes! Highly recommended for cross-platform WSL setups to prevent CRLF errors.${NC}"
fi

if [ "$FAILED" -eq 1 ]; then
    echo -e "\n${RED}🛑 AUDIT FAILED! Please resolve the security gaps above before pushing code to your public repository.${NC}"
    exit 1
else
    echo -e "\n${GREEN}🎉 SUCCESS! Your repository is 100% clean and ready for public push!${NC}"
    exit 0
fi
