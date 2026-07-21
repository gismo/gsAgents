---
name: module-map
description: Per-submodule context for G+Smo optional/ modules (gsKLShell, gsElasticity, ...) from pre-generated files — headers, unittest suites, example targets, enabled-status. Use when a task touches a submodule; load only the relevant module's file. Also regenerates the files.
argument-hint: "[module|--regen]"
allowed-tools: Read, Bash(python3:*)
---

Generated per-module context files live at:

```
.claude/gismo-maps/modules/index.md      # one line per module
.claude/gismo-maps/modules/<name>.md     # details per module
```

Each `<name>.md` contains: README summary, whether the module is enabled in `submodules.txt`, whether it is its own git repo (never commit submodule changes from the root repo!), its headers with `@brief` lines, its unittest suites (these compile into the main `unittests` binary when enabled), and its example targets.

Usage rules:
- **Load only the module file(s) relevant to the task at hand** — never all of them. Start from `index.md` when unsure which module covers a capability.
- Working from the gismo root and inside `optional/<module>` is equivalent: the same files apply.
- **These files are per-checkout and are not shipped with the plugin — on a fresh checkout they
  do not exist yet.** If `index.md` is absent, generate before answering; treat it as a normal
  first-run step, not an error.
- Regenerate with `python3 ${CLAUDE_PLUGIN_ROOT}/skills/module-map/scripts/gen_module_map.py` when modules were added/enabled or after large submodule updates; report the STATUS line.

Submodule specialist convention (hybrid model): a submodule may ship its own agents under `optional/<module>/.claude/agents/`; those are aggregated into the root `.claude/agents/` by cmake (see `cmake/AggregateSubmoduleAgents.cmake`) so they are available when working from the root.
