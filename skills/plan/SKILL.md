---
name: plan
description: G+Smo planning conventions — triage the request into quick or standard mode, then write a plan.md (and, in standard mode, a decomposition) that implementer agents can execute without discovery. Use at the end of plan mode for any G+Smo change, before invoking /gismo:implement.
allowed-tools: Read, Write, Grep, Glob, Bash, Agent, ListAgents, SendMessage, TaskCreate, TaskGet, TaskList, TaskUpdate
argument-hint: "[--quick|--full]"
---

You are preparing a G+Smo feature plan for execution by the closed-loop framework (`/gismo:implement`). The full artifact formats are in `${CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md` — read that file now; this skill only adds the planning guidance.

## Session rules

**Keep a todo list.** Track the planning session's own steps in the native task
list (`TaskCreate` / `TaskUpdate`): the triage verdict, the grounding lookups
still open, each section of `plan.md`, the decomposition. A plan is written
front to back but researched out of order, and the list is what keeps a
half-grounded file inventory from being handed to `/gismo:implement` as if it
were finished. The Task tools exist only when the session was started with
`CLAUDE_CODE_ENABLE_TODO_TOOLS=1` (see the README); without them, keep the
same list as a checklist at the top of your working notes and carry on.

**Ask early: ask when the answer changes the plan and the tree cannot answer it.** Planning is the cheapest place
in this framework to resolve anything: a question here costs one exchange, while
the same uncertainty left in the plan becomes a spec line, then a task cycle,
then a repair round — and the agents that execute the plan cannot ask anyone,
they work autonomously against whatever you wrote. So when the request does not
already settle it — scope, which existing class to build on, a tolerance, an
interface, how far a refactor should reach, what "done" means for the
verification section — put it to the user rather than choosing the plausible
option and writing it down as fact. Batch the open questions into one exchange
instead of drip-feeding them, and never ask what the tree already answers: a
question is for a decision, a lookup is for a fact.

**Check for adjacent sessions first** (Claude Code >= 2.1.224): call `ListAgents`,
which lists other local Claude Code sessions with their name and working
directory — no branch, no plan slug. A session is adjacent when its working
directory is this worktree, inside it or contains it, or its name contains the
plan slug. None found: proceed and say nothing. Found: show them to the user and
ask how they relate — independent; coordinate, in which case `SendMessage` each
one a short plain-text note naming this plan and the files it will touch (never
file contents); or stop. If `ListAgents` is unavailable or denied, skip
silently. A slug match only works if sessions are named after the plan, so
recommend once, in one line, `claude --name <slug>` or `/rename <slug>`.

## 0. Triage first: quick or standard

Not every request deserves the full closed loop. **Decide the mode before you write
anything**, state the verdict and the reason in one line to the user, and record it as a
`Mode:` line at the top of `plan.md`. `--quick` or `--full` in the invocation overrides
the rubric — say so and obey it.

A request is **quick** when *all* of these hold:

- it decomposes into **at most 2 coherent tasks**;
- it adds **no new public API** (no new class, no new public method or free function
  that other code is expected to call);
- it changes **no numerical algorithm** — no new discretisation, quadrature, solver
  step, convergence criterion or tolerance;
- **nothing later builds on it** — no task in this run, and no known follow-up, depends
  on its output;
- it touches roughly **≤ 5 files**.

Anything else is **standard**. Typical quick work: adding a few examples, extending an
existing example with a flag, a doc/doxygen pass, a localised bug fix with an obvious
cause, adding a test to an existing suite. Typical standard work: a new class or
assembler, anything in `src/` that a test or example will then use, a refactor across
modules, anything with an EoC table to defend.

The rule is a checklist, not a vibe: if you cannot point at the clauses that hold, it is
standard. When it is genuinely borderline, say so and ask the user rather than guessing
(the session rule above, and here for a concrete reason) — the cost difference between
the two modes is exactly what they are choosing.

### What each mode produces

- **Quick** — a short `plan.md` (Context / Approach / File inventory / Verification, a
  handful of lines each) and nothing else. Do **not** write a task decomposition;
  `/gismo:implement` handles 1–2 tasks itself. Skip the sizing rules below — they are
  for standard mode — but keep the grounding rules: quick does not mean ungrounded.
- **Standard** — a full `plan.md` plus the decomposition described below.

## 1. Writing `plan.md`

Start the file with `Mode: quick | standard` on its own line — `/gismo:implement` reads
it to choose its path. Then: **Context** (why; problem; intended outcome) → **Approach** (the chosen design, not alternatives) → **File inventory** (every file to be created/modified, grouped by task) → **Verification** (how the end result is checked: which tests, which example runs, expected numbers where known).

**Premises and status are append-only.** Once `plan.md` is written, a premise or a status line in it is never rewritten. A correction is a dated paragraph under the original — `Update YYYY-MM-DD (reason): …` — so the record of what was believed, and when it stopped being, survives. A status table may gain rows and columns; no cell is overwritten without a dated note. (Decomposition entries, file inventories and acceptance criteria are instructions, not premises, and are corrected in place.)

**Write `rules.md` next to `plan.md`** (standard mode; quick mode only when the plan leans on a repo fact worth re-checking): `.claude/plans/<slug>/rules.md` holds the plan's standing rules — conventions and facts every task must respect, e.g. which paths are tracked, which target builds what, which tolerance was pre-registered. You, the planner, are its writer. **Every factual sentence carries the command that verifies it**, written so the spec-writer can re-run it verbatim:

```
- `examples/CH/` is tracked by git.
  verify: `bash -c 'test -n "$(git ls-files examples/CH)"'`
```

A verify command exits nonzero when its rule is false, so its exit code is the verdict. A pipe or a compound goes inside `bash -c '…'`, which is how the spec-writer passes it to `run_logged.sh`. A verify command only reads: it never builds, configures or modifies anything.

A rule you cannot attach a command to is a judgment, not a fact: state it as a decision, not as something that "is" so. Specs reference `rules.md` by md5 and never copy it (contract, task spec format); like `plan.md`, its statements are corrected by appended dated updates, not rewritten. This is different from `context.md`, the per-run fact ledger, which the orchestrator alone writes.

Ground the plan in reality first:
- Locate everything via the generated maps (`.claude/gismo-maps/library-map.md`, `.claude/gismo-maps/modules/<mod>.md`) and read the key existing files. A plan that names a function that doesn't exist produces blocked tasks.
- The maps are per-checkout and absent on a fresh clone. If the one you need is missing, generate it (`/gismo:tree`, `/gismo:module-map`) rather than planning without it — an ungrounded plan is the most expensive thing you can hand the framework, because every task built on it blocks.
- Delegate lookups instead of reading the library yourself: `gismo:scout` (**haiku**) for one settled fact — an exact signature, where a class lives, which suite covers a feature — dispatching several scouts in the same message when the plan needs several facts, and `gismo:indexer` (**sonnet**) when grounding needs real exploration. Never pass a `model` argument to the Agent tool: the tier is fixed by each agent's own definition (see the dispatch rule in `TASK_CONTRACT.md`).
- Ground beyond the files the plan names: also look at the callers, sibling implementations and existing tests of whatever the plan touches, so the plan reflects how the code is actually used. This is planning only — implementers keep the zero-discovery rule.
- Reuse before writing: name the existing G+Smo classes/utilities each task should build on, with paths.
- For submodule work, note that `optional/<module>` is its own git repo.

## 2. Decomposing into tasks (standard mode only)

The implementers execute without discovery — **the intelligence must be in the task file, not the agent**:

- Size: one task = one coherent change an agent can hold in its head — a class + its instantiation files, a test suite, an example. Split anything requiring two kinds of expertise (code vs test vs example vs docs) into separate tasks for the matching agent type.
- Zero-discovery rule: every file path, every function to call, every pattern to imitate ("do it like `gsFoo::bar` in src/gsX/gsFoo.hpp:120") is spelled out. If you had to search for it while planning, write down what you found.
- Review level: `full` is the default and stays the level for `src/` and driver code; `measurement` is for a deliverable of a data file plus an analysis script; `light` and `none` as `/gismo:implement` defines them.
- Acceptance criteria must be *checkable by a machine or a diff reader*: "suite gsNewFeature_test passes", "example runs with default args and prints an EoC table ≈ 3", never "code is clean".
- Dependencies: order tasks so each builds on completed ones; mark truly independent tasks `Parallelizable-with:` so the orchestrator can run them concurrently.
- Tests are their own tasks (gismo:test-writer), and a feature task's criteria should not depend on tests that don't exist yet — sequence: implement → test → (optionally) example → docs.
