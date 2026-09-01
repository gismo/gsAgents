---
name: tidy
description: Strip change-narration comments from the working diff before it is committed — the "I removed this because…", "previously we used…", "NOTE: added for task 3" scaffolding that agents write while implementing. Keeps genuine code comments (doxygen, theory links, complexity notes, non-obvious rationale). Use at the end of a /gismo:implement run, or standalone on any dirty G+Smo tree before committing.
argument-hint: "[path or git-ref, default: the working diff]"
allowed-tools: Read, Edit, Grep, Glob, Bash, Agent
---

You are cleaning commit noise out of a diff. Comments written *to the diff reader* are
useful while a change is being made and are dead weight the moment it lands: the reasoning
belongs in the report, the commit message and the review, all of which survive. Comments
written *to the next developer reading the file* stay.

## Scope

Default target is the working diff: `git diff` plus untracked files from
`git status --short`. An argument narrows it to a path, or compares against a git ref.
**Only ever touch lines that this diff added or modified** — pre-existing comments in a
file you happen to be editing are somebody else's decision, not yours.

Never change executable statements, signatures, includes, or CMake logic. This is a
comment-only pass. If removing a comment seems to require a code change, leave it and
note it.

## Delete: comments about the change

- **Narration of the diff.** "Removed the old loop", "replaced by the new helper",
  "previously this used gsFoo", "changed from real_t to index_t". The file no longer
  contains what these describe; git does.
- **Process and task scaffolding.** "NOTE: added for task 3", "per the spec", "TODO(review)",
  "as requested", "this addresses the reviewer's point 2", agent-run identifiers.
- **Restatements of the code.** `// loop over the elements` above a loop over the
  elements; `// increment i` above `++i`; a comment block that just names the function it
  sits on without adding anything a reader could not see.
- **Justifications of an absence.** A paragraph explaining why some other approach was
  *not* taken, or why a deleted line was deleted, attached to code that no longer exists.
- **Commented-out code** the diff introduced, unless a live comment explains why it is
  parked there.
- **Hedging and self-reference.** "This should work", "I chose this because", anything in
  the first person.

## Keep: comments about the code

- Doxygen blocks (`/** */`, `///`, `\brief`, `\param`, `\ingroup`) — always.
- The theory link: the equation, the paper, the scheme being implemented. G+Smo solver
  code is *expected* to carry these.
- Algorithmic complexity notes, and why a non-obvious formulation was chosen when the
  obvious one is wrong (numerical stability, a cancellation, an aliasing hazard).
- Units, index conventions, tensor shapes, expected file formats, the meaning of a
  magic constant.
- Live `TODO`/`FIXME` that names real remaining work, and warnings about a real trap
  ("callers must have called `compute()` first").
- Anything that would make a reader who never saw this diff stop and ask "why?".

**The test**: read the comment as if the diff never existed and you are seeing the file
for the first time. Does it still say something true and useful about the code in front
of you? Keep it. Does it only make sense as a message to someone reviewing a change?
Delete it. When you genuinely cannot decide, keep it — a surviving mediocre comment is
cheaper than a deleted load-bearing one.

Density is not a target. Do not delete good comments to hit a ratio, and do not add
comments here — this pass only removes.

## Procedure

1. Collect the target files from the diff. If there are more than ~10, dispatch one
   `gismo:doc-writer` (sonnet — the cheapest tier, and comment-only edits are exactly its
   mandate) per group of files, quoting this skill's Delete/Keep rules and the file list
   in the prompt. Otherwise do it yourself; a bounded comment-only pass is not worth a
   dispatch.
2. Edit. Removing a comment must not change a single token of executable code.
3. **Syntax-check every file you touched** —
   `bash ${CLAUDE_PLUGIN_ROOT}/skills/syntax-check/scripts/syntax_check.sh <files>` — a
   deleted `*/` or a mangled line-continuation is the one way a comment-only edit breaks
   a build. If any file fails, fix it or revert that file.
4. Report: per file, how many comment blocks were removed and one line on what kind, plus
   anything you deliberately kept that a reader might expect to have gone. Do not paste
   the diff. Never commit — the user decides that.
