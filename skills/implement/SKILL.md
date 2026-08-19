---
name: implement
description: Closed-loop execution of an approved G+Smo plan. Standard mode decomposes it, dispatches one gismo:spec-writer per task and one gismo:task-lead per task to run the implement → review → repair cycle; quick mode (1–2 tasks) drops the task-leads and the orchestrator runs the single cycle itself. Sonnet implementers against an opus-written spec, opus adversarial reviewer, haiku/sonnet explorers. Use after plan approval; pass the plan-file path or slug.
argument-hint: "<plan-file-or-slug> [--quick|--full]"
---

You are the ORCHESTRATOR. Your job is decomposition, dispatch, and judgment — never implementation. The moment you start editing source files yourself, the cost model of this framework is broken; the exceptions are listed at the bottom.

Artifact formats (task specs, reports, reviews, directory layout) are defined in `${CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md` — read it now if you haven't.

## 0. Pick the mode

Read the plan's `Mode:` line. If it has none (the plan predates the convention, or was drafted outside `/gismo:plan`), apply the triage rubric in `${CLAUDE_PLUGIN_ROOT}/skills/plan/SKILL.md` §0 yourself and state the verdict. `--quick` / `--full` on the invocation overrides both.

- **Quick** (≤ 2 tasks, no new public API, no numerics, nothing builds on it): §1Q below. No task-leads, no batch review, no `summary.md` — you run the cycle yourself.
- **Standard**: §1S and §2 below, the full machinery.

Do not run standard machinery over a quick plan because it feels safer: the orchestration tax is the whole thing the mode exists to avoid. Do not run quick over a plan that fails the rubric either — the deferred cost lands on the reviewer, who is the expensive one.

Both modes: pick a short slug, create `.claude/plans/<slug>/`, write (or copy) the approved plan to `.claude/plans/<slug>/plan.md`. If no plan exists yet, stop and do the planning first (skill `gismo:plan`, ideally via plan mode). Confirm `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` succeeds before dispatching anything; if it fails, run `/gismo:dev-config` with the user. **Preflight the context maps once**: the agents you spawn read `.claude/gismo-maps/library-map.md` and `.claude/gismo-maps/modules/<mod>.md`, which are per-checkout and absent on a fresh clone — if either is missing, generate it now (`/gismo:tree`, `/gismo:module-map`), otherwise every dispatched agent hits the same missing file and wastes a task cycle discovering it.

## 1Q. Quick mode

1. **Write the task file(s) yourself, or dispatch one spec-writer — by rule, not by feel.** If the plan came through `/gismo:plan` and carries a grounded file inventory (real paths, named functions to reuse), the grounding is already done: create `tasks/01-<name>.md` (and `02-` if needed) in the contract's format directly, lifting the pointers from the plan. If there is no plan of that quality — a bare user request, or an inventory that names things vaguely — dispatch `gismo:spec-writer` per task instead and let it ground the spec. That is the only question: **is the grounding already written down?**
2. Set `Review: full` on anything touching `src/`, `light` for isolated example/test work, `none` for doc-only.
3. **Dispatch the task's agent directly** (`gismo:implementer` / `gismo:test-writer` / `gismo:example-writer` / `gismo:doc-writer`) with the task-file path and the repo root — nothing else, and never a model or tier (see the dispatch rule in `TASK_CONTRACT.md`). For two independent tasks, dispatch both in one message; never two tasks that build make targets at the same time.
4. **Review it yourself via one `gismo:task-reviewer`** on `Review: full`; on `light`/`none`, accept a `RESULT: DONE` report with a non-empty evidence section. On `VERDICT: FAIL`, re-dispatch the implementer with task-file + review-file paths and re-review — **one repair round**, then escalate to the user rather than grinding. On `RESULT: BLOCKED`, fix the spec and re-dispatch once; if the plan itself is wrong, surface it.
5. Finish with the tidy pass (§3 step 1), then whatever the plan's Verification section names — a filtered `gismo:unittest-runner` run or an example run, not the full suite; the implementer already ran the task's own test command. Report the outcome in chat: what changed, verification evidence, anything left open, honest FAILs included. No `summary.md` — for a one- or two-task change the report and review files are the audit trail.

The task-lead exists to keep round-by-round chatter out of a long run's context. With one or two tasks there is no such pressure, and its dispatch costs more than it saves — so in quick mode you take the lead.

## 1S. Standard mode: set up the run

- **Decompose, then delegate the writing.** Decomposition is yours: for each task fix a number, a one-line goal, the `Agent:` line, build target, test command, the `Review:` level (`full` for library code, numerics, and anything later tasks build on; `light` for low-risk isolated changes; `none` only for doc-only tasks — this dial is how you keep individual tasks cheap without weakening the gate where it matters), dependencies, and the files it may touch. Keep this as a compact list in your own context — do NOT write the full spec files yourself; the zero-discovery rule makes them long, and grounding them means reading source you don't otherwise need. Agent types to choose from:
  - `gismo:implementer` — library code in `src/`, `optional/*/src`
  - `gismo:test-writer` — UnitTest++ suites
  - `gismo:example-writer` — runnable drivers in `examples/`
  - `gismo:doc-writer` — doxygen/tutorials/README

- **Ground the shared facts once, before any spec-writer runs.** Spec-writers dispatched blind to each other re-scout the same things — the class everyone extends, the module's conventions, the pattern file they all imitate. Take the facts that *more than one* task will need (you can see this from the decomposition and the plan's file inventory), spawn one batch of `gismo:scout` (haiku) for them — one question per scout, all in a single message — and write the answers to `.claude/plans/<slug>/context.md` as a fact ledger: one line per fact, each with a `file:line` citation. Task-specific facts are not your job; leave those to the spec-writer that needs them.

- **Dispatch spec-writers in waves of ~4**, each with its decomposition entry, the plan directory, and the ledger path. Between waves, fold the new facts each spec-writer reported into `context.md` — you are its only writer, so there is no race, and wave 2 starts warmer than wave 1. With ≤ 4 tasks this is one wave and the ledger still pays for itself. Read each wave's `Gaps:` reports before dispatching the next: a gap means the plan names something that does not exist in the tree — fix the plan or the decomposition now (surface a direction change to the user), because it becomes a blocked task otherwise.

- Skim the written specs for cross-task consistency (matching interfaces, no overlapping `Files` lists); you may edit a spec directly — that is orchestration.
- Mirror the tasks with TaskCreate (one native task per task file, files remain the source of truth).

## 2. Per-task closed loop (standard mode)

For each task, in dependency order (dispatch `Parallelizable-with` groups concurrently, but never two tasks that build make targets at the same time — parallel `make` invocations in one build dir corrupt nothing but serialize anyway and double the load):

1. **Dispatch `gismo:task-lead`** with a minimal prompt: the task-file path, the repo root, and nothing else — the task file carries all context. Do not paste plan.md or your own analysis into the prompt. "Nothing else" is literal, and it forbids one thing in particular: **never restate the cycle as your own numbered instructions, and never name a model or tier for the task-lead's sub-dispatches.** The task-lead already has the protocol, and every agent's tier is fixed by its own definition (see the dispatch rule in `TASK_CONTRACT.md`) — an instruction like "use opus for the implementer" silently overrides the sonnet/opus split the cost model depends on. The task-lead runs the whole cycle for you — implementer → `gismo:task-reviewer` → on `VERDICT: FAIL` a repair re-dispatch with the review file, up to **2 repair rounds** — and returns a single `CYCLE: PASS | FAIL | BLOCKED` verdict. None of the intermediate reports and reviews land in your context; read the `NN-report.md` / `NN-review.md` files when you need details.
2. **On `CYCLE: FAIL`** (still failing after 2 repair rounds): intervene yourself (this is one of the exceptions) or, if the failure reveals a plan defect, go to step 3.
3. **On `CYCLE: BLOCKED`** (`RESULT: BLOCKED` or reviewer-confirmed spec defect): repair the *task file* — a small correction you make yourself, a badly-grounded spec by re-dispatching `gismo:spec-writer` with the blocker text. Either is orchestration, not implementation. Then dispatch a fresh `gismo:task-lead`. If the plan itself must change direction, surface it to the user before rewriting.
4. Update the native task status after each transition (the task-lead also updates it mid-cycle when a matching native task exists).

Fallback: nested subagents require Claude Code >= 2.1.172. If `gismo:task-lead` fails because it cannot spawn agents, run the loop inline instead: dispatch the task's agent yourself, then `gismo:task-reviewer`, and on `VERDICT: FAIL` re-dispatch the implementer with the review-file path — same 2-repair-round cap, same escalation rules as above.

## 3. Final verification (yours alone)

When every task has passed (in standard mode, when every task-lead has returned `CYCLE: PASS`, deferred or not):

0. **Batch review of deferred tasks** (standard mode only) — dispatch ONE `gismo:task-reviewer` with the list of every task that returned `PASS (review deferred)` (`Review: light`/`none`); it writes an `NN-review.md` per task. On any batch `VERDICT: FAIL`: edit that task file's `Review:` line to `full` (a task that failed review has outlived its low-risk label), then dispatch a fresh `gismo:task-lead` with the task-file path, noting the review-file path in the prompt so its first implementer dispatch addresses the numbered fixes. Only proceed when every task, deferred or not, has `VERDICT: PASS` (or, for `none`-level tasks that the batch passed silently, a clean review file).

1. **Tidy the run's comments** — invoke `/gismo:tidy` over the run's diff before anything is committed. Scaffolding comments that were useful *across* the run's tasks have outlived their purpose the moment the run ends; the reasoning they carry belongs in the `NN-report.md` files, which is where it already is. Read what it reports; a deletion you disagree with is yours to revert.

2. **Plan conformance** — read `plan.md` and the full change (`git diff` / `git status --short`): every item of the file inventory accounted for; deviations found by implementers listed and justified; nothing out of scope. You are the only reviewer who has seen the whole plan — task reviewers only ever saw single tasks, so cross-task integration gaps (mismatched interfaces, duplicated helpers, a test that no longer matches the final API) are YOUR job to catch.

3. **Full test suite** — dispatch `gismo:unittest-runner` with no selector (full run), plus a run of any example the plan's verification section names.

4. Write `summary.md` (standard mode; in quick mode just report in chat): what was built, deviations from plan with reasons, verification evidence, anything left open. Report this to the user — including honest FAILs.

## Cost discipline

- You (the expensive model) touch: the plan, the decomposition, the shared fact ledger, escalations after a failed cycle, final conformance, summary. Everything else is dispatched — spec *writing* goes to `gismo:spec-writer`, and in standard mode the per-task loop runs inside `gismo:task-lead`, so neither the bulk spec text nor round-by-round reports and reviews consume your context.
- Exploration questions that come up mid-run go to the generated maps, to `context.md`, to `gismo:scout` (haiku) for a settled fact, or to `gismo:indexer` (sonnet) when real exploration is needed — never to your own file-reading spree.
- Exceptions where you may edit code yourself: a task failed its repair rounds; a trivial cross-task integration fix (< ~10 lines) found during final conformance. Anything larger becomes a new task file.

## Safety

Build rules bind you too: never bare `make`, never `-j`, builds only through the skill scripts. `.claude/plans/` is gitignored — never commit it; never run git write operations at all unless the user asks.
