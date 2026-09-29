# G+Smo task contract (shared by orchestrator, spec-writers, task-leads, implementers, reviewer)

Every feature run lives in `.claude/plans/<slug>/` (gitignored):

```
.claude/plans/<slug>/
├── plan.md            # the approved plan (context, approach, file inventory, verification)
├── context.md         # shared fact ledger — facts several tasks need (standard mode)
├── rules.md           # standing rules — each factual sentence with its verifying command (written by the planner)
├── tasks/
│   ├── 01-<name>.md   # task spec (orchestrator decomposes, gismo:spec-writer writes)
│   ├── 01-report.md   # implementation report (written by the implementer agent)
│   ├── 01-review.md   # review verdict (written by gismo:task-reviewer)
│   ├── logs/          # NNN-<slug>.log — verbatim command logs (written by run_logged.sh)
│   └── ...
├── dispatches.log     # one line per implementer pass, per review and per verdict (see the protocols below)
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
  `summary.md`. A `light`/`none` task is not skipped: final verification runs the
  same one-reviewer batch review over the deferred tasks as standard mode. Every
  other rule in this contract — the file formats, the implementer protocol, the
  dispatch rule, build safety — applies to both modes.

## Task spec format (`NN-<name>.md`)

```markdown
# Task NN: <one-line goal>
Agent: gismo:implementer | gismo:test-writer | gismo:example-writer | gismo:doc-writer
Build target: <make target to build, or "none">
Test command: bash ${CLAUDE_PLUGIN_ROOT}/skills/run-tests/scripts/run_unittests.sh <prefix>   (or "none")
Review: full | measurement | light | none
Standing rules: rules.md @ md5 <md5 of rules.md when the spec-writer verified it>   (or "none")
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

## Standing rules check
- <rule sentence from rules.md> — `<its verifying command>` → <log path and line range of the run>

## Acceptance criteria
- [ ] Checkable statements only (compiles, test X passes, output Y appears...)
```

Standing rules are never copied into a spec. The `Standing rules:` line names
`rules.md` and the md5 it had when the spec-writer verified it; `## Standing
rules check` lists every factual sentence of `rules.md` the task relies on with
the log of the run that confirmed it. During `/gismo:implement` the orchestrator
owns `rules.md`: before each task-lead or implementer dispatch it compares the
spec's md5 with the current one, and if they differ the spec's record is stale
and the orchestrator re-runs that spec's rules check before dispatching. A rule a
spec-writer reports as refuted under `Gaps:` is recorded by the orchestrator as a
dated `Update YYYY-MM-DD (reason): …` paragraph in `rules.md`, and the user is told.

A premise or a status stated in a spec is never rewritten. A correction is a
dated paragraph under the original — `Update YYYY-MM-DD (reason): …` — and the
original text stays, so the record of what was believed survives the correction.
A status table may gain rows and columns; no cell is overwritten without a dated
note. This covers statements of what is true or done (the premises in `Context`,
any status); the instruction lines — `Review:`, `Files`, the acceptance
criteria — are what the task is told to do, and a correction to them is made in
place.

Write `## Acceptance criteria` as real, independently checkable items, not one
criterion artificially split into several. They live in the task file only; the
native task list carries one entry per task, never one per criterion.

The `Review:` level is the orchestrator's cost/robustness dial, fixed at
decomposition time:

- `full` — the whole adversarial cycle, in-cycle, per task. Default for
  library code, numerics, driver code, and anything a later task builds on.
- `measurement` — in-cycle, per task, for a task whose deliverable is a data
  file plus an analysis script. Its real work is re-deriving the headline
  numbers and checking the report's fences; no attack applies to a CSV and a
  script, so there is no attack phase. The reviewer's procedure is under
  **Reviewer protocol** below. `full` stays the level for `src/` and driver
  code.
- `light` / `none` — **review is deferred, not skipped.** The task-lead
  accepts a `RESULT: DONE` report with a non-empty evidence section whose cited
  logs all end `STATUS: OK` and returns `CYCLE: PASS (review deferred)`
  (missing evidence earns one evidence pass, see the implementer protocol,
  step 8 — not a repair round; a failing or still-missing verification goes
  the evidence route, see the task-lead protocol); the
  orchestrator collects all deferred tasks and dispatches ONE
  `gismo:task-reviewer` in **batch mode** at the end of the run (before final
  conformance), in quick mode as well as standard. A task that returned
  `PASS (review deferred)` stays `in_progress` in the native task list until the
  batch review passes it or its fix-up pass is applied. In the batch, `light`
  tasks get a diff-vs-spec read, `none` tasks an evidence sanity check.
  `light` fits low-risk, well-isolated changes; `none` doc-only tasks.
  Neither is ever for code that a test or another task builds on — that is
  what makes end-of-run batching safe.
- A task that FAILs its batch review has outlived its low-risk label: the
  orchestrator escalates the spec's `Review:` line to `full` and re-runs
  `gismo:task-lead` (giving the review-file path as context in the prompt) —
  never another deferred pass. A failed evidence pass takes the same route,
  citing the failing log path or `no evidence` in place of a review file.

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
   may read it; implementers may not. Then read `rules.md` (the plan's standing
   rules, beside `plan.md`) and **re-run the verifying command of every factual
   sentence your task relies on**, through `run_logged.sh` so each run has a
   log (a command of the form `bash -c '…'` is passed verbatim after the slug). Record the results in the spec's `## Standing rules check` and put
   `rules.md`'s md5 on the `Standing rules:` line. A sentence whose command no
   longer confirms it is not carried into the spec: report it under `Gaps:`
   and leave `rules.md` to the orchestrator, which owns it during a run. Never copy standing rules out of a sibling
   spec — a rule is only as current as the last run of its command.
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
5. Write `NN-<name>.md` in the format above — when it already exists, correct a
   premise or status by an appended `Update YYYY-MM-DD (reason): …` paragraph,
   never by rewriting the line — and return
   `SPEC: WRITTEN | BLOCKED` plus a `Gaps:` list and a `New facts:` list
   (facts worth sharing, with `file:line`; `none` if there are none).

The spec-writer's Bash is for re-running a rule's verifying command and nothing
else: it never builds, runs the code under change, or configures.

## Verdict vocabulary (reviewer → task-lead)

Line 1 of `NN-review.md` carries exactly one of three strings, and whoever
reads it matches them **exactly, most specific first** — a substring test for
`PASS` silently swallows the middle one:

- `VERDICT: PASS` — nothing left to do.
- `VERDICT: PASS (fix-ups)` — the artifact is right and the text *about* it is
  wrong. Every blocking finding of this round is textual: a report claim the
  diff does not support, a stale or narrating comment, doxygen wording that
  overstates what the code does. Code, tests and scope are sound. It is
  repaired by one text edit and **no second review**.
- `VERDICT: FAIL` — a defect in the artifact, or in the integrity of the
  evidence. Costs a repair round.

`PASS (fix-ups)` exists because a prose defect would otherwise cost exactly what
a numerical bug costs: a fresh implementer round plus a fresh opus review. It
decides **routing only.** Check 1 of the reviewer's list (does the report
describe what the diff really does) keeps its primacy, stays mandatory, and
still blocks the cycle from ending silently on an inaccurate report. The verdict
determines who applies the correction and whether the reviewer runs again.

Three tests separate the classes, and a fix-up needs all three:

1. **Deletion test** — if the offending text were simply deleted, would the
   task still be done? A report sentence or a narrating comment: yes. A missing
   guard or a wrong tolerance: no.
2. **Executable-code test** — can the correction be applied without touching a
   line the compiler reads? If it needs code, it is a `FAIL`.
3. **Deliverable test** — is text the *deliverable* here? On an
   `Agent: gismo:doc-writer` task, on any acceptance criterion whose subject is
   documentation, or in a doxygen block stating the contract of a public API
   (that block is the specification callers read, not commentary), wrong text
   is the defect itself: `FAIL`. Otherwise doc work becomes unfailable.

Two adjacencies decide many cases and must not be blurred. *"The report
describes the change inaccurately"* is a fix-up. *"The report quotes output no
tool produced"* is fabricated evidence and stays a `FAIL` on its own, because
what is wrong there is not the wording — it is that nothing backs it, and the
rest of the report's quotes need checking too. And on evidence proper:

- a fence that **differs from an existing log** (a retyped line, a dropped
  header, re-sorted output, `kappa` for `κ`, a shortened path, a command other
  than the one logged), over an artifact the reviewer finds sound, is
  `PASS (fix-ups)` — the fix is to replace the fence with the log's own lines;
- a fence presented as **command or tool output** with **no backing log** — no
  log path, or a path that does not exist, or no line range in it that contains
  the text — is `FAIL`: nothing produced it. The rule covers fences shown as
  output only. An excerpt of a file in the diff or a quotation of the spec is
  checked against that file; a scout's answer is cited as a scout answer; in a
  measurement report, data rows and tables are checked against the CSV. None of
  these needs a log. An advisor verdict line, which no logged command produces,
  is checked as the implementer protocol describes (step 5).

A `PASS (fix-ups)` review must be **self-applying and truth-bearing**: under a
`## Required fix-ups` heading, each numbered item names `file:line` and gives
the replacement text (or "delete these lines"), and states the true fact
plainly enough that the review file alone is correct about the change even if
the fix-up were never applied. That is what makes skipping the re-review safe —
downstream readers (task-lead, orchestrator, `summary.md`) read the review, not
only the report.

## Task-lead protocol (gismo:task-lead)

One task-lead per task, dispatched by the orchestrator with the task-file path
and, when the orchestrator mirrored the task into the run's native task list,
that task's native task ID. The task-lead holds no Task tools: it forwards the ID
and never changes a native task's status.
It runs the closed loop as nested subagents (Claude Code >= 2.1.172):

1. Read the task file's `Agent:` and `Review:` lines — nothing else. No
   plan.md, no source, no context files: the implementer reads them itself.
2. Dispatch that agent with the task-file path, plus the native task ID if you
   were given one — forward it verbatim rather than searching for a match
   yourself — and the optional review-file path the orchestrator passed after a
   batch `FAIL`, or the marker `evidence failure: <log path | no evidence>` after
   a failed evidence pass, which the first dispatch carries so the numbered
   fixes (or the failing log) are addressed. Every dispatch and every
   `SendMessage` to an implementer or the reviewer states the round explicitly
   as `round: N` (0 for the first pass, N for repair round N; fix-up and
   evidence passes carry the round of the cycle they belong to); the receiver
   logs exactly that round. A first dispatch that carries a batch review's
   `FAIL` or an evidence-failure marker is `round: 1`: the pre-batch report has
   no `## Round` section, so the first pass of the fresh cycle is logged as
   `repair` at round 1, writes `## Round 1`, and counts as repair round 1 of the
   cap. On its return, dispatch `gismo:task-reviewer` with the same path and the
   round just implemented — `Review: full` or `measurement` only. On
   `light`/`none`, skip the reviewer (the orchestrator batch-reviews these at
   the end): a `RESULT: DONE` report with a non-empty evidence section whose
   every cited verification log ends `STATUS: OK` (`tail -n1` of each) is
   `CYCLE: PASS (review deferred)` at round 0. An empty or missing evidence
   section is a defect in the report, not in the artifact. It earns one
   **evidence pass** (implementer protocol, step 8): tell the agent
   (`SendMessage`, or a fresh dispatch of the same type if it is gone) to "run
   the task's verification through run_logged.sh and cite the logs; change no
   code". No reviewer follows it and no repair round is spent. Afterwards the
   same test applies. `RESULT: BLOCKED` (the verification cannot run) is
   `CYCLE: BLOCKED`. Every other outcome is an **evidence failure**: a cited
   verification log whose last line is not `STATUS: OK` (the verification ran
   and failed — an artifact defect), or a pass that still yields no evidence.
   The task-lead cannot write files, so it returns `CYCLE: FAIL (evidence)`
   naming the failing log or `no evidence`, and the orchestrator applies the
   batch-`FAIL` route: it edits the task's `Review:` line to `full` and
   dispatches a fresh task-lead carrying `evidence failure: <log path | no
   evidence>` in place of a review file; the first implementer pass is repair
   round 1, logged `repair` at `round: 1`, and a per-task review follows as in
   any `full` cycle.
3. `VERDICT: FAIL` → put the implementer back on the task with task-file +
   review-file paths — `SendMessage` to the agent it already spawned, whose
   context is warm (it already has the native task ID from round 0, no need
   to repeat it), or a fresh dispatch when that agent is gone (repeat the
   native task ID, same as round 0) — then re-review. Maximum **2 repair
   rounds**, then stop. A nudge to a still-running agent is not a repair
   round; a message carrying review fixes is.
   `VERDICT: PASS (fix-ups)` → **no re-review, no repair round.** Send the
   review's `## Required fix-ups` list to the agent you already spawned
   (`SendMessage`, or a fresh dispatch of the same agent type if it is gone)
   with the standing constraint: apply the listed corrections exactly, change
   no executable code, update the report, and if a correction cannot be applied
   without touching code, stop and say so instead of doing it. On its
   `FIXUPS: APPLIED` the cycle ends `CYCLE: PASS (fix-ups applied)` — the
   reviewer does not run again. A refusal means the reviewer misclassified the
   finding: convert it into the normal FAIL route above, reviewer included,
   counted against the cap.
4. `RESULT: BLOCKED` or a reviewer-confirmed spec defect ends the cycle at
   once — repair rounds cannot fix a broken spec.

   **A pass is finished only if the agent's returned final message ends with
   its completion line** — the text the `Agent` tool or a `SendMessage` reply
   hands back, not a file on disk: `RESULT: DONE` / `RESULT: BLOCKED` for an
   implementer or writer pass, `FIXUPS: APPLIED` / `FIXUPS: BLOCKED` for a
   fix-up pass, `VERDICT: …` for the reviewer. A stale file cannot fake a fresh
   return. `NN-report.md`, `NN-review.md` and `dispatches.log` remain the
   record: read them for content once the return confirms the pass finished.
   A return without the line is a partial return: one free re-nudge, then
   `CYCLE: BLOCKED` with the reason `no result after re-nudge`.
5. Return `CYCLE: PASS | PASS (fix-ups applied) | PASS (review deferred) | FAIL | FAIL (evidence) | BLOCKED`
   plus rounds used, the outstanding fixes (FAIL) or the blocker (BLOCKED). A
   `BLOCKED` caused by an agent that returned twice without its completion line
   states the reason `no result after re-nudge`, distinct from a spec defect.
   The task-lead edits no files and its
   Bash is read-only inspection (`git diff`, reading a report) — never a build
   or a test run; spec repair and escalation belong to the orchestrator. Its
   `SendMessage` reaches only the two agents that cycle spawned itself, never
   the orchestrator or a sibling lead.

## Implementer protocol (all implementer agents)

1. If your dispatch included a native task ID, mark it `in_progress`
   (`TaskUpdate`) before doing anything else. Never mark it `completed`:
   completed means reviewed, and the orchestrator marks it when the cycle
   passes. No ID means no matching native task; skip this silently rather than
   searching for one. If `TaskUpdate` is missing or errors, note it in the
   report and continue — a tracking failure is never `RESULT: BLOCKED`. Then log your own dispatch:
   append `<UTC ISO timestamp, date -u +%FT%TZ>\t<task-file basename>\t<your agent name>\t<round>\t<kind>`
   (tab-separated; the round is the `round: N` your dispatcher passed — `0` for
   the first pass, `N` for repair round N; if none was passed, log `?` and
   continue — a missing round degrades the log and never blocks; kind `impl` for the first pass, `repair` when the
   prompt carries a `FAIL` review for round N, `fixup` when it carries a
   `PASS (fix-ups)` review, `evidence` for an evidence-completion pass (a prompt that carries a batch review's `FAIL`, from before the cycle began, is logged as `repair` at round 1, and its report section is `## Round 1`) — fix-up
   and evidence passes keep the round of the cycle they belong to and are not
   repair rounds) to `dispatches.log` beside your task file's
   `tasks/` directory (`.claude/plans/<slug>/dispatches.log`). Your dispatcher
   cannot write files; this log is the only record of how many implementer
   and reviewer passes a run spent (scouts, advisor consults and spec-writers
   are not logged). Lines written before the `kind` column existed have four
   fields; treat a missing fifth field as unknown. Write the line again each
   time a message brings you back in (a `repair`, `fixup` or `evidence` line
   for that round): a warm agent that receives fixes by `SendMessage` is not
   re-dispatched, so nothing else records the pass. The reviewer's `verdict`
   lines (see the reviewer protocol) carry a sixth field, the verdict string;
   a reader that only knows five fields ignores it.
2. Read YOUR task file only, plus the context it points to. Never read plan.md.
   For small factual gaps (a location, a signature, a convention) spawn
   `gismo:scout` (haiku) — one question per scout, so several facts mean
   several scouts dispatched in the same message, never several questions in
   one call — and `gismo:indexer` (sonnet) only when the answer needs
   multi-step exploration. Never any other agent type.
3. Implement within the listed files. If the spec turns out to be impossible or
   wrong, STOP and write the blocker into your report — do not improvise scope.
   **Advice comes from exactly one source, chosen by config — never two.**
   `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` prints
   `GISMO_ADVISOR` (you already run this via the build scripts):
   - `GISMO_ADVISOR=native` — Claude Code's own advisor is configured and
     subagents inherit it, so it is already advising you. **Do not consult
     `gismo:advisor`**; note `Advisor: native` in your report and move on.
     The native advisor returns prose, not a verdict line: it has no
     `ADVICE:` string, so your report must never contain one on a native run.
   - `GISMO_ADVISOR=agent` (the default) — no native advisor is configured.
     Consult `gismo:advisor` (opus) at the trigger points below.

   The value is detected from the harness, not declared by you — never override
   it or reason about which advisor "should" apply. Run the script and obey it.

   Three trigger points — the first two fire on need, the third on risk:
   a. **Open decision.** Whenever you are about to commit to a numerical or API
      approach the spec left open — before you write the code, not after.
   b. **Stuck loop.** After two failed build or test cycles against the *same*
      error, consult before attempting a third. A third identical attempt is
      rarely the one that works, and this is the cheapest moment to be told you
      are attacking the wrong layer.
   c. **Completion check**, before writing your report: **mandatory on
      `Review: full` tasks**, optional on `measurement` and on `light`/`none` —
      `measurement` is re-derived by the reviewer from the retained data, and
      `light`/`none` carry little enough risk that the deferred batch review is
      proportionate; an opus consult to bless such a change is not.
   Pass the task-file path, the decision, and the options you are weighing; it
   reads the spec and your diff itself. At most **2 consults per task** — it is
   the most expensive agent you can reach, so if several triggers fire, spend
   them on the earliest ones: advice before the code is written is worth more
   than advice after.
   Act on its verdict line: `ADVICE: PROCEED` → follow the recommendation;
   `ADVICE: SPEC DECIDES` → you misread the spec, follow the spec;
   `ADVICE: BLOCKED` → report `RESULT: BLOCKED` relaying its reasoning. Copy
   every consult's verdict line into your report **verbatim** — it is one of
   those three exact strings and nothing else, pasted from the consult you
   actually made, never reconstructed from memory or composed to summarise
   advice. A verdict line in a report is evidence that a consult happened; an
   invented one is fabricated evidence, and the reviewer treats it as such.
   Never settle an open judgment call by guessing.
4. Verify, in order:
   a. `bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <every touched file>`
   b. `bash ${CLAUDE_PLUGIN_ROOT}/skills/build-target/scripts/build_target.sh <build target>`
   c. the task's test command

   Run every command whose output the report will cite through
   `bash ${CLAUDE_PLUGIN_ROOT}/skills/evidence-log/scripts/run_logged.sh <task-dir> <slug> <command…>`
   (skill `gismo:evidence-log`; `<task-dir>` is the `tasks/` directory beside your
   task file, `<slug>` starts with your task number). It keeps
   `<task-dir>/logs/NNN-<slug>.log` and prints its path, md5 and a `STATUS:` line; the same
   `STATUS:` line is the last line of the log, after `# exit: N`, so it is
   citable like any other line.
   For a code change, evidence is a real run that exercises the change, and
   only that: a syntax-only check or a command that failed to start is not
   evidence — fix the invocation and run it again. The exception is a task
   that changes no executable code: for comment-only and doc-only edits to
   source files the evidence is a logged `syntax_check.sh`, and for
   markdown-only tasks a logged link or render check (a `grep`/`ls` of the
   referenced paths and anchors, or the repo's markdown checker if it has one).
   Either is cited by log reference like any other output.
5. Write `NN-report.md` — **this is where the reasoning goes, not the source**
   (see comment discipline below): files changed, what was done, verification evidence
   (the STATUS lines, cited as the last line of their logs, + relevant output tails), and any deviation from the spec
   with its reason. Optionally end with a `Suggestions (not done):` section listing extras you judged useful but left undone because they fall outside the task's scope; the reviewer does not treat these as defects, and they are not a licence to do them. Every claim must be auditable against a tool result from
   this run — only report work you can point to evidence for; if something is
   unverified or failing, say so plainly instead of hedging. **Evidence is
   cited by reference, never transcribed:** cite output as
   `logs/NNN-<slug>.log:L1-L2 (md5 <hash>)`. Where the report shows the lines,
   read the log with the Read tool — its line numbers equal the log's own — and
   paste lines L1-L2 exactly, without the line-number prefix: nothing retyped,
   re-sorted, shortened or normalised. The reviewer diffs the fence against that
   range of the log, whose md5 is the one cited. An advisor verdict line, which
   no logged command produces, is copied character-for-character from the
   consult's reply. Paraphrase freely in your own prose, but never dress a
   summary up as a quotation: a plausible-looking quote that no tool produced
   is worse than no quote, because it survives review that real evidence would
   not.
   Do not write `RESULT: DONE` while an acceptance criterion is unmet. End the
   file with `RESULT: DONE` or `RESULT: BLOCKED`. Later passes never rewrite
   what is already written: each appends a section headed `## Round N` (N is the
   round of the cycle it belongs to; a fix-up or evidence pass adds the suffix
   `(fix-ups)` or `(evidence)`) and ends that section with its own completion
   line — `RESULT: …` for a repair or evidence pass, `FIXUPS: …` for a fix-up
   pass. Whatever the pass, the final message you return ends with the same
   completion line the file ends with, mirroring it exactly (`RESULT: DONE`,
   `RESULT: BLOCKED`, `FIXUPS: APPLIED` or `FIXUPS: BLOCKED`); your dispatcher
   judges the pass finished only by that line at the end of your returned
   message. `## Round N` headings and `round: N` are record-keeping only.
   Leave the outer native task
   (step 1) `in_progress` either way; the orchestrator marks it `completed`
   once the cycle has passed and the work has been reviewed, and a repair round
   re-dispatches against the same ID.
6. You operate autonomously: nobody answers questions mid-task. Never end your
   turn on a question, a plan, or a promise ("I'll now build...") — end only
   after the report file is written (`RESULT: BLOCKED` is a report, not a
   question).

7. **Fix-up round.** You may be sent back with a review's
   `## Required fix-ups` list instead of required fixes. That review passed
   your artifact and is correcting only the text about it, so this round is
   deliberately cheap: apply each listed correction exactly as written, **touch
   no line the compiler reads**, re-run `syntax_check.sh` on any source file
   you edited (a mangled comment delimiter is the one way a text edit breaks a
   build — no rebuild, no test re-run beyond that), make the report say what
   the artifact actually does, and end your turn with `FIXUPS: APPLIED`. A fence
   the review flags is replaced by the log's own lines, read with the Read tool
   (its line numbers equal the log's) and pasted exactly — the verification
   itself is not re-run. If one
   of the corrections cannot be made without changing code, apply the others
   and end with `FIXUPS: BLOCKED: <which one, and what code change it needs>` —
   that routes the task back through a normal repair round, which is where a
   code change belongs. Never widen a fix-up round into "while I was in
   there" work. Write the completion line as the last line of the report's
   `## Round N (fix-ups)` section and as the last line of your returned final
   message.

8. **Evidence pass.** You may be sent back with the message "run the task's
   verification through run_logged.sh and cite the logs; change no code",
   because a `light`/`none` report came back without an evidence section. Log
   the dispatch with kind `evidence`. You may re-run the task's verification
   through `run_logged.sh` and cite the logs; you must not change code. Append a
   `## Round N (evidence)` section that cites the logs and end it with an updated
   `RESULT: DONE` — or `RESULT: BLOCKED` if the verification cannot run, which
   ends the cycle `CYCLE: BLOCKED`. A verification that runs and fails is a
   defect in the artifact, not a blocker: end `RESULT: DONE` citing the failing
   log (its last line `STATUS: FAIL`), and the cycle takes the evidence route
   (`CYCLE: FAIL (evidence)`). The pass costs no repair round. End your
   returned final message with that same completion line.

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
depth — or the measurement procedure below when the task's `Review:` line says
`measurement`) and batch (dispatched by the orchestrator with the run's deferred
`light`/`none` tasks; depth scaled per task's level, one `NN-review.md`
each, plus cross-task consistency notes). Both follow:

1. Log your own dispatch as the implementer does: append
   `<UTC ISO timestamp, date -u +%FT%TZ>\t<task-file basename>\tgismo:task-reviewer\t<round>\treview` to
   `.claude/plans/<slug>/dispatches.log` (one line per task when dispatched in
   batch mode). The round is the `round: N` your dispatcher passed; if none was
   given, it is the number of the `## Round N` section you are about to write
   (0 for a first review). A batch review logs its `review` and `verdict` lines
   with the round `batch`. Once the verdict is written (step 3), append a second line of
   the same shape with kind `verdict` and the verdict string as a sixth field —
   `…\tgismo:task-reviewer\t<round>\tverdict\tPASS (fix-ups)` — so the
   time between the two lines is the review's cost. Then read the task spec, the report, and
   `git diff -- <listed files>` (plus
   `git status --short` to catch out-of-scope edits). When the spec's
   `Parallelizable-with:` line implies a dependency (an earlier task it is
   *not* listed as parallel with), also read that task's report and
   `git diff` over its own `## Files` list — a test that passes vacuously or
   by the opposite mechanism from what it claims is only visible to a
   reviewer holding both the test and the code it tests.
2. Audit the report's evidence (genuine STATUS lines, output consistent with
   the diff); re-run the test command **only** when that evidence is missing,
   inconsistent, or stale — not as a routine step. **Diff every fence against
   its log**: for each `logs/NNN-<slug>.log:L1-L2` citation, check that the log
   exists, that its md5 is the one cited, and `diff` the fence in the report
   against lines L1-L2 of the log. A fence that differs from an existing
   log is a report defect — `PASS (fix-ups)` when the artifact is sound, the
   required fix being the log's own lines. A fence or quote presented as command or
   tool output with no backing log at all is fabricated evidence; excerpts of a
   diff file or a spec quote are checked against that file, scout answers are
   cited as scout answers, and in measurement reports data rows and tables are
   checked against the CSV. Other quoted evidence is checkable
   on its face: an advisor verdict line that is not exactly `ADVICE: PROCEED`,
   `ADVICE: SPEC DECIDES` or `ADVICE: BLOCKED`, or any `ADVICE:` line at all in
   a report marked `Advisor: native` (the native advisor emits no verdict
   line), was not produced by any advisor. Fabricated evidence — a quote no log
   or tool result backs — is a `FAIL` on
   its own — the numbered fix is to remove the invented quote and state what
   actually happened — and it means the rest of the report's quotes need
   checking rather than trusting. Spend the effort attacking
   instead: hostile/degenerate inputs against the built binaries, probes of
   numerical hazards seen in the diff, and checks that each new test can
   actually fail; on a task with a dependency (per step 1), does the test
   actually exercise the case the dependency implemented? A successful
   in-scope attack is a FAIL with the exact reproduction command.
3. Write `NN-review.md`: on a repair round the file already exists — never
   overwrite it, append a new `## Round N` section with its own `VERDICT:`
   line below the existing rounds, and rewrite line 1 to that latest verdict
   (task-lead reads only line 1, so it must always be current). The verdict is
   one of the three exact strings in **Verdict vocabulary** above, chosen by
   the three tests there: `PASS`, `PASS (fix-ups)` when every blocking finding
   of this round is textual over a sound artifact, `FAIL` otherwise. For FAIL a
   numbered list under `## Required fixes`, for `PASS (fix-ups)` the
   self-applying list under `## Required fix-ups` — each item concrete enough
   to act on without re-investigation — and either way a `Notes:` section for
   non-blocking findings: report everything found, at every severity; only
   blocking findings decide the verdict. Mixed rounds are `FAIL`: when one
   finding needs code, the implementer is going back in anyway, so carry the
   textual ones in the same numbered list. Your returned final message ends
   with the same `VERDICT: …` line that heads the review file (in batch mode, a closing
   list with one `<task-file basename>: VERDICT: …` line per task); your
   dispatcher judges the review finished only by that line.
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
      the artifact, including quoted numbers and line references. Blocking, but
      usually blocking *cheaply*: when the artifact itself is sound, this is
      the `PASS (fix-ups)` class — you still find it, still write it, still
      state the true fact, and the correction is applied without another round
      of you. A quote no tool produced is the exception and stays `FAIL`.
   2. **Acceptance criteria demonstrably met**, and evidence genuine
      (`STATUS: OK` present, output consistent with the diff).
   3. **Correctness**: numerical-stability hazards, unmet criteria, logic
      defects, silent narrowing.
   4. **Documentation claims**: doxygen or note text asserting more than the
      source of truth supports, and stale comments the change invalidated.
      Same routing as check 1 — fix-ups over a sound artifact, except where the
      text *is* the deliverable (doc tasks, documentation acceptance criteria,
      the doxygen contract of a public API), which is a `FAIL`.
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

### Measurement review (`Review: measurement`)

For a task whose deliverable is a data file plus an analysis script, replace
the attack phase (hostile inputs, executed attacks) with:

1. **Re-derive every headline number** from the retained data file, with the
   analysis script or an independent one-liner, reading columns by header name
   and never by position. A number the report states that the data does not
   give is a defect in the artifact or the report — `FAIL` or `PASS (fix-ups)`
   by the three tests above.
2. **Diff every fence against its log** (reviewer step 2).
3. **Check that the pre-registered rule was applied as committed**: thresholds,
   cut-offs and selection rules are read from the committed text the report
   names, never from the spec's paraphrase of it.
4. **No attack phase.** One pass per round; the verdict rules are those of the main protocol.

The ordered checks above still apply — the report must describe what the
artifact does, criteria must be met, scope must hold — with steps 1 and 3
standing in for the attack.

## Build safety (absolute, for every agent)

- Never run bare `make` and never pass `-j` yourself: only
  `build_target.sh <target>` (jobs come from the config, capped at nproc/2).
- Never remove or reconfigure a build directory.
- Reconfiguring (`cd <builddir> && cmake .`) is allowed only after adding a new
  .cpp file, and `build_target.sh` will tell you when it is needed.
