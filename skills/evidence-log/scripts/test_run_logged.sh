#!/usr/bin/env bash
# Tests for run_logged.sh. Usage: bash test_run_logged.sh
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RL="$HERE/run_logged.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; failn=0
check() { # name, condition exit code
    if [ "$2" -eq 0 ]; then pass=$((pass+1)); echo "ok   $1"; else failn=$((failn+1)); echo "FAIL $1"; fi
}

out1="$(bash "$RL" "$T/task" first echo hello)"; rc1=$?
bash "$RL" "$T/task" second true >/dev/null
log1="$T/task/logs/001-first.log"; log2="$T/task/logs/002-second.log"
check "numbering: 001 then 002" $([ -f "$log1" ] && [ -f "$log2" ]; echo $?)
bash "$RL" "$T/task" third true >/dev/null
check "numbering: 003 follows" $([ -f "$T/task/logs/003-third.log" ]; echo $?)

bash "$RL" "$T/task" fail -- sh -c 'exit 7' >/dev/null; rc=$?
check "exit code propagates (7)" $([ "$rc" -eq 7 ]; echo $?)
check "exit code recorded in log" $(grep -qx '# exit: 7' "$T/task/logs/004-fail.log"; echo $?)
check "success exit is 0" $([ "$rc1" -eq 0 ]; echo $?)

bash "$RL" "$T/task" err sh -c 'echo to-stdout; echo to-stderr >&2' >/dev/null
check "stderr captured" $(grep -qx 'to-stderr' "$T/task/logs/005-err.log"; echo $?)
check "stdout captured" $(grep -qx 'to-stdout' "$T/task/logs/005-err.log"; echo $?)

printed="$(echo "$out1" | sed -n 's/^md5: //p')"
actual="$(md5sum "$log1" | cut -d' ' -f1)"
check "printed md5 matches md5sum" $([ -n "$printed" ] && [ "$printed" = "$actual" ]; echo $?)
check "printed log path" $([ "$(echo "$out1" | sed -n 's/^log: //p')" = "$log1" ]; echo $?)
check "STATUS line last" $([ "$(echo "$out1" | tail -n1)" = "STATUS: OK" ]; echo $?)
check "printed line count" $([ "$(echo "$out1" | sed -n 's/^lines: //p')" = "$(wc -l < "$log1")" ]; echo $?)

bash "$RL" "$T/task" quote printf '%s|' 'a b' "c'd" 'e"f' '$HOME' >/dev/null
# The header line is printf %q of the argv; compute the expectation independently.
expected="# command: printf %s\\| a\\ b c\\'d e\\\"f \\\$HOME"
check "command logged exactly (quoting)" $([ "$(sed -n 1p "$T/task/logs/006-quote.log")" = "$expected" ]; echo $?)
check "logged command replays to the same output" $(
    cmdline="$(sed -n '1s/^# command: //p' "$T/task/logs/006-quote.log")"
    [ "$(eval "$cmdline")" = "a b|c'd|e\"f|\$HOME|" ]; echo $?)
check "quoted command output verbatim" $(grep -qxF 'a b|c'"'"'d|e"f|$HOME|' "$T/task/logs/006-quote.log"; echo $?)
check "start and end timestamps" $(grep -qE '^# start: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z$' "$log1" && grep -qE '^# end: ' "$log1"; echo $?)

for i in 1 2 3 4 5 6; do bash "$RL" "$T/par" "p$i" true >/dev/null & done; wait
check "parallel callers get distinct numbers" $([ "$(ls "$T/par/logs" | sed 's/-.*//' | sort -u | wc -l)" -eq 6 ] && [ -z "$(ls -A "$T/par/logs" | grep '^\.claim')" ]; echo $?)

bash "$RL" "$T/task" >/dev/null 2>&1; rc=$?
check "bad usage exits 2" $([ "$rc" -eq 2 ]; echo $?)

check "log's last line is the STATUS line (OK)" $([ "$(tail -n1 "$log1")" = "STATUS: OK" ] && [ "$(tail -n2 "$log1" | head -n1)" = "# exit: 0" ]; echo $?)
check "log's last line is the STATUS line (FAIL)" $([ "$(tail -n1 "$T/task/logs/004-fail.log")" = "STATUS: FAIL (exit 7)" ]; echo $?)
check "printed STATUS equals the log's last line" $([ "$(echo "$out1" | tail -n1)" = "$(tail -n1 "$log1")" ]; echo $?)

kout="$(timeout --preserve-status -s TERM 1 bash "$RL" "$T/task" killme sleep 30)"; krc=$?
klog="$T/task/logs/$(ls "$T/task/logs" | grep -- '-killme.log$')"
check "killed: exit code is 128+15" $([ "$krc" -eq 143 ]; echo $?)
check "killed: trailer names the signal" $(grep -qx '# killed: TERM' "$klog"; echo $?)
check "killed: last log line is a STATUS line" $(tail -n1 "$klog" | grep -q '^STATUS: FAIL (killed: TERM)$'; echo $?)
check "killed: log path printed" $([ "$(echo "$kout" | sed -n 's/^log: //p')" = "$klog" ]; echo $?)

# A signalled logger stops the whole process group of the command: nothing lands after STATUS.
sigtest() { # name, slug, signal, group(0|1), expected rc
    local name="$1" slug="$2" sig="$3" grp="$4" want="$5" pid rc lg
    set -m
    bash "$RL" "$T/sig" "$slug" sh -c '(sleep 1; echo LATE) & wait' >/dev/null &
    pid=$!
    set +m
    sleep 0.4
    if [ "$grp" -eq 1 ]; then kill -"$sig" -- "-$pid"; else kill -"$sig" "$pid"; fi
    wait "$pid"; rc=$?
    sleep 1.5
    lg="$(ls "$T/sig/logs"/*-"$slug".log)"
    check "$name: exit code is $want" $([ "$rc" -eq "$want" ]; echo $?)
    check "$name: STATUS is the last line after the grandchild's delay" $(tail -n1 "$lg" | grep -q '^STATUS: FAIL (killed: '; echo $?)
    check "$name: grandchild output absent" $(! grep -qx LATE "$lg"; echo $?)
}
sigtest "TERM to logger" sigterm TERM 0 143
sigtest "INT to logger's process group" sigint INT 1 130
check "INT: trailer names the signal" $(grep -qx '# killed: INT' "$T"/sig/logs/*-sigint.log; echo $?)

# A group member that traps TERM and finishes its cleanup late: the logger waits for it,
# so its output lands before the STATUS line and the printed md5 covers the whole log.
set -m
lout="$(mktemp "$T/lateout.XXXXXX")"
bash "$RL" "$T/late" lateclean sh -c 'sh -c "trap \"sleep 0.5; echo CLEANED; exit\" TERM; while :; do sleep 0.1; done" & wait' >"$lout" &
lpid=$!
set +m
sleep 0.5
kill -TERM "$lpid"; wait "$lpid"
llog="$(ls "$T"/late/logs/*-lateclean.log)"
check "lateclean: STATUS is the last line" $(tail -n1 "$llog" | grep -q '^STATUS: FAIL (killed: TERM)$'; echo $?)
check "lateclean: late cleanup output kept before STATUS" $(grep -qx CLEANED "$llog"; echo $?)
check "lateclean: printed md5 equals md5sum" $([ "$(sed -n 's/^md5: //p' "$lout")" = "$(md5sum "$llog" | cut -d' ' -f1)" ]; echo $?)

# A command that ignores TERM is KILLed after the grace period; the trailer is still written.
set -m
bash "$RL" "$T/stub" stubborn sh -c 'trap "" TERM; while :; do sleep 0.2; done' >/dev/null 2>&1 &
spid=$!
set +m
sleep 0.5
t0=$SECONDS
kill -TERM "$spid"; wait "$spid"; src=$?
dt=$((SECONDS - t0))
slog="$(ls "$T"/stub/logs/*-stubborn.log)"
check "stubborn: logger returns within 7 s (took ${dt}s)" $([ "$dt" -le 7 ]; echo $?)
check "stubborn: exit code is 143" $([ "$src" -eq 143 ]; echo $?)
check "stubborn: trailer written, STATUS last" $(grep -qx '# killed: TERM' "$slog" && [ "$(tail -n1 "$slog")" = "STATUS: FAIL (killed: TERM)" ]; echo $?)

env SHELLOPTS=errexit bash "$RL" "$T/task" errexit false >/dev/null; erc=$?
elog="$(ls "$T"/task/logs/*-errexit.log)"
check "errexit: exit code propagates (1)" $([ "$erc" -eq 1 ]; echo $?)
check "errexit: trailer and STATUS written" $(grep -qx '# exit: 1' "$elog" && [ "$(tail -n1 "$elog")" = "STATUS: FAIL (exit 1)" ]; echo $?)

echo "passed=$pass failed=$failn"
[ "$failn" -eq 0 ]
