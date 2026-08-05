---
name: implement
description: Closed-loop execution of an approved G+Smo plan — the main session decomposes it, dispatches one gismo:spec-writer per task to write the specs and one gismo:task-lead per task to run the implement → review → repair cycle (opus implementers, opus reviewer, sonnet helpers), keeping both off the main context, and ends with a plan-conformance check. Use after plan approval for any multi-step change; pass the plan-file path or slug.
argument-hint: "<plan-file-or-slug>"
---

You are the ORCHESTRATOR. Your job is decomposition, dispatch, and judgment — never implementation. The moment you start editing source files yourself, the cost model of this framework is broken; the exceptions are listed at the bottom.

Artifact formats (task specs, reports, reviews, directory layout) are defined in `${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md` — read it now if you haven't.

## 1. Set up the run

- Pick a short slug for the feature; create `.claude/plans/<slug>/` and `tasks/`.
- Write (or copy) the approved plan to `.claude/plans/<slug>/plan.md`. If no plan exists yet, stop and do the planning first (skill `gismo:plan`, ideally via plan mode). If the plan was drafted in plain plan mode *without* `/gismo:plan`, read `${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/plan/SKILL.md` now and bring the plan up to its standard (grounded file inventory with real paths, checkable verification) before decomposing — a free-form plan decomposes into blocked tasks.
- **Decompose, then delegate the writing.** Decomposition is yours: for each task fix a number, a one-line goal, the `Agent:` line, build target, test command, the `Review:` level (`full` for library code, numerics, and anything later tasks build on; `light` for low-risk isolated changes; `none` only for doc-only tasks — this dial is how you keep small tasks cheap without weakening the gate where it matters), dependencies, and the files it may touch. Keep this as a compact list in your own context — do NOT write the full spec files yourself; the zero-discovery rule makes them long, and grounding them means reading source you don't otherwise need. Dispatch one `gismo:spec-writer` per task (parallel — they are independent) with its decomposition entry and the plan directory; each reads the tree, grounds the pointers, and writes its `tasks/NN-<name>.md`. Agent types to choose from:
  - `gismo:implementer` — library code in `src/`, `optional/*/src`
  - `gismo:test-writer` — UnitTest++ suites
  - `gismo:example-writer` — runnable drivers in `examples/`
  - `gismo:doc-writer` — doxygen/tutorials/README (sonnet, cheapest)
- Read the spec-writers' `Gaps:` reports before dispatching any work. A gap means the plan names something that does not exist in the tree — fix the plan or the decomposition now (surface a direction change to the user), because it becomes a blocked task otherwise. Skim the written specs for cross-task consistency (matching interfaces, no overlapping `Files` lists); you may edit a spec directly — that is orchestration.
- Mirror the tasks with TaskCreate (one native task per task file, files remain the source of truth). Confirm `bash ${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` succeeds before dispatching anything; if it fails, run `/gismo:dev-config` with the user.
- **Preflight the context maps once, before dispatching.** The agents you spawn read
  `.claude/gismo-maps/library-map.md` and `.claude/gismo-maps/modules/<mod>.md`, which are
  per-checkout and absent on a fresh clone. If either is missing, generate it now (`/gismo:tree`,
  `/gismo:module-map`) — otherwise every dispatched agent hits the same missing file and wastes
  a task cycle discovering it.

## 2. Per-task closed loop

For each task, in dependency order (dispatch `Parallelizable-with` groups concurrently, but never two tasks that build make targets at the same time — parallel `make` invocations in one build dir corrupt nothing but serialize anyway and double the load):

1. **Dispatch `gismo:task-lead`** with a minimal prompt: the task-file path, the repo root, and nothing else — the task file carries all context. Do not paste plan.md or your own analysis into the prompt. The task-lead runs the whole cycle for you — implementer → `gismo:task-reviewer` → on `VERDICT: FAIL` a repair re-dispatch with the review file, up to **2 repair rounds** — and returns a single `CYCLE: PASS | FAIL | BLOCKED` verdict. None of the intermediate reports and reviews land in your context; read the `NN-report.md` / `NN-review.md` files when you need details.
2. **On `CYCLE: FAIL`** (still failing after 2 repair rounds): intervene yourself (this is one of the exceptions) or, if the failure reveals a plan defect, go to step 3.
3. **On `CYCLE: BLOCKED`** (`RESULT: BLOCKED` or reviewer-confirmed spec defect): repair the *task file* — a small correction you make yourself, a badly-grounded spec by re-dispatching `gismo:spec-writer` with the blocker text. Either is orchestration, not implementation. Then dispatch a fresh `gismo:task-lead`. If the plan itself must change direction, surface it to the user before rewriting.
4. Update the native task status after each transition (the task-lead also updates it mid-cycle when a matching native task exists).

Fallback: nested subagents require Claude Code >= 2.1.172. If `gismo:task-lead` fails because it cannot spawn agents, run the loop inline instead: dispatch the task's agent yourself, then `gismo:task-reviewer`, and on `VERDICT: FAIL` re-dispatch the implementer with the review-file path — same 2-repair-round cap, same escalation rules as above.

## 3. Final verification (yours alone)

When every task-lead has returned `CYCLE: PASS` (deferred or not):

0. **Batch review of deferred tasks** — dispatch ONE `gismo:task-reviewer` with the list of every task that returned `PASS (review deferred)` (`Review: light`/`none`); it writes an `NN-review.md` per task. On any batch `VERDICT: FAIL`: edit that task file's `Review:` line to `full` (a task that failed review has outlived its low-risk label), then dispatch a fresh `gismo:task-lead` with the task-file path, noting the review-file path in the prompt so its first implementer dispatch addresses the numbered fixes. Only proceed when every task, deferred or not, has `VERDICT: PASS` (or, for `none`-level tasks that the batch passed silently, a clean review file).

1. **Plan conformance** — read `plan.md` and the full change (`git diff` / `git status --short`): every item of the file inventory accounted for; deviations found by implementers listed and justified; nothing out of scope. You are the only reviewer who has seen the whole plan — task reviewers only ever saw single tasks, so cross-task integration gaps (mismatched interfaces, duplicated helpers, a test that no longer matches the final API) are YOUR job to catch.
2. **Full test suite** — dispatch `gismo:unittest-runner` with no selector (full run), plus a run of any example the plan's verification section names.
3. Write `summary.md`: what was built, deviations from plan with reasons, verification evidence, anything left open. Report this to the user — including honest FAILs.

## Cost discipline

- You (the expensive model) touch: the plan, the decomposition, escalations after a failed cycle, final conformance, summary. Everything else is dispatched — spec *writing* goes to `gismo:spec-writer` and the per-task loop runs inside `gismo:task-lead`, so neither the bulk spec text nor round-by-round reports and reviews consume your context.
- Exploration questions that come up mid-run go to `gismo:indexer` (sonnet) or the generated maps — not to your own file-reading spree.
- Exceptions where you may edit code yourself: a task failed 2 repair rounds; a trivial cross-task integration fix (< ~10 lines) found during final conformance. Anything larger becomes a new task file.

## Safety

Build rules bind you too: never bare `make`, never `-j`, builds only through the skill scripts. `.claude/plans/` is gitignored — never commit it; never run git write operations at all unless the user asks.
