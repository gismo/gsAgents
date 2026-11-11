#!/usr/bin/env bash
# tree_cleanup.sh — one-off mechanical cleanup of an existing G+Smo tree (run by the user).
# Usage: tree_cleanup.sh <whitespace|doxygen-tags> [--apply] [<path>...]
# Dry run by default. --apply needs a clean tree, never commits, and prints a proof.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
gismo_env >/dev/null 2>&1
if [ -z "${GISMO_ROOT:-}" ]; then
    echo "tree_cleanup: not inside a G+Smo checkout" >&2
    echo "STATUS: FAIL not inside a G+Smo checkout"
    exit 2
fi
exec python3 "$SCRIPT_DIR/tree_cleanup.py" "$@"
