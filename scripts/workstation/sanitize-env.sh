#!/usr/bin/env bash
# This script sanitizes a .env file by removing comments and trailing whitespace making it compatible with make
set -euo pipefail

INPUT_FILE="${1:-}"
OUTPUT_FILE="${2:-}"


if [ -z "$INPUT_FILE" ] || [ -z "$OUTPUT_FILE" ]; then
    echo "FAILED: Both Input and Output files must be provided."
    exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo "FAILED: $INPUT_FILE not found."
    exit 1
fi

# ADR 011 Rule 2: Safe File Staging (No sed -i)
# Treat INPUT_FILE as immutable and compile the result directly to OUTPUT_FILE
sed -e 's/[[:space:]]*#.*//' -e 's/[[:space:]]*$//' "$INPUT_FILE" > "$OUTPUT_FILE"
