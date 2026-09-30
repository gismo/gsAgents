# gsAgents: diagnosis of the current agent stack, and a plan to change it

**Date:** 2026-08-29 · **Branch:** `agent-tuning-quick-mode-and-comments`
**Status:** findings verified, then adversarially re-checked (§6); 7 fixes applied; batching (§3 items 3–7, 9) deferred pending measurement.

Update 2026-09-29 (0.8.0): the A1–A5 fixes are committed, and the proposal in `PROPOSAL-evidence-and-review-rules.md` (R2, R3, R4, R7) has since landed in 0.8.0. `skills/diagnose/scripts/test_harvest.py` now runs 41 tests, not the 30 stated here.

This document is written to be read cold, by a reviewer who was not present for
the analysis. Every number below is measured, and the method that produced it is
stated so it can be attacked.

---

## 0. What prompted this

The `/gismo:*` framework is rigorous but expensive. When the orchestrator
decomposes a plan into many tasks, each task spawns its own task-lead, its own
implement→review loop, and its own repair rounds. Cheap model tiers and a review
ladder were introduced to contain the cost; the suspicion was that the real
problem is *granularity* — that the orchestrator should batch related work and
hand a batch to one lead.

Rather than tune from intuition, we mined the framework's own execution history.

---

## 1. Method, and its limits

A harvester (`skills/diagnose/scripts/harvest.py`, stdlib-only, 30 tests) walks
`~/Code` and `~/.claude/projects` and extracts, with provenance, from four
artifact types: task specs, implementation reports, adversarial review files,
session transcripts, and curated memory documents. Extraction only — it never
classifies what a finding means. Five haiku miners then grouped the resulting
slices; ranking and attribution are the orchestrator's.

**Corpus after deduplication: 75 run directories, 701 review verdicts, 501
deviation passages, 327 user corrections, 53 `type: feedback` memory documents,
250 top-level session transcripts.** All artifacts date from 2026-07 and
2026-08, so there is no stale-skill-version confound.

Three methodological traps were found the hard way and are worth stating,
because a reviewer should check whether they were really avoided:

1. **Term frequency over whole review files is meaningless.** The reviewer
   protocol lists comment discipline, conventions and falsification as mandatory
   *checklist* items, so those words appear in most reviews regardless of
   findings. Measured: "comment" in 892 files whole-file, **15** when scoped to
   the `## Required fixes` region; `std::move` 336 → **0**; `scope creep`
   144 → **0**. Every count in this document is fix-scoped.
2. **Review files accumulate repair rounds in one file.** 34 files carry more
   than one `VERDICT:` line and **24 of those have no round heading at all**, so
   a heading-based parser silently collapses ~70% of multi-round files to a
   single verdict. Verdicts are parsed as sequences, with every `VERDICT:`
   treated as a round boundary. (The 34 is a raw-corpus count; after
   deduplication it is 17 of 696. The verdict totals below are post-dedup.)
   **This trap has a bigger sibling, found only on re-check:** most reviewers
   *overwrite* the review file on a repair round rather than appending, so the
   surviving verdict is the last one. See F4.
3. **`Code/Archive/` holds copies, not history.** 64 of 138 raw run dirs shared
   a slug and 39 of 40 sampled pairs were byte-identical. Counting both inflates
   every recurrence figure. Deduplicated on content hash (not slug), which
   removed 45% of the raw corpus. **5 duplicate review-fix entries still
   survived** where run dirs differ slightly but review files are identical.

**Known limits.** `class_key` is a text slug, so it clusters only near-verbatim
repeats — 5 of 72 review fixes, 0 of 728 `★★★` memory findings. All frequency
claims below therefore come from the miners' taxonomy, not from automated
recurrence. Deviation percentages are from a ~450-line sample of 501 items.

---

## 2. Findings

### F1 — Generic subagents silently run on the caller's tier  *(FIXED)*

`TASK_CONTRACT.md`, `agents/task-lead.md` and `agents/debugger.md` all stated
**"never pass a `model` argument"** absolutely. That is right for `gismo:*`
agents, whose tier is declared in their own file. It is *inverted* for `Explore`,
`Plan`, `general-purpose` and `fork`, which declare no model and **inherit the
caller's** — so obeying the rule literally runs exploration on the top tier.

Measured twice, three days apart. `feedback_never_spawn_fable_subagents.md`
(2026-08-26) records the user, angry, after one agent fanned out into 11
expensive sub-agents: *"Use CHEAP subagents, NEVER spawn fable!"* The session
that produced this document opened by dispatching three `Explore` agents with no
model override and was stopped by the user for exactly that.

A second memory, `feedback_respect_agent_models`, states the absolute form. The
two read as contradictory, which is why the rule kept being misapplied.

### F2 — Between a third and a half of demanded fixes are about what was *written*, not what was *built*  *(FIXED)*

Taxonomy of **72 distinct** fixes the adversarial reviewer demanded:

| category | n |
|---|---|
| report narrative inaccuracies | 14 |
| false / misleading documentation claims | 11 |
| numerical or measurement errors | 11 |
| missing documentation content | 11 |
| unmet acceptance criteria / logic bugs | 8 |
| report structure / completeness | 8 |
| missing or incomplete implementation | 7 |
| stale code comments | 5 |
| test flakiness | 3 |
| missing test coverage | 2 |
| **code convention violations** | **2** |

Report + documentation + structure + stale comments ≈ **49%**. An independent
mechanical check (regex for report/claim/asserts/justification, not the miner's
judgment) puts the floor at **22 of 72 = 31%**. Conventions are **2 of 72 =
2.8%** — yet the reviewer protocol gave conventions a dedicated checklist bullet
and report accuracy a passing clause.

Spot-checked verbatim, these are genuine false-claim findings, not wording nits:
*"asserts causation the note explicitly forbids"*; *"the falsified 'untested on
either side' claim"*; *"'quoted verbatim' labels a paraphrase"*.

**Caveat a reviewer should weigh:** 26 FAIL verdicts produced these 72 fixes,
concentrated in a handful of runs. This is a strong signal about *what reviewers
catch*, not a population estimate over all work.

### F3 — Runs are large, and the user has said so repeatedly

Median **8 tasks per run**, mean 10.9, max 70. 50 of 73 runs have ≥5 tasks; only
11 are quick-mode eligible. Each task costs **3 opus calls** (spec-writer,
mandatory advisor completion check, reviewer) plus a sonnet lead and a cold-start
implementer that re-reads what its siblings just read.

The largest user-correction category (95+ of 327) is challenging design
assumptions, and includes verbatim:

> "Why do we have SO MANY tasks again? Are they all needed or are we
> overengineering"

> "Please respect the rules and make sure you use as little resources as
> possible"

### F4 — The review gate's first-pass FAIL rate is ~36%, not 3.7%  *(CORRECTED)*

The first draft of this document reported **675 PASS vs 26 FAIL across 701
verdicts** and concluded the gate fires once in 27. That is the *final-state*
rate. The tell was internal: 118 repair rounds cannot follow from 26 FAILs.

Re-check: of 679 single-verdict review files, **243 (36%)** contain text in the
review or its sibling report naming a prior round ("Round 2", "supersedes the
round-1 FAIL review of the same file", "re-review after repair round 2").
Negation false positives spot-checked at ~4%. Adding the 4 files with a literal
first-round FAIL and the 5 that never passed: **first-pass FAIL ≈ 252/686 ≈
33–37%.** Evidence paths: `gismo_compositeMaps/.claude/plans/hr-adaptivity-study/
tasks/03-review.md`, `gismo_immersed/.claude/plans/momfit-rule/tasks/07-review.md`.

Consequences. The reviewer is the highest-yield step in the pipeline, not the
lowest; roughly one task in three ships a defect the implementer's own
verification did not catch. The cost case for *removing* review per task is
gone; the rigor case for a reviewer that sees coupled work (F5) is stronger.
And the corpus itself is lossy: review files must append rounds, never
overwrite (applied — §3 item A4).

### F5 — Coupled multi-agent work is the *typical* run, and it is reviewed uncoupled

**58 of 75 runs (77%) mix ≥2 agent types.** Dominant shapes: all four agent types
(20 runs), example+implementer+test (13), implementer+test (8).

Today the class is reviewed by an opus agent that never saw its test, and the
test by one that never saw the class. *"The suite passes but does not exercise
the case the implementation got wrong"* is unreachable from either seat.
`skills/plan/SKILL.md` already sequences implement → test → example → docs, so
the framework couples the group and then reviews it uncoupled.

Same-type coupling is also common: **53 of 73 runs (73%)** contain ≥2 tasks
of the same agent type whose `Files:` lists intersect (e.g. `momfit-rule` tasks
02, 13, 14 all edit `gsAlgoimMomentFittingRule.h`), and 57 of 73 share a build
target — so within-type batching has real material, and the `Files`
disjointness rule (`skills/implement/SKILL.md:51`) is already honoured only
between parallel tasks.

Independently corroborated: `feedback_batch_task_reviews.md` (2026-08-26)
already recorded *"only a reviewer holding both can catch a test that passes
vacuously or by the opposite mechanism — **the recurring failure mode in this
tree**"*.

### F6 — Most blocked tasks are unsatisfiable specs, not failed implementations

Of 13 blocker passages, **8 are "task spec wrong or impossible"**; 2 are
dependencies on an already-blocked task; 1 environment; 2 genuine code defects.

The quoted blockers are architecture-level scope problems (*"all three are
architecture-level changes … explicitly out of scope per the task's own
guidance"*) and untested empirical premises. These are **plan** defects the
spec-writer faithfully transcribed — it already reports grounding gaps and has no
mandate to judge whether a premise is achievable.

### F7 — Project-scoped memory does not reach the sessions that need it

**135 of 210** memory documents live in one project directory
(`gismo-worktrees`); 53 are `type: feedback`, i.e. general rules. A session in any
other project — including `gsAgents` — loads none of them. F1 is the proof: the
rule existed, was correct, and still recurred.

---

## 3. The plan

### Applied already

1. **`TASK_CONTRACT.md` §Dispatch rule** now separates declared-tier `gismo:*`
   agents (never override) from generic types that inherit the caller's model
   (must be given `haiku`/`sonnet` explicitly), and notes that not dispatching at
   all is cheaper than either. *Fixes F1.*
2. **`TASK_CONTRACT.md` §Reviewer protocol** checklist reordered by measured
   frequency: report-vs-artifact accuracy first, conventions last and explicitly
   labelled rare (2 of 72). *Fixes F2.*

Applied after the adversarial re-check (§6), all independent of batching:

- **A1. Reviewer reads dependency diffs.** `TASK_CONTRACT.md` reviewer step 1:
  for a task that depends on an earlier one (the complement of
  `Parallelizable-with`), read that task's report and diff too, and attack
  "does the test exercise the case the dependency implemented?". This delivers
  the F5 property — one reviewer holds both the test and the code — without
  any artifact restructuring. *Addresses F5 directly; batching must beat this.*
- **A2. Hook enforcement of the dispatch rule.** `scripts/guard-agent-model.py`
  now denies `Agent` calls whose `subagent_type` is generic (`Explore`, `Plan`,
  `general-purpose`, `fork`, or absent) and carry no `model`. F1 had already
  recurred past a correct memory and a correct contract line; prose was not the
  fixing mechanism. *Closes F1 and the F7 route by which it recurred.*
- **A3. `Feasible:` line from the spec-writer** (`agents/spec-writer.md`), read
  by the orchestrator alongside `Gaps:` (`skills/implement/SKILL.md` §1S). The
  spec-writer is opus and already reads the sources; it is the cheapest seat
  for the satisfiability judgment. *Addresses F6; replaces proposed item 8.*
- **A4. Reviews append, never overwrite.** `TASK_CONTRACT.md` reviewer step 3
  and `agents/task-reviewer.md`: repair rounds add a `## Round N` section, line
  1 is rewritten to the latest verdict so `agents/task-lead.md:20` still works.
  *Makes F4 measurable next time.*
- **A5. Dispatch log.** `task-lead` and quick mode append one line per dispatch
  to `.claude/plans/<slug>/dispatches.log`. *Instrumentation for §5 step 3.*

### Proposed — the batching change

The organising idea, and the part most worth attacking:

> **Batch = the unit of review** (one lead, one review file, one verdict).
> **Task = the unit of dispatch** (one agent type, one context).

Today these are accidentally 1:1. Decoupling them is the change. Two axes, which
compose:

- **Within-type** (items → one task file): items sharing agent type, build
  target, test command **and source files**. Collapses spec-writer, advisor,
  implementer, reviewer and build to one each. *A cost change.*
- **Cross-type** (tasks → one batch): the coupled implement → test → example →
  doc chain. Collapses only the reviewer. *A rigor change that pays for itself.*

**3. Sizing rule** (`skills/plan/SKILL.md` §2). Replace "one coherent change an
agent can hold in its head" with **the unit of a task is the unit of
verification** — a floor (do not split below one build + one test command)
paired with a ceiling (what one sonnet implementer holds; what one opus reviewer
can attack in one pass). Without the ceiling the rule merges a whole run.
*Addresses F3.*

**4. File naming.** Number = batch (unit of review), letter = member (unit of
dispatch): `01a-assembler.md`, `01b-tests.md`, `01c-docs.md`, one `01-review.md`.
A single-member batch stays `01-<name>.md` exactly as today, so quick mode and
existing runs are untouched.

**5. Agents: zero new types, one rename.**
- `task-lead` → **`batch-lead`** (stays sonnet). Dispatches members in order,
  then one reviewer over the group. Returns a per-member verdict line.
- `task-reviewer` gains a **third mode**: full depth over a batch's combined
  diff, fixes tagged by member. **Its input contract genuinely changes** — today
  it takes one task-file path and locates the report itself; given `01b-…md` it
  cannot infer it should review `01a`+`01b`+`01c`. The lead must pass the batch
  id or member list. This is where an implementation would break silently.
- Everything else unchanged.

**6. Contract edits.**
- `## Goal` may carry an enumerated item list; `## Acceptance criteria` grouped
  per item (feeds the existing criteria-mirroring rule).
- `Review:` stays per-member; batch effective level is **max-wins**. Consequence
  to decide deliberately: the end-of-run deferred-batch path becomes close to
  vestigial.
- Fixes tagged to `none`/`light` members land in `Notes:` unless they are
  correctness defects — otherwise doxygen nits can consume a batch's shared
  repair budget and starve a real defect.
- `Parallelizable-with` moves to batch level. Members inside a batch are
  sequential, which satisfies the concurrent-build rule for free.
- Relax `Files` disjointness (`skills/implement/SKILL.md:51`) to "no overlap
  between units that run **in parallel**" — a doc-writer editing doxygen inside
  `gsFooAssembler.h` legitimately overlaps the implementer's file.
- Round cap **per batch, not per member**. When it runs out with fixes
  outstanding: `CYCLE: FAIL`, orchestrator intervenes under the existing
  exception. This makes intervention somewhat more likely.
- Report/review naming ripples: the implementer writes `01a-report.md` while the
  review is one `01-review.md` with per-member verdicts, so `agents/task-lead.md:20`
  ("read line 1 of the freshly written `NN-review.md`") no longer decides a
  member's fate.
- Quick-mode rubric restated in batch terms (≤ 1 batch), leaning on the safety
  clauses, since "≤ 2 tasks" and "≤ 5 files" stop discriminating.

**7. Advisor placement.** The mandatory completion check fires per `Review: full`
**dispatch**, so a three-member batch fires three opus checks feeding one opus
group review. Since the batch review is now the real gate, fire the mandatory
check on the batch's **terminal member**, advisory for the others. Roughly a
third of the remaining opus bill. *Addresses F3.*

**8. ~~Decomposition satisfiability check~~** — superseded by A3.

**9. Todo-list shaping.** Batch = one native task, members = sub-tasks; collapse
preflight / ledger / spec-writer waves into one "run setup" item. Open question:
whether sub-tasks render nested or flat in the user's UI — if flat, entries move
from parent to child level and the wall is unchanged.

**10. Cross-project memory promotion.** *Not a skill change, and explicitly the
user's call which docs qualify.* *Addresses F7.*

---

## 4. What this plan does **not** claim

- **The 3.7% FAIL rate does not tell us whether implementers are good or the
  reviewer is lenient.** Nothing in the corpus separates these, and the batching
  case does not depend on which it is.
- **Batching spends latency to buy tokens.** Three independent fixes that today
  run as three concurrent task-leads would run sequentially inside one
  implementer. Dispatches and opus calls fall; wall-clock per batch rises. This
  is a trade, not a free win.
- **Whether a group review is genuinely one opus call's worth of work** is
  unmeasured. The dispatch count certainly falls; the token count may be ~1.5×
  a single review rather than 1×. Measure on the first real run rather than
  settling it analytically.
- **Automated recurrence does not work yet** beyond near-verbatim repeats, so
  every frequency in §2 rests on a haiku taxonomy over a pre-filtered slice, with
  the one independent regex cross-check noted in F2.

---

## 5. Order

1. F1, F2 and A1–A5 are applied.
2. Run 2–3 real `/gismo:implement` runs with the dispatch log and appending
   reviews in place. Measure: first-pass FAIL rate directly; opus dispatches
   per task; whether A1 alone closes the "test passes vacuously" class.
3. Decide on batching (items 3–7, 9) against those numbers, with §6 C1–C6
   answered in the design first. Item 10 is the user's call at any time.

## 6. Adversarial re-check of this document

Written after §§1–5, by attacking them. Findings that changed the document are
marked; the rest are open design questions batching must answer.

**On the numbers.**
- A1 *(changed F4)*: 3.7% was the residual FAIL rate; first-pass is ~36%.
- A2 *(changed F5, refuted)*: within-type file overlap was unmeasured; measured
  at 73% of runs, so within-type batching is not vacuous.
- A3: "roughly a third of the opus bill" for item 7 is not supported by the
  arithmetic. A 3-member cross-type batch today is 3 spec + 3 advisor + 3 review
  = 9 opus calls; proposed is 3 + 1 + 1 = 5, and the advisor is 2 of the 4 saved
  (~22%), only if the group review is genuinely 1× a single review.
- A4: F6 rests on n = 13.
- A5 *(fixed)*: a line reference pointed past the end of the file.
- The doc's §1 "34 multi-verdict files" was a raw count; the verdict totals
  were post-dedup. Now stated.

**Cheaper alternatives that had not been considered** — now applied as A1–A3.

**Where the batching design will break** (open):
- C1. Intra-batch repair cascades: repairing member *a* invalidates *b* and *c*
  that built on it. Either the repair round re-verifies the whole batch or
  downstream members go stale silently. Decide and write it down.
- C2. The sizing ceiling "what one sonnet implementer holds" is the phrase it
  replaces. Give the orchestrator a proxy it can apply: one build target, ≤ N
  files, ≤ N acceptance criteria.
- C3. Quick mode's "≤ 2 tasks" is a context bound on the orchestrator
  (`skills/implement/SKILL.md:36`), not only a risk bound. "≤ 1 batch" with five
  members loses it; keep a member cap.
- C4. Terminal-member-only completion check (item 7) removes the check from
  exactly where F2 says it earns its keep — report honesty. Cut design consults
  before completion checks.
- C5. The reviewer's changed input contract is a silent-failure point: require
  a `MEMBERS:` line in the batch review and have the lead refuse a review that
  lists fewer members than dispatched.
- C6. Latency: today's parallel task-leads become sequential members. For a run
  with three independent groups this can roughly triple wall-clock. Say so to
  the user before the first batched run.
