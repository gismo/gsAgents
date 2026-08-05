---
name: plan
description: G+Smo planning conventions — how to write a plan.md and decompose it into task files that implementer agents can execute without discovery. Use at the end of plan mode for any multi-step G+Smo change, before invoking /gismo:implement.
allowed-tools: Read, Write, Grep, Glob
---

You are preparing a G+Smo feature plan for execution by the closed-loop framework (`/gismo:implement`). The full artifact formats are in `${CODEX_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/implement/TASK_CONTRACT.md` — read that file now; this skill only adds the planning guidance.

## Writing `plan.md`

Structure: **Context** (why; problem; intended outcome) → **Approach** (the chosen design, not alternatives) → **File inventory** (every file to be created/modified, grouped by task) → **Verification** (how the end result is checked: which tests, which example runs, expected numbers where known).

Ground the plan in reality first:
- Locate everything via the generated maps (`.claude/gismo-maps/library-map.md`, `.claude/gismo-maps/modules/<mod>.md`) and read the key existing files. A plan that names a function that doesn't exist produces blocked tasks.
- Reuse before writing: name the existing G+Smo classes/utilities each task should build on, with paths.
- For submodule work, note that `optional/<module>` is its own git repo.

## Decomposing into tasks

The implementers execute without discovery — **the intelligence must be in the task file, not the agent**:

- Size: one task = one coherent change an agent can hold in its head — a class + its instantiation files, a test suite, an example. Split anything requiring two kinds of expertise (code vs test vs example vs docs) into separate tasks for the matching agent type.
- Zero-discovery rule: every file path, every function to call, every pattern to imitate ("do it like `gsFoo::bar` in src/gsX/gsFoo.hpp:120") is spelled out. If you had to search for it while planning, write down what you found.
- Acceptance criteria must be *checkable by a machine or a diff reader*: "suite gsNewFeature_test passes", "example runs with default args and prints an EoC table ≈ 3", never "code is clean".
- Dependencies: order tasks so each builds on completed ones; mark truly independent tasks `Parallelizable-with:` so the orchestrator can run them concurrently.
- Tests are their own tasks (gismo:test-writer), and a feature task's criteria should not depend on tests that don't exist yet — sequence: implement → test → (optionally) example → docs.
