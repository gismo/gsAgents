#!/usr/bin/env bash
# review_scope.sh — list the files (or changed line ranges) a review has to look at.
# Usage: review_scope.sh [--base <ref>] [--nested-base <module-path>=<ref>]...
#                        [--lines | --digest] [--all-files] [--split-renames] [--no-skip] [<path>...]
#
#   default      working tree against HEAD, plus untracked files
#   --base REF   working tree against `git merge-base REF HEAD` (root repo only)
#   --nested-base optional/<module>=REF
#                that nested repository against `git merge-base REF HEAD` run inside it;
#                repeatable, one per module (a leading ./ and a trailing / are ignored; the
#                same module twice, a repository without commits and an unknown ref are
#                failures). Nested repositories without one use HEAD.
#   --lines      emit "<path>\t<start>-<end>" per added/changed hunk instead of the file list
#   --digest     print one line, the md5 over the sorted rows
#                "<status> <path> <md5 of the file's current content, or - when deleted>"
#                of every listed file (untracked files and nested repositories included),
#                and exit 0. Equal digests mean the same files with the same content, so it
#                serves as a staleness check where `git diff | md5sum` would miss untracked
#                files and nested repositories. Honours --base, --nested-base and <path>s.
#   --all-files  do not filter by extension
#   --split-renames
#                list a rename as two rows, D <old path> and A <new path>, instead of one R row
#   --no-skip    skip only .git and .claude directories and untracked files of a top-level build* tree; by default external, env, venv, build*
#                and similar directories are skipped at any depth
#   <path>...    restrict to these paths (relative to the cwd or absolute)
#
# stdout (TSV): <repo>\t<status>\t<path>   repo = "." or optional/<module>,
#               status = A|M|D|R, path relative to the G+Smo root.
# Nested git repositories under optional/ are diffed on their own; a root-level
# `git diff` sees nothing inside them. A repository without commits is diffed against the
# empty tree, so all its files count as added. Last line: STATUS: OK <n> files | STATUS: FAIL <reason>.
# Exit codes: 0 ok, 2 failure (bad option, bad module path, ref without merge base, git error).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Directory names skipped at any depth. `build*` is matched separately by prefix.
SKIP_DIRS="external .claude venv .venv env node_modules __pycache__ site-packages .git"

fail() {
    echo "review_scope: $1" >&2
    echo "STATUS: FAIL $1"
    exit 2
}

BASE=""; LINES=0; DIGEST=0; ALLFILES=0; NOSKIP=0; RENAME_OPT="-M"; PATHS=()
declare -A NESTED_BASE=()

# add_nested_base <module-path>=<ref>
# The module path is normalised: leading "./", trailing "/" and doubled "/" are dropped.
add_nested_base() {
    local mod="${1%%=*}" ref="${1#*=}"
    case "$1" in *=*) ;; *) fail "--nested-base needs <module-path>=<ref>, got '$1'" ;; esac
    while [ "$mod" != "${mod//\/\//\/}" ]; do mod="${mod//\/\//\/}"; done
    while :; do
        case "$mod" in
            ./*) mod="${mod#./}" ;;
            */)  mod="${mod%/}" ;;
            *)   break ;;
        esac
    done
    [ -n "$mod" ] && [ -n "$ref" ] || fail "--nested-base needs <module-path>=<ref>, got '$1'"
    [ -z "${NESTED_BASE[$mod]+set}" ] || fail "--nested-base given twice for '$mod'"
    NESTED_BASE["$mod"]="$ref"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --base)      [ $# -ge 2 ] || fail "--base needs a ref"; BASE="$2"; shift 2 ;;
        --base=*)    BASE="${1#--base=}"; shift ;;
        --nested-base)   [ $# -ge 2 ] || fail "--nested-base needs <module-path>=<ref>"; add_nested_base "$2"; shift 2 ;;
        --nested-base=*) add_nested_base "${1#--nested-base=}"; shift ;;
        --lines)     LINES=1; shift ;;
        --digest)    DIGEST=1; shift ;;
        --all-files) ALLFILES=1; shift ;;
        --split-renames) RENAME_OPT="--no-renames"; shift ;;
        --no-skip)   NOSKIP=1; shift ;;
        -h|--help)   sed -n '2,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
        --)          shift; PATHS+=("$@"); break ;;
        -*)          fail "unknown option $1" ;;
        *)           PATHS+=("$1"); shift ;;
    esac
done

[ "$NOSKIP" -eq 1 ] && SKIP_DIRS=".git .claude"

source "$SCRIPT_DIR/../../dev-config/scripts/gismo_env.sh"
# Only the repo root is needed here; a missing build directory is not an error.
gismo_env >/dev/null 2>&1
[ -n "${GISMO_ROOT:-}" ] || fail "not inside a G+Smo checkout"
ROOT="$(realpath "$GISMO_ROOT")"

GIT_ERR="$(mktemp)" || fail "cannot create a temporary file"
trap 'rm -f "$GIT_ERR"' EXIT

# git_out <dir> <git args...> -> stdout in GIT_OUT; any git failure ends the run.
# Colour is forced off: escape codes in the output break the hunk-header match.
# Every revision argument must be followed by `--`: a stray untracked file named
# HEAD (present in worktrees) otherwise makes the revision ambiguous.
git_out() {
    local dir="$1" where; shift
    where="${dir#"$ROOT"}"; where="${where#/}"
    if ! GIT_OUT="$(git -C "$dir" -c core.quotepath=off -c color.ui=false -c color.diff=false "$@" 2>"$GIT_ERR")"; then
        fail "git ${1} failed in ${where:-.}$(err_tail)"
    fi
}

# err_tail -> ": <first line of git's stderr>", or nothing when git said nothing.
err_tail() {
    local m
    m="$(head -n1 "$GIT_ERR")"
    [ -z "$m" ] || printf ': %s' "$m"
}

PREFIXES=()
for p in ${PATHS[@]+"${PATHS[@]}"}; do
    abs="$(realpath -m -- "$p")"
    case "$abs" in
        "$ROOT")   PREFIXES+=("") ;;
        "$ROOT"/*) PREFIXES+=("${abs#"$ROOT"/}") ;;
        *)         fail "path outside the G+Smo root: $p" ;;
    esac
done

git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || fail "$ROOT is not a git repository"

# Nested repositories: optional/<module> with its own .git (directory or gitfile).
NESTED=()
for d in "$ROOT"/optional/*/; do
    [ -e "${d}.git" ] && NESTED+=("optional/$(basename "$d")")
done

for m in "${!NESTED_BASE[@]}"; do
    found=0
    for n in ${NESTED[@]+"${NESTED[@]}"}; do [ "$n" = "$m" ] && found=1; done
    [ "$found" -eq 1 ] || fail "--nested-base: '$m' is not a nested repository under optional/"
done

want_path() {
    [ "${#PREFIXES[@]}" -eq 0 ] && return 0
    local q
    for q in "${PREFIXES[@]}"; do
        [ -z "$q" ] && return 0
        case "$1" in "$q"|"$q"/*) return 0 ;; esac
    done
    return 1
}

keep_path() {
    want_path "$1" || return 1
    local base="${1##*/}" dir="" c
    case "$1" in */*) dir="${1%/*}" ;; esac
    local IFS=/
    for c in $dir; do
        if [ "$NOSKIP" -eq 0 ]; then case "$c" in build*) return 1 ;; esac; fi
        case " $SKIP_DIRS " in *" $c "*) [ -n "$c" ] && return 1 ;; esac
    done
    [ "$ALLFILES" -eq 1 ] && return 0
    case "$base" in
        *.h|*.hpp|*.cpp|*.cxx|*.cc|*.py|*.cmake|CMakeLists.txt|*.dox|*.md) return 0 ;;
    esac
    return 1
}

ENTRIES=()
# emit <label> <status> <path> [<old path>]
emit() {
    keep_path "$3" || return 0
    ENTRIES+=("$1"$'\t'"$2"$'\t'"$3"$'\t'"${4:-}")
}

in_nested() {
    local n
    for n in ${NESTED[@]+"${NESTED[@]}"}; do
        case "$1" in "$n"|"$n"/*) return 0 ;; esac
    done
    return 1
}

# resolve_ref <label> -> prints the diff base for that repo
resolve_ref() {
    if [ -n "$BASE" ] && [ "$1" = "." ]; then
        git -C "$ROOT" merge-base "$BASE" HEAD 2>"$GIT_ERR" || return 1
    elif [ "$1" != "." ] && [ -n "${NESTED_BASE[$1]:-}" ]; then
        git -C "$ROOT/$1" merge-base "${NESTED_BASE[$1]}" HEAD 2>"$GIT_ERR" || return 1
    else
        local dir="$ROOT"; [ "$1" = "." ] || dir="$ROOT/$1"
        if git -C "$dir" rev-parse --verify -q HEAD >/dev/null 2>&1; then
            echo HEAD
        else
            # No commits yet: everything counts as added relative to the empty tree.
            git -C "$dir" hash-object -t tree /dev/null
        fi
    fi
}

collect_repo() {
    local label="$1" dir prefix="" ref st a b s p o
    if [ "$label" = "." ]; then dir="$ROOT"; else dir="$ROOT/$label"; prefix="$label/"; fi
    # A repository without commits is diffed against the empty tree; a base requested for
    # it cannot be resolved.
    if ! git -C "$dir" rev-parse --verify -q HEAD >/dev/null 2>&1; then
        [ -z "${NESTED_BASE[$label]:-}" ] || fail "--nested-base: $label has no commits"
    fi
    if [ "$label" != "." ] && [ -z "${NESTED_BASE[$label]:-}" ]; then NESTED_DIFFED+=("$label"); fi
    ref="$(resolve_ref "$label")" || fail "no merge-base between '${NESTED_BASE[$label]:-$BASE}' and HEAD$([ "$label" = "." ] || printf ' in %s' "$label")$(err_tail)"
    git_out "$dir" diff --name-status "$RENAME_OPT" --relative "$ref" --
    while IFS=$'\t' read -r st a b; do
        s="${st:0:1}"; p="$a"; o=""
        case "$s" in
            R) p="$b"; o="$a" ;;
            C) s=A; p="$b" ;;
            T) s=M ;;
            A|M|D) ;;
            *) continue ;;
        esac
        if [ "$label" = "." ] && in_nested "$prefix$p"; then continue; fi
        emit "$label" "$s" "$prefix$p" "${o:+$prefix$o}"
    done <<<"$GIT_OUT"
    git_out "$dir" ls-files --others --exclude-standard --
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        case "$p" in */) continue ;; esac
        if [ "$label" = "." ] && in_nested "$prefix$p"; then continue; fi
        # An untracked top-level build tree holds thousands of generated files and no
        # source, so it stays out even under --no-skip; tracked files there are listed.
        if [ "$NOSKIP" -eq 1 ] && [ "$label" = "." ]; then case "$p" in build*/*) continue ;; esac; fi
        emit "$label" A "$prefix$p"
    done <<<"$GIT_OUT"
}

NESTED_DIFFED=()
collect_repo "."
for n in ${NESTED[@]+"${NESTED[@]}"}; do collect_repo "$n"; done
if [ -n "$BASE" ] && [ "${#NESTED_DIFFED[@]}" -gt 0 ]; then
    echo "review_scope: --base does not apply to nested repos (unrelated refs): ${NESTED_DIFFED[*]}; using their working diff against HEAD" >&2
fi

SORTED=()
if [ "${#ENTRIES[@]}" -gt 0 ]; then
    while IFS= read -r line; do SORTED+=("$line"); done < <(printf '%s\n' "${ENTRIES[@]}" | LC_ALL=C sort -u -t$'\t' -k1,1 -k3,3)
fi

if [ "$DIGEST" -eq 1 ]; then
    # md5 of the sorted rows
    #   "<status> <path> <md5 of content | -> <base blob | -> <base mode | -> <current mode | ->"
    # Paths are root-relative, so the rows do not depend on the cwd. The base side is the blob
    # id and mode of the file (the old path for a rename) at the repository's own comparison
    # ref, so identical working bytes against a different base digest differently. The
    # comparison commit id itself is not hashed: rebasing without touching a file leaves its
    # blob id, and so the digest, unchanged.
    rows=""
    declare -A DREF=()
    for e in ${SORTED[@]+"${SORTED[@]}"}; do
        IFS=$'\t' read -r label st p o <<<"$e"
        h="-"; bb="-"; bm="-"; cm="-"
        if [ "$st" != D ] && [ -f "$ROOT/$p" ]; then
            h="$(md5sum <"$ROOT/$p")"; h="${h%% *}"
            if [ -L "$ROOT/$p" ]; then cm=l; elif [ -x "$ROOT/$p" ]; then cm=x; else cm=f; fi
        fi
        if [ "$st" != A ]; then
            if [ "$label" = "." ]; then dir="$ROOT"; rel="${o:-$p}"; else dir="$ROOT/$label"; rel="${o:-$p}"; rel="${rel#"$label"/}"; fi
            if [ -z "${DREF[$label]+x}" ]; then
                DREF[$label]="$(resolve_ref "$label")" || fail "no merge-base between '${NESTED_BASE[$label]:-$BASE}' and HEAD$([ "$label" = "." ] || printf ' in %s' "$label")$(err_tail)"
            fi
            ref="${DREF[$label]}"
            bb="$(git -C "$dir" rev-parse -q --verify "$ref:$rel" 2>/dev/null)" || bb="-"
            bm="$(git -C "$dir" ls-tree "$ref" -- "$rel" 2>/dev/null | awk 'NR == 1 { print $1 }')"
            [ -n "$bm" ] || bm="-"
        fi
        rows+="$st $p $h $bb $bm $cm"$'\n'
    done
    printf '%s' "$rows" | LC_ALL=C sort | md5sum | cut -d' ' -f1
    exit 0
fi

if [ "$LINES" -eq 0 ]; then
    for e in ${SORTED[@]+"${SORTED[@]}"}; do
        IFS=$'\t' read -r label st p o <<<"$e"
        printf '%s\t%s\t%s\n' "$label" "$st" "$p"
    done
    echo "STATUS: OK ${#SORTED[@]} files"
    exit 0
fi

# Hunk ranges of the new file: "+c,d" -> c-(c+d-1); d=0 is a pure deletion.
hunk_ranges() {
    awk -v p="$1" '
        /^@@/ {
            if (match($0, /\+[0-9]+(,[0-9]+)?/)) {
                t = substr($0, RSTART + 1, RLENGTH - 1)
                n = split(t, f, ",")
                c = f[1] + 0; d = (n > 1) ? f[2] + 0 : 1
                if (d > 0) printf "%s\t%d-%d\n", p, c, c + d - 1
            }
        }'
}

COUNT=0
for e in ${SORTED[@]+"${SORTED[@]}"}; do
    IFS=$'\t' read -r label st p o <<<"$e"
    [ "$st" = D ] && continue
    if [ "$label" = "." ]; then dir="$ROOT"; rel="$p"; ro="$o"; else dir="$ROOT/$label"; rel="${p#"$label"/}"; ro="${o#"$label"/}"; fi
    out=""
    if [ "$st" = A ]; then
        [ -f "$ROOT/$p" ] || continue
        n="$(awk 'END { print NR }' "$ROOT/$p")"
        [ "$n" -gt 0 ] && out="$(printf '%s\t1-%d' "$p" "$n")"
    else
        ref="$(resolve_ref "$label")" || fail "no merge-base between '${NESTED_BASE[$label]:-$BASE}' and HEAD$([ "$label" = "." ] || printf ' in %s' "$label")$(err_tail)"
        files=("$rel"); [ -n "$ro" ] && files=("$ro" "$rel")
        git_out "$dir" diff -U0 "$RENAME_OPT" "$ref" -- "${files[@]}"
        out="$(hunk_ranges "$p" <<<"$GIT_OUT")"
    fi
    if [ -n "$out" ]; then
        printf '%s\n' "$out"
        COUNT=$((COUNT + 1))
    fi
done
echo "STATUS: OK $COUNT files"
