# G+Smo task contract (shared by orchestrator, spec-writers, task-leads, implementers, reviewer)

Every feature run lives in `.claude/plans/<slug>/` (gitignored):

```
.claude/plans/<slug>/
├── plan.md            # the approved plan (context, approach, file inventory, verification)
├── context.md         # shared fact ledger — facts several tasks need (standard mode)
├── tasks/
│   ├── 01-<name>.md   # task spec (orchestrator decomposes, gismo:spec-writer writes)
│   ├── 01-report.md   # implementation report (written by the implementer agent)
│   ├── 01-review.md   # review verdict (written by gismo:task-reviewer)
│   └── ...
└── summary.md         # final plan-conformance summary (written by the orchestrator)
```

The run has a **mode**, set by the plan's `Mode:` line (rubric in
`${CLAUDE_PLUGIN_ROOT}/skills/plan/SKILL.md` §0):

- **standard** — the full machinery: one `gismo:spec-writer` per task, one
  `gismo:task-lead` per task, deferred batch review, `summary.md`.
- **quick** (≤ 2 tasks, no new public API, no numerics, nothing builds on it) —
  the orchestrator writes the task file itself when the plan is already
  grounded (a spec-writer only when it is not), dispatches the agent directly,
  runs one `gismo:task-reviewer` and one repair round at most. No task-lead, no
  batch review, no `summary.md`. Every other rule in this contract — the file
  formats, the implementer protocol, the dispatch rule, build safety — applies
  unchanged.

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

A multi-item `## Acceptance criteria` list doubles as the implementer's own
in-task todo list — it mirrors each checkbox into a native sub-task and
checks them off as it goes (implementer protocol, step 3 below). Write real,
independently checkable items, not one criterion artificially split into
several.

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

**The rule above governs `gismo:*` agents, whose tier is declared in their own
file. Generic agent types are the exact opposite case.** `Explore`, `Plan`,
`general-purpose` and `fork` declare no model — they **inherit the caller's**.
For them, omitting `model` is not neutrality, it silently runs exploration on
the most expensive tier in the session. So when you dispatch a generic type,
**pass `model: haiku`** for mechanical extraction, counting or a settled
lookup, and `model: sonnet` when the answer needs synthesis.

Both halves are the same principle — the tier is never an accident — and they
have been confused before: one run fanned a generic agent out into eleven
sub-agents on the top tier before the user stopped it. Prefer `gismo:scout`
(haiku) or `gismo:indexer` (sonnet) over a generic type in the first place;
they carry their tier with them and cannot inherit yours.

Cheapest of all is not dispatching. A subagent pays a full system prompt and
tool schemas before doing any work, so a `find`/`grep`/`wc` you could run
inline costs less run directly than delegated — delegate a lookup to protect
context, not to save tokens, and know which one you are buying.

## Spec-writer protocol (gismo:spec-writer)

The orchestrator decomposes; one spec-writer per task writes the file.
Dispatched with a decomposition entry (number, one-line goal, `Agent:`, build
target, test command, dependencies, allowed files) and the plan directory.

1. Read `plan.md` for intent — spec-writers are on the orchestration side and
   may read it; implementers may not.
2. **Read `context.md` first** (when the dispatch names it): the orchestrator
   has already looked up the facts several tasks share, each with a `file:line`
   citation. A fact that is in the ledger is settled — use it, never re-scout
   it. Sibling spec-writers run concurrently, so anything you look up that the
   ledger lacks is very likely being looked up next to you; keep your own
   lookups to what is specific to *your* task.
3. Ground every remaining pointer in the real tree: exact paths, signatures, the
   `file.hpp:120` location of the pattern to imitate, the relevant module map.
   Delegate the lookups — `gismo:scout` (haiku) per fact, `gismo:indexer`
   (sonnet) when exploration is needed; no other agent type. Return the
   generally-useful facts you found in a `New facts:` list (below); the
   orchestrator folds them into the ledger for the next wave. Never write to
   `context.md` yourself — it has exactly one writer, and concurrent appends
   would race.
4. Never invent a pointer. A plan reference that does not exist in the tree is
   a **grounding gap**, reported to the orchestrator — not guessed around.
5. Write `NN-<name>.md` in the format above and return
   `SPEC: WRITTEN | BLOCKED` plus a `Gaps:` list and a `New facts:` list
   (facts worth sharing, with `file:line`; `none` if there are none).

The spec-writer has no Bash tool: it never builds, runs, or configures.

## Task-lead protocol (gismo:task-lead)

One task-lead per task, dispatched by the orchestrator with the task-file path
and, when the orchestrator mirrored the task into the run's native todo list,
that task's native task ID.
It runs the closed loop as nested subagents (Claude Code >= 2.1.172):

1. Read the task file's `Agent:` and `Review:` lines — nothing else. No
   plan.md, no source, no context files: the implementer reads them itself.
2. Dispatch that agent with the task-file path, plus the native task ID if you
   were given one — the implementer updates it directly, so forward it
   verbatim rather than searching for a match yourself; on its return,
   dispatch `gismo:task-reviewer` with the same path — `Review: full` only. On
   `light`/`none`, skip the reviewer (the orchestrator batch-reviews these
   at the end): a `RESULT: DONE` report with a non-empty evidence section
   is `CYCLE: PASS (review deferred)` at round 0; an empty or missing evidence
   section earns one repair round ("complete the evidence section") by either
   route in 3, after which a still-evidence-less report is `CYCLE: FAIL`.
3. `VERDICT: FAIL` → put the implementer back on the task with task-file +
   review-file paths — `SendMessage` to the agent it already spawned, whose
   context is warm (it already has the native task ID from round 0, no need
   to repeat it), or a fresh dispatch when that agent is gone (repeat the
   native task ID, same as round 0) — then re-review. Maximum **2 repair
   rounds**, then stop. A nudge to a still-running agent is not a repair
   round; a message carrying review fixes is.
4. `RESULT: BLOCKED` or a reviewer-confirmed spec defect ends the cycle at
   once — repair rounds cannot fix a broken spec.
5. Return `CYCLE: PASS | FAIL | BLOCKED` plus rounds used, the outstanding
   fixes (FAIL) or the blocker (BLOCKED). The task-lead edits no files and its
   Bash is read-only inspection (`git diff`, reading a report) — never a build
   or a test run; spec repair and escalation belong to the orchestrator. Its
   `SendMessage` reaches only the two agents that cycle spawned itself, never
   the orchestrator or a sibling lead.

## Implementer protocol (all implementer agents)

1. If your dispatch included a native task ID, mark it `in_progress`
   (`TaskUpdate`) before doing anything else — you own that transition now,
   not your dispatcher. No ID means no matching native task; skip this
   silently rather than searching for one. Then log your own dispatch:
   append `<UTC ISO timestamp, date -u +%FT%TZ>\t<task-file basename>\t<your agent name>\t<round>`
   (tab-separated; round `0` initially, `N` when your prompt carries a review
   file for repair round N) to `dispatches.log` beside your task file's
   `tasks/` directory (`.claude/plans/<slug>/dispatches.log`). Your dispatcher
   cannot write files; this log is the only record of how many agents a run
   actually spent, and the `diagnose` skill reads it.
2. Read YOUR task file only, plus the context it points to. Never read plan.md.
   For small factual gaps (a location, a signature, a convention) spawn
   `gismo:scout` (haiku) — one question per scout, so several facts mean
   several scouts dispatched in the same message, never several questions in
   one call — and `gismo:indexer` (sonnet) only when the answer needs
   multi-step exploration. Never any other agent type.
3. If `## Acceptance criteria` lists more than one checkable item, mirror each
   into its own native sub-task (`TaskCreate`) before you start implementing,
   and mark each `completed` (`TaskUpdate`) the moment you've actually
   satisfied it — a progress trail through *this* task, independent of the
   single outer ID from step 1 (if you were given one). A criteria list of
   one item, or none, doesn't warrant it — skip silently rather than
   inventing a breakdown the spec doesn't have.
4. Implement within the listed files. If the spec turns out to be impossible or
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
5. Verify, in order:
   a. `bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <every touched file>`
   b. `bash ${CLAUDE_PLUGIN_ROOT}/skills/build-target/scripts/build_target.sh <build target>`
   c. the task's test command
6. Write `NN-report.md` — **this is where the reasoning goes, not the source**
   (see comment discipline below): files changed, what was done, verification evidence
   (the STATUS lines + relevant output tails), and any deviation from the spec
   with its reason. Every claim must be auditable against a tool result from
   this run — only report work you can point to evidence for; if something is
   unverified or failing, say so plainly instead of hedging. Every
   acceptance-criterion sub-task from step 3 should be `completed` by now — one
   still open means that criterion isn't actually met, so don't write
   `RESULT: DONE` against it. End the file with `RESULT: DONE` or
   `RESULT: BLOCKED`. If you have an outer native task ID (step 1), mark it
   `completed` on `RESULT: DONE`; leave it `in_progress` on `RESULT: BLOCKED`
   — the task isn't finished, and the orchestrator's repair path re-dispatches
   against the same ID.
7. You operate autonomously: nobody answers questions mid-task. Never end your
   turn on a question, a plan, or a promise ("I'll now build...") — end only
   after the report file is written (`RESULT: BLOCKED` is a report, not a
   question).

## Comment discipline (all implementer agents)

**The report is the place for reasoning about the change; the source is the
place for reasoning about the code.** You have `NN-report.md` precisely so you
do not have to narrate your work in comments — and the report survives review
while a comment survives forever, in a file whose next reader never saw your
diff.

Never write into the source:

- narration of the change — "removed the old loop", "previously this used
  `gsFoo`", "replaced by the helper below", a paragraph explaining a deletion;
- task or process scaffolding — "added for task 3", "per the spec", "addresses
  review point 2", run identifiers, `TODO(review)`;
- restatements of what the code plainly says, or first-person hedging ("this
  should work", "I chose this because");
- commented-out code you replaced. It is in git.

Do write, as always:

- doxygen on anything public;
- the theory: the equation, the scheme, the reference being implemented;
- complexity notes, and *why* a non-obvious formulation is the correct one when
  the obvious one is not (stability, cancellation, aliasing, index conventions,
  units, tensor shapes);
- real `TODO`/`FIXME` naming real remaining work, and warnings about real traps.

The test before you type a comment: **would this still be true and useful to
someone reading the file who never saw this diff?** If it only makes sense as a
message to a reviewer, it belongs in the report. If you need scaffolding notes
to keep track while you work, that is fine — delete them before you write the
report; a run-level `/gismo:tidy` pass exists as a safety net, not as your
excuse.

Match the surrounding file's comment density either way. G+Smo source is not
uncommented, and stripping the theory out of a solver is the opposite failure.

## Reviewer protocol (gismo:task-reviewer)

Two modes: per-task (dispatched by a task-lead, one path, full adversarial
depth) and batch (dispatched by the orchestrator with the run's deferred
`light`/`none` tasks; depth scaled per task's level, one `NN-review.md`
each, plus cross-task consistency notes). Both follow:

1. Log your own dispatch as the implementer does: append
   `<UTC ISO timestamp, date -u +%FT%TZ>\t<task-file basename>\tgismo:task-reviewer\t<round>` to
   `.claude/plans/<slug>/dispatches.log` (one line per task when dispatched in
   batch mode). Then read the task spec, the report, and
   `git diff -- <listed files>` (plus
   `git status --short` to catch out-of-scope edits). When the spec's
   `Parallelizable-with:` line implies a dependency (an earlier task it is
   *not* listed as parallel with), also read that task's report and
   `git diff` over its own `## Files` list — a test that passes vacuously or
   by the opposite mechanism from what it claims is only visible to a
   reviewer holding both the test and the code it tests.
2. Audit the report's evidence (genuine STATUS lines, output consistent with
   the diff); re-run the test command **only** when that evidence is missing,
   inconsistent, or stale — not as a routine step. Spend the effort attacking
   instead: hostile/degenerate inputs against the built binaries, probes of
   numerical hazards seen in the diff, and checks that each new test can
   actually fail; on a task with a dependency (per step 1), does the test
   actually exercise the case the dependency implemented? A successful
   in-scope attack is a FAIL with the exact reproduction command.
3. Write `NN-review.md`: on a repair round the file already exists — never
   overwrite it, append a new `## Round N` section with its own `VERDICT:`
   line below the existing rounds, and rewrite line 1 to that latest verdict
   (task-lead reads only line 1, so it must always be current). Verdict `PASS`
   or `FAIL`, for FAIL a numbered list
   of required fixes (each concrete enough to act on without re-investigation),
   and a `Notes:` section for non-blocking findings — report everything found,
   at every severity; only blocking findings decide the verdict.
   Check for, in this order — the order is measured from 77 fixes this
   reviewer actually demanded across the run corpus, not assumed:

   1. **Does the report describe what the diff really does?** This is the
      single largest defect class in the corpus: between a third and a half
      of all demanded fixes are about what the implementer *wrote* — its
      report, its doc claims, its stated justification — rather than what it
      built. (31% of 72 corpus fixes name a report claim explicitly; ~49%
      once false documentation claims and report-structure gaps are folded
      in.) A report that
      claims a hedge, a scope, a measurement or a rationale the artifact does
      not carry is a blocking finding, because the orchestrator reads the
      report and cannot see the diff. Check every load-bearing claim against
      the artifact, including quoted numbers and line references.
   2. **Acceptance criteria demonstrably met**, and evidence genuine
      (`STATUS: OK` present, output consistent with the diff).
   3. **Correctness**: numerical-stability hazards, unmet criteria, logic
      defects, silent narrowing.
   4. **Documentation claims**: doxygen or note text asserting more than the
      source of truth supports, and stale comments the change invalidated.
   5. On test tasks, **falsification evidence** (each new test observed to
      FAIL once, per the test-writer's protocol) present in the report.
   6. No out-of-scope files touched, no scope creep.
   7. **G+Smo conventions** (`give()` not `std::move`, GISMO_EXPORT/.cpp for
      non-template free functions, h/hpp/_.cpp split) and comment discipline.
      Real, but rare: 2 of 77 corpus fixes. Do not spend the pass here, and
      do not let a clean convention sweep stand in for check 1.

   The report should also carry the `gismo:advisor` verdict lines; advice
   solicited and then ignored is worth a note, and a decision the implementer
   clearly made alone is worth a look.

## Build safety (absolute, for every agent)

- Never run bare `make` and never pass `-j` yourself: only
  `build_target.sh <target>` (jobs come from the config, capped at nproc/2).
- Never remove or reconfigure a build directory.
- Reconfiguring (`cd <builddir> && cmake .`) is allowed only after adding a new
  .cpp file, and `build_target.sh` will tell you when it is needed.
