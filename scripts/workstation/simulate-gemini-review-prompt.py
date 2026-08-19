#!/usr/bin/env python3
import os
import sys
import json
import argparse
import re
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract Git diff and simulate the exact rendered prompt sent to Gemini API."
    )
    parser.add_argument(
        "--diff-path",
        default="build/pr_changes.diff",
        help="Path to the input Git diff file"
    )
    parser.add_argument(
        "--output-prompt-path",
        default="build/rendered_prompt.txt",
        help="Path to save the compiled prompt text"
    )
    return parser.parse_args()

def parse_diff_to_changes_list(diff_content):
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    current_file = None
    lines_by_file = {}
    changed_lines = set()
    
    current_line = 0
    for line in diff_content.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            if current_file.endswith(".md") or current_file.startswith("docs/"):
                current_file = None
                continue
            lines_by_file[current_file] = []
        elif line.startswith("@@"):
            match = hunk_re.match(line)
            if match:
                current_line = int(match.group(1))
        elif current_file and current_line > 0:
            if line.startswith("+") and not line.startswith("+++"):
                lines_by_file[current_file].append((current_line, line[1:]))
                changed_lines.add((current_file, current_line))
                current_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                pass
            else:
                current_line += 1
                
    formatted_list = []
    for filename, lines in lines_by_file.items():
        if lines:
            formatted_list.append(f"=== FILE: {filename} ===")
            for line_num, content in lines:
                formatted_list.append(f"Line {line_num}: {content}")
            formatted_list.append("")
            
    return "\n".join(formatted_list), changed_lines

def main():
    args = parse_args()
    
    diff_path = args.diff_path
    output_prompt_path = args.output_prompt_path

    # Ensure the parent directory for the input diff file exists if we need to auto-generate it
    diff_parent = os.path.dirname(os.path.abspath(diff_path))
    if diff_parent:
        os.makedirs(diff_parent, exist_ok=True)

    if not os.path.exists(diff_path):
        print(f"ℹ️ Input diff file '{diff_path}' not found on disk.")
        print("Creating a realistic mock diff file representing workstation changes for testing...")
        
        # Write a mock diff representing changes that often trick linters
        mock_diff = """diff --git a/scripts/bare-metal/deploy-ha-dns.sh b/scripts/bare-metal/deploy-ha-dns.sh
index 123456..789012 100755
--- a/scripts/bare-metal/deploy-ha-dns.sh
+++ b/scripts/bare-metal/deploy-ha-dns.sh
@@ -1,5 +1,6 @@
+set -euo pipefail
 # Simple deployment script
-echo "Deploying HA DNS"
+echo "Deploying HA DNS on control plane"
diff --git a/Makefile b/Makefile
index abc123..def456 100644
--- a/Makefile
+++ b/Makefile
@@ -10,3 +10,4 @@
 else ifeq ($(USE_PROFILES),true)
+  else ifeq ($ wildcard $(SANITIZE_SCRIPT),)
   include $(CLEAN_ENV)
"""
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(mock_diff)
        print(f"✅ Generated sample mock diff at '{diff_path}'.")

    with open(diff_path, "r", encoding="utf-8") as f:
        diff_content = f.read().strip()

    changes_list, changed_lines = parse_diff_to_changes_list(diff_content)
    if not changes_list:
        print("❌ Error: No code additions or changes found in diff to analyze.")
        sys.exit(1)

    prompt = f"""You are an expert DevOps and Platform Engineer auditing code quality, syntax, security, and architectural anti-patterns in a Kubernetes homelab.

Perform an exhaustive, line-by-line pass of the diff. Do not stop after finding the first few issues. You must report EVERY valid issue you find, even minor formatting, style violations, or optimization points. Aim to populate the 'comments' array with all detected discrepancies. Do not summarize or group distinct issues into a single comment.

Focus on:
1. POSIX-safe shell scripting (avoiding bash-isms like '&>' in standard /bin/sh recipes).
2. Safe environment sourcing and dynamic configurations in Makefiles.
3. Terraform module declarations, ensuring required arguments are populated and secrets are sensitive.
4. Kubernetes manifest security (avoiding hardcoded secrets or privileged contexts).

⚠️ CRITICAL CONTEXT: YOU ARE ANALYZING A RAW GIT DIFF, NOT A COMPLETE FILE.
The first line of any code block you see is NOT necessarily the first line of the file. To prevent false positives, adhere strictly to these rules:
- Do NOT flag "missing shebangs" (e.g., #!/bin/bash) on shell scripts unless you explicitly see the shebang being deleted in the diff.
- Do NOT flag "missing imports" or "missing variables" if they might be declared in lines of the file that are outside the current diff hunks.
- Only report definitive syntax errors, security flaws (CWE), or credential leaks visible within the modified lines.

Identify issues and classify them strictly as:
- 'CRITICAL': Security vulnerabilities, credential leaks, or fatal syntax errors.
- 'WARNING': Architectural style drift, optimizations, or style issues.

You must return your output strictly in JSON format. Do not wrap your response in markdown code blocks. The JSON structure must match this exact schema:
{{
  "comments": [
    {{
      "file": "filename",
      "line": line_number_integer,
      "severity": "CRITICAL or WARNING",
      "message": "Markdown warning/error string"
    }}
  ]
}}

Analyze only the lines showing additions or changes in this PR. You MUST map each comment 'file' and 'line' to the exact lines listed below. Do not comment on any file or line number that is not listed below. If no issues are found, return an empty comments list.

Here are the exact added/changed files and line numbers in this PR:

{changes_list}

For larger context, here is the full unified diff of the changes:

{diff_content}"""

    # Ensure the parent directory for the output file exists before writing
    output_parent = os.path.dirname(os.path.abspath(output_prompt_path))
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    with open(output_prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    print("\n" + "="*80)
    print("🎬 LOCAL PROMPT SIMULATION COMPLETED SUCCESSFULLY!")
    print("="*80)
    print("1. Unified Diff parsed to changes list indices.")
    print("2. Formatted prompt generated using doubled bracket escaping.")
    print(f"3. Rendered prompt successfully saved to: '{output_prompt_path}'")
    print("4. Preview of the exact content being sent to Gemini API:")
    print("-"*80)
    lines = prompt.splitlines()
    for l in lines[:30]:
        print(l)
    if len(lines) > 30:
        print(f"\n[... Truncated {len(lines) - 30} lines ...]")
        print(f"[... To inspect the full rendered prompt, open '{output_prompt_path}' ...]")
    print("-"*80)

if __name__ == "__main__":
    main()
