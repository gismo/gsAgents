[![Validate plugin](https://github.com/gismo/gsAgents/actions/workflows/validate-plugin.yml/badge.svg)](https://github.com/gismo/gsAgents/actions/workflows/validate-plugin.yml)

# gsAgents — G+Smo developer agent plugin

A Claude Code plugin providing a cost-tiered, closed-loop agent framework for
developing the [G+Smo](https://github.com/gismo/gismo) isogeometric analysis
library: specialist agents for implementation, testing, examples, docs and
review, plus guarded build / test / syntax-check skills.

Build safety is built in: every compilation goes through a guarded wrapper that
refuses bare `make` (which would build all ~61 examples) and caps `-j` (unbounded
parallelism has exhausted RAM and crashed machines).

## What's in the plugin

**Agents** (dispatched via the Agent tool as `gismo:<name>`):

| Agent | Tier | Role |
|---|---|---|
| `gismo:implementer` | opus | Library code in `src/`, `optional/*/src` |
| `gismo:test-writer` | opus | UnitTest++ suites |
| `gismo:example-writer` | opus | Runnable drivers in `examples/` |
| `gismo:task-reviewer` | opus | Adversarial per-task PASS/FAIL gate (attacks the change; no routine test re-runs) |
| `gismo:task-lead` | sonnet | Per-task loop-driver: implement → review → repair cycles |
| `gismo:spec-writer` | opus | Expands one decomposition line into a grounded task spec |
| `gismo:doc-writer` | sonnet | Doxygen / tutorials / README |
| `gismo:builder` | sonnet | Guarded `make` wrapper |
| `gismo:unittest-runner` | sonnet | Build + run + analyse tests |
| `gismo:debugger` | sonnet | GDB / Valgrind |
| `gismo:indexer` | sonnet | Codebase exploration (reads generated maps) |

The per-task closed loop runs as **nested subagents** (requires Claude Code
>= 2.1.172): `/gismo:implement` dispatches one `gismo:task-lead` per task,
which spawns the task's implementer and then `gismo:task-reviewer`, re-dispatching
the implementer with the review file on `VERDICT: FAIL` — up to 2 repair rounds —
before returning a single `CYCLE: PASS/FAIL/BLOCKED` verdict. The round-by-round
reports and reviews stay out of the main session's context; the files under
`.claude/plans/<slug>/tasks/` remain the audit trail.

Cost control: the orchestrator spawns only `gismo:spec-writer` (setup, opus —
the spec is where the framework's intelligence lives) and `gismo:task-lead`
(loop, sonnet); a task-lead spawns only its task's agent and
`gismo:task-reviewer`; spec-writers and the three opus implementers may spawn
only the sonnet `gismo:indexer`; nobody else spawns agents.

The ceremony also scales with risk: each task spec carries a `Review:` level,
fixed by the orchestrator at decomposition time. `full` tasks get the
in-cycle adversarial review; `light`/`none` tasks defer their review into
ONE end-of-run batch pass (diff-vs-spec read for `light`, evidence sanity
for `none`, plus a cross-task consistency look the per-task reviews can't
give) — so trivial tasks are cheap, nothing ships unreviewed, and a task
that fails its batch review is repaired under the full cycle.

The orchestrator therefore never writes the bulk artifacts: it decomposes the
plan into one compact line per task and dispatches a `gismo:spec-writer` to
ground each one against the real tree (exact paths, signatures, patterns to
imitate). A pointer the plan names but the tree lacks comes back as a
**grounding gap** before any opus agent is dispatched.

### Overriding the model tiers

The `model:` values above are **defaults**, not hard constraints — each is just a
pin in the agent's frontmatter (`agents/*.md`). You can override them without
editing any files:

- **Session-wide:** set `CLAUDE_CODE_SUBAGENT_MODEL=<alias>` to force *every*
  agent onto one model for that session — e.g. `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`
  to run the whole framework cheaper, or `=opus` for maximum capability. This
  takes precedence over the frontmatter pins.
- **Per agent, permanently:** edit the `model:` line in that agent's file (valid
  aliases: `opus`, `sonnet`, `haiku`, `fable`, or a full model id).
- **Unpin entirely:** remove the `model:` line (or set `model: inherit`) and that
  agent runs on your **main session's** model instead of a fixed tier.

### Prompting standards

The agent and skill prompts follow Anthropic's official model-specific
prompting guides — [Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5),
[Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5),
[Fable 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5).
In particular: reviewers report with coverage first and filter downstream
(never "only high-severity"); verification lives in an independent
fresh-context reviewer rather than "double-check your work" instructions;
subagent spawning is explicitly capped; task specs carry the full
specification up front (zero-discovery rule); and reports must ground every
claim in tool-result evidence. Keep these properties when editing prompts.

**Skills** (invoke as `/gismo:<name>`):

| Skill | Purpose |
|---|---|
| `/gismo:plan` | Planning conventions → `plan.md` + task files |
| `/gismo:implement` | Closed-loop orchestration of an approved plan |
| `/gismo:dev-config` | Set build dir + parallel-jobs cap |
| `/gismo:build-target` | Guarded `make <target>` — the only sanctioned build |
| `/gismo:syntax-check` | Per-file `-fsyntax-only` gate via `compile_commands.json` |
| `/gismo:run-tests` | Build + run unit tests, optionally filtered |
| `/gismo:tree` | Core-library map (src/, examples/, unittests/) |
| `/gismo:module-map` | Per-submodule context for `optional/` modules |

## Installation

### Via the Claude Code CLI

```bash
claude plugin marketplace add gismo/gsAgents
claude plugin install gismo@gsagents
```

Or, from a local checkout of this repo:

```bash
claude plugin marketplace add /path/to/gsAgents
claude plugin install gismo@gsagents
```

### Via the G+Smo CMake flag (optional)

For developers who want the install driven from their G+Smo build configuration:

```bash
cmake -DGISMO_INSTALL_AGENTS=ON \
      -DGISMO_AGENTS_SOURCE=/path/to/gsAgents \
      -DGISMO_AGENTS_SCOPE=user .
cmake --build . --target install-agents
```

`GISMO_AGENTS_SCOPE` is `user` (default), `project`, or `local`. The target
validates the manifest before touching your configuration and is safe to re-run.
Opting out (the default, `GISMO_INSTALL_AGENTS=OFF`) leaves your tree untouched.

## Repository layout

```
gsAgents/
├── .claude-plugin/
│   ├── plugin.json         # plugin manifest
│   └── marketplace.json    # this repo doubles as its own marketplace
├── agents/*.md             # agent definitions (Claude format)
├── skills/<name>/          # SKILL.md + scripts/, per the Agent Skills standard
├── cmake/InstallPlugin.cmake
└── CMakeLists.txt          # optional install flag
```

There is **no build or generation step**: the repository *is* the plugin. Skills
reference their bundled scripts via `${CLAUDE_PLUGIN_ROOT}`, which the CLI
resolves at load time.

## Generated context maps

`/gismo:tree` and `/gismo:module-map` generate per-checkout maps into
`<gismo-root>/.claude/gismo-maps/` — they are project data, not shipped with the
plugin (one install serves many worktrees). On a fresh checkout the maps do not
exist yet; the skills generate them on first use.

## Scope

gsAgents currently targets **Claude Code only**. GitHub Copilot CLI and OpenCode
were evaluated and deferred — see `PLUGIN_MIGRATION_BRIEF.md` for the provider
research and the rationale.
