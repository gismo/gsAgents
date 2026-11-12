#!/usr/bin/env bash
# gismo_env.sh — resolve the G+Smo repo root, build directory and job cap.
#
# Source it from other scripts:   source "$(dirname "$0")/../../dev-config/scripts/gismo_env.sh"
# Or run it directly to inspect:  ./gismo_env.sh
#
# Exports: GISMO_ROOT, GISMO_BUILD_DIR, GISMO_JOBS, GISMO_ADVISOR,
#          GISMO_BUILD_TYPE, GISMO_NDEBUG (1 | 0 | unknown)
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
    _gismo_env_resolve
    local rc=$? _v
    for _v in ${_GISMO_ENV_DERIVED:-}; do
        printf -v "_GISMO_ENV_VAL_$_v" '%s' "${!_v-}"
    done
    return $rc
}

_gismo_env_resolve() {
    # --- forget what an earlier call derived ---
    # Variables this function derived on a previous call are removed, so each call
    # recomputes them -- but only while they still hold the derived value (kept in
    # _GISMO_ENV_VAL_<name> by gismo_env). A value assigned in between counts as
    # pre-set, like one present before the first call.
    # The record is deliberately not exported: a child shell sees inherited values
    # as pre-set.
    local _v _rv
    for _v in ${_GISMO_ENV_DERIVED:-}; do
        _rv="_GISMO_ENV_VAL_$_v"
        [ "${!_v-}" = "${!_rv-}" ] && unset "$_v"
    done
    _GISMO_ENV_DERIVED=""
    for _v in GISMO_ROOT GISMO_BUILD_DIR GISMO_JOBS GISMO_ADVISOR GISMO_BUILD_TYPE GISMO_NDEBUG; do
        [ -n "${!_v:-}" ] || _GISMO_ENV_DERIVED="$_GISMO_ENV_DERIVED $_v"
    done

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
    local cfg_build="" cfg_jobs="" cfg_advisor=""
    if [ -f "$cfg" ]; then
        cfg_build="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('build_dir',''))" "$cfg" 2>/dev/null)"
        cfg_jobs="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('jobs',''))" "$cfg" 2>/dev/null)"
        cfg_advisor="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('advisor',''))" "$cfg" 2>/dev/null)"
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

    # --- advisor mode: who advises the sonnet implementers ---
    #   agent  (default) -> implementers consult the gismo:advisor subagent
    #   native           -> Claude Code's own advisor is configured (advisorModel);
    #                       subagents inherit it, so implementers skip gismo:advisor
    #                       and advice is not doubled.
    #
    # Detected, not declared. A hand-set config value goes stale the moment the
    # user runs /advisor or /advisor off, and a stale `agent` is the expensive
    # failure: every implementer then gets both advisors. So settings.json is
    # read directly, and the config file can only escalate to `native` — never
    # override a detected native back down to `agent`.
    #
    # Undetectable: `claude --advisor <model>` is a per-session flag that touches
    # no file. Set advisor=native in the config (or GISMO_ADVISOR in the
    # environment) when you launch that way.
    if [ -z "${GISMO_ADVISOR:-}" ]; then
        GISMO_ADVISOR=agent
        # CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1 ignores any configured advisorModel,
        # so there is no native advisor to defer to whatever the settings say.
        if [ "${CLAUDE_CODE_DISABLE_ADVISOR_TOOL:-}" != "1" ]; then
            local s
            for s in "$GISMO_ROOT/.claude/settings.local.json" \
                     "$GISMO_ROOT/.claude/settings.json" \
                     "$HOME/.claude/settings.json"; do
                [ -f "$s" ] || continue
                if python3 -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1])).get('advisorModel') else 1)" "$s" 2>/dev/null; then
                    GISMO_ADVISOR=native
                    break
                fi
            done
        fi
        [ "$cfg_advisor" = "native" ] && GISMO_ADVISOR=native
    fi
    case "$GISMO_ADVISOR" in agent|native) ;; *) GISMO_ADVISOR=agent ;; esac
    export GISMO_ADVISOR

    # --- build type and whether assertions are live ---
    #   GISMO_BUILD_TYPE  CMAKE_BUILD_TYPE of the build dir, or `unknown`
    #   GISMO_NDEBUG      1 = -DNDEBUG is in effect (GISMO_ASSERT and assert() compiled out)
    #                     0 = assertions live
    #                     unknown = neither the cache nor compile_commands.json decides it
    #
    # The flags decide, not the build-type name: G+Smo's RelWithDebInfo carries no
    # -DNDEBUG (CMAKE_CXX_FLAGS_RELWITHDEBINFO is `-O2 -g`), so assertions stay live
    # there although the type looks like a release. Order of evidence:
    #   1. CMakeCache.txt: -DNDEBUG in CMAKE_CXX_FLAGS or CMAKE_CXX_FLAGS_<TYPE>.
    #   2. compile_commands.json: -DNDEBUG on the entries whose file lies under
    #      <root>/src (external libraries and files outside the root are ignored):
    #      1 if all carry it, 0 if none does, unknown if they disagree or there are none.
    # A non-empty CMAKE_BUILD_TYPE alone gives 0 when compile_commands.json is absent.
    # A pre-set GISMO_BUILD_TYPE / GISMO_NDEBUG wins, like the other variables.
    if [ -z "${GISMO_BUILD_TYPE:-}" ] || [ -z "${GISMO_NDEBUG:-}" ]; then
        local cache="$GISMO_BUILD_DIR/CMakeCache.txt" btype="" flags="" tflags="" nd="unknown"
        btype="$(_gismo_cache_get CMAKE_BUILD_TYPE "$cache")"
        flags="$(_gismo_cache_get CMAKE_CXX_FLAGS "$cache")"
        if [ -n "$btype" ]; then
            tflags="$(_gismo_cache_get "CMAKE_CXX_FLAGS_$(printf '%s' "$btype" | tr '[:lower:]' '[:upper:]')" "$cache")"
        fi
        # -DNDEBUG may also come from add_definitions() and appear only in the compile
        # commands, so the cache alone settles the answer only when it says 1.
        [ -n "$btype" ] && nd=0
        case "$flags $tflags" in *-DNDEBUG*) nd=1 ;; esac
        if [ "$nd" != 1 ] && [ -s "$GISMO_BUILD_DIR/compile_commands.json" ]; then
            nd="$(_gismo_cc_ndebug "$GISMO_BUILD_DIR/compile_commands.json" "$GISMO_ROOT")"
        fi
        [ -z "${GISMO_BUILD_TYPE:-}" ] && GISMO_BUILD_TYPE="${btype:-unknown}"
        [ -z "${GISMO_NDEBUG:-}" ] && GISMO_NDEBUG="$nd"
    fi
    case "$GISMO_NDEBUG" in 0|1|unknown) ;; *) GISMO_NDEBUG=unknown ;; esac
    export GISMO_BUILD_TYPE GISMO_NDEBUG
    return 0
}

# Prints 1, 0 or unknown: whether -DNDEBUG is on the compile commands of the sources
# under <root>/src in a compile_commands.json ($1). $2 is the root. O(entries).
_gismo_cc_ndebug() {
    python3 - "$1" "$2" 2>/dev/null <<'PY' || echo unknown
import json, os, shlex, sys
path, root = sys.argv[1], os.path.realpath(sys.argv[2])
src = os.path.join(root, "src") + os.sep


def defines_ndebug(args):
    """Whether NDEBUG is defined after the last -D/-U of it (-D NDEBUG and -DNDEBUG alike)."""
    on, i = False, 0
    while i < len(args):
        a = args[i]
        if a in ("-D", "-U") and i + 1 < len(args):
            a, i = a + args[i + 1], i + 1
        if a == "-DNDEBUG" or a.startswith("-DNDEBUG="):
            on = True
        elif a == "-UNDEBUG":
            on = False
        i += 1
    return on


flags = []
for e in json.load(open(path)):
    f = os.path.realpath(os.path.join(e.get("directory", ""), e["file"]))
    if not f.startswith(src):
        continue
    args = e["arguments"] if "arguments" in e else shlex.split(e["command"])
    flags.append(defines_ndebug(args))
print("unknown" if not flags or any(flags) != all(flags) else int(flags[0]))
PY
}

# Value of a CMake cache entry (any type), empty if absent. Entries look like
# `KEY:TYPE=value`; the value may itself contain `=` and surrounding quotes.
_gismo_cache_get() {
    local v
    v="$(grep -m1 "^$1:[A-Z]*=" "$2" 2>/dev/null)" || return 0
    v="${v#*=}"
    v="${v#\'}"; v="${v%\'}"
    printf '%s' "$v"
}

# When executed (not sourced), print the resolved environment.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    set -u
    gismo_env || exit 1
    echo "GISMO_ROOT=$GISMO_ROOT"
    echo "GISMO_BUILD_DIR=$GISMO_BUILD_DIR"
    echo "GISMO_JOBS=$GISMO_JOBS"
    echo "GISMO_ADVISOR=$GISMO_ADVISOR"
    echo "GISMO_BUILD_TYPE=$GISMO_BUILD_TYPE"
    echo "GISMO_NDEBUG=$GISMO_NDEBUG"
    grep -m1 '^CMAKE_BUILD_TYPE:' "$GISMO_BUILD_DIR/CMakeCache.txt" 2>/dev/null || true
    echo "STATUS: OK"
fi
