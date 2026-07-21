#!/usr/bin/env bash
# syntax_check.sh — gate every changed file through the compiler before building.
# Usage: syntax_check.sh [--allow-degraded] <file> [<file> ...]
# Requires compile_commands.json in the build dir (run /gismo:dev-config if missing).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
gismo_env || exit 2
exec python3 "$SCRIPT_DIR/syntax_check.py" "$@"
