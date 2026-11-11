#!/usr/bin/env bash
# review_lint.sh — deterministic style checks on the changed lines of a G+Smo diff.
# Usage: review_lint.sh [--base <ref>] [--all-lines] [--no-clang-format] [--linters] [<path>...]
# Only the repo root is required; a missing build directory just disables clang-tidy.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
gismo_env >/dev/null 2>&1
if [ -z "${GISMO_ROOT:-}" ]; then
    echo "review_lint: not inside a G+Smo checkout" >&2
    echo "STATUS: FAIL not inside a G+Smo checkout"
    exit 2
fi
exec python3 "$SCRIPT_DIR/review_lint.py" "$@"
