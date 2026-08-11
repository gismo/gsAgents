# gsAgents → plugin migration brief

Written 2026-07-20 as a handover. Goal: rebuild gsAgents so the G+Smo developer
agent framework ships as an **installable plugin via each CLI's own plugin
mechanism** (Claude Code, GitHub Copilot CLI, OpenCode), ideally **without**
gsAgents maintaining its own universal-JSON compiler, plus an **optional CMake
flag** that performs the install for a developer who wants it.

Nothing in this document has been implemented. A previous session built the
framework itself (see below) and researched the provider formats; the packaging
work starts fresh.

---

## 1. What already exists and is validated — do NOT rebuild

A complete, smoke-tested closed-loop agent framework lives in the G+Smo worktree at
`/home/hverhelst/Code/gismo_worktrees/worktrees/agents/.claude/`. It is the input
to this migration.

**Agents** (`.claude/agents/`), model pinned per file in frontmatter:

| Agent | Model | Role |
|---|---|---|
| `gismo-implementer` | sonnet | library code in `src/`, `optional/*/src` |
| `gismo-test-writer` | sonnet | UnitTest++ suites |
| `gismo-example-writer` | sonnet | runnable drivers in `examples/` |
| `gismo-task-reviewer` | opus | per-task PASS/FAIL review gate |
| `gismo-task-lead` | sonnet | per-task loop-driver: implement → review → repair cycles |
| `gismo-spec-writer` | opus | expands one decomposition line into a grounded task spec |
| `gismo-doc-writer` | sonnet | doxygen / tutorials / README |
| `gismo-builder` | sonnet | guarded make wrapper |
| `gismo-unittest-runner` | sonnet | build + run + analyse tests |
| `gismo-debugger` | sonnet | GDB / Valgrind |
| `gismo-indexer` | sonnet | codebase exploration (reads generated maps) |
| `gismo-scout` | haiku | one-shot factual lookups (file:line, signatures) |
| `gismo-advisor` | opus | mid-task consultant for the sonnet implementers |

Nesting rule: the orchestrator spawns `gismo-spec-writer` (setup) and
`gismo-task-lead` (loop), which spawns its task's implementer plus
`gismo-task-reviewer`; spec-writer, the implementers, the reviewer, doc-writer
and debugger may spawn the cheap explorers `gismo-scout` (haiku) and
`gismo-indexer` (sonnet); the implementers additionally consult `gismo-advisor`
(opus) at two mandatory decision points, capped at 2 per task; explorers and the
advisor spawn nothing.
This is a deliberate cost control. (Nested subagents require Claude Code
>= 2.1.172; depth here peaks at 3 of the allowed 5.)
The `model:` pins are defaults — a session-wide `CLAUDE_CODE_SUBAGENT_MODEL`
override, or an omitted pin (inherit), lets users retune the tiers per run.

**Skills** (`.claude/skills/`), each `SKILL.md` + `scripts/`:

- `gismo:dev-config` — writes `.claude/gismo-dev.local.json` (build dir + jobs cap);
  asserts/enables `CMAKE_EXPORT_COMPILE_COMMANDS`
- `gismo:build-target` — the only sanctioned `make`; refuses bare/`all` targets, caps `-j`
- `gismo:syntax-check` — `-fsyntax-only` gate; **requires** `compile_commands.json`
- `gismo:run-tests` — builds + runs `unittests` with prefix filtering
- `gismo:tree`, `gismo:module-map` — generators for the library/submodule context maps
- `gismo:plan`, `gismo:implement` — the orchestration protocol
  (`gismo:implement/TASK_CONTRACT.md` defines task specs, reports, reviews)

**Validated end-to-end** on 2026-07-18: `gismo-test-writer` (sonnet, ~33k tokens)
implemented a task and self-verified; `gismo-task-reviewer` (sonnet, ~31k tokens)
independently re-ran the tests and returned PASS. A worked example of the artifact
formats is kept at `.claude/plans/framework-smoke/`.

Also present: `cmake/AggregateSubmoduleAgents.cmake` in the gismo repo, which
symlinks `optional/<mod>/.claude/agents/*.md` into the root `.claude/agents/` as
`<mod>--<name>.md` (tested both directions, including stale-link cleanup). Keep this
— it solves submodule-shipped specialists being invisible from the repo root.

---

## 2. Research findings (verified July 2026)

### Skills ARE universal — this is the big win

All three CLIs read Claude's skill directory natively:

- **OpenCode** scans `.opencode/skills/`, **`.claude/skills/`**, `.agents/skills/`
  (+ `~/.config/opencode/skills/`, `~/.claude/skills/`, `~/.agents/skills/`)
- **Copilot CLI** accepts `.github/skills`, **`.claude/skills`**, or `.agents/skills`
  for project skills, and explicitly supports scripts and supplementary files inside
  the skill directory

⇒ **One skills tree serves all three verbatim. No conversion, no compiler.**

Two constraints for the union:
- Skill `name` must be **lowercase alphanumeric with single hyphens**, 1–64 chars
  (OpenCode enforces). Current names contain a colon (`gismo:build-target`) and are
  **invalid for OpenCode** — rename to `build-target`, `dev-config`, … The Claude
  plugin then re-supplies the `gismo:` namespace automatically, so `/gismo:build-target`
  still works for Claude users.
- Only `name` + `description` are universally recognised; `argument-hint` and
  `allowed-tools` are Claude-only and silently ignored elsewhere (harmless).

### Agents are NOT universal

| Target | Directory | Extension | per-agent `model:` |
|---|---|---|---|
| Claude | `agents/` | `.md` | yes |
| Copilot CLI | `.github/agents/` (repo) or `~/.copilot/agents/` | **`.agent.md`** | yes |
| Copilot org/cloud | `agents/` in the org's `.github`/`.github-private` repo | `.md` | yes |
| OpenCode | `.opencode/agents/`, `~/.config/opencode/agents/` | `.md` | yes |

OpenCode's Claude-compatibility covers skills and `CLAUDE.md` — **not** `.claude/agents/`.
Copilot needs a different extension plus extra frontmatter (`target`,
`user-invocable`, `mcp-servers`). All three do support per-agent model selection, so
the tiered design survives everywhere.

⇒ Some agent transformation is unavoidable, but it is a **rename + frontmatter map**,
not a compiler framework. Roughly a 100-line script, or a CI step.

⚠️ **Trap:** `foo.agent.md` also ends in `.md`. If Claude and Copilot agent files
share one directory, Claude will likely try to load the Copilot ones. Emit
**separate per-provider trees**.

🐛 **Existing bug:** gsAgents currently emits Copilot output as
`.github/agents/my-agent.md`. Copilot CLI requires `.agent.md`, so today's Copilot
agents are probably never discovered. Verify and fix during the migration.

### Plugin packaging is NOT universal

- **Claude**: `.claude-plugin/plugin.json` (only that file in there); `agents/`,
  `skills/`, `commands/`, `hooks/` at the **plugin root**. Marketplace =
  `.claude-plugin/marketplace.json`; a plain git repo can be one.
  Install: `/plugin marketplace add <owner/repo>` then `/plugin install <name>@<marketplace>`.
  Local dev: `claude --plugin-dir ./my-plugin` + `/reload-plugins`.
  Per-repo auto-enable: `.claude/settings.json` with `extraKnownMarketplaces` +
  `enabledPlugins`.
- **Copilot CLI**: `plugin.json` in a **`.github/`** subdir of the plugin; marketplace
  at `.github/plugin/marketplace.json`; install
  `copilot plugin install <name>@<marketplace>`. Packages agents, skills, hooks, MCP.
- **OpenCode**: "plugins" are **npm/TypeScript packages** that register tools and
  hooks programmatically. This is a *different concept* — there is no documented
  OpenCode plugin format that installs agents or skills as data.

### Org-level Copilot agents are cloud-only

Org agents live in `agents/` at the **root** of the org's `.github` /
`.github-private` repo as plain `.md`. The Copilot **CLI** docs list only
`~/.copilot/agents/` and the repo's `.github/agents/`. No evidence the CLI consumes
org-level agents — treat `gismo/.github` as serving github.com/cloud only, not the CLI.

---

## 3. Decisions already taken (by the user)

1. **Install must be via each CLI's own plugin mechanism**, not by committing files
   into the G+Smo repo. Keeping `.claude/` in the main repo works but "pollutes".
2. **Optional CMake flag** performs the install for developers who want it
   (evolution of today's `GISMO_AGENT_PROVIDERS` / `LinkAgents.cmake` /
   `FetchAgents.cmake`), so opting out leaves the tree pristine.
3. **Prefer dropping the gsAgents universal-JSON compiler** — the syntax is largely
   universal, so hand-maintaining JSON per agent is redundant.
4. Skill names get hyphenated (no colons) — required by OpenCode, and gives free
   `gismo:` namespacing under a Claude plugin.
5. Generated context maps (`library-map.md`, `modules/*.md`) are **per-checkout data**
   and must be written into the project (`<gismo-root>/.claude/gismo-maps/`), never
   into the skill/plugin — a plugin installs once but serves many worktrees.
6. Keep the existing `.claude/` framework working throughout the migration; retire it
   only once the plugin is proven.

---

## 4. Open questions — resolve these FIRST

1. **Can OpenCode install agents via a plugin at all?** Its plugins are npm/TS
   packages with a hooks/tools API; agents are directories or `opencode.json` config.
   Investigate whether an OpenCode plugin can contribute agent definitions (e.g. by
   injecting config) — if not, decision 1 is **not achievable for OpenCode** and that
   provider needs a fallback (symlink into `.opencode/agents/`, or config generation).
   *This is the main risk to the "always a plugin" goal.*
2. **Script path portability.** `${CLAUDE_PLUGIN_ROOT}` is Claude-only. A skill's
   `SKILL.md` must tell the agent where its `scripts/` live, and the answer differs
   between a plugin install and a project-local `.claude/skills/`. Options: a
   provider-substituted token at build time; a small resolver snippet in each SKILL.md
   that tries both; or having the CMake flag install scripts to a fixed project path
   (e.g. `.gismo-agents/bin/`) that every provider can reference identically.
   **Decide this before writing any SKILL.md.**
3. **Exact Copilot plugin layout** for agents + skills together (docs are thin; the
   community reports `plugin.json` must sit in `.github/`, contradicting the official
   docs). Validate against a real `copilot plugin install`.
4. **How much compiler survives?** Skills need none. Agents need a rename +
   frontmatter map. Confirm whether that lives in CI (GitHub Actions, like today's
   deploy workflow producing `output-*` branches) or in a small script run on demand.

---

## 5. Suggested starting structure (not final)

```
gsAgents/
├── .claude-plugin/marketplace.json     # Claude marketplace (repo doubles as one)
├── .github/plugin/marketplace.json     # Copilot marketplace
├── plugin/                             # canonical, mostly provider-neutral
│   ├── skills/<name>/SKILL.md + scripts/     # shared verbatim by all providers
│   └── agents/*.md                           # Claude-format = source of truth
├── build/                              # CI-generated per-provider trees
│   ├── claude/    (.claude-plugin/plugin.json + agents/ + skills/)
│   ├── copilot/   (.github/plugin.json + agents/*.agent.md + skills/)
│   └── opencode/  (agents/*.md + skills/)   # pending Q1
└── .github/workflows/                  # CI: generate + publish
```

Retire: `compiler/`, `agents/*.json`, `skills/*/*.json`, and the many
`WORKTREE_AGENTS_*.md` scratch documents at the repo root.

---

## 6. Gotchas worth carrying over

- **G+Smo `.gitignore` ignores** `.claude/*`, `.github/*`, `.opencode/*`, `AGENTS.md`
  **and `CLAUDE.md`**. So nothing agent-related is committed today, and any
  `CLAUDE.md` guidance added locally does not reach teammates. Per-repo plugin
  auto-enable would need a `!.claude/settings.json` exception.
- **Name collisions:** the current fetch manifests carry `my-agent`, `my-command`,
  `my-better-command`, `my-skill`, `gismo:build`, `gismo:configure`. Avoid reusing
  those names; `GISMO_AGENTS_FORCE_DOWNLOAD=ON` overwrites manifest-listed files only.
- **Claude precedence:** project `.claude/agents/` **overrides** plugin agents of the
  same name; plugin skills are namespaced (`/plugin:skill`) so they never collide.
  This makes a side-by-side migration safe.
- **Build safety is non-negotiable** in every agent prompt: never bare `make` (builds
  all ~61 examples), never unbounded `-j` (has crashed machines via RAM exhaustion).
  Everything goes through `build_target.sh`.
- G+Smo's unittests binary is **UnitTest++**, selected by positional **prefix
  matching** on suite/test/file names — there are no doctest-style `--list-*` flags
  (the `-R` hint in `unittests/main.cpp` is stale).
- Header syntax-checks need the real prelude: `gsForwardDeclarations.h` **and**
  `gsTemplateTools.h` (the latter alone lacks the std includes); unittest TUs need
  `-I optional/gsUnitTest -I unittests`.
