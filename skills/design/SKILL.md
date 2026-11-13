---
name: design
description: "Decide the interface of a G+Smo feature before it is planned, so that it reaches no further into the core library than it has to. Maps which core classes the feature must touch, proposes two or three alternative interfaces from least to most intrusive, counts what each would change, and lets the user choose. Writes the chosen interface as declarations together with an intrusion budget: the list of core files the feature may change, which the plan, the implement loop and the review then check mechanically. `audit` measures how intrusive an existing branch became and proposes how to pull it back; `check` runs the budget check by hand. Use before /gismo:plan for any feature that adds public API or needs something from the core library; it never edits source."
argument-hint: "<feature description>   |   audit [<base-ref>]   |   check [<slug>]"
allowed-tools: Read, Write, Grep, Glob, Bash, Agent
---

You are designing the interface of a G+Smo feature together with the user. The failure this skill exists to prevent is a feature that, after a few rounds of implementation, has changed core classes and their API when a smaller reach would have served: each step looked reasonable where it was taken, and nobody chose the sum. So the reach is chosen here, once, by the user, with the alternatives side by side, and written down in a form a script can hold later work to.

This skill runs in the main session because it asks the user questions, and only the main session can. It edits no source file. It writes two files in `<gismo-root>/.claude/plans/<slug>/`, the directory `/gismo:plan` and `/gismo:implement` use for the same feature:

- `design.md` — what was considered, what was chosen and why, and the chosen interface as declarations.
- `budget.tsv` — the intrusion budget.

Scripts are in `${CLAUDE_PLUGIN_ROOT}/skills/design/scripts/`, written `$S` below. The first argument chooses the job: exactly the word `audit` goes to **Audit**, exactly `check` to **Check**; anything else, including a sentence that merely begins with one of those words, is a feature description and starts at section 1.

## The intrusion ladder

Every alternative sits on one rung. Lower is better unless something concrete is lost.

1. **Module only.** The feature lives in its own directory and uses core through its public API as it stands. No core file changes.
2. **Existing extension point.** Core already offers the hook — a virtual to override, a template parameter, a visitor, an option, a factory registration. No core file changes, or a registration line at most.
3. **One new extension point.** Core gains one small hook that is general: it would be worth having if this feature did not exist, it has a default that leaves every existing caller and derived class untouched, and it knows nothing about the feature.
4. **Modify core classes.** Existing signatures, members or behaviour change, or core comes to know about the feature.

A rung-3 hook that only this feature could ever use is rung 4 under another name. Say so when an alternative has that shape.

## The budget file

`budget.tsv` is the ceiling on how far the feature may reach, set once and kept across every plan made for the feature. A plan's file inventory says what one run will touch; a fix plan after a review writes a new inventory, and so does the next iteration. The budget is the list that does not start afresh each time, which is what makes a slow widening visible.

One row per line, columns separated by whitespace, `#` for comments:

```
home    optional/gsKLShell/                 the feature lives here
base    .                     stable
base    optional/gsKLShell    main
allow   src/gsCore/gsFunctionSet.h          one new virtual with a default body
```

- `home` — a directory the feature owns and may change freely. At least one.
- `base` — the ref a repository is compared against: `.` for the G+Smo root, a path for an optional module that is its own git repository. Without a row for a repository, only its uncommitted changes are seen. The ref is the third word; a row carries nothing after it.
- `allow` — a file outside home that may change, with the reason. A path without wildcards allows that file, or as a directory everything beneath it. A glob is accepted after a leading directory name: `*` stays within one directory, `**` crosses directories. A row that begins with a wildcard is refused, because a glob over the whole tree allows everything; so is a row that covers all of `src/` or every optional module (`src/`, `src/**`, `optional/*/src/**`), for the same reason. Keep reasons specific: "one new virtual", not "needed", and name files one by one where you can, since a wide glob is a budget that has stopped counting.

Paths are written from the G+Smo root and contain no spaces.

Outside home and the allowed files, the check flags every modified, deleted or renamed file, and every new file except examples, unit tests and documentation: a new file under `examples/`, `unittests/`, `doc/` or `docs/`, at the root or in an optional module, is not flagged. A new file anywhere else is, because a new CMake script or workflow can change how the core is built as surely as an edit to `src/` can.

**Only the user widens the budget.** No agent adds an `allow` row on its own judgement, and neither do you: when work turns out to need a core file that is not allowed, put the question to the user — what needs it, what the alternative inside the budget would cost. A budget an agent can extend holds nothing. On a yes, widening is these four edits, made together so that the files never disagree, by whichever skill the user answered in:

1. the `allow` row in `budget.tsv`, with its reason;
2. a dated line under `## Budget changes` in `design.md` with the user's reason in their words;
3. an entry under `## Core changes` in `design.md` saying what is added to that file;
4. the new `md5sum` of `budget.tsv` in the `Budget:` line of `design.md` and of every `plan.md` that names this budget. That line is a pointer kept current, not a premise, so it is corrected in place.

## 1. Frame the feature

Settle these before any exploration, from the request where it answers them and by asking where it does not. Ask them together, once.

- **What the feature must do**, as a user of the library would call it: the two or three calls that matter. An interface cannot be compared without them.
- **Where it lives** — an existing optional module, a new one, a directory under `src/`. This becomes the `home` row. If the user has no view, recommend an optional module when the feature is a method or application, and `src/` only when other modules are expected to build on it.
- **The slug** — reuse the plan slug if `.claude/plans/` already has one for this feature, otherwise propose a short one.
- **What must not change** — public API the user wants left alone, bindings that must keep working, a release boundary.

Confirm `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` succeeds, which also locates the G+Smo root; if it fails, run `/gismo:dev-config` with the user. If `design.md` already exists for the slug, read it and ask whether this is a revision of that design or a different feature.

## 2. Map the contact surface

The contact surface is the set of core classes, functions and headers the feature has to reach, and who else depends on them. Delegate it; you want the map, not the source.

- `gismo:indexer` — one dispatch: given the feature and its home, which core classes and headers must it call, derive from or extend; for each, what extension points it already offers (virtuals, template parameters, options, factories, visitors); how many classes derive from it and roughly how many call sites use the members in question; whether it is wrapped in the Python bindings. Ask for file and line on every claim.
- `gismo:scout` — one per exact signature you then need, several in one message.

Use the generated maps (`.claude/gismo-maps/`) first where they answer the question; generate a missing one with `/gismo:tree` or `/gismo:module-map`.

Write the result as the `## Contact surface` section of `design.md`: one line per core class with its header, what the feature needs from it, the extension points it has, and the derived-class and caller counts with where each number came from. A count the indexer estimated is written as an estimate.

## 3. Propose alternatives

Two or three, each on a named rung, each as declarations: the classes and signatures a caller would see and the core declarations that would be added or changed. No function bodies.

- The lowest rung that can work is always one of them. If rung 1 cannot work, say in one or two sentences what blocks it — the specific member that is private, the hook that does not exist — since that sentence is what justifies everything above it.
- Do not pad. Two real alternatives are better than three where one is a strawman.
- For each, state what the user of the feature gives up or gains against the others: a call that becomes clumsier, a copy that is made, a virtual call in a loop.

## 4. Measure each alternative

Count, for each alternative, from its declarations and the contact surface:

| Measure | What is counted |
|---|---|
| Core files changed | each file outside home that would be edited, by name |
| Public signatures | added, and changed or removed, in core headers |
| New virtuals | each one, with the number of derived classes that inherit it, and whether it is pure |
| Callers that must change | call sites outside home that no longer compile or change meaning |
| Dependencies | new includes in core headers; any include that points from core into the feature's home |
| Instantiation | explicit-instantiation files (`*_.cpp`) and `.hpp` files that must change |
| Python bindings | bound classes whose signatures change, or new API left unbound |
| Behaviour | any existing default or result that changes for code that does not use the feature |

These are counts from a sketch, not from compiled code: label the table so, and mark any figure you could not ground as unknown. An include from core into the feature's home, a pure virtual added to a class with derived classes, and a changed behaviour for existing callers are each named in words beneath the table, because a count of one hides how much they cost.

## 5. Let the user choose

Present the alternatives in plain words: what each is, what it costs core, what it costs the user of the feature, and your recommendation with its reason. Keep file-and-line detail out of the question; it is in `design.md` for whoever wants it. Recommend the lowest rung whose cost to the feature's users is acceptable, and say what that cost is.

Then stop until the user answers. The choice is theirs: how much core churn a feature is worth is a maintainer's judgement.

**A panel, when it would help.** Offer a debate — do not run one unasked — when the recommended alternative is on rung 3 or 4, or when the user says they cannot decide. Say what it costs: two opus dispatches. On a yes:

1. Write `.claude/plans/<slug>/debate/topics.md`: each open choice as a neutral question, with the alternatives and their measurement tables beneath it.
2. Dispatch `gismo:task-reviewer` in debate mode twice in one message, naming the directory `.claude/plans/<slug>/`, with `position: minimal-intrusion — argue for the alternative that changes core least` and `position: ergonomics — argue for the alternative that serves the feature's users best`. Add `position: performance — argue from the cost at run time` only when the interface sits on a hot path such as assembly or evaluation loops. Never pass a `model`.
   Each brief also says: scratch files go under `/tmp`; no git command that writes, `git fetch` included; files are never duplicated from the shell.
3. Chair it: for each topic write a ruling into `design.md` with the four parts `/gismo:review` uses — **Decision** (one of the alternatives, or `for you to decide`), **Because**, **Against**, **Would change it**. The positions were assigned, so their agreement means nothing, and an argument its own side conceded is gone. The figures in the measurement tables are counts from a sketch: a panelist's claim counts as measured only where it ran or read something in the tree and says what.

This panel is one round. Unlike the review's, it has no automatic rebuttal: a rebuttal round (`round: rebuttal`, the same positions once more) runs only if the user asks for it after reading the ruling, because the user is present here and can press the point themselves. The ruling is advice; the user still chooses.

## 6. Write the design

`design.md`:

```
# Design: <feature>
Date: <YYYY-MM-DD>   Slug: <slug>   Home: <path>   Rung: <1-4>
Budget: <path of budget.tsv from the G+Smo root> @ md5 <md5>

## What the feature must do
## Contact surface
## Alternatives            (each with its rung, declarations and measurement table)
## Choice                  (which, the user's reason in their words, and what was given up)
## Debate ruling           (when a panel ran)
## Interface               (the chosen alternative: declarations only, each with the file it goes in)
## Core changes            (one entry per allow row: the file, exactly what is added or changed, and why it cannot live in home)
## Budget changes          (dated lines, added when the user widens the budget)
```

`budget.tsv`: the `home` rows, a `base` row for each repository the feature touches (ask which ref the work branches from if it is not evident; never fetch), and one `allow` row per file under `## Core changes`. A rung-1 design has no `allow` rows, and that is the point of it; a rung-2 design has one only where using the extension point means a registration line in a core file.

Compute the md5 with `md5sum` and write it into the `Budget:` line. The header lines are kept current: a later change to the budget updates that line in the same step.

The sections from `## What the feature must do` to `## Choice` are a record and are not rewritten afterwards; a correction is a dated paragraph beneath the original. `## Interface` and `## Core changes` are instructions to the planner and are corrected in place, with the user's agreement when the correction changes what core gains.

Then tell the user, in a few lines: the rung chosen, the core files allowed, the paths of the two files, and that `/gismo:plan` is the next step. The planner takes `## Interface` as its approach and must keep its file inventory inside the budget.

## Audit

`/gismo:design audit [<base-ref>]` looks at a branch that already exists and answers: how far into core did this feature go, and how much of that was needed?

1. **Frame it.** Settle the slug as in section 1: the feature's existing plan slug, else a short one you propose. Ask where the feature lives (propose the directory holding most of the added files) and which ref each repository branched from; `<base-ref>` is the root repository's. Write a draft `.claude/plans/<slug>/budget.tsv` with the `home` and `base` rows and no `allow` rows. If a `budget.tsv` is already there, the feature was designed: measure against it as it stands and write nothing over it.
2. **Measure.** `bash $S/intrusion.sh measure <budget.tsv> > .claude/plans/<slug>/intrusion.tsv` — stdout only, since the script prints notices on stderr. Read the last line first: on `STATUS: FAIL` nothing was measured, so relay the reason and stop; an output without rows is a result only beneath `STATUS: OK`. Each `FILE` row is a changed file outside home with its added and removed lines, added virtuals, added includes, includes that point into home, and whether it is a public header. Rows marked `exempt=yes` are new examples, unit tests and documentation outside home, which no budget restricts; the audit concerns the rows marked `exempt=no`. A `BASE` row gives, per repository, the commit the change was measured from, so `git -C <repo> diff <commit> -- <path inside that repository>` shows what a row counts; a row's own path is written from the G+Smo root. If no row is `exempt=no`, the feature is on rung 1: say so and stop.
3. **Classify.** For each file, what the change is and which rung it amounts to. Read the diff of a core file yourself when the files are few and the hunks short; past five files or a few hundred lines, dispatch `gismo:indexer` with `intrusion.tsv` and ask, per file, what was changed, who else is affected, and whether an existing extension point would have served. Give it no view of your own on the answer.
4. **Propose,** per file, one of:
   - **move** — the change belongs in home (a helper, a specialisation, a feature-specific branch);
   - **replace** — an existing extension point does the job; name it;
   - **generalise** — keep the change but reshape it into a hook that does not know the feature;
   - **keep** — it is a small general addition already;
   - **revert** — it is unrelated to the feature (a drive-by edit, a formatting change).
   With each, what pulling it back would cost: the files and callers that follow.
5. **Write** `design-audit.md` — the measurement totals, the per-file table, and the proposal — and put the choices to the user in plain words, the largest reach first. The files the user decides to keep become the `allow` rows of `budget.tsv`. What is to be pulled back is ordinary work: suggest `/gismo:plan` with `design-audit.md` as its input. The planner treats `design-audit.md` with its budget as it treats a design: the budget binds the plan, and the audit's proposal takes the place of `## Interface`.

An audit states what was measured and what was read. "This could have used the existing hook" is a judgement until someone tries it, and is written as one.

## Check

`/gismo:design check [<slug>]` runs `bash $S/intrusion.sh check .claude/plans/<slug>/budget.tsv` and relays the result. With no slug, take the newest `.claude/plans/*/budget.tsv`.

- `STATUS: OK` — every changed file is inside the budget. A `SKIP base` row above it names a repository, or counts the other optional modules, that the budget has no `base` row for: only its uncommitted changes were compared, so work already committed on the branch was not seen. Relay it; on a feature branch it means the check has seen less than the user thinks.
- `STATUS: FINDINGS <n>` — list the `DS-BUDGET` rows. For each, the remedies are to move the change into home, to do without it, or to ask the user to widen the budget; you do not choose among them for the user.
- `STATUS: FAIL` — the budget file is malformed or missing, or a ref does not exist; relay the reason. Nothing was checked, which is not the same as nothing found.

The same check runs on its own inside `/gismo:plan` (against the file inventory), in the `/gismo:implement` loop, and in `/gismo:review`.

## Safety

- No source file is edited by this skill, and no agent it dispatches edits one.
- No git command that writes; `git fetch` writes. Never `git worktree prune`.
- Files are never duplicated from the shell (`cp`, `mv`, a redirect from one file into another): use Read and Write. Say so in every brief, since agents do not see the user's own instructions.
- Never commit; `.claude/plans/` is ignored by git and stays local.
