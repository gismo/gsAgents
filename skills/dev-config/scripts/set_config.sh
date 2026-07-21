#!/usr/bin/env bash
# set_config.sh — write .claude/gismo-dev.local.json deterministically.
# Usage: set_config.sh <build_dir> [jobs]
#   <build_dir>  path to a configured cmake build dir (absolute or relative to repo root)
#   [jobs]       parallel make jobs (default 4; clamped to nproc/2 at use time)
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/gismo_env.sh"

# Resolve only the repo root (build dir is what we are about to set).
GISMO_BUILD_DIR=ignore-autodetect
d="$PWD"
GISMO_ROOT=""
while [ "$d" != "/" ]; do
    if [ -f "$d/CMakeLists.txt" ] && [ -d "$d/src/gsCore" ]; then GISMO_ROOT="$d"; break; fi
    d="$(dirname "$d")"
done
[ -n "$GISMO_ROOT" ] || { echo "set_config: not inside a G+Smo checkout" >&2; echo "STATUS: FAIL"; exit 1; }

BUILD_DIR="${1:-}"
JOBS="${2:-4}"
[ -n "$BUILD_DIR" ] || { echo "usage: set_config.sh <build_dir> [jobs]" >&2; echo "STATUS: FAIL"; exit 2; }

case "$BUILD_DIR" in
    /*) ABS="$BUILD_DIR" ;;
    *)  ABS="$GISMO_ROOT/$BUILD_DIR" ;;
esac
[ -f "$ABS/CMakeCache.txt" ] || { echo "set_config: $ABS has no CMakeCache.txt (not a configured build dir)" >&2; echo "STATUS: FAIL"; exit 1; }
case "$JOBS" in (*[!0-9]*|'') echo "set_config: jobs must be a number" >&2; echo "STATUS: FAIL"; exit 2 ;; esac

# compile_commands.json is a hard requirement for /gismo:syntax-check (exact
# per-file flags -- a submodule file must never be checked with the wrong
# defines/includes). Enable it here if missing: a cache-var flip, no rebuild.
if [ ! -f "$ABS/compile_commands.json" ]; then
    echo "set_config: compile_commands.json missing in $ABS -- enabling CMAKE_EXPORT_COMPILE_COMMANDS (no rebuild triggered)"
    ( cd "$ABS" && cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON . ) || {
        echo "set_config: cmake reconfigure failed" >&2; echo "STATUS: FAIL"; exit 1;
    }
    [ -f "$ABS/compile_commands.json" ] || {
        echo "set_config: compile_commands.json still missing after reconfigure (unsupported generator?)" >&2
        echo "STATUS: FAIL"; exit 1;
    }
fi

mkdir -p "$GISMO_ROOT/.claude"
printf '{\n  "build_dir": "%s",\n  "jobs": %s\n}\n' "$ABS" "$JOBS" > "$GISMO_ROOT/.claude/gismo-dev.local.json"

echo "Wrote $GISMO_ROOT/.claude/gismo-dev.local.json:"
cat "$GISMO_ROOT/.claude/gismo-dev.local.json"
grep -m1 '^CMAKE_BUILD_TYPE:' "$ABS/CMakeCache.txt" || true
echo "STATUS: OK"
