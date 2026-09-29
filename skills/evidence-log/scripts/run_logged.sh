#!/usr/bin/env bash
# run_logged.sh — run one command and keep a verbatim log of it, so a report can cite
# the output by log path and line range instead of retyping it.
#
# Usage: run_logged.sh <task-dir> <slug> [--] <command> [args...]
#
# Writes <task-dir>/logs/NNN-<slug>.log, NNN being the next free 3-digit number in that
# directory (allocated atomically, so parallel callers never share a number). Log layout:
#
#   # command: <argv, shell-quoted with printf %q — paste-able and exact>
#   # cwd: <working directory>
#   # start: <UTC ISO timestamp>
#   --- output (stdout and stderr interleaved) ---
#   <the command's output, in the order it was written>
#   --- end output ---        (or "--- end output (no trailing newline) ---" when the
#                              command's last byte was not a newline)
#   # end: <UTC ISO timestamp>
#   # killed: <TERM|INT|HUP>    (only when the logger itself was signalled; the command's process
#                              group is sent TERM)
#   # exit: <exit code>
#   STATUS: OK | FAIL (exit N) | FAIL (killed: SIG)     (always the log's last line, so it is citable)
#
# stdout and stderr share one stream so the log reads as a terminal would have shown it;
# the two are not distinguishable afterwards.
#
# Prints the log path, its line count, its md5 (all three describe the finished log,
# STATUS line included) and the same STATUS line, and exits with the command's own exit
# code, except that a received TERM, INT or HUP makes it 128 plus that signal's number
# (143, 130, 129); 2 on bad usage, before anything runs.
#
# The command runs in its own process group, so a signal to the logger stops the command
# and everything it spawned; it is not attached to the terminal's foreground group, so
# commands that read the TTY interactively are unsupported.
set -u
set +e

fail_usage() {
    echo "run_logged: $1" >&2
    echo "usage: run_logged.sh <task-dir> <slug> [--] <command> [args...]" >&2
    echo "STATUS: FAIL"
    exit 2
}

[ $# -ge 3 ] || fail_usage "need a task dir, a slug and a command"
TASK_DIR="$1"; SLUG="$2"; shift 2
[ "${1:-}" = "--" ] && shift
[ $# -ge 1 ] || fail_usage "no command given"
case "$SLUG" in
    ''|*[!A-Za-z0-9._-]*) fail_usage "slug '$SLUG' must match [A-Za-z0-9._-]+" ;;
esac

LOG_DIR="$TASK_DIR/logs"
mkdir -p "$LOG_DIR" || fail_usage "cannot create $LOG_DIR"

# Next free NNN: one past the highest existing number. A claim directory makes the
# choice atomic; it is dropped once the log file exists and holds the number itself.
LOG=""
n=0
for f in "$LOG_DIR"/[0-9][0-9][0-9]-*.log; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"; v=$((10#${b%%-*}))
    [ "$v" -gt "$n" ] && n=$v
done
while :; do
    n=$((n + 1))
    [ "$n" -le 999 ] || fail_usage "no free log number left in $LOG_DIR"
    num="$(printf '%03d' "$n")"
    if mkdir "$LOG_DIR/.claim-$num" 2>/dev/null; then
        if ls "$LOG_DIR/$num"-*.log >/dev/null 2>&1; then
            rmdir "$LOG_DIR/.claim-$num"
            continue
        fi
        LOG="$LOG_DIR/$num-$SLUG.log"
        : > "$LOG"
        rmdir "$LOG_DIR/.claim-$num"
        break
    fi
done

utc() { date -u +%FT%TZ; }
{
    printf '# command:'; printf ' %q' "$@"; printf '\n'
    printf '# cwd: %s\n' "$PWD"
    printf '# start: %s\n' "$(utc)"
    echo '--- output (stdout and stderr interleaved) ---'
} >> "$LOG"

# The command runs in the background so a signal sent to this script interrupts `wait`
# and the trailer can still be written. stdin is passed through explicitly (a background
# job would otherwise read /dev/null).
killed=""
killnum=0
child=""
on_signal() {
    killed="$1"
    case "$1" in HUP) killnum=129 ;; INT) killnum=130 ;; *) killnum=143 ;; esac
    [ -n "$child" ] && kill -TERM -- "-$child" 2>/dev/null
}
trap 'on_signal TERM' TERM
trap 'on_signal INT' INT
trap 'on_signal HUP' HUP

[ -t 0 ] && exec </dev/null
set -m
( trap - INT QUIT; exec "$@" ) >> "$LOG" 2>&1 <&0 &
child=$!
set +m
{ wait "$child"; } 2>/dev/null
rc=$?
if [ -n "$killed" ]; then
    rc=$killnum
    # Drain the whole group, not just its leader: members still cleaning up after
    # TERM would otherwise write past STATUS. Escalate to KILL after a ~5 s grace
    # period. The braces keep bash's job-status notice ("Killed") off stderr.
    {
        i=0
        while kill -0 -- "-$child" 2>/dev/null; do
            [ $i -ge 50 ] && { kill -KILL -- "-$child" 2>/dev/null; sleep 0.1; break; }
            sleep 0.1; i=$((i + 1))
        done
    } 2>/dev/null
fi
trap - TERM INT HUP

endmark='--- end output ---'
if [ -n "$(tail -c1 "$LOG")" ]; then
    echo >> "$LOG"
    endmark='--- end output (no trailing newline) ---'
fi
if [ -n "$killed" ]; then
    status="STATUS: FAIL (killed: $killed)"
elif [ $rc -eq 0 ]; then
    status="STATUS: OK"
else
    status="STATUS: FAIL (exit $rc)"
fi
{
    echo "$endmark"
    printf '# end: %s\n' "$(utc)"
    [ -n "$killed" ] && printf '# killed: %s\n' "$killed"
    printf '# exit: %s\n' "$rc"
    echo "$status"
} >> "$LOG"

echo "log: $LOG"
echo "lines: $(wc -l < "$LOG")"
echo "md5: $(md5sum "$LOG" | cut -d' ' -f1)"
echo "$status"
exit $rc
