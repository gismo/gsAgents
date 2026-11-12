---
name: pr
description: "Write the pull-request description for a finished G+Smo change, and open the pull request only when told to. Follows G+Smo's own template (lines prefixed NEW:, IMPROVED:, FIXED:, API:, and the doxygen and tests checklist), states semantic and API changes explicitly, cites what the review checked and what it left open, and carries a note saying which parts were AI-generated and what a human reviewed. Writes one description per repository, since an optional module is its own repository and needs its own pull request. Use as the last step after /gismo:plan, /gismo:implement, /gismo:tidy and /gismo:review. It never commits, and it pushes or opens a pull request only on an explicit yes, as a draft unless told otherwise."
argument-hint: "[<base-ref>] [--slug <slug>] [--ready]"
allowed-tools: Read, Write, Grep, Glob, Bash
---

You write the description of a pull request from what the earlier steps left on disk, show it to the user, and open the pull request only if they say so. The description is assembled from records — the design, the plan, the review report, the git log — and not from your memory of the session: a reader of the pull request has none of that, and a claim in a description that no file supports is the kind a reviewer finds first.

Publishing is outward-facing and cannot be taken back: a pushed branch and an opened pull request notify people and stay visible after they are closed. So nothing leaves the machine on inference. Writing the text is the job; pushing and opening are separate steps, each needing its own explicit yes in this run.

## 1. Find what is being proposed

Confirm `bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-config/scripts/gismo_env.sh` succeeds; it locates the G+Smo root.

**Repositories.** A feature can span the G+Smo root and one or more optional modules, and each `optional/<module>` with its own `.git` is a separate repository with its own remote, branch and pull request. For the root and for every such module, read: the current branch, its upstream if any, and the commits ahead of the base (`git -C <repo> log --oneline <base>..HEAD`). The base is `<base-ref>` for the root when given; otherwise the branch's merge target if `gh pr view` already knows one, else the repository's default branch (`gh repo view --json defaultBranchRef`). For a module, the base is its own default branch unless the feature's `budget.tsv` has a `base` row for it. A repository with no commits ahead of its base has nothing to propose: leave it out and say so.

**Uncommitted work.** Run `bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/review_scope.sh --all-files`. A pull request carries commits, so anything this lists is not in it. Tell the user which files are uncommitted and ask whether to go on without them; do not commit them yourself.

**The records.** `<slug>` is `--slug` when given, else the plan directory under `.claude/plans/` that matches the branch name or was written most recently; when two are plausible, ask. From `.claude/plans/<slug>/` read what exists:

| File | What it gives the description |
|---|---|
| `design.md`, `budget.tsv` | the chosen interface, the alternatives that were turned down, the core files the feature was allowed to touch and why |
| `plan.md` | the purpose (Context) and the verification that was promised |
| `summary.md`, `tasks/NN-report.md` | what was built and which checks ran, with their log paths |
| newest `review/<stamp>/review.md` with `decisions.md` | what was reviewed, at which level, what was found, what was fixed, accepted or deferred, and what was not checked |

None of these is required. A change made by hand has only its commits, and the description is then written from the log and the diff statistics alone, and says less.

## 2. Establish the facts the description states

Each of these is settled from a file or a command, and a fact that cannot be settled is written as unknown.

- **API and semantic changes.** This section is never left out: a pull request that changes behaviour without saying so is the defect this skill most exists to prevent. Sources, in order: `## Public symbols changed` in the review's `findings/correctness.md`; `## Interface` and `## Core changes` in `design.md`; the `Design audit` section of the review. From them list every public class, method or free function that is added, changed or removed, and every case where existing code that does not use the feature gets a different result, default or cost. With no review and no design, look at the diff of public headers yourself (`git diff <base>..HEAD --stat -- '*.h'`, then the changed declarations) and say in the description that the list was read from the diff and not reviewed. When there are none, the section says "None", with the source that shows it.
- **Reach into core.** With a budget, run `bash ${CLAUDE_PLUGIN_ROOT}/skills/design/scripts/intrusion.sh check <budget.tsv>` and report the result: the files outside the feature's directory that changed, each with the reason from its `allow` row. A `DS-BUDGET` finding is stated, not hidden.
- **Review.** The level, the date, the counts by severity, and what the report lists under **Not checked**. From `decisions.md`, which findings were fixed, accepted (with the reason given), deferred or handed over. Recompute the staleness check of `/gismo:review resolve` step 1: if the change has moved on since the review, the description says the review predates the latest commits.
- **Tests and documentation.** Which suites and examples were run and passed, from the review's **Build and test** section or the run's `summary.md`, with nothing claimed that has no log. Whether new public API has doxygen is answered by the review's `DX-PUBLIC` findings, and is unknown without a review.

**Warn before writing** when: no review was run; the newest review has an open `blocker` or `major` that `decisions.md` does not record as fixed or accepted; the review is stale; a `DS-BUDGET` finding is open. Say which, in a line each, and ask whether to write the description anyway. If the user goes on, the description states the same thing in its Review section. A warning the user has seen does not become a silence the maintainers get.

## 3. Ask what only the user knows

Ask these together, once.

- **What a human reviewed.** The description carries a note that the work is AI-generated, and that note is only worth reading if it says what a person actually did: read the diff in full, read parts of it, ran the examples, checked the numerics against a reference, or none of these. Ask; never assume, and never write "reviewed by" on the user's behalf.
- **Anything the maintainers should know that no file holds**: the issue this closes, a paper it implements, follow-up work that is planned.

## 4. Write the description

One file per repository: `.claude/plans/<slug>/pr/<repo>.md`, where `<repo>` is `gismo` for the root and the module name otherwise. The first line is the title; the rest is the body.

Read that repository's own `.github/PULL_REQUEST_TEMPLATE.md` and follow it; a module may have a different one, or none. G+Smo's template asks for a change list with one line per change, each beginning with its kind in capitals, and a three-item checklist. The body has this shape:

```
<title: one line, imperative, under 70 characters, no trailing period>

NEW: <a new class, function, example or capability, one per line>
IMPROVED: <an existing capability made faster, more general or clearer>
FIXED: <a defect, with what went wrong and when>
API: <a public signature or documented behaviour that changed; every entry of the next section has a line here>

## What and why
<two to five sentences: the problem, the approach, where the code lives. Not a list of files.>

## API and semantic changes
<every added, changed or removed public symbol; every changed default, result or cost for existing code; or "None", with how that is known>

## Design
<with a design: the interface chosen, the less and more intrusive alternatives that were turned down and why, and the core files changed with the reason for each. Omit without one.>

## Verification
<suites and examples run, with results; convergence orders or reference values where the change has them>

## Review
<level and date; findings by severity; what was fixed, accepted, deferred; what was not checked; or "No review was run.">

## Checklist
- [x] Explanation of what the changes do and why
- [ ] New code documented with Doxygen comments
- [ ] New tests or examples for the changes

## AI assistance
<the note; see below>
```

- A change-list line states one thing a user of the library would notice. Leave out a kind that has no entry. Refactoring that changes nothing observable is `IMPROVED:` only if something got measurably better; otherwise it goes in **What and why**.
- A checklist item is ticked only when section 2 established it. An item that could not be established stays unticked with the reason after it ("not checked: no review was run").
- Write for a maintainer who has not seen the session: no task numbers, no plan slugs, no paths under `.claude/`, no references to "the review above". The records stay local, so what the description takes from them it restates.
- Do not write an `@name` that is not a real GitHub login you mean to notify; the template's own team mention stays out of the body.
- When the feature spans repositories, each description names the others under **What and why** ("Requires the companion pull request in gsKLShell"), with the link once it exists.

**The AI note.** State plainly that the change was written with an AI coding assistant, which parts were generated — the implementation, the tests, the examples, the documentation, this description — and what the user said a person did, in their words. Then what the automated review covered and did not. For instance:

```
The implementation, tests and this description were generated with an AI coding assistant
(Claude Code with the gismo plugin). I read the full diff of src/ and ran the two new
examples; I did not check the unit tests line by line. An automated review at level
"large" ran on <date>: see Review above for what it covered and what it left unchecked.
```

It is written in the first person because the user is the author of the pull request and answers for it. If the user reviewed nothing, the note says that.

## 5. Show it, and stop

Show each description in full, with the repository, the branch and the base it is for, and the path of the file. Then ask what to do, without assuming an answer:

- **leave it** — the files are the result; the user opens the pull request themselves;
- **change something** — edit the file and show it again;
- **open it.**

## 6. Open the pull request (only on an explicit yes)

For each repository, in this order, and stopping at the first step that fails:

1. **The branch must be on the remote.** If it has no upstream or is ahead of it, say so and ask whether to push; pushing is its own yes. On a yes, `git -C <repo> push -u <remote> <branch>`, never with `--force`. If the user has no push access to the repository, a fork is needed: say so and let the user set it up.
2. **Check for an existing pull request** (`gh pr view <branch>`). If one exists, do not create a second: offer to update its description (`gh pr edit --body-file`), which also needs a yes.
3. **Create it as a draft**: `gh pr create --draft --base <base> --head <branch> --title "<first line>" --body-file <file without its first line>`, run inside the repository. `--ready` in the invocation, or the user saying so now, opens it ready for review instead. A draft is the default because the maintainers are notified when a pull request becomes ready, and the user may want to look at it on the site first.
4. Report the URL. With several repositories, open the modules first, then put their URLs into the core description before opening it.

If `gh` is missing or not signed in, say so and stop with the files written; do not look for another way to publish.

## Safety

- Never commit, amend, rebase or force-push. The pull request carries the user's commits as they are.
- No push and no `gh pr create`, `gh pr edit`, `gh pr ready` or `gh pr comment` without a yes given in this run for that step. A yes from an earlier session, or to an earlier description, does not carry over.
- Never `git worktree prune`. `git fetch` writes: compare against the refs already there, and say how old the base ref is when that matters.
- Files are never duplicated from the shell (`cp`, `mv`, a redirect from one file into another): use Read and Write.
- The description contains nothing private: no local paths outside the repository, no names or addresses beyond the commit authors, no content of files that are not part of the change.
