# Design record: `/gismo:review`, one rulebook, one lint gate (0.9.0)

**Date:** 2026-11-11 · **Branch:** `release-0.9.0`
**Status:** implemented; the decisions below were settled with the maintainer before the build and are not open.

This record states why 0.9.0 adds a review skill and what it changes in the existing agents, so that
a later reader can tell which parts are deliberate. The agent and skill files describe the behaviour;
this file is where the history lives.

---

## 1. Evidence

The starting point was a hindsight look at 16 worktrees' `.claude/plans/` directories (the same kind of
corpus `skills/diagnose` mines). Three things stood out:

1. **Text-only defects drive most repair rounds.** Trailing whitespace, a comment narrating the change,
   a missing doxygen block, a wrong file header: findings a script can decide, which cost a full
   opus review and a sonnet repair round each. The `PASS (fix-ups)` verdict of 0.8.0 made them cheaper;
   it did not make them stop occurring.
2. **Style was unchecked.** The task reviewer's mandate is the task spec and correctness; its
   convention check (reviewer protocol, item 7) is last in its order and was never backed by a written
   rulebook, so naming, header structure, example and test consistency were whatever each writer
   remembered of the sibling file.
3. **The same rules were re-typed in every plan.** Each plan's `rules.md` repeated "no `cp`/`mv`",
   "no git writes", "build only through `build_target.sh`", "denied commands are reported", and a spec-writer
   re-verified them per task. A rule that is typed per plan is as current as the last person who typed it.

## 2. Decisions

- `/gismo:review` is a skill with four levels, `light`, `medium`, `large`, `ultra`; the level is the
  budget (see the README for what each runs). The review edits no source: its one touch on the tree is
  the ultra mutation proof, which temporarily reverts a hunk and restores it byte-for-byte, and only
  after the user confirms in that run.
- A report is processed in a separate step, `/gismo:review resolve`. Each finding is triaged when the
  report is written: `mechanical` (a script decided it and no executable token changes), `local` (a
  measured defect with one evident remedy inside the change) or `decision` (everything else). Resolve
  asks the user the decisions first, routes `local` findings and `fix` answers through
  `/gismo:implement`, applies the mechanical batch through `gismo:doc-writer`, and waits for a yes
  before each. The orchestrator may move a finding towards `decision`, never away from it, and a
  reviewer never fixes its own findings. The reason for the split: a report that is only a file is a
  dead end, and a review that fixes as it goes marks its own homework.
- One run writes one dated directory, `.claude/plans/<slug>/review/<timestamp>/`, with `input/`,
  `findings/` (one file per reviewer), `debate/` and `logs/`, so a re-review after the fixes does not
  overwrite the first.
- The rules are written once in `skills/review/CONVENTIONS.md`, each with an ID, a severity and a
  checker (`script`, `style`, `review`). A rule not written there is not a finding. The rules are strict
  and context-free wherever a script can decide them, so two runs give the same answer.
- **Only added or changed lines are ever reported.** Pre-existing violations are not findings. The existing
  tree is brought in line by `tree_cleanup.sh` (whitespace first, then doxygen tags), run by the user in
  one mechanical pass with a proof, so that later reviews and a later clang-format start from a clean
  sheet. clang-format itself waits for a fitted config.
- C++14 is the ceiling for `src/`, `examples/` and `unittests/` (what CI compiles); `optional/` modules are
  not checked for language level.
- Doxygen uses the `@` form; every new public symbol has a block. `GISMO_ENSURE` at construction, setup and
  API entry, `GISMO_ASSERT` for per-element or per-quadrature-point invariants; a corruption guard in a
  hot path is flagged for hoisting, not converted. `std::move` is a finding on G+Smo types only (use
  `give`); `index_t` for loop counters, sizes and anything indexing a matrix, basis or DoF.
- Comment volume is a number in the report, never a finding by itself; findings are for concrete defects
  (repeated rationale, capital-letter emphasis, rationale mixed into a contract).
- Examples: core files are `<topic>_example.cpp`, `main` returns `EXIT_SUCCESS`/`EXIT_FAILURE`, an example
  runs with no arguments in seconds, writes ParaView output only behind `--plot`, and is standalone.
  A `gsStopwatch` per stage is not required.
- Examples and unit tests are commented block by block (`EX-COMMENT`, `UT-COMMENT`): what each `TEST`
  verifies and where its expected values come from, what each block sets up, does or checks. They are
  reviewed by reading — by maintainers, users and agents — so a comment that would be a restatement in
  library code is required here, and `/gismo:tidy` keeps it.
- Tests are inspected by reading at medium and large and proven by mutation at ultra. A test of an
  assertion reads `GISMO_NDEBUG` (exported by `gismo_env.sh`) and uses `CHECK_THROW_IN_DEBUG` for a
  `GISMO_ASSERT`.
- `Author(s):` on a new file is the output of `git config user.name`; blank or copied lines are findings.
- The debate panel is on at ultra and, at large, only with `--debate`; the orchestrator chairs it.
  It takes questions of judgement; a question of fact is settled by running something.
- Every finding carries an evidence label, `MEASURED`, `REASONED` or `UNVERIFIED`; the same three labels
  now head the reports of `gismo:advisor`, `gismo:indexer` and `gismo:debugger`.

## 3. Changes to the existing framework

| Change | Why |
|---|---|
| `skills/implement/STANDING_RULES.md`, referenced from the contract, `plan`, `implement` and `spec-writer` | The rules that hold in every plan live once; `rules.md` keeps only plan-specific, verifiable facts. |
| The four writers point at `CONVENTIONS.md` instead of keeping their own lists, and run `review_lint.sh` after the syntax check | One rulebook cannot drift from itself; a finding fixed before the build costs no review. |
| Lint gate in the task-lead (contract step 2b, implementer step 9, dispatch kind `lint`) | A bounce for a script finding is not a repair round and happens at most once per task; leftover lint output goes to the reviewer so it does not rediscover it. |
| `/gismo:tidy` takes its file list from `review_scope.sh` and its starting comment list from `review_lint.sh` | Nested `optional/` repositories were invisible to a plain `git diff`; the regex finds the obvious cases deterministically and the model keeps the Delete/Keep judgement. |
| `/gismo:implement` ends its report with a one-line suggestion to run `/gismo:review medium` | Per-task reviews cannot see a defect that spans tasks. Suggested, never run automatically. |
| `gismo_env.sh` exports `GISMO_BUILD_TYPE` and `GISMO_NDEBUG` | Whether assertions are live was assumed from the build type; G+Smo's `RelWithDebInfo` carries no `-DNDEBUG`, so the flags decide. |
| `harvest.py` reads `.claude/plans/<slug>/review/<timestamp>/` (`findings/*.md` and `input/lint.tsv`) and ranks recurring RULE-IDs | A rule that keeps being broken is a rule to reword; the same recurrence-over-distinct-runs counting as for task reviews. |
| `guard-agent-model.py`, `audit-agent-models.py`, `audit-models` | No change: both scripts discover agents from the `agents/` directory, so `gismo:style-checker` (sonnet) is covered automatically. |

## 4. Limits

- Lint is a pattern match. `CM-NARR` finds the phrases in its table, not every narrating sentence; the
  Delete/Keep judgement and the style checker remain.
- `GISMO_NDEBUG` is `unknown` when neither `CMakeCache.txt` nor `compile_commands.json` decides it, and
  agents then make no claim that an assertion was exercised.
- `EX-GETVALUES` looks back at most 15 lines of code for `try` instead of tracking scope; a `try` that
  far above is not recognised, and a `catch` on an earlier line ends the search.
- The level costs are qualitative. No per-level token measurement exists yet; a first batch of real
  reviews, mined with `/gismo:diagnose`, is what would justify retuning the levels.
- `skills/diagnose/scripts/test_harvest.py` grew from 41 tests at 0.8.0 (see `DIAGNOSIS-AND-PLAN.md`).

Update 2026-11-12 (review of 0.9.0): section 2 names three triage classes. Commit `071f615` added two, `confirm` and `info`; `skills/review/SKILL.md` section 7 is the current statement.
