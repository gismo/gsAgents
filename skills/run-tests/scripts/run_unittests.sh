#!/usr/bin/env bash
# run_unittests.sh — build the unittests target and run it, optionally filtered.
#
# Usage: run_unittests.sh [--no-build] [prefix ...]
#   prefix    zero or more selectors, prefix-matched by the unittests binary against
#             suite names, test names, and source file names
#             (e.g. `run_unittests.sh gsMatrix` runs everything starting with gsMatrix).
#
# Exit: 0 all selected tests pass, 1 failures (or no test matched), 2 setup error.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
gismo_env || exit 2

NO_BUILD=0
if [ "${1:-}" = "--no-build" ]; then NO_BUILD=1; shift; fi

if [ "$NO_BUILD" -ne 1 ]; then
    bash "$SCRIPT_DIR/../../build-target/scripts/build_target.sh" unittests || {
        echo "run_unittests: building 'unittests' failed (is GISMO_BUILD_UNITTESTS=ON in this build dir?)" >&2
        echo "STATUS: FAIL"
        exit 2
    }
fi

BIN="$GISMO_BUILD_DIR/bin/unittests"
[ -x "$BIN" ] || { echo "run_unittests: $BIN not found/executable" >&2; echo "STATUS: FAIL"; exit 2; }

echo "run_unittests: $BIN $*"
start=$SECONDS
"$BIN" "$@"
rc=$?
echo "run_unittests: finished in $(( SECONDS - start ))s (exit $rc)"
if [ $rc -eq 0 ]; then echo "STATUS: OK"; else echo "STATUS: FAIL"; fi
exit $rc
