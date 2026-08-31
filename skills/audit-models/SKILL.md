---
name: audit-models
description: Check which model each gismo subagent actually ran on, against the tier its definition declares. Use when a run cost more than expected, after changing agent tiers, or to confirm the cheap agents really are cheap — an agent file's `model:` line states an intention, and only the transcripts show what resolved.
allowed-tools: Bash, Read
---

Run the auditor over this project's session transcripts:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/audit-agent-models.py
```

Add `--cwd <path>` to audit a different checkout, `--session <id>` for one
session, `--quiet` for mismatches only. It exits 1 when any agent ran off its
declared tier.

## Reading the result

Each row is one subagent run: `declared=<tier> ran=<tier>`, and the summary
names the cause of any mismatch. Three outcomes matter:

- **`[call passed model=…]` on a mismatch** — the dispatching agent overrode
  the tier explicitly. The shipped `PreToolUse` guard (`hooks/hooks.json`)
  denies this, so seeing it means the guard is not active: check the plugin is
  installed and up to date rather than treating the run as a one-off.
- **A mismatch with no override noted** — the harness resolved something other
  than the frontmatter. Check the agent file's `model:` value is a tier the
  harness knows.
- **A row for `Explore`, `general-purpose` or another non-gismo agent**
  (`declared=-`) — nothing is wrong with it per se, but a `gismo:*` name that
  fails to resolve silently becomes one of these at the *caller's* tier. If
  such a row is doing work a gismo agent should have done, the plugin
  installed in this checkout is probably older than the agent being called.

Transcripts are per-machine: this audits runs that happened where you are
running it, not runs from another machine or a cloud session.

Report what the audit found. Do not edit agent files to "fix" a mismatch — a
tier that disagrees with its definition is a dispatch or install problem, and
rewriting the definition to match the wrong behaviour hides it.
