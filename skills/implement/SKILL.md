---
name: implement
description: Closed-loop execution of an approved G+Smo plan — the main session orchestrates cheap agents (sonnet implementers, sonnet reviewer, haiku helpers) that implement, self-verify, and get reviewed task by task, ending with a plan-conformance check. Use after plan approval for any multi-step change; pass the plan-file path or slug.
argument-hint: "<plan-file-or-slug>"
---

You are the ORCHESTRATOR. Your job is decomposition, dispatch, and judgment — never implementation. The moment you start editing source files yourself, the cost model of this framework is broken; the exceptions are listed at the bottom.

Artifact formats (task specs, reports, reviews, directory layout) are defined in `${CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md` — read it now if you haven't.

## 1. Set up the run

- Pick a short slug for the feature; create `.claude/plans/<slug>/` and `tasks/`.
- Write (or copy) the approved plan to `.claude/plans/<slug>/plan.md`. If no plan exists yet, stop and do the planning first (skill `gismo:plan`, ideally via plan mode).
- Decompose the plan into task files `tasks/NN-<name>.md` per the contract and the sizing rules in `gismo:plan`. Choose each task's `Agent:` line:
  - `gismo:implementer` — library code in `src/`, `optional/*/src`
  - `gismo:test-writer` — UnitTest++ suites
  - `gismo:example-writer` — runnable drivers in `examples/`
  - `gismo:doc-writer` — doxygen/tutorials/README (haiku, cheapest)
- Mirror the tasks with TaskCreate (one native task per task file, files remain the source of truth). Confirm `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` succeeds before dispatching anything; if it fails, run `/gismo:dev-config` with the user.
- **Preflight the context maps once, before dispatching.** The agents you spawn read
  `.claude/gismo-maps/library-map.md` and `.claude/gismo-maps/modules/<mod>.md`, which are
  per-checkout and absent on a fresh clone. If either is missing, generate it now (`/gismo:tree`,
  `/gismo:module-map`) — otherwise every dispatched agent hits the same missing file and wastes
  a task cycle discovering it.

## 2. Per-task closed loop

For each task, in dependency order (dispatch `Parallelizable-with` groups concurrently, but never two tasks that build make targets at the same time — parallel `make` invocations in one build dir corrupt nothing but serialize anyway and double the load):

1. **Dispatch** the task's agent with a minimal prompt: the task-file path, the repo root, and nothing else — the task file carries all context. Do not paste plan.md or your own analysis into the prompt.
2. **Review**: when the report lands, dispatch `gismo:task-reviewer` with the task-file path.
3. **Repair loop**: on `VERDICT: FAIL`, re-dispatch the same implementer agent with the task-file path + the review-file path ("address every numbered fix, update your report"). Maximum **2 repair rounds** per task; after that, intervene yourself (this is one of the exceptions) or, if the failure reveals a plan defect, go to step 4.
4. **Blocked tasks** (`RESULT: BLOCKED` or reviewer-confirmed spec defect): fix the *task file* (or plan) yourself — that is orchestration, not implementation — then re-dispatch. If the plan itself must change direction, surface it to the user before rewriting.
5. Update the native task status after each transition.

## 3. Final verification (yours alone)

When every task has `VERDICT: PASS`:

1. **Plan conformance** — read `plan.md` and the full change (`git diff` / `git status --short`): every item of the file inventory accounted for; deviations found by implementers listed and justified; nothing out of scope. You are the only reviewer who has seen the whole plan — task reviewers only ever saw single tasks, so cross-task integration gaps (mismatched interfaces, duplicated helpers, a test that no longer matches the final API) are YOUR job to catch.
2. **Full test suite** — dispatch `gismo:unittest-runner` with no selector (full run), plus a run of any example the plan's verification section names.
3. Write `summary.md`: what was built, deviations from plan with reasons, verification evidence, anything left open. Report this to the user — including honest FAILs.

## Cost discipline

- You (the expensive model) touch: plan, task files, reviews of reviews, final conformance, summary. Everything else is dispatched.
- Exploration questions that come up mid-run go to `gismo:indexer` (haiku) or the generated maps — not to your own file-reading spree.
- Exceptions where you may edit code yourself: a task failed 2 repair rounds; a trivial cross-task integration fix (< ~10 lines) found during final conformance. Anything larger becomes a new task file.

## Safety

Build rules bind you too: never bare `make`, never `-j`, builds only through the skill scripts. `.claude/plans/` is gitignored — never commit it; never run git write operations at all unless the user asks.
