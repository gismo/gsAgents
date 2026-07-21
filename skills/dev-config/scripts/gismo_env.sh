#!/usr/bin/env bash
# gismo_env.sh — resolve the G+Smo repo root, build directory and job cap.
#
# Source it from other scripts:   source "$(dirname "$0")/../../dev-config/scripts/gismo_env.sh"
# Or run it directly to inspect:  ./gismo_env.sh
#
# Exports: GISMO_ROOT, GISMO_BUILD_DIR, GISMO_JOBS
#
# Resolution order:
#   1. Pre-set environment variables win.
#   2. .claude/gismo-dev.local.json at the repo root ({"build_dir": "...", "jobs": N}).
#   3. Auto-detect: exactly one build*/ dir at the repo root -> use it.
#      Several -> hard error telling the caller to run /gismo:dev-config.
# Jobs are always clamped to [1, nproc/2] with a default of 4.

_gismo_env_fail() {
    echo "gismo_env: $1" >&2
    echo "STATUS: FAIL" >&2
    return 1
}

gismo_env() {
    # --- repo root ---
    if [ -z "${GISMO_ROOT:-}" ]; then
        local d="$PWD"
        while [ "$d" != "/" ]; do
            if [ -f "$d/CMakeLists.txt" ] && [ -d "$d/src/gsCore" ]; then
                GISMO_ROOT="$d"
                break
            fi
            d="$(dirname "$d")"
        done
    fi
    [ -n "${GISMO_ROOT:-}" ] || { _gismo_env_fail "not inside a G+Smo checkout (no CMakeLists.txt + src/gsCore found upwards from $PWD)"; return 1; }
    export GISMO_ROOT

    # --- config file ---
    local cfg="$GISMO_ROOT/.claude/gismo-dev.local.json"
    local cfg_build="" cfg_jobs=""
    if [ -f "$cfg" ]; then
        cfg_build="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('build_dir',''))" "$cfg" 2>/dev/null)"
        cfg_jobs="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('jobs',''))" "$cfg" 2>/dev/null)"
    fi

    # --- build dir ---
    if [ -z "${GISMO_BUILD_DIR:-}" ]; then
        if [ -n "$cfg_build" ]; then
            case "$cfg_build" in
                /*) GISMO_BUILD_DIR="$cfg_build" ;;
                *)  GISMO_BUILD_DIR="$GISMO_ROOT/$cfg_build" ;;
            esac
        else
            local candidates=()
            local b
            for b in "$GISMO_ROOT"/build*/; do
                [ -f "${b}CMakeCache.txt" ] && candidates+=("${b%/}")
            done
            if [ "${#candidates[@]}" -eq 1 ]; then
                GISMO_BUILD_DIR="${candidates[0]}"
            elif [ "${#candidates[@]}" -eq 0 ]; then
                _gismo_env_fail "no configured build*/ directory found under $GISMO_ROOT (run cmake first, or run /gismo:dev-config)"; return 1
            else
                _gismo_env_fail "multiple build dirs found (${candidates[*]##*/}); run /gismo:dev-config to pick one"; return 1
            fi
        fi
    fi
    [ -f "$GISMO_BUILD_DIR/CMakeCache.txt" ] || { _gismo_env_fail "GISMO_BUILD_DIR=$GISMO_BUILD_DIR is not a configured cmake build dir"; return 1; }
    export GISMO_BUILD_DIR

    # --- jobs (default 4, hard cap nproc/2, never below 1) ---
    local np cap
    np="$(nproc 2>/dev/null || echo 4)"
    cap=$(( np / 2 )); [ "$cap" -lt 1 ] && cap=1
    if [ -z "${GISMO_JOBS:-}" ]; then
        GISMO_JOBS="${cfg_jobs:-4}"
    fi
    case "$GISMO_JOBS" in (*[!0-9]*|'') GISMO_JOBS=4 ;; esac
    [ "$GISMO_JOBS" -gt "$cap" ] && GISMO_JOBS="$cap"
    [ "$GISMO_JOBS" -lt 1 ] && GISMO_JOBS=1
    export GISMO_JOBS
    return 0
}

# When executed (not sourced), print the resolved environment.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    set -u
    gismo_env || exit 1
    echo "GISMO_ROOT=$GISMO_ROOT"
    echo "GISMO_BUILD_DIR=$GISMO_BUILD_DIR"
    echo "GISMO_JOBS=$GISMO_JOBS"
    grep -m1 '^CMAKE_BUILD_TYPE:' "$GISMO_BUILD_DIR/CMakeCache.txt" 2>/dev/null || true
    echo "STATUS: OK"
fi
