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
| `gismo:implementer` | sonnet | Library code in `src/`, `optional/*/src` |
| `gismo:test-writer` | sonnet | UnitTest++ suites |
| `gismo:example-writer` | sonnet | Runnable drivers in `examples/` |
| `gismo:task-reviewer` | sonnet | Per-task PASS/FAIL review gate |
| `gismo:doc-writer` | haiku | Doxygen / tutorials / README |
| `gismo:builder` | haiku | Guarded `make` wrapper |
| `gismo:unittest-runner` | haiku | Build + run + analyse tests |
| `gismo:debugger` | haiku | GDB / Valgrind |
| `gismo:indexer` | haiku | Codebase exploration (reads generated maps) |

Cost control: the three sonnet implementers may spawn only the haiku
`gismo:indexer`; nobody else spawns agents.

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
