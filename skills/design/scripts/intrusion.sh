#!/usr/bin/env bash
# intrusion.sh — check or measure how far a feature reaches outside its home directories.
# Usage: intrusion.sh check   <budget-file> [--files <list-file>]
#        intrusion.sh measure <budget-file>
# Only the repo root is required; a missing build directory is not an error.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
gismo_env >/dev/null 2>&1
if [ -z "${GISMO_ROOT:-}" ]; then
    echo "intrusion: not inside a G+Smo checkout" >&2
    echo "STATUS: FAIL not inside a G+Smo checkout"
    exit 2
fi
exec python3 "$SCRIPT_DIR/intrusion.py" "$@"
