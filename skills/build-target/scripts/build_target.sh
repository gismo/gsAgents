#!/usr/bin/env bash
# build_target.sh — the ONLY sanctioned way for agents to build G+Smo targets.
#
# Usage: build_target.sh <target> [jobs] [--yes-really]
#
# Guards (each one has crashed machines or wasted hours before):
#   * an explicit target is REQUIRED — bare `make` builds ALL examples and takes forever
#   * `all` / `examples` are refused unless --yes-really is passed
#   * jobs are clamped to the configured cap (default 4, hard cap nproc/2) — unbounded -j
#     exhausts RAM and can crash the machine
#
# Exit codes: 0 build OK, 1 build failed, 2 bad usage/refused.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
gismo_env || exit 2

TARGET="${1:-}"
shift || true
JOBS_ARG=""
YES_REALLY=0
for a in "$@"; do
    case "$a" in
        --yes-really) YES_REALLY=1 ;;
        *[!0-9]*) echo "build_target: unknown argument '$a'" >&2; echo "STATUS: FAIL"; exit 2 ;;
        *) JOBS_ARG="$a" ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "build_target: no target given. Bare 'make' builds ALL examples — always name a target." >&2
    echo "usage: build_target.sh <target> [jobs] [--yes-really]" >&2
    echo "STATUS: FAIL"
    exit 2
fi
case "$TARGET" in
    all|examples)
        if [ "$YES_REALLY" -ne 1 ]; then
            echo "build_target: refusing target '$TARGET' (builds everything, very slow)." >&2
            echo "Pass --yes-really if this is intentional." >&2
            echo "STATUS: FAIL"
            exit 2
        fi ;;
esac

# Optional explicit jobs, still clamped by gismo_env's cap logic.
if [ -n "$JOBS_ARG" ]; then
    GISMO_JOBS="$JOBS_ARG"
    np="$(nproc 2>/dev/null || echo 4)"; cap=$(( np / 2 )); [ "$cap" -lt 1 ] && cap=1
    [ "$GISMO_JOBS" -gt "$cap" ] && { echo "build_target: clamping jobs $JOBS_ARG -> $cap (nproc/2 cap)"; GISMO_JOBS="$cap"; }
    [ "$GISMO_JOBS" -lt 1 ] && GISMO_JOBS=1
fi

LOG="$(mktemp "${TMPDIR:-/tmp}/gismo_build_XXXXXX.log")"
echo "build_target: make $TARGET -j$GISMO_JOBS  (in $GISMO_BUILD_DIR)"
start=$SECONDS
( cd "$GISMO_BUILD_DIR" && make "$TARGET" -j"$GISMO_JOBS" ) >"$LOG" 2>&1
rc=$?
elapsed=$(( SECONDS - start ))

if [ $rc -eq 0 ]; then
    tail -n 3 "$LOG"
    echo "build_target: '$TARGET' built in ${elapsed}s"
    echo "STATUS: OK"
else
    echo "build_target: '$TARGET' FAILED after ${elapsed}s — last 40 lines:" >&2
    tail -n 40 "$LOG" >&2
    if grep -q "No rule to make target" "$LOG"; then
        echo "hint: unknown target — if you added a new .cpp file, reconfigure first: (cd $GISMO_BUILD_DIR && cmake .)" >&2
    fi
    echo "full log: $LOG" >&2
    echo "STATUS: FAIL"
fi
exit $rc
