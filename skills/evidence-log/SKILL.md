---
name: evidence-log
description: Run a command through a logger that keeps a verbatim, numbered log (command, UTC start/end, stdout+stderr, exit code) and prints its path and md5, so a report cites output by log path and line range instead of retyping it. Use for every command whose output a task report quotes.
argument-hint: "<task-dir> <slug> <command...>"
allowed-tools: Bash(bash:*)
---

Run a command whose output you will cite through the logger — never retype output into a report:

```
bash ${CLAUDE_PLUGIN_ROOT}/skills/evidence-log/scripts/run_logged.sh <task-dir> <slug> <command> [args...]
```

`<task-dir>` is the `tasks/` directory beside your task file (`.claude/plans/<plan>/tasks`); `<slug>` names the check and starts with your task number, e.g. `01-unittests`. Parallel tasks share the directory, so the number `NNN` is allocated per call, never chosen by you.

What it does:
- Writes `<task-dir>/logs/NNN-<slug>.log` and keeps it. The log holds the command line (shell-quoted, exact), the working directory, UTC start and end, the output, and the exit code. stdout and stderr are **interleaved** in one stream, in the order the command wrote them — the log reads as the terminal would have.
- Prints `log:`, `lines:`, `md5:` and a last line `STATUS: OK`, `STATUS: FAIL (exit N)` or `STATUS: FAIL (killed: SIG)`. The same STATUS line is the last line of the log, after `# exit: N`, so it can be cited by line number. If the logger is sent TERM, INT or HUP it sends TERM to the command's whole process group and waits for every member to exit, up to a ~5 s grace period after which the group is sent KILL, so the command and everything it spawned stop and nothing lands after the STATUS line; it records `# killed: <signal>` in the trailer, still prints the log path, and exits with 128 plus the received signal's number (129 HUP, 130 INT, 143 TERM). Otherwise the script exits with the command's own exit code, so it drops into any pipeline that checks `$?`.
- The command runs in its own process group, detached from the terminal's foreground group, and a TTY on stdin is replaced by `/dev/null`: commands that read the terminal interactively are unsupported.
- Runs the command as given (argv, no re-quoting): to log a pipeline or a redirect, wrap it as `bash -c '…'` and the whole string is logged.

Citing:
- Cite evidence as `logs/NNN-<slug>.log:L1-L2 (md5 <hash>)`. To show lines, read the original log with the Read tool — its line numbers equal the log's own line numbers — and paste lines L1-L2 exactly, without the line-number prefix. The reviewer diffs the fence against that range of the log, whose md5 is the one cited. A fence in a report is a copy of those lines, nothing retyped, nothing normalised — not a shortened path, not a re-sorted list, not `kappa` for `κ`.
- The line numbers are the log's own, header included, so cite them after the run, from `grep -n` or `sed -n`, not from memory.
- A command that failed to start is still logged; it is not evidence that the change works (see the implementer rules) — fix the invocation and run it again, and cite the run that exercised the change.

Do not edit a log after the run: its md5 is what a reviewer checks the citation against.
