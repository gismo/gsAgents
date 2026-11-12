# Design record: `/gismo:design`, the intrusion budget, and `/gismo:pr` (0.10.0)

**Date:** 2026-11-11 · **Branch:** `release-0.10.0` (stacked on `release-0.9.0`)
**Status:** implemented; the decisions below were settled with the maintainer. A third 0.10.0
feature, shared agent memory as checked facts, is agreed but not built and is not covered here.

This record states why 0.10.0 adds a design step before planning and a pull-request step after
review, and what it changes in the existing skills. The agent and skill files describe the
behaviour; this file is where the history lives.

---

## 1. Evidence

1. **Generated features reached further into core than they needed to.** After several iterations
   a feature had changed core classes and their API. No single step was wrong: each plan, and each
   fix plan after a review, wrote its own file inventory, and each could add one core file for a
   locally good reason. Nothing held the sum.
2. **A pull-request description omitted semantic and API changes.** A past review of the
   maintainer's found them missing from a description that was otherwise complete.
3. **Scripts that can report "clean" when they skipped something.** The review of 0.9.0 found this
   pattern repeatedly. The scripts added here were attacked for it specifically (section 4).

## 2. Decisions

- `/gismo:design` is a skill, not an agent: it has to ask the user to choose, and only the main
  session can ask. It runs before `/gismo:plan`.
- Alternatives are placed on a four-rung ladder — module only, an extension point core already has,
  one small general new extension point, modifying core classes — and each is counted, not only
  described: core files, public signatures, new virtuals and the classes that inherit them, callers,
  includes, instantiation files, Python bindings, behaviour that changes for existing code. In the
  design job these are counts from declarations and are labelled so; only the audit measures a diff.
- **The budget is a separate file, `budget.tsv`, and not the plan's file inventory.** The maintainer
  asked why it was not simply part of planning. The answer that settled it: an inventory says what
  one run touches and is rewritten by every plan; the budget is the ceiling for the feature across
  all of them, and it is the one list that does not start afresh. A plan's inventory must fit inside
  it.
- **Only the user widens a budget.** No agent adds an `allow` row. Widening is four edits made
  together (the row, a dated line and a core-changes entry in the design, the md5 in every `Budget:`
  line), defined once in the design skill and referenced by plan, implement and review.
- A violation stops the implement run and asks; in a review it is a `major` finding (`DS-BUDGET`)
  that is always a `decision` and never auto-fixed. It is not a review `blocker`, because a blocker
  ends the review before the rest of the change is read.
- **Outside the budget** means: any existing file modified, deleted or renamed outside the feature's
  `home`, and any new file that is not an example, a unit test or documentation (`examples/`,
  `unittests/`, `doc/`, `docs/`, at the root or in a module). The first version flagged new files
  only under `src/`; an independent review on 2026-11-12 showed that a new `cmake/` script or CI
  workflow then passed the check, and the user chose to narrow the exemption to what the skill
  text already named.
- An `allow` row that covers all of `src/` or every optional module (`src/**`, `src/**/*.h`,
  `optional/*/src/**`) is refused like a row beginning with a wildcard (user's decision,
  2026-11-12): it allows everything the budget exists to count.
- The debate panel is offered, never run unasked, when the recommended interface is on rung 3 or 4.
  It is two opus positions and one round. The first proposal copied the review panel (three
  positions, two rounds, six dispatches); the maintainer objected to the cost, and the user is
  present in a design session and can press a point themselves, which a review panel cannot assume.
- `/gismo:plan` uses a design automatically when one exists and otherwise only suggests the design
  step; it is not required.
- **The design audit is part of `large` and `ultra` reviews**, at the maintainer's request and as the
  0.9.0 review also recommended. It runs with or without a budget: `intrusion.sh measure`, then one
  `gismo:task-reviewer` with `focus: intrusion` (rule `DS-REACH`) when the change touches more than
  new examples, tests and docs outside its home. Without a budget the home is inferred as the
  optional module holding most of the changed files; work on core itself has no home and is not
  audited.
- `/gismo:pr` writes the description from records on disk, one per repository. The section on API
  and semantic changes is never omitted. Pushing and opening a pull request each need an explicit
  yes in that run; a draft is the default.
- The AI note is written in the first person and says what a person reviewed, which the skill asks
  for and never infers. The exact default wording is the maintainer's to change.

## 3. Changes to the existing framework

| Change | Why |
|---|---|
| `review_scope.sh` gains `--nested-base <module>=<ref>`, `--split-renames`, `--no-skip` | A nested repository was always compared with its own `HEAD`, so committed module work was invisible; a rename showed only its new path, hiding a core file moved away; the skip list hid tracked files under `external/` and similar names. Output without the options is unchanged. |
| `agents/task-reviewer.md`: debate mode takes a named position with a one-line brief | The design panel argues `minimal-intrusion` against `ergonomics`, which the fixed `change`/`keep`/`cost` set could not express. |
| `agents/task-reviewer.md`: `focus: intrusion` | The design audit inside a review. |
| `CONVENTIONS.md` section 9, rules `DS-BUDGET` and `DS-REACH` | A rule not written there is not a finding. |
| `/gismo:review`: budget check at every level, design audit at `large` and `ultra`, `--budget`, `accept` on a budget finding widens the budget | So a review can both find and settle a budget violation. |
| `/gismo:plan`: `Budget:` line, inventory checked against the budget | The cheapest place to catch a core file the design did not allow is before anything is built. |
| `/gismo:implement`: budget check after every passing task cycle and at the end of the run, by the orchestrator | The first plan put it in the task-lead. The task-lead does not read `plan.md`, and with parallel tasks a whole-change check inside one cycle reports another task's edit; so the task-lead and the task contract are unchanged. |

## 4. How it was checked

- `skills/design/scripts/test_intrusion.py`: 108 tests on throwaway repositories with nested
  repositories.
- Two rounds of adversarial review of the scripts and one consistency review of the skill texts,
  each by a fresh reviewer. Defects found and fixed, each with a test: a core file moved into home
  not flagged; `..` in a file list read as inside home; tracked files under skipped directory names
  unseen; committed work reported as "OK, 0 changed" when the budget named no base; a crash exiting
  with the findings code; `*` crossing directories; a quoted file name passing as outside `src/`;
  `allow **` allowing everything; an `allow` row meaning a directory only when it existed on disk.
  The first test suite let four deliberate breakages of the script pass; each now has a test.
- The text review found that a failed check could be read as a clean one in four skills, that the
  audit would have dispatched its reviewer on almost every change, and that a review had no way to
  widen a budget. All fixed.

## 5. Limits

- **Not run on a real G+Smo tree.** The worktrees available at build time were not usable as git
  repositories. Everything above was checked on constructed repositories.
- `/gismo:pr` was not exercised end to end; its text was written against G+Smo's template as
  published.
- The fixes made after the second script review, and the skill texts changed after their review,
  have tests or were re-read but were not independently reviewed again.
- The check sees files, not semantics: an allowed file can be changed more than the design intended.
  `DS-REACH` and the declarations in `design.md` are what cover that.
- A new file in a git-ignored path and a nested repository outside `optional/` are not seen.
- Audit counts: `virtual` on a line added inside an already-open block comment, or inside a raw
  string literal, is counted as code. Budget rows cannot hold paths with spaces.
- `.claude/plans/` is ignored by git, so a design does not travel with the branch; `/gismo:pr`
  restates what the description needs from it.
