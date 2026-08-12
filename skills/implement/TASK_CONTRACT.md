# G+Smo task contract (shared by orchestrator, spec-writers, task-leads, implementers, reviewer)

Every feature run lives in `.claude/plans/<slug>/` (gitignored):

```
.claude/plans/<slug>/
├── plan.md            # the approved plan (context, approach, file inventory, verification)
├── tasks/
│   ├── 01-<name>.md   # task spec (orchestrator decomposes, gismo:spec-writer writes)
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
Review: full | light | none
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

The `Review:` level is the orchestrator's cost/robustness dial, fixed at
decomposition time:

- `full` — the whole adversarial cycle, in-cycle, per task. Default for
  library code, numerics, and anything a later task builds on.
- `light` / `none` — **review is deferred, not skipped.** The task-lead
  accepts a `RESULT: DONE` report with a non-empty evidence section and
  returns `CYCLE: PASS (review deferred)` (missing evidence earns one repair
  re-dispatch, then `CYCLE: FAIL`); the orchestrator collects all
  deferred tasks and dispatches ONE `gismo:task-reviewer` in **batch mode**
  at the end of the run (before final conformance). In the batch, `light`
  tasks get a diff-vs-spec read, `none` tasks an evidence sanity check.
  `light` fits low-risk, well-isolated changes; `none` doc-only tasks.
  Neither is ever for code that a test or another task builds on — that is
  what makes end-of-run batching safe.
- A task that FAILs its batch review has outlived its low-risk label: the
  orchestrator escalates the spec's `Review:` line to `full` and re-runs
  `gismo:task-lead` (giving the review-file path as context in the prompt) —
  never another deferred pass.

## Dispatch rule: the tier is not yours to choose

Binding on every agent in this framework that spawns another, orchestrator
included. **Never pass a `model` argument to the Agent tool, and never write a
model, tier or cost instruction into a dispatch prompt.** Each agent's tier is
declared in its own definition — scout is haiku, the implementers are sonnet,
spec-writer, reviewer and advisor are opus — and a `model` argument silently
overrides that declaration. The whole cost model of this framework is the tier
split; an agent that re-decides it at dispatch time dismantles the design while
appearing to follow it, and nothing in the agent files will show what happened.

If a task genuinely needs a stronger model than its agent declares, that is not
a dispatch-time tweak: the implementers escalate one decision to `gismo:advisor`
(opus), and everything else is the orchestrator's call to make in the spec.

## Spec-writer protocol (gismo:spec-writer)

The orchestrator decomposes; one spec-writer per task writes the file.
Dispatched with a decomposition entry (number, one-line goal, `Agent:`, build
target, test command, dependencies, allowed files) and the plan directory.

1. Read `plan.md` for intent — spec-writers are on the orchestration side and
   may read it; implementers may not.
2. Ground every pointer in the real tree: exact paths, signatures, the
   `file.hpp:120` location of the pattern to imitate, the relevant module map.
   Delegate the lookups — `gismo:scout` (haiku) per fact, `gismo:indexer`
   (sonnet) when exploration is needed; no other agent type.
3. Never invent a pointer. A plan reference that does not exist in the tree is
   a **grounding gap**, reported to the orchestrator — not guessed around.
4. Write `NN-<name>.md` in the format above and return
   `SPEC: WRITTEN | BLOCKED` plus a `Gaps:` list.

The spec-writer has no Bash tool: it never builds, runs, or configures.

## Task-lead protocol (gismo:task-lead)

One task-lead per task, dispatched by the orchestrator with the task-file path.
It runs the closed loop as nested subagents (Claude Code >= 2.1.172):

1. Read the task file's `Agent:` and `Review:` lines — nothing else. No
   plan.md, no source, no context files: the implementer reads them itself.
2. Dispatch that agent with the task-file path; on its return, dispatch
   `gismo:task-reviewer` with the same path — `Review: full` only. On
   `light`/`none`, skip the reviewer (the orchestrator batch-reviews these
   at the end): a `RESULT: DONE` report with a non-empty evidence section
   is `CYCLE: PASS (review deferred)`; an empty or missing evidence section
   earns one repair re-dispatch ("complete the evidence section"), after
   which a still-evidence-less report is `CYCLE: FAIL`.
3. `VERDICT: FAIL` → re-dispatch the implementer with task-file + review-file
   paths, then re-review. Maximum **2 repair rounds**, then stop.
4. `RESULT: BLOCKED` or a reviewer-confirmed spec defect ends the cycle at
   once — repair rounds cannot fix a broken spec.
5. Return `CYCLE: PASS | FAIL | BLOCKED` plus rounds used, the outstanding
   fixes (FAIL) or the blocker (BLOCKED). The task-lead edits no files and
   runs no builds; spec repair and escalation belong to the orchestrator.

## Implementer protocol (all implementer agents)

1. Read YOUR task file only, plus the context it points to. Never read plan.md.
   For small factual gaps (a location, a signature, a convention) spawn
   `gismo:scout` (haiku) — one question per scout, so several facts mean
   several scouts dispatched in the same message, never several questions in
   one call — and `gismo:indexer` (sonnet) only when the answer needs
   multi-step exploration. Never any other agent type.
2. Implement within the listed files. If the spec turns out to be impossible or
   wrong, STOP and write the blocker into your report — do not improvise scope.
   **Advice comes from exactly one source, chosen by config — never two.**
   `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` prints
   `GISMO_ADVISOR` (you already run this via the build scripts):
   - `GISMO_ADVISOR=native` — Claude Code's own advisor is configured and
     subagents inherit it, so it is already advising you. **Do not consult
     `gismo:advisor`**; note `Advisor: native` in your report and move on.
   - `GISMO_ADVISOR=agent` (the default) — no native advisor is configured.
     Consult `gismo:advisor` (opus) at the trigger points below.

   Three trigger points — the first two fire on need, the third on risk:
   a. **Open decision.** Whenever you are about to commit to a numerical or API
      approach the spec left open — before you write the code, not after.
   b. **Stuck loop.** After two failed build or test cycles against the *same*
      error, consult before attempting a third. A third identical attempt is
      rarely the one that works, and this is the cheapest moment to be told you
      are attacking the wrong layer.
   c. **Completion check**, before writing your report: **mandatory on
      `Review: full` tasks**, optional on `light`/`none` — those carry little
      enough risk that the deferred batch review is proportionate, and an opus
      consult to bless a trivial change is not.
   Pass the task-file path, the decision, and the options you are weighing; it
   reads the spec and your diff itself. At most **2 consults per task** — it is
   the most expensive agent you can reach, so if several triggers fire, spend
   them on the earliest ones: advice before the code is written is worth more
   than advice after.
   Act on its verdict line: `ADVICE: PROCEED` → follow the recommendation;
   `ADVICE: SPEC DECIDES` → you misread the spec, follow the spec;
   `ADVICE: BLOCKED` → report `RESULT: BLOCKED` relaying its reasoning. Record
   every consult's verdict line in your report so the reviewer can see what was
   advised. Never settle an open judgment call by guessing.
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

Two modes: per-task (dispatched by a task-lead, one path, full adversarial
depth) and batch (dispatched by the orchestrator with the run's deferred
`light`/`none` tasks; depth scaled per task's level, one `NN-review.md`
each, plus cross-task consistency notes). Both follow:

1. Read the task spec, the report, and `git diff -- <listed files>` (plus
   `git status --short` to catch out-of-scope edits).
2. Audit the report's evidence (genuine STATUS lines, output consistent with
   the diff); re-run the test command **only** when that evidence is missing,
   inconsistent, or stale — not as a routine step. Spend the effort attacking
   instead: hostile/degenerate inputs against the built binaries, probes of
   numerical hazards seen in the diff, and checks that each new test can
   actually fail. A successful in-scope attack is a FAIL with the exact
   reproduction command.
3. Write `NN-review.md`: verdict `PASS` or `FAIL`, for FAIL a numbered list
   of required fixes (each concrete enough to act on without re-investigation),
   and a `Notes:` section for non-blocking findings — report everything found,
   at every severity; only blocking findings decide the verdict.
   Check for: acceptance criteria met, evidence genuine (STATUS: OK present),
   G+Smo conventions, no out-of-scope files touched, no scope creep, and — on
   test tasks — falsification evidence (each new test observed to FAIL once,
   per the test-writer's protocol) present in the report. The report should
   also carry the `gismo:advisor` verdict lines; advice that was solicited and
   then ignored is worth a note, and a decision the implementer clearly made
   alone is worth a look.

## Build safety (absolute, for every agent)

- Never run bare `make` and never pass `-j` yourself: only
  `build_target.sh <target>` (jobs come from the config, capped at nproc/2).
- Never remove or reconfigure a build directory.
- Reconfiguring (`cd <builddir> && cmake .`) is allowed only after adding a new
  .cpp file, and `build_target.sh` will tell you when it is needed.
