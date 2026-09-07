#!/usr/bin/env python3
import argparse
import json
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract Git diff and consult Gemini for secure homelab code review annotations."
    )
    parser.add_argument(
        "--diff-path",
        default=os.environ.get("GEMINI_DIFF_PATH", "pr_changes.diff"),
        help="Path to the input Git diff file"
    )
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GEMINI_OUTPUT_PATH", "review_output.json"),
        help="Path to save the generated JSON review findings"
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
        help="The Gemini model name to query"
    )
    parser.add_argument(
        "--api-version",
        default=os.environ.get("GEMINI_API_VERSION", "v1beta"),
        help="The Gemini API version to use"
    )
    return parser.parse_args()

def parse_diff_to_changes_list(diff_content):
    """
    Parses a unified diff and returns a formatted list of files and absolute line numbers
    indicating where lines of code were added or modified (+ lines), along with a set of valid (file, line) pairs.
    This serves as a high-density index for the LLM to map comments precisely.
    """
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    current_file = None
    lines_by_file = {}
    changed_lines = set()

    current_line = 0
    for line in diff_content.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            # 🛡️ Skip review for documentation, markdown files, and any auto-generated docs
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
            elif line.startswith("\\"):
                # Ignore diff metadata lines (e.g., "\ No newline at end of file")
                pass
            elif line.startswith("-") and not line.startswith("---"):
                # Deleted lines do not advance line numbers in the new file
                pass
            else:
                # Unchanged context lines advance the line count
                current_line += 1

    # Format into a clean text block
    formatted_list = []
    for filename, lines in lines_by_file.items():
        if lines:
            formatted_list.append(f"=== FILE: {filename} ===")
            for line_num, content in lines:
                formatted_list.append(f"Line {line_num}: {content}")
            formatted_list.append("") # Spacer

    return "\n".join(formatted_list), changed_lines

def filter_suppressed_comments(review_data, changed_lines, repo_root="."):
    """
    Filters out:
    1. Comments that are not on actively changed lines in the PR diff (prevents GitHub 422 errors).
    2. Comments pointing to lines in files that contain '# ai-ignore' or standard equivalent overrides.
    """
    comments = review_data.get("comments", [])
    filtered_comments = []

    # Establish a secure, fully resolved root anchor
    safe_root = Path(repo_root).resolve()

    for comment in comments:
        filename = comment.get("file")
        line_num = comment.get("line")

        if not filename or not line_num:
            continue

        try:
            line_num_int = int(line_num)
        except (ValueError, TypeError):
            continue

        # 1. Enforce strict PR diff alignment. If a comment is not on an actively changed line,
        # discard it to guarantee GitHub REST API won't reject the review payload with a 422 error.
        if (filename, line_num_int) not in changed_lines:
            print(f"🧹 Discarding AI comment on {filename}:{line_num_int} - line is not part of the active PR additions/modifications.")
            continue

        try:
            # 🛡️ Secure Path Resolution (CWE-22 Path Traversal Prevention)
            resolved_path = safe_root.joinpath(filename).resolve()

            # 🛡️ Boundary Check: Guarantee the path cannot escape safe_root
            if not resolved_path.is_relative_to(safe_root):
                print(f"⚠️ Security Alert: Blocked directory traversal attempt to '{filename}'")
                continue

            file_path = resolved_path
            if not file_path.exists():
                filtered_comments.append(comment)
                continue

            # Safely open the vetted, in-bounds file
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            idx = line_num_int - 1
            if 0 <= idx < len(lines):
                target_line = lines[idx]
                if "ai-ignore" in target_line:
                    print(f"🔇 Suppressed AI comment on {filename}:{line_num_int} due to inline 'ai-ignore' override.")
                    continue
        except (OSError, UnicodeDecodeError) as e:
            print(f"⚠️ Warning reading file {filename} during suppression check: {e}", file=sys.stderr)

        filtered_comments.append(comment)

    review_data["comments"] = filtered_comments
    return review_data

def sanitize_json_response(text):
    """
    Safely strips any surrounding markdown code block markers (like ```json ... ```)
    returned by the LLM before passing it to the json parser, and programmatically
    repairs any invalid backslash escape sequences to prevent JSONDecodeErrors.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Programmatically repair invalid backslash escapes inside JSON string values
    fixed = []
    in_string = False
    escape = False

    i = 0
    while i < len(text):
        c = text[i]
        if not in_string:
            if c == '"':
                in_string = True
            fixed.append(c)
            i += 1
        else:
            if escape:
                if c not in '"\\/bfnrtu':
                    fixed.insert(-1, '\\')
                escape = False
                fixed.append(c)
                i += 1
            else:
                if c == '\\':
                    escape = True
                    fixed.append(c)
                    i += 1
                elif c == '"':
                    in_string = False
                    fixed.append(c)
                    i += 1
                else:
                    fixed.append(c)
                    i += 1

    return "".join(fixed)

def extract_retry_delay(err_body: str, headers) -> float:
    # 1. Check HTTP header first
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass

    # 2. Extract suggested delay from Google's response message (e.g., "retry in 14.2s")
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_body, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # 3. Default safe duration to clear rolling TPM limits if unspecified
    return 60.0

def main():
    args = parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    diff_path = args.diff_path
    output_path = args.output_path
    model = args.model
    api_version = args.api_version

    # Initialize default empty comments file to ensure downstream steps don't crash
    default_output = {"comments": []}
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    except OSError:
        pass

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(default_output, f, indent=2)

    if not os.path.exists(diff_path):
        print(f"⚠️ Warning: Input diff file '{diff_path}' not found. Skipping analysis.", file=sys.stderr)
        return

    with open(diff_path, "r", encoding="utf-8") as f:
        diff_content = f.read().strip()

    if not diff_content:
        print(f"✅ PR Diff '{diff_path}' is empty. No changes to analyze.")
        return

    # Extract exact lines of code modified with their line numbers
    changes_list, changed_lines = parse_diff_to_changes_list(diff_content)
    if not changes_list:
        print("✅ No code additions or changes found in diff to analyze.")
        return

    prompt = f"""You are an automated PR review engine providing inline feedback on a GitHub pull request diff.
Your output JSON is parsed directly by an automated GitHub workflow to post inline PR review comments.
Assume this code was authored by a senior systems engineer and has already passed strict ShellCheck validation.
Your baseline default output is an empty list: {{"comments": []}}.

TASK:
Identify ONLY genuine functional bugs, security vulnerabilities (CWE), data-loss hazards, or unhandled runtime crashes.
Do NOT report stylistic preferences, micro-optimizations, educational notes, or defensive idioms.

CLASSIFICATION:
- 'CRITICAL': Security vulnerabilities (CWE), command injections, credential leaks, or fatal syntax/runtime crashes.
- 'WARNING': Definite logic errors, race conditions, or unhandled execution paths that result in corrupted state or broken services.
(NOTE: If an observation is merely an optimization, style preference, architectural suggestion, or non-fatal edge case, it is DISQUALIFIED. Do not post it.)

MANDATORY SUPPRESSION RULES:
1. Defensive Traps & Cleanup: Never flag 'trap ... EXIT' combined with explicit deletion as redundant, racing, or interfering with recovery. Idempotent cleanup is standard architecture.
2. Tooling Invariants:
   - GNU envsubst: '$VAR' matches both '$VAR' and '${{VAR}}'. Do not report brace mismatches.
   - Shell: Do not flag unquoted assignments, variables inside '[[ ]]', or missing files/imports outside the diff hunks.
3. Guarded Logic: Do not critique string parsing or loops if validation checks already reject empty or malformed values.
4. Falsification Requirement: Verify the literal text of the diff. Never claim a flag, quote, or check is missing if it physically appears in the diff.

OUTPUT FORMAT:
Return valid JSON only matching the schema consumed by GitHub Actions. Every comment must include a reproducible failure proof showing how an unhandled crash or state corruption occurs:

{{
  "comments": [
    {{
      "path": "path/to/file",
      "line": 123,
      "severity": "CRITICAL" | "WARNING",
      "message": "### [SEVERITY]\n**Failure Proof:** <Concrete input/state showing reproducible crash or data corruption>\n\n**Issue:** <Explanation of defect and corrective action>"
    }}
  ]
}}

If no genuine defects meet this standard, return:
{{"comments": []}}

Analyze only the lines showing additions or changes in this PR. You MUST map each comment 'file' and 'line' to the exact lines listed below. Do not comment on any file or line number that is not listed below. If no issues are found, return an empty comments list.

Here are the exact added/changed files and line numbers in this PR:

{changes_list}

For larger context, here is the full unified diff of the changes:

{diff_content}"""

    # 🛡️ Secure Credentials passing using Headers instead of Query Params (Prevents leak in GHA logs)
    url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "thinkingConfig": {
                "thinkingBudget" : 512
            },
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "comments": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "file": {"type": "STRING"},
                                "line": {"type": "INTEGER"},
                                "severity": {"type": "STRING", "enum": ["CRITICAL", "WARNING"]},
                                "message": {"type": "STRING"}
                            },
                            "required": ["file", "line", "severity", "message"]
                        }
                    }
                },
                "required": ["comments"]
            }
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    max_retries = 5
    initial_delay = 2.0
    backoff_factor = 2.0
    # Allow 240s for large unified diffs + reasoning time
    socket_timeout = 240

    encoded_data = json.dumps(payload).encode("utf-8")

    for attempt in range(max_retries):
        try:
            print(f"🚀 Sending diff from '{diff_path}' to Gemini API ({api_version}/{model}) for secure analysis (Attempt {attempt + 1}/{max_retries})...")
            # 🛡️ Safe timeout set to 90 seconds to allow the LLM ample processing time on larger structured payloads

            # Construct a fresh Request object per attempt
            req = urllib.request.Request(
                url,
                data=encoded_data,
                headers=headers,
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=socket_timeout) as response:
                res_data = json.loads(response.read().decode("utf-8"))

            # text_response = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            candidate = res_data.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])
            if not parts:
                finish_reason = candidate.get("finishReason", "UNKNOWN")
                print(f"⚠️ Warning: Model returned no content parts. Finish reason: {finish_reason}", file=sys.stderr)
                return
            text_response = parts[0].get("text", "").strip()

            # Sanitize LLM formatting failures before parsing
            sanitized_response = sanitize_json_response(text_response)
            ai_reviews = json.loads(sanitized_response)

            # Apply dynamic inline suppression and valid-line filtering logic
            ai_reviews = filter_suppressed_comments(ai_reviews, changed_lines)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ai_reviews, f, indent=2)

            print(f"✅ AI Review completed. Issues found: {len(ai_reviews.get('comments', []))}. Saved results to '{output_path}'.")
            break

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")

            if attempt < max_retries - 1:
                if e.code == 429:
                    suggested_delay = extract_retry_delay(err_body, e.headers)
                    # Enforce a minimum floor of 60s for full TPM quota resets, plus jitter
                    sleep_time = max(suggested_delay, 60.0) + random.uniform(1.0, 3.0)
                    print(f"⏳ Rate limit reached (HTTP 429). Waiting {sleep_time:.2f}s for quota window to reset...", file=sys.stderr)
                    time.sleep(sleep_time)
                    continue

                elif e.code in [429, 500, 502, 503, 504] and attempt < max_retries - 1:
                    sleep_time = initial_delay * (backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    print(f"⚠️ Gemini API returned transient error HTTP {e.code} ({e.reason}). Retrying in {sleep_time:.2f}s...", file=sys.stderr)
                    time.sleep(sleep_time)
                    continue
            else:
                print(f"❌ API HTTP Error: {e.code} - {err_body}", file=sys.stderr)
                sys.exit(1)

        # Catch both URLError and direct socket/TimeoutError exceptions
        except (urllib.error.URLError, TimeoutError) as e:
            err_msg = str(getattr(e, "reason", e))
            is_timeout = isinstance(e, (TimeoutError, socket.timeout)) or "timed out" in err_msg.lower()

            if is_timeout and attempt < max_retries - 1:
                sleep_time = initial_delay * (backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                print(f"⚠️ Socket read operation timed out after {socket_timeout}s. Retrying in {sleep_time:.2f}s...", file=sys.stderr)
                time.sleep(sleep_time)
                continue
            else:
                print(f"❌ Connection/Socket Error: {err_msg}", file=sys.stderr)
                sys.exit(1)

        except (json.JSONDecodeError, UnicodeDecodeError, OSError, KeyError, IndexError) as e:
            print(f"❌ Error during AI review processing: {e}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
