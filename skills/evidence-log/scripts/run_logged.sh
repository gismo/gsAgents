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
#   # stray: killed             (only when the command exited but members of its process group
#                              were still running after the grace period, and were killed)
#   # exit: <the command's exit code; 128+N when the logger's signal N ended the command>
#   STATUS: OK | FAIL (exit N) | FAIL (killed: SIG) | FAIL (stray processes killed)
#                              (always the log's last line, so it is citable)
#
# stdout and stderr share one stream so the log reads as a terminal would have shown it;
# the two are not distinguishable afterwards.
#
# Prints the log path, its line count, its md5 (all three describe the finished log,
# STATUS line included) and the same STATUS line, and exits with the command's own exit
# code, except that a received TERM, INT or HUP makes it 128 plus that signal's number
# (143, 130, 129), and a command that exited 0 but left stray processes makes it 1; 2 on
# bad usage, before anything runs.
#
# The command runs in its own process group, so a signal to the logger stops the command
# and everything it spawned; it is not attached to the terminal's foreground group, so
# commands that read the TTY interactively are unsupported.
#
# The trailer is written only once that whole group is gone. When the command exits
# while members it started are still running, they get ~5 s to finish (their output
# lands before STATUS); survivors are sent TERM, then KILL, and the run is recorded as
# failed. A descendant that leaves the group (setsid, its own job control) is invisible
# to the logger and can still write past STATUS.
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
stray=""
# group_alive: true while the command's process group has a member that is not a
# zombie. The group outlives its leader, so this still sees descendants after the
# command itself has exited. Zombies are skipped because they have closed their
# descriptors and cannot write; under a subreaper that never reaps (a container whose
# PID 1 is not an init) orphans stay zombies indefinitely. Without ps, fall back to
# kill -0, which counts zombies as live.
group_alive() {
    kill -0 -- "-$child" 2>/dev/null || return 1
    command -v ps >/dev/null 2>&1 || return 0
    ps -A -o pgid= -o stat= 2>/dev/null |
        awk -v g="$child" '$1 == g && $2 !~ /^Z/ { f = 1 } END { exit !f }'
}
# group_gone N [stop-on-signal]: wait until the group is empty, for N seconds at most
# (between N-1 and N, as $SECONDS ticks whole seconds; the deadline is on the clock
# rather than a poll count because each poll runs ps); non-zero if members remain.
# With a second argument it also gives up as soon as the logger is signalled, so the
# signal's own grace period starts afresh.
group_gone() {
    local end=$((SECONDS + $1))
    while group_alive; do
        [ "$SECONDS" -ge "$end" ] && return 1
        [ -n "${2:-}" ] && [ -n "$killed" ] && return 1
        sleep 0.1
    done
}
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
# A signal that interrupted wait leaves 128+N from wait, not the command's code. One
# arriving later, during the drain below, leaves the command's real code in rc.
[ -n "$killed" ] && rc=$killnum
# Drain the whole group, not just its leader: members still running (cleaning up after
# TERM, or backgrounded by a command that has already exited) would otherwise write
# past STATUS and change the log after its md5 was printed. Each stage has a ~5 s grace
# period. The braces keep bash's job-status notice ("Killed") off stderr.
{
    if [ -z "$killed" ] && ! group_gone 5 stop-on-signal && [ -z "$killed" ]; then
        stray=1
        kill -TERM -- "-$child"
    fi
    group_gone 5 || { kill -KILL -- "-$child"; sleep 0.1; }
} 2>/dev/null
ret=$rc
if [ -n "$killed" ]; then
    ret=$killnum
elif [ -n "$stray" ] && [ $rc -eq 0 ]; then
    ret=1
fi
trap - TERM INT HUP

endmark='--- end output ---'
if [ -n "$(tail -c1 "$LOG")" ]; then
    echo >> "$LOG"
    endmark='--- end output (no trailing newline) ---'
fi
if [ -n "$killed" ]; then
    status="STATUS: FAIL (killed: $killed)"
elif [ -n "$stray" ]; then
    status="STATUS: FAIL (stray processes killed)"
elif [ $rc -eq 0 ]; then
    status="STATUS: OK"
else
    status="STATUS: FAIL (exit $rc)"
fi
{
    echo "$endmark"
    printf '# end: %s\n' "$(utc)"
    [ -n "$killed" ] && printf '# killed: %s\n' "$killed"
    [ -n "$stray" ] && printf '# stray: killed\n'
    printf '# exit: %s\n' "$rc"
    echo "$status"
} >> "$LOG"

echo "log: $LOG"
echo "lines: $(wc -l < "$LOG")"
echo "md5: $(md5sum "$LOG" | cut -d' ' -f1)"
echo "$status"
exit $ret
