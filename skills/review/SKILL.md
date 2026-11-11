---
name: review
description: "Review a G+Smo change at a chosen depth — light, medium, large or ultra — and write one ranked, triaged report. Checks the diff against the written conventions (style, naming, file structure, example and test consistency and commenting), and from medium up for correctness, numerics, test quality and documentation truth; large and ultra also build, run tests and examples, and ultra tries to refute every finding. The review itself never edits source. A separate `resolve` step walks the user through the findings that need a decision and routes the rest to fixes, and `cleanup` runs the one-off mechanical tree cleanup; both change files only after an explicit yes. Use before committing or opening a pull request, on the working diff, a branch, a checked-out PR, or a path."
argument-hint: "<light|medium|large|ultra> [<base-ref> | pr <N> | <path>...] [--build|--no-build] [--linters] [--debate]   |   resolve [<review-dir>]   |   cleanup <whitespace|doxygen-tags> [--apply] [<path>...]"
allowed-tools: Read, Write, Grep, Glob, Bash, Agent
---

You are the ORCHESTRATOR of a code review. You collect the change, run the mechanical checks, dispatch reviewers, and write the report. You do not review code yourself: a reviewer that has watched the others work has already accepted their framing, and your context is better spent weighing what they found. You read finding files, not source — open a source file only to settle a disagreement between two findings.

The rules being enforced are in `${CLAUDE_PLUGIN_ROOT}/skills/review/CONVENTIONS.md`. Scripts are in `${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/`, written `$S` below.

This skill has three jobs, chosen by the first argument:

- a level (`light`, `medium`, `large`, `ultra`) — **review**, sections 0 to 7. A review edits no source file. Its one touch on the tree is the mutation proof at ultra, which the user confirms in that run and which leaves the tree byte-identical.
- `resolve` — **process a finished review** with the user: go to **Resolve**.
- `cleanup` — **the one-off tree cleanup**: go to **Tree cleanup**.

## 0. Read the request

**Level.** With none given, show this table and ask; do not guess, because the levels differ several-fold in cost.

| Level | Runs | Models | Builds |
|---|---|---|---|
| `light` | lint script, syntax-check, style checker | 1 sonnet | no |
| `medium` | light + correctness review (which also reads for numerics, tests and docs) | + 1 opus | no |
| `large` | medium + dedicated numerics review + dedicated tests/docs review + build, filtered tests, changed examples | + 2 opus, 2 sonnet | yes |
| `ultra` | large + full test suite + valgrind + callers outside the diff + refutation of every finding + debate panel + mutation proof | + 2 to 8 opus, 2 sonnet | yes |

**Target.** Nothing: the working diff, including untracked files. A git ref: everything since the merge base with it. `pr <N>`: resolve the PR's base and head with `gh pr view <N> --json baseRefName,headRefName`; the head must be the branch that is checked out — if it is not, stop and say which branch to check out, never check it out yourself. One or more paths: restrict the diff to them.

**Flags.**
- `--build` at light or medium adds step 3 (build, filtered tests, example runs) and nothing else: no extra reviewer.
- `--no-build` at large or ultra drops every step that needs a binary; reviewers are dispatched with `run: no` and what they could not execute is reported `REASONED`.
- `--linters` adds clang-tidy and cppcheck where installed.
- `--debate` turns the debate panel on at large.

## 1. Collect the change

Everything a review produces lives in one directory:

```
<gismo-root>/.claude/plans/<slug>/review/<YYYYMMDD-HHMM>/
  review.md        the report
  decisions.md     written by the resolve step
  input/           scope.tsv  lines.tsv  lint.tsv  syntax.txt  diff.md5
  findings/        one file per reviewer
  debate/          topics.md and one file per position
  logs/            verbatim output of commands that findings quote
```

`<slug>` is the slug of the `/gismo:implement` plan this change came from when there is one (its `.claude/plans/<slug>/` already exists), otherwise the branch name. The dated subdirectory keeps each run intact, since a change is usually reviewed again after it is fixed. Call the directory `D`. Shell state does not persist between your Bash calls, so write its literal path in every command.

```
mkdir -p D/input D/findings D/debate D/logs
bash $S/review_scope.sh [--base <ref>] [<path>…]              > D/input/scope.tsv
bash $S/review_scope.sh --lines [--base <ref>] [<path>…]      > D/input/lines.tsv
bash $S/review_lint.sh [--base <ref>] [--linters] [<path>…]   > D/input/lint.tsv
git diff [<merge base>] | md5sum                               > D/input/diff.md5
```

The scope script also sees changes inside `optional/` modules that are their own git repositories, which a plain `git diff` at the root does not. If the scope is empty, say so and stop. If it holds more than about 60 files, tell the user the count and ask whether to narrow it before spending anything: a review that large is usually a mistaken target.

`review_lint.sh` ends with `STATUS: OK` when it has no major or minor finding; notes may still be listed above it.

Then run `bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <changed C++ files>` and keep its output as `D/input/syntax.txt`. A file that does not compile is a `blocker`, and there is no point reviewing the rest at depth until it does: write the report with that one finding and stop.

## 2. Dispatch reviewers

Dispatch the agents of a step in one message so they run concurrently. Each is given the directory `D` and what is listed here; none is given your opinion of the change. Never pass a `model` to a `gismo:` agent — its tier is fixed in its definition.

| Level | Agent | Dispatch | Writes |
|---|---|---|---|
| all | `gismo:style-checker` | `D` | `findings/style.md` |
| medium | `gismo:task-reviewer` | diff mode, `focus: correctness`, `also: numerics, tests-docs` | `findings/correctness.md` |
| large, ultra | `gismo:task-reviewer` | diff mode, `focus: correctness` | `findings/correctness.md` |
| large, ultra | `gismo:task-reviewer` | diff mode, `focus: numerics` | `findings/numerics.md` |
| large, ultra | `gismo:task-reviewer` | diff mode, `focus: tests-docs` | `findings/tests-docs.md` |

Every reviewer dispatch also states `run: yes` or `run: no`. When step 3 applies, do it first so the reviewers go out with `run: yes`; the style checker needs no binary and goes out together with the builder.

## 3. Build and run (large, ultra, or `--build`)

Delegate; you want the verdict, not the log. What these agents return goes into the report's **Build and test** section, not into a finding file — except a failure, which becomes a finding as stated.

1. `gismo:builder` — the targets the change affects: the library if `src/` changed, each changed example, the unit-test binary if tests or `src/` changed. Derive target names from `scope.tsv`. A build failure is a `blocker`: write the report and stop.
2. `gismo:unittest-runner` — filtered to the suites covering the changed files; at ultra, no filter.
3. Each changed example, with no arguments: `bash ${CLAUDE_PLUGIN_ROOT}/skills/evidence-log/scripts/run_logged.sh D <name> timeout 120 <binary>`. A non-zero exit or a timeout (exit 124) is a `major` finding under EX-DEFAULT, citing the log.

**ultra only**

4. `gismo:debugger` — each changed example under valgrind with its default arguments.
5. `gismo:indexer` — "which callers outside these files use these symbols?", with the list under `## Public symbols changed` in `findings/correctness.md`. Give its answer to the refutation pass.

## 4. Refute (ultra)

Once the finding files exist, dispatch one `gismo:task-reviewer` in diff mode with `focus: refute`. It marks every finding `upheld`, `refuted` or `undecided` in `findings/refute.md`. A refuted finding leaves the main body of the report and is listed under **Refuted** with the reason, so the user can see what was considered.

## 5. Debate (ultra; large with `--debate`)

A debate is for questions of judgement. A question of fact is settled by running something, and putting it to a panel only produces a confident answer to whatever sounded best — send those to the refutation pass or leave them `UNVERIFIED`.

**Select topics.** A finding goes to the panel when it is `major` or `blocker` and one of these holds: two reviewers disagree about it; the refutation pass left it `undecided`; it is `REASONED` and the fix it implies has a real cost (an API change, a refactor, a performance trade). Write them to `D/debate/topics.md`, each as a neutral question with the finding quoted beneath it. No topics, no panel — say so in the report. More than six: keep the six with the most at stake.

**Run it.** Every panelist gets all topics in one dispatch, so the cost does not grow with the number of topics.
1. Dispatch `gismo:task-reviewer` in debate mode twice, with `position: change` and `position: keep`; add `position: cost` when any topic touches a public interface. Each writes `D/debate/<position>.md`.
2. When the statements are written, dispatch the same positions once more with `round: rebuttal`.

**Chair it.** You are the chair. For each topic, read the statements and rebuttals and write a ruling into the report:
- **Decision:** `fix before merge`, `acceptable as written`, or `for you to decide`.
- **Because:** the argument that carried it, in a sentence or two.
- **Against:** the strongest opposing argument, fairly put.
- **Would change it:** the evidence that would reverse the decision.

Do not count votes: the positions were assigned, so agreement among them means nothing. `MEASURED` outranks `REASONED`, and an argument its own side conceded is gone. When what remains turns on a preference only the maintainer can hold — how much API churn is tolerable, whether a refactor belongs in this change — the ruling is `for you to decide`, with both sides laid out. That is a proper outcome, not a failure of the panel.

## 6. Mutation proof (ultra)

Ask the user before this step, in plain words: it temporarily reverts individual hunks of the change in the working tree, rebuilds, runs the new tests to confirm each one fails without its fix, and restores the files, checking by md5 that they are byte-identical afterwards. Nothing else should be editing the tree meanwhile. On a yes, dispatch `gismo:task-reviewer` in diff mode with `focus: mutation`; it writes `findings/mutation.md`. On a no, skip it and record under **Not checked** that the tests were inspected by reading only.

## 7. Write the report

`D/review.md`. Merge `findings/*.md` and `input/lint.tsv`:
- A finding reported by two agents appears once, citing both.
- Keep each agent's severity and evidence label. Lower or drop a finding only for a reason you state.
- Script findings need no elaboration: group them by rule with a count and the locations.

**Triage every finding** into one action class. It decides what the resolve step may do with it.

| Class | A finding belongs here when | Resolve does |
|---|---|---|
| `mechanical` | a script decided it AND fixing it changes no executable token: WS-TAB, WS-TRAIL, WS-CRLF, DX-TAG, NS-CLOSE, CM-NARR, CM-DEAD, CM-LINEREF, HD-FILE, HD-MPL, HD-AUTHOR | applies them as one batch, after one yes |
| `local` | it is `MEASURED`, there is one evident remedy, and the remedy stays inside the files of the change: every other script finding, a missing doxygen block, an uncommented test, an uninitialised member | turns them into tasks for the closed loop |
| `decision` | anything else: every `REASONED` or `UNVERIFIED` finding, every debate topic, and whatever would change a public interface, touch a file outside the change, or admits more than one reasonable fix | asks the user |

When unsure between two classes, take the one further down the table. You may move a finding down, never up: a reviewer's `REASONED` finding is not yours to declare mechanical, because a finding in the first two classes is acted on without the user being asked about it individually.

```
REVIEW: <level> — <b> blocker, <m> major, <k> minor, <j> note
Triage: <n> mechanical, <n> local, <n> decision
Target: <what was reviewed>   Files: <n>   Added lines: <n> (comments <pct>%)

## Blockers            (omit an empty section)
## Major
## Minor
## Notes
## Debate rulings      (when a panel ran)
## Refuted             (ultra)
## Build and test      (what was built and run, pass/fail, log paths)
## Not checked         (every check this level or these flags skipped, and each tool that was missing)
```

Each finding is one block:

```
### R<n> | <severity> | <MEASURED|REASONED|UNVERIFIED> | <RULE-ID or -> | <path>:<line> | <mechanical|local|decision>
Source: <finding file(s) and their F-numbers, or lint>
What: …
Evidence: …
Direction: …
```

**Not checked** is mandatory and honest: a light review that says nothing about correctness must say that it did not look.

Then tell the user, in a few lines: the headline counts, the blockers and majors by name, the triage counts, what was not checked, and the path of the report. Do not paste the report. End by asking once whether to go through it now (`resolve`) or leave it; when comment findings dominate, mention that `/gismo:tidy` handles those.

## Resolve

`/gismo:review resolve [<review-dir>]` processes a finished report with the user. With no directory, take the newest `.claude/plans/*/review/*/` that has a `review.md`. It works from the report alone, so it can run right after the review or in a later session.

The order matters: a decision can make smaller findings moot, and edits shift line numbers, so decisions come first and the mechanical batch last. Nothing is changed before the user has said yes to that step, and the reviewers never fix their own findings — fixes go through the implementing agents and their own review.

1. **Check the report is current.** Recompute the diff's md5 as in step 1 and compare with `input/diff.md5`. If the change has moved on, say so: locations may be stale, and a fresh `light` review is the cheap way to refresh them. Continue only if the user wants to.
2. **Show the triage counts**, then take the `decision` findings, most severe first, a few at a time. For each, in plain words and without file-and-line detail in the question: what is at stake, what happens under each option, and your recommendation. A debate ruling is the recommendation where there is one, with the argument against it. The user answers `fix` (and how, where there is a choice), `accept` (the code stays; record why) or `defer`. Write each answer to `D/decisions.md` as it is given:
   `R<n> — fix | accept | defer — <date> — <the user's reason or chosen option, in their words>`
3. **Plan the fixes.** The `local` findings and every decision answered `fix` become a plan in `D/fix-plan.md`, written to the conventions of `/gismo:plan`, with each task carrying the finding's evidence and direction so the implementer rediscovers nothing. Show the task list and, on a yes, run `/gismo:implement` on it; its own triage picks quick or standard mode. With nothing to fix, skip this step.
4. **Apply the mechanical batch.** Re-run `review_lint.sh` first — the list in the report predates step 3. On a yes, dispatch one `gismo:doc-writer` with the fresh lint lines of the mechanical rules and the instruction that no executable token may change; it syntax-checks what it touched.
5. **Confirm.** Re-run `review_lint.sh` and the syntax check. Append a `## Outcome` section to `D/decisions.md`: each finding as `fixed`, `accepted`, `deferred` or `still present`. Tell the user the counts and suggest a `light` review of the result, which gets its own dated directory.

A deferred finding simply stays open in the report. Never commit; the user does.

## Tree cleanup

`/gismo:review cleanup <whitespace|doxygen-tags> [--apply] [<path>…]` runs `bash $S/tree_cleanup.sh` with the same arguments and relays its output. It is a one-off mechanical pass that brings an existing tree in line with the whitespace and doxygen-tag rules, so that later reviews start from a clean sheet.

- Without `--apply` it only counts. Show the totals.
- Before `--apply`, tell the user what it will do: it rewrites every listed file in place, it refuses to start on a tree with uncommitted changes, it will conflict with open branches that touch the same lines, and it does not commit. Run it only on an explicit yes.
- Afterwards relay the proof result. `STATUS: FAIL proof` means the script changed something other than what the pass allows: say so and leave the tree for the user to inspect.
- Suggest one commit per pass and adding each commit hash to `.git-blame-ignore-revs`. Optional modules that are separate repositories are cleaned one at a time by naming their path.

## Cost discipline

- The level is the budget. Do not add a reviewer the level does not list because the change looks interesting; suggest the next level in the report.
- One dispatch per row of the table in step 2. A reviewer that returns without its `FINDINGS:` line did not finish: continue that agent, do not start a second one.
- Do not re-run a reviewer to get a second opinion on a finding; that is what the refutation pass and the panel are for, at the levels that have them.

## Safety

- No agent commits, and neither do you. No git command that writes, never `git worktree prune`.
- Builds only through `gismo:builder`; never a bare `make`.
- Never post to a pull request. The report is a file.
- Files are never duplicated from the shell (`cp`, `mv`, a redirect from one file into another). Say so in every brief you write: agents do not see the user's own instructions.
