# Proposal: evidence by reference, single-source standing rules, append-only plans, measurement review

Status: proposal (2026-09-23), not applied. Source: the ch-m4-fixbatch hindsight audit in the gismo OpInf
worktree (`.claude/plans/ch-m4-fixbatch/FABLE_HINDSIGHT_AUDIT_2026-09-23.md`, §4 and §6).

Update 2026-09-29 (landed in 0.8.0): R2 (evidence by reference: `skills/evidence-log` and `run_logged.sh`, citations as log path plus line range), R3 (standing rules in `rules.md`, referenced by md5 from specs), R4 (append-only premises and status, dated `Update` paragraphs) and R7 (`Review: measurement` with its reviewer procedure) are applied, together with verdict-timestamp logging in `dispatches.log`. The in-flight `PASS (fix-ups)` work this proposal waited on is in the tree.

**Apply after the in-flight PASS (fix-ups) work lands.** `skills/implement/TASK_CONTRACT.md`,
`skills/implement/SKILL.md`, `agents/task-reviewer.md` and `agents/task-lead.md` carry uncommitted edits
that introduce the `VERDICT: PASS (fix-ups)` vocabulary. R2 and R7 build on that section.

## R2 — Evidence by reference, never by transcription

**Problem.** Across one campaign, 11 review rounds returned FAIL over an artifact the reviewer called sound
in the same file. Each FAIL was for a transcription defect in a report fence: a hand-retyped output line, a
dropped `echo` header, re-sorted `grep -c` output, `κ` written as `kappa`, a shortened path, or a command
that differed from the one actually run. Together those rounds cost at least 6 h 42 min of implementer
time, plus a second full review each. These are normalisation errors that a language model makes when it
copies text, not deceit. They recurred even after the spec named them.

**Rule.**
- Every command whose output is cited runs through a logger. The logger writes the command, stdout and
  stderr, the exit code and the UTC start and end times to `<task-dir>/logs/NNN-<slug>.log`, and prints
  the log path and its md5.
- Reports cite evidence as `logs/NNN-<slug>.log:L1-L2` (md5 `…`). They paste nothing that a logged
  `sed -n` did not print, and do not retype output.
- The reviewer checks each fence mechanically, with `diff` against the log's line range.
- Contract change, in TASK_CONTRACT.md's verdict vocabulary:
  - a fence that differs from an existing verbatim log, over a sound artifact, is **PASS (fix-ups)**;
  - a fence with **no** backing log is **FAIL** (fabricated evidence).
  The fabrication penalty stays where the harm is.

**Where.**
- `skills/implement/TASK_CONTRACT.md`:
  - the "quoted … character-for-character" clause (≈ l.320-324) becomes "cited by log path and line
    range";
  - the fabricated-evidence adjacency (≈ l.181-185) and the reviewer audit step (≈ l.408-414) get the
    split above.
- New skill `skills/evidence-log/`: a `SKILL.md` and `scripts/run_logged.sh`, in the shape of
  `build_target.sh` (redirect, capture `$?`, emit a `STATUS:` line). The log is kept, not a `mktemp`
  file.
- `agents/implementer.md`, `example-writer.md`, `test-writer.md`: run cited commands through
  `run_logged.sh`.
- `agents/task-reviewer.md`: the fence-diff step.

## R3 — Standing rules live in one file, included by reference

**Problem.** A false factual rule ("`examples/CH/` is untracked") was refuted in one task's review. It
was then copied verbatim into two later specs as a "re-verified" standing rule and refuted again.
Standing-rules blocks were being copied from the previous spec, and no spec-writer re-ran a factual
sentence it inherited.

**Rule.**
- A plan's standing rules live in `.claude/plans/<slug>/rules.md`. The per-run fact ledger
  `context.md` is a different thing and keeps its single writer.
- Specs include the rules by reference ("Standing rules: `rules.md` @ md5 …"). A spec never copies
  rules from a sibling spec.
- Every factual sentence in `rules.md` carries the command that verifies it. The spec-writer re-runs
  those commands and records their output in the spec.

**Where.**
- `skills/plan/SKILL.md`: the existing `## Standing rules` heading (l.10) means session-scoped planning
  rules. Rename it, e.g. to `## Session rules`, to avoid a name collision.
- `agents/spec-writer.md` (≈ l.13-34): read and verify `rules.md`, never copy.
- `skills/implement/TASK_CONTRACT.md`: spec format gains a `Standing rules:` reference line.

## R4 — Plans and specs are append-only for premises and status

**Problem.** `plan.md` was edited in place ("Three premises of the original bullet were wrong and are
corrected here"), so the record of what a premise was is gone. Pre-registrations in the same campaign
were append-only; the plan was not.

**Rule.** A premise or status in `plan.md` or a spec is never rewritten. A correction is a dated
paragraph under the original: *Update YYYY-MM-DD (reason): …*. A status table may gain rows and columns,
but no cell is overwritten without a dated note.

**Where.**
- `skills/plan/SKILL.md` §1 "Writing plan.md" (≈ l.68-71).
- The task-spec section of `skills/implement/TASK_CONTRACT.md`.

## R7 — `Review: measurement`

**Problem.** Full adversarial review earned its cost on library and driver code: it found code defects,
a segfault and a SIGABRT by attack. It was overpriced for measurement tasks whose artifact is a CSV plus a
script. There, the real work is re-deriving the headline numbers and checking fences, and no attack phase
applies.

**Rule.** A fourth review level, `measurement`, for tasks whose deliverable is a data file plus an
analysis script:
1. re-derive every headline number from the retained CSV, reading columns by header name, never by
   position;
2. diff every fence against its log (R2);
3. check that the pre-registered rule was applied as committed: thresholds read from the committed
   text, not from the spec;
4. no attack phase, and one round.
`full` stays the level for `src/` and driver code.

**Where.**
- `skills/implement/SKILL.md` (l.31, l.40, l.68-72): the dial gains `measurement`.
- `agents/task-reviewer.md` (l.3, l.15): the depth branch.
- `skills/implement/TASK_CONTRACT.md` (≈ l.440-465): the procedure.

## Also worth logging (audit §4.3)

`dispatches.log` records dispatch times only. Log the verdict timestamp as well, and the fix-up passes
sent via SendMessage, so that the cost of a round can be recovered.
