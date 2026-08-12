#!/usr/bin/env python3
"""PreToolUse guard: refuse Agent calls that override a gismo agent's tier.

An explicit `model` argument on the Agent tool takes precedence over the agent
file's frontmatter, so a dispatcher can silently promote the haiku scout to opus
and nothing in the agent definition would show it. This denies such calls at the
point of dispatch, with a reason the caller sees.

Wire it in settings.json:

    "hooks": {
      "PreToolUse": [
        { "matcher": "Agent",
          "hooks": [{ "type": "command",
                      "command": "${CLAUDE_PLUGIN_ROOT}/scripts/guard-agent-model.py" }] }
      ]
    }

Calls to non-gismo agents, and calls that pass no model, are left to the normal
permission flow.
"""

import json
import re
import sys
from pathlib import Path


def declared_tiers(agents_dir):
    """Minimal frontmatter read — kept local so the hook stays a single file."""
    declared = {}
    for path in sorted(Path(agents_dir).glob("*.md")):
        name, model, in_frontmatter = path.stem, None, False
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.rstrip() == "---":
                    if in_frontmatter:
                        break
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    match = re.match(r"^(name|model):\s*(\S+)", line)
                    if match and match.group(1) == "model":
                        model = match.group(2).strip("\"'")
                    elif match:
                        name = match.group(2).strip("\"'")
        declared[name] = model
    return declared


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0  # malformed input is not this hook's problem

    tool_input = payload.get("tool_input") or {}
    override = tool_input.get("model")
    subagent = tool_input.get("subagent_type") or ""
    if not override or not subagent:
        return 0

    # `gismo:scout` in a call, `scout.md` on disk.
    bare = subagent.split(":")[-1]
    declared = declared_tiers(Path(__file__).resolve().parent.parent / "agents")
    want = declared.get(bare)
    if not want or want == override:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"{subagent} declares model: {want}; this call passes model={override}, "
                    f"which overrides it. Drop the model argument to run {bare} on its own "
                    f"tier, or dispatch a different agent if you need {override}."
                ),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
