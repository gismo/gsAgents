# G+Smo task contract (shared by orchestrator, task-leads, implementers, reviewer)

Every feature run lives in `.claude/plans/<slug>/` (gitignored):

```
.claude/plans/<slug>/
├── plan.md            # the approved plan (context, approach, file inventory, verification)
├── tasks/
│   ├── 01-<name>.md   # task spec (written by the orchestrator)
│   ├── 01-report.md   # implementation report (written by the implementer agent)
│   ├── 01-review.md   # review verdict (written by gismo:task-reviewer)
│   └── ...
└── summary.md         # final plan-conformance summary (written by the orchestrator)
```

## Task spec format (`NN-<name>.md`)

```markdown
# Task NN: <one-line goal>
Agent: gismo:implementer | gismo:test-writer | gismo:example-writer | gismo:doc-writer
Build target: <make target to build, or "none">
Test command: bash ${CLAUDE_PLUGIN_ROOT}/skills/run-tests/scripts/run_unittests.sh <prefix>   (or "none")
Parallelizable-with: <task numbers, or "none">

## Goal
What must exist / behave differently when this task is done.

## Files
- path/to/file.h — create | edit: what changes
(EVERY file the agent may touch. Touching anything else is out of scope.)

## Context
- Pointers the agent needs: existing functions/classes to reuse (with paths),
  the relevant .claude/gismo-maps/modules/<mod>.md file,
  code snippets or patterns to follow. The agent should need NO discovery.

## Acceptance criteria
- [ ] Checkable statements only (compiles, test X passes, output Y appears...)
```

## Task-lead protocol (gismo:task-lead)

One task-lead per task, dispatched by the orchestrator with the task-file path.
It runs the closed loop as nested subagents (Claude Code >= 2.1.172):

1. Read the task file's `Agent:` line — nothing else. No plan.md, no source,
   no context files: the implementer reads those itself.
2. Dispatch that agent with the task-file path; on its return, dispatch
   `gismo:task-reviewer` with the same path.
3. `VERDICT: FAIL` → re-dispatch the implementer with task-file + review-file
   paths, then re-review. Maximum **2 repair rounds**, then stop.
4. `RESULT: BLOCKED` or a reviewer-confirmed spec defect ends the cycle at
   once — repair rounds cannot fix a broken spec.
5. Return `CYCLE: PASS | FAIL | BLOCKED` plus rounds used, the outstanding
   fixes (FAIL) or the blocker (BLOCKED). The task-lead edits no files and
   runs no builds; spec repair and escalation belong to the orchestrator.

## Implementer protocol (all implementer agents)

1. Read YOUR task file only, plus the context it points to. Never read plan.md.
   For small factual gaps (a location, a signature, a convention) opus
   implementers may spawn the cheaper `gismo:indexer` — a couple of precise
   questions per task at most; never any other agent type.
2. Implement within the listed files. If the spec turns out to be impossible or
   wrong, STOP and write the blocker into your report — do not improvise scope.
3. Verify, in order:
   a. `bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <every touched file>`
   b. `bash ${CLAUDE_PLUGIN_ROOT}/skills/build-target/scripts/build_target.sh <build target>`
   c. the task's test command
4. Write `NN-report.md`: files changed, what was done, verification evidence
   (the STATUS lines + relevant output tails), and any deviation from the spec
   with its reason. Every claim must be auditable against a tool result from
   this run — only report work you can point to evidence for; if something is
   unverified or failing, say so plainly instead of hedging. End the file with
   `RESULT: DONE` or `RESULT: BLOCKED`.
5. You operate autonomously: nobody answers questions mid-task. Never end your
   turn on a question, a plan, or a promise ("I'll now build...") — end only
   after the report file is written (`RESULT: BLOCKED` is a report, not a
   question).

## Reviewer protocol (gismo:task-reviewer)

1. Read the task spec, the report, and `git diff -- <listed files>` (plus
   `git status --short` to catch out-of-scope edits).
2. Independently re-run the test command when one is given (`--no-build` only if
   the report shows a fresh successful build of the same target).
3. Write `NN-review.md`: verdict `PASS` or `FAIL`, for FAIL a numbered list
   of required fixes (each concrete enough to act on without re-investigation),
   and a `Notes:` section for non-blocking findings — report everything found,
   at every severity; only blocking findings decide the verdict.
   Check for: acceptance criteria met, evidence genuine (STATUS: OK present),
   G+Smo conventions, no out-of-scope files touched, no scope creep.

## Build safety (absolute, for every agent)

- Never run bare `make` and never pass `-j` yourself: only
  `build_target.sh <target>` (jobs come from the config, capped at nproc/2).
- Never remove or reconfigure a build directory.
- Reconfiguring (`cd <builddir> && cmake .`) is allowed only after adding a new
  .cpp file, and `build_target.sh` will tell you when it is needed.
