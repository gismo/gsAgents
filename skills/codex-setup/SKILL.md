---
name: codex-setup
description: Check and prepare an OpenAI Codex install for the gismo plugin. Codex loads the plugin's skills, scripts and hook, but not its agents, and by default lets a subagent spawn no further agents; this skill reports what is missing, installs the gismo agents as Codex roles (gismo:implementer, gismo:task-reviewer, ...) with each tier mapped to a Codex model, and raises agents.max_depth to the 3 levels the task loop needs. Run once after installing or updating the plugin in Codex, or when a gismo dispatch fails with an unknown agent_type or "Agent depth limit reached". Codex only; it never writes anything without an explicit yes.
argument-hint: "[check | install [--tier TIER=MODEL]... | set-depth]"
allowed-tools: Bash, Read
---

You prepare Codex to run the gismo agent framework. This is for OpenAI Codex only: if
you are running in Claude Code, say so and stop, because Claude Code loads the agents
from the plugin itself.

The script is `scripts/codex_setup.py` in the directory of this `SKILL.md`. Run it with
that absolute path; Codex does not expand `${CLAUDE_PLUGIN_ROOT}`, so do not use it here.
Its last line is `STATUS: OK` or `STATUS: FAIL <n>`; each other line is
`OK|WARN|FAIL|INFO <item>: <message>`.

## Steps

1. **Check** (read-only):
   ```
   python3 <skill-dir>/scripts/codex_setup.py check [--project <gismo checkout>]
   ```
   Pass `--project` when the user works in a G+Smo checkout that has its own
   `.codex/config.toml`. Show the user every `FAIL` and `WARN` line. If the status is
   `OK`, stop here.

2. **Agents** (`FAIL agents`, or `FAIL models`). Show the tier map from the
   `INFO tiers` line, and the models the account offers if a `FAIL models` line lists
   them. Ask the user which Codex model each tier should use: haiku is the cheap lookup
   tier (scout), sonnet the working tier (implementers, task-lead, builder), opus the
   judging tier (task-reviewer, spec-writer, advisor). Only after an explicit yes, run
   ```
   python3 <skill-dir>/scripts/codex_setup.py install [--tier opus=<model>] [--tier sonnet=<model>] [--tier haiku=<model>]
   ```
   The script remembers the map, so later runs need `--tier` only to change it. It
   writes `$CODEX_HOME/agents/gismo-<name>.toml`, replaces only files it wrote itself
   and removes roles the plugin no longer ships.

3. **Depth** (`FAIL max_depth`). Explain that the task loop nests three levels
   (orchestrator, task-lead, implementer, scout) and Codex's default allows one. Only
   after an explicit yes, run
   ```
   python3 <skill-dir>/scripts/codex_setup.py set-depth
   ```
   It backs up `config.toml` first and prints the backup path. If it refuses because
   `agents` is defined as a dotted key or inline table, show the user the line to change
   by hand instead of editing `config.toml` yourself.

4. **Re-check** with step 1 and report the result.

5. **Tell the user** what remains manual:
   - Start a new Codex session: Codex reads roles at session start.
   - Approve the plugin's `PreToolUse` hook in `/hooks`. Until then the tier guard
     does not run.
   - Rerun this skill after every plugin update. The roles embed the plugin's install
     path, which changes with each version, and `check` reports them as out of date.

Never edit `config.toml` or the role files by hand, and never run `install` or
`set-depth` without the user's yes.
